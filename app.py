
import re
import io
from datetime import datetime
from typing import Dict, List, Tuple, Any

import pandas as pd
import streamlit as st
from pypdf import PdfReader

try:
    import pdfplumber
except Exception:
    pdfplumber = None

try:
    import pytesseract
    from pdf2image import convert_from_bytes
except Exception:
    pytesseract = None
    convert_from_bytes = None


st.set_page_config(
    page_title="Sistema de Glosa Aduanal",
    page_icon="🛃",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
.block-container {padding-top: 1rem; padding-bottom: 3rem;}
.main-title {font-size: 2.1rem; font-weight: 800; margin-bottom: 0;}
.sub-title {color: #555; margin-top: 0;}
.card {
    border: 1px solid #e5e7eb;
    border-radius: 16px;
    padding: 16px;
    background: #ffffff;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.good {color:#087f23; font-weight:800;}
.warn {color:#b7791f; font-weight:800;}
.bad {color:#b00020; font-weight:800;}
.small {font-size: 0.85rem; color:#666;}
</style>
""", unsafe_allow_html=True)

# ============================================================
# UTILIDADES GENERALES
# ============================================================
def normalize(text: Any) -> str:
    if text is None:
        return ""
    text = str(text).upper()
    repl = {
        "；": ";", "，": ",", "：": ":", "（": "(", "）": ")",
        "\u00a0": " ", "Ó": "O", "Í": "I", "Á": "A", "É": "E", "Ú": "U"
    }
    for a, b in repl.items():
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip()

def number(value):
    if value in [None, ""]:
        return None
    s = str(value).upper()
    s = s.replace(",", "").replace("$", "").replace("US", "").replace("USD", "").replace("KGS", "").replace("KG", "")
    s = re.sub(r"[^0-9.\-]", "", s)
    try:
        return float(s)
    except Exception:
        return None

def money_fmt(v):
    if v in [None, ""]:
        return ""
    try:
        return f"{float(v):,.2f}"
    except Exception:
        return str(v)

def text_fmt(v):
    if v is None:
        return ""
    return str(v)

def ddmmyyyy(text):
    t = normalize(text)
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", t)
    if m:
        return f"{int(m.group(1)):02d}/{int(m.group(2)):02d}/{m.group(3)}"

    months = {
        "JAN": "01", "JANUARY": "01",
        "FEB": "02", "FEBRUARY": "02",
        "MAR": "03", "MARCH": "03",
        "APR": "04", "APRIL": "04",
        "MAY": "05",
        "JUN": "06", "JUNE": "06",
        "JUL": "07", "JULY": "07",
        "AUG": "08", "AUGUST": "08",
        "SEP": "09", "SEPTEMBER": "09",
        "OCT": "10", "OCTOBER": "10",
        "NOV": "11", "NOVEMBER": "11",
        "DEC": "12", "DECEMBER": "12",
    }
    m = re.search(r"(JANUARY|JAN|FEBRUARY|FEB|MARCH|MAR|APRIL|APR|MAY|JUNE|JUN|JULY|JUL|AUGUST|AUG|SEPTEMBER|SEP|OCTOBER|OCT|NOVEMBER|NOV|DECEMBER|DEC)\.?\s*(\d{1,2})(?:ST|ND|RD|TH)?[,]?\s*(\d{4})", t)
    if m:
        return f"{int(m.group(2)):02d}/{months[m.group(1)]}/{m.group(3)}"
    return ""

def split_tokens_csv(value):
    if not value:
        return []
    return sorted(set([x.strip() for x in str(value).replace(";", ",").split(",") if x.strip()]))

def set_equal(a, b):
    return set(split_tokens_csv(a)) == set(split_tokens_csv(b))

def contains_any(text, words):
    t = normalize(text)
    return any(w in t for w in words)

# ============================================================
# LECTURA PDF
# ============================================================
def read_with_pypdf(uploaded):
    uploaded.seek(0)
    reader = PdfReader(uploaded)
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            pages.append(f"\n--- PAGINA {i} ---\n{page.extract_text() or ''}")
        except Exception:
            pages.append(f"\n--- PAGINA {i} ---\n")
    return "\n".join(pages)

def read_with_pdfplumber(uploaded):
    if pdfplumber is None:
        return ""
    uploaded.seek(0)
    pages = []
    try:
        with pdfplumber.open(uploaded) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                try:
                    text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
                    tables = page.extract_tables() or []
                    table_text = ""
                    for table in tables:
                        for row in table:
                            table_text += " | ".join([str(x or "") for x in row]) + "\n"
                    pages.append(f"\n--- PAGINA {i} ---\n{text}\n{table_text}")
                except Exception:
                    pages.append(f"\n--- PAGINA {i} ---\n")
    except Exception:
        return ""
    return "\n".join(pages)

def read_with_ocr(uploaded, lang="eng+spa"):
    if pytesseract is None or convert_from_bytes is None:
        return ""
    uploaded.seek(0)
    images = convert_from_bytes(uploaded.read(), dpi=220)
    pages = []
    for i, img in enumerate(images, start=1):
        try:
            pages.append(f"\n--- PAGINA {i} OCR ---\n{pytesseract.image_to_string(img, lang=lang)}")
        except Exception as e:
            pages.append(f"\n--- PAGINA {i} OCR ERROR {e} ---\n")
    return "\n".join(pages)

def read_pdf(uploaded, use_ocr=False):
    a = read_with_pypdf(uploaded)
    b = read_with_pdfplumber(uploaded)
    txt = b if len(b) > len(a) else a

    if use_ocr and len(txt.strip()) < 500:
        o = read_with_ocr(uploaded)
        if len(o.strip()) > len(txt.strip()):
            txt = o
    return txt

# ============================================================
# EXTRACCION
# ============================================================
def extract_common(text) -> Dict[str, Any]:
    t = normalize(text)
    d = {}

    # Facturas
    facturas = sorted(set(re.findall(r"\b[A-Z]{1,5}\d{4,}[A-Z0-9\-]*\b", t)))
    hf = [x for x in facturas if x.startswith("HF")]
    d["Factura"] = hf[0] if hf else (facturas[0] if facturas else "")

    d["Fecha factura"] = ddmmyyyy(t)

    inc = re.search(r"\b(FOB|CIF|CFR|EXW|FCA|DAP|DDP|DDU|CPT|CIP)\b", t)
    d["Incoterm"] = inc.group(1) if inc else ""

    if "US$" in t or "US DOLLARS" in t:
        d["Moneda"] = "USD"
    else:
        mon = re.search(r"\b(USD|EUR|MXN|CNY|RMB|JPY)\b", t)
        d["Moneda"] = mon.group(1) if mon else ""

    bl = re.search(r"\b(ZIM[A-Z0-9]{8,}|ONEY[A-Z0-9]+|MAEU[A-Z0-9]+|HLCU[A-Z0-9]+|MEDU[A-Z0-9]+|CMDU[A-Z0-9]+|OOLU[A-Z0-9]+|COSU[A-Z0-9]+)\b", t)
    d["BL"] = bl.group(1) if bl else ""

    d["Contenedores"] = ", ".join(sorted(set(re.findall(r"\b[A-Z]{4}\d{7}\b", t))))

    # Sellos: más conservador para evitar series.
    seals = sorted(set(re.findall(r"\b[A-Z]{1,3}\d{8,12}\b", t)))
    d["Sellos"] = ", ".join(seals)

    # Series para montacargas/equipo. Ajustable.
    series = sorted(set(re.findall(r"\b(?:25|26)\d{6}\b", t)))
    d["Series"] = ", ".join(series)
    d["Cantidad series"] = len(series)

    vals = []
    patterns = [
        r"TOTAL(?:\(FOB [^)]+\))?[:\sA-Z()合计]*US\$?\s*([0-9,]+\.\d{2})",
        r"TOTAL[:\s]*\$?\s*([0-9,]+\.\d{2})",
        r"VAL\.?\s*MON\.?\s*FACT.*?([0-9,]+\.\d{2})",
        r"VALOR\s+DOLARES[:\s]*([0-9,]+\.\d{2})",
        r"VALOR\s+COMERCIAL[:\s]*([0-9,]+\.\d{2})",
    ]
    for pat in patterns:
        for x in re.findall(pat, t):
            n = number(x)
            if n:
                vals.append(n)
    d["Valor factura"] = max(vals) if vals else None

    wt = None
    for pat in [
        r"PESO\s*BRUTO[:\s]*([0-9,]+\.\d{2,3}|[0-9,]+)",
        r"TOTAL[:\sA-Z()]*([0-9,]+\.\d{2,3}|[0-9,]+)\s*KGS?",
        r"TOTAL\s*:\s*\d+X\d+HC\s*([0-9,]+\.\d{2,3}|[0-9,]+)",
    ]:
        m = re.search(pat, t)
        if m:
            wt = number(m.group(1))
            break
    d["Peso bruto kg"] = wt

    # Cantidad por patrones de packing/factura
    qty_candidates = []
    for q in re.findall(r"\b([0-9]+)\s+(?:PIEZA|PIEZAS|UNIT|UNITS|PKG|PKGS|PACKAGE|PACKAGES)\b", t):
        try:
            qty_candidates.append(int(q))
        except Exception:
            pass
    d["Cantidad total detectada"] = sum(qty_candidates) if qty_candidates else None

    return d

def extract_pedimento(text) -> Dict[str, Any]:
    t = normalize(text)
    d = extract_common(text)

    m = re.search(r"NUM\.?\s*PEDIMENTO[:\s]*([0-9]{2}\s+[0-9]{2}\s+[0-9]{4}\s+[0-9]{7}|[0-9 ]{15,25})", t)
    d["Pedimento"] = m.group(1).strip() if m else ""

    m = re.search(r"\bCVE\.?\s*PEDIM(?:ENTO)?[:\s]*([A-Z0-9]{2})\b", t)
    if not m:
        m = re.search(r"\b(A1|IN|AF|RT|V1)\b", t)
    d["Clave pedimento"] = m.group(1) if m else ""

    m = re.search(r"\bTIPO\s*OPER[:\s]*(IMP|EXP)\b", t)
    d["Tipo operación"] = m.group(1) if m else ("IMP" if " IMPORTADOR" in t or "IMP " in t else "")

    m = re.search(r"\bRFC[:\s]*([A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3})\b", t)
    d["RFC importador"] = m.group(1) if m else ""

    m = re.search(r"NOMBRE,\s*DENOMINACION\s*O\s*RAZON\s*SOCIAL[:\s]*(.*?)\s+(?:VAL\.|DOMICILIO|CURP)", t)
    d["Importador"] = m.group(1).strip() if m else ""

    m = re.search(r"DATOS DEL PROVEEDOR.*?NOMBRE,\s*DENOMINACION\s*O\s*RAZON\s*SOCIAL\s*(.*?)\s+VINCULACION", t)
    d["Proveedor"] = m.group(1).strip() if m else ""

    m = re.search(r"FRACCION.*?(\d{8})", t)
    d["Fracción"] = m.group(1) if m else ""

    m = re.search(r"VALOR\s+ADUANA[:\s]*([0-9,]+\.\d{2}|[0-9,]+)", t)
    d["Valor aduana MXN"] = number(m.group(1)) if m else None

    m = re.search(r"PRECIO\s+PAGADO/VALOR\s+COMERCIAL[:\s]*([0-9,]+\.\d{2}|[0-9,]+)", t)
    d["Valor comercial MXN"] = number(m.group(1)) if m else None

    m = re.search(r"TIPO\s*CAMBIO[:\s]*([0-9]+\.[0-9]+)", t)
    d["Tipo cambio"] = number(m.group(1)) if m else None

    m = re.search(r"FLETE\s*MAR[IÍ]TIMO[:\s]*([0-9,]+\.\d{2}|[0-9,]+)\s*USD", t)
    d["Flete USD"] = number(m.group(1)) if m else None

    m = re.search(r"SEGUROS[:\s]*([0-9,]+\.\d{2}|[0-9,]+)\s*USD", t)
    d["Seguro USD"] = number(m.group(1)) if m else None

    # Cantidad UMC pedimento
    m = re.search(r"UMC\s+CANTIDAD\s+UMC.*?\b6\s+([0-9]+\.\d+)", t)
    d["Cantidad UMC"] = number(m.group(1)) if m else d.get("Cantidad series")

    d["Borrador"] = "SI" if "BORRADOR SIN VALIDEZ" in t else "NO"
    return d

def extract_merchandise(text, doc_name) -> List[Dict[str, Any]]:
    t = normalize(text)
    rows = []

    # Invoice tipo Hifoune
    pat = r"(ELECTRIC FORKLIFT\s+FBL\d+).*?SERIAL NO\.?\s*([0-9;,\s]+).*?(\d+)\s+US\$?([0-9,]+\.\d{2})\s+US\$?([0-9,]+\.\d{2})"
    for m in re.finditer(pat, t):
        desc, ser, qty, unit, total = m.groups()
        rows.append({
            "Documento": doc_name,
            "Descripción / Modelo": desc.strip(),
            "Series": ", ".join(sorted(set(re.findall(r"\b(?:25|26)\d{6}\b", ser)))),
            "Cantidad": number(qty),
            "Precio unitario USD": number(unit),
            "Total USD": number(total)
        })

    # Carta traducción español
    pat2 = r"(MONTACARGAS ELECTRICO\s+[0-9.]+\s*TON.*?FUNCIONAMIENTO)\s+([0-9]+)\s+PIEZA\s+([0-9,]+\.\d{2})\s+([0-9,]+\.\d{2})"
    for m in re.finditer(pat2, t):
        desc, qty, unit, total = m.groups()
        rows.append({
            "Documento": doc_name,
            "Descripción / Modelo": desc.strip(),
            "Series": "",
            "Cantidad": number(qty),
            "Precio unitario USD": number(unit),
            "Total USD": number(total)
        })
    return rows

# ============================================================
# VALIDACIONES NIVEL AGENCIA
# ============================================================
def compare_field(field, ped_val, doc_vals, tolerance=0.02, mode="exact"):
    present = {k:v for k,v in doc_vals.items() if v not in [None, "", " "]}
    if not present:
        return "⚠️ No localizado", "No se encontró en soportes"

    matches = []
    diffs = []
    for name, val in present.items():
        if mode == "number":
            ok = abs(float(ped_val or 0) - float(val or 0)) <= tolerance
        elif mode == "set":
            ok = set_equal(ped_val, val)
        else:
            ok = normalize(ped_val) == normalize(val)

        if ok:
            matches.append(f"{name}: {text_fmt(val)}")
        else:
            diffs.append(f"{name}: {text_fmt(val)}")

    if diffs and not matches:
        return "❌ Diferencia", "; ".join(diffs)
    if diffs and matches:
        return "⚠️ Parcial", "Coincide: " + "; ".join(matches) + " | Diferente: " + "; ".join(diffs)
    return "✔️ Coincide", "; ".join(matches)

def build_glosa(ped_data, docs_data, tolerance):
    specs = [
        ("Factura", "exact", "CRITICO"),
        ("Fecha factura", "exact", "CRITICO"),
        ("Valor factura", "number", "CRITICO"),
        ("Incoterm", "exact", "MEDIO"),
        ("Moneda", "exact", "CRITICO"),
        ("Peso bruto kg", "number", "MEDIO"),
        ("BL", "exact", "CRITICO"),
        ("Contenedores", "set", "CRITICO"),
        ("Series", "set", "CRITICO"),
        ("Cantidad series", "number", "MEDIO"),
    ]
    rows = []
    for field, mode, risk in specs:
        doc_vals = {name: d.get(field) for name, d in docs_data.items()}
        status, detail = compare_field(field, ped_data.get(field), doc_vals, tolerance, mode)
        rows.append({
            "Riesgo": risk,
            "Campo": field,
            "Pedimento": money_fmt(ped_data.get(field)) if mode == "number" else text_fmt(ped_data.get(field)),
            "Estatus": status,
            "Soportes / Observaciones": detail
        })
    return pd.DataFrame(rows)

def build_audit_checks(ped_data, docs_data, merch_df):
    rows = []

    def add(check, status, risk, obs):
        rows.append({"Validación agencia": check, "Estatus": status, "Riesgo": risk, "Observación": obs})

    add(
        "Pedimento definitivo",
        "❌ Revisar" if ped_data.get("Borrador") == "SI" else "✔️ OK",
        "CRITICO" if ped_data.get("Borrador") == "SI" else "BAJO",
        "El documento indica BORRADOR SIN VALIDEZ" if ped_data.get("Borrador") == "SI" else "No se detectó leyenda de borrador"
    )

    inc = ped_data.get("Incoterm", "")
    flete = ped_data.get("Flete USD")
    seguro = ped_data.get("Seguro USD")
    if inc == "FOB":
        ok = (flete or 0) > 0 and (seguro or 0) > 0
        add(
            "Incrementables para FOB",
            "✔️ OK" if ok else "⚠️ Revisar",
            "MEDIO",
            f"FOB requiere revisar flete/seguro. Flete USD={flete}, Seguro USD={seguro}"
        )

    # Integridad de valor mercancía por líneas
    if merch_df is not None and not merch_df.empty and "Total USD" in merch_df:
        total_lines = pd.to_numeric(merch_df["Total USD"], errors="coerce").sum()
        ped_val = ped_data.get("Valor factura") or 0
        diff = abs(total_lines - ped_val)
        add(
            "Suma de partidas vs valor factura",
            "✔️ OK" if diff <= 0.02 else "❌ Revisar",
            "CRITICO" if diff > 0.02 else "BAJO",
            f"Suma líneas USD={total_lines:,.2f}; Pedimento USD={ped_val:,.2f}; Diferencia={diff:,.2f}"
        )

        qty_lines = pd.to_numeric(merch_df["Cantidad"], errors="coerce").sum()
        ped_qty = ped_data.get("Cantidad UMC") or ped_data.get("Cantidad series") or 0
        add(
            "Cantidad de mercancía vs líneas/series",
            "✔️ OK" if abs(qty_lines - ped_qty) <= 0.02 else "⚠️ Revisar",
            "MEDIO",
            f"Cantidad líneas={qty_lines:,.2f}; Pedimento={ped_qty:,.2f}"
        )
    else:
        add("Detalle de mercancía estructurado", "⚠️ Revisar", "MEDIO", "No se logró estructurar partidas; revisar visualmente factura/packing")

    # BL y contenedores obligatorios
    add(
        "BL declarado",
        "✔️ OK" if ped_data.get("BL") else "❌ Revisar",
        "CRITICO",
        ped_data.get("BL") or "No localizado"
    )
    add(
        "Contenedores declarados",
        "✔️ OK" if ped_data.get("Contenedores") else "❌ Revisar",
        "CRITICO",
        ped_data.get("Contenedores") or "No localizados"
    )

    return pd.DataFrame(rows)

def score(glosa_df, audit_df):
    all_status = list(glosa_df["Estatus"]) + list(audit_df["Estatus"])
    bad = sum("❌" in s for s in all_status)
    warn = sum("⚠️" in s for s in all_status)
    ok = sum("✔️" in s for s in all_status)
    total = max(len(all_status), 1)
    pct = round(ok / total * 100, 1)
    if bad:
        sem = "🔴 ALTO RIESGO"
    elif warn:
        sem = "🟡 REVISAR"
    else:
        sem = "🟢 LIBERABLE"
    return sem, pct, bad, warn, ok

# ============================================================
# UI
# ============================================================
st.markdown('<p class="main-title">🛃 Sistema de Glosa Aduanal</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-title">Nivel agencia aduanal: pedimento vs factura, packing list, BL/DO, incrementables, series, contenedores y reporte de auditoría.</p>', unsafe_allow_html=True)

with st.sidebar:
    st.header("Configuración")
    use_ocr = st.checkbox("OCR para PDFs escaneados", value=False)
    tolerance = st.number_input("Tolerancia importes/cantidades", 0.00, 20.00, 0.02, 0.01)
    show_text = st.checkbox("Mostrar texto extraído", value=False)
    st.markdown("---")
    st.caption("Recomendación: usa PDFs con texto seleccionable. Activa OCR solo si vienen escaneados.")

ped_file = st.file_uploader("1) PEDIMENTO PDF", type=["pdf"])
support_files = st.file_uploader("2) Documentos soporte PDF", type=["pdf"], accept_multiple_files=True)

if not ped_file:
    st.info("Carga el PEDIMENTO para iniciar.")
    st.stop()

if not support_files:
    st.info("Carga factura, packing list, BL/DO, carta traducción u otros soportes.")
    st.stop()

with st.spinner("Leyendo documentos y ejecutando glosa aduanal..."):
    ped_text = read_pdf(ped_file, use_ocr)
    ped_data = extract_pedimento(ped_text)

    docs_data = {}
    raw_texts = {"PEDIMENTO.pdf": ped_text}
    merch_rows = []

    for f in support_files:
        txt = read_pdf(f, use_ocr)
        raw_texts[f.name] = txt
        docs_data[f.name] = extract_common(txt)
        merch_rows.extend(extract_merchandise(txt, f.name))

    merch_df = pd.DataFrame(merch_rows) if merch_rows else pd.DataFrame()
    glosa_df = build_glosa(ped_data, docs_data, tolerance)
    audit_df = build_audit_checks(ped_data, docs_data, merch_df)
    sem, pct, bad, warn, ok = score(glosa_df, audit_df)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Semáforo", sem)
c2.metric("Score", f"{pct}%")
c3.metric("Críticas", bad)
c4.metric("Advertencias", warn)
c5.metric("OK", ok)

st.divider()

tabs = st.tabs([
    "📋 Resumen ejecutivo",
    "✅ Glosa comparativa",
    "🧠 Validaciones agencia",
    "📦 Mercancía",
    "📄 Pedimento",
    "📎 Soportes",
    "📝 Texto extraído"
])

with tabs[0]:
    st.subheader("Resumen ejecutivo")
    st.write(f"**Resultado:** {sem}")
    st.write(f"**Coincidencia general:** {pct}%")

    crit = glosa_df[glosa_df["Estatus"].str.contains("❌|⚠️", regex=True)]
    audcrit = audit_df[audit_df["Estatus"].str.contains("❌|⚠️", regex=True)]

    if crit.empty and audcrit.empty:
        st.success("No se detectaron diferencias relevantes. Operación aparentemente liberable.")
    else:
        st.warning("Se detectaron puntos para revisión antes de validar/liberar.")
        st.write("**Diferencias/campos a revisar:**")
        st.dataframe(pd.concat([
            crit.rename(columns={"Campo": "Concepto", "Soportes / Observaciones": "Observación"})[["Riesgo", "Concepto", "Estatus", "Observación"]],
            audcrit.rename(columns={"Validación agencia": "Concepto", "Observación": "Observación"})[["Riesgo", "Concepto", "Estatus", "Observación"]]
        ], ignore_index=True), use_container_width=True)

with tabs[1]:
    st.subheader("Glosa comparativa")
    st.dataframe(glosa_df, use_container_width=True)

with tabs[2]:
    st.subheader("Validaciones nivel agencia aduanal")
    st.dataframe(audit_df, use_container_width=True)

with tabs[3]:
    st.subheader("Mercancía detectada")
    if merch_df.empty:
        st.info("No se estructuró detalle de mercancía. Se recomienda revisar factura/packing visualmente.")
    else:
        st.dataframe(merch_df, use_container_width=True)
        st.caption(f"Total cantidad detectada: {pd.to_numeric(merch_df['Cantidad'], errors='coerce').sum():,.2f}")
        st.caption(f"Total valor detectado USD: {pd.to_numeric(merch_df['Total USD'], errors='coerce').sum():,.2f}")

with tabs[4]:
    st.subheader("Datos detectados del pedimento")
    st.dataframe(pd.DataFrame([ped_data]), use_container_width=True)

with tabs[5]:
    st.subheader("Datos detectados en soportes")
    st.dataframe(pd.DataFrame.from_dict(docs_data, orient="index"), use_container_width=True)

with tabs[6]:
    if show_text:
        selected = st.selectbox("Documento", list(raw_texts.keys()))
        st.text_area("Texto extraído", raw_texts[selected], height=520)
    else:
        st.info("Activa 'Mostrar texto extraído' en la barra lateral.")

# Export Excel
output = io.BytesIO()
with pd.ExcelWriter(output, engine="openpyxl") as writer:
    pd.DataFrame({
        "Resultado": [sem],
        "Score": [pct],
        "Críticas": [bad],
        "Advertencias": [warn],
        "OK": [ok],
        "Fecha reporte": [datetime.now().strftime("%d/%m/%Y %H:%M")]
    }).to_excel(writer, index=False, sheet_name="Resumen")
    glosa_df.to_excel(writer, index=False, sheet_name="Glosa")
    audit_df.to_excel(writer, index=False, sheet_name="Validaciones")
    pd.DataFrame([ped_data]).to_excel(writer, index=False, sheet_name="Pedimento")
    pd.DataFrame.from_dict(docs_data, orient="index").to_excel(writer, sheet_name="Soportes")
    if not merch_df.empty:
        merch_df.to_excel(writer, index=False, sheet_name="Mercancia")
    pd.DataFrame({"Documento": list(raw_texts.keys()), "Texto extraido": list(raw_texts.values())}).to_excel(writer, index=False, sheet_name="Texto")

st.download_button(
    "⬇️ Descargar reporte Excel nivel agencia",
    output.getvalue(),
    file_name=f"glosa_agencia_aduanal_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
