
import re
import io
from datetime import datetime
from typing import Dict, Any, List

import pandas as pd
import streamlit as st
from pypdf import PdfReader

try:
    import pdfplumber
except Exception:
    pdfplumber = None


st.set_page_config(
    page_title="Sistema de Glosa Aduanal",
    page_icon="🛃",
    layout="wide"
)

st.title("🛃 Sistema de Glosa Aduanal")
st.caption("Pedimento vs carta traducción, factura, packing list y BL/DO.")


# ============================================================
# UTILIDADES
# ============================================================
def normalize(text: Any) -> str:
    if text is None:
        return ""
    text = str(text).upper()
    replacements = {
        "；": ";",
        "，": ",",
        "：": ":",
        "（": "(",
        "）": ")",
        "\u00a0": " ",
        "Á": "A",
        "É": "E",
        "Í": "I",
        "Ó": "O",
        "Ú": "U",
    }
    for a, b in replacements.items():
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip()


def clean_number(value):
    if value in [None, ""]:
        return None
    s = str(value).upper()
    s = s.replace(",", "")
    s = s.replace("$", "")
    s = s.replace("US", "")
    s = s.replace("USD", "")
    s = s.replace("KGS", "")
    s = s.replace("KG", "")
    s = re.sub(r"[^0-9.\-]", "", s)
    try:
        return float(s)
    except Exception:
        return None


def fmt_money(value):
    if value in [None, ""]:
        return ""
    try:
        return f"{float(value):,.2f}"
    except Exception:
        return str(value)


def date_to_ddmmyyyy(text):
    if not text:
        return ""
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

    m = re.search(
        r"(JANUARY|JAN|FEBRUARY|FEB|MARCH|MAR|APRIL|APR|MAY|JUNE|JUN|JULY|JUL|AUGUST|AUG|SEPTEMBER|SEP|OCTOBER|OCT|NOVEMBER|NOV|DECEMBER|DEC)\.?\s*(\d{1,2})(?:ST|ND|RD|TH)?[,]?\s*(\d{4})",
        t
    )
    if m:
        return f"{int(m.group(2)):02d}/{months[m.group(1)]}/{m.group(3)}"

    return ""


def split_list(value):
    if not value:
        return []
    return sorted(set([x.strip() for x in str(value).replace(";", ",").split(",") if x.strip()]))


def same_set(a, b):
    return set(split_list(a)) == set(split_list(b))


# ============================================================
# LECTURA PDF
# ============================================================
def read_pdf_pypdf(uploaded_file):
    uploaded_file.seek(0)
    reader = PdfReader(uploaded_file)
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            pages.append(f"\n--- PAGINA {i} ---\n" + (page.extract_text() or ""))
        except Exception:
            pages.append(f"\n--- PAGINA {i} ---\n")
    return "\n".join(pages)


def read_pdf_pdfplumber(uploaded_file):
    if pdfplumber is None:
        return ""
    uploaded_file.seek(0)
    pages = []
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
                table_text = ""
                try:
                    for table in page.extract_tables() or []:
                        for row in table:
                            table_text += " | ".join(str(c or "") for c in row) + "\n"
                except Exception:
                    pass
                pages.append(f"\n--- PAGINA {i} ---\n{text}\n{table_text}")
    except Exception:
        return ""
    return "\n".join(pages)


def read_pdf(uploaded_file):
    a = read_pdf_pypdf(uploaded_file)
    b = read_pdf_pdfplumber(uploaded_file)
    return b if len(b) > len(a) else a


# ============================================================
# EXTRACCION ESPECIFICA
# ============================================================
def extract_invoice_no(t):
    # Prioridad específica para este patrón
    m = re.search(r"\bHF\d{8,}[A-Z0-9\-]*\b", t)
    if m:
        return m.group(0)

    m = re.search(r"(?:INVOICE\s*NO\.?|FACTURA\(S\)\s*NO\.?|FACTURA\s*NO\.?)\s*[:#]?\s*([A-Z0-9\-]+)", t)
    if m:
        return m.group(1)

    return ""


def extract_invoice_date(t, invoice_no=""):
    # Pedimento: HF20251124D-01 13/03/2026 FOB USD 222,715.00
    if invoice_no:
        m = re.search(re.escape(invoice_no) + r"\s+(\d{1,2}/\d{1,2}/\d{4})", t)
        if m:
            return date_to_ddmmyyyy(m.group(1))

    # Carta traducción: FECHA(S): 13/03/2026
    m = re.search(r"FECHA\(S\)\s*[:#]?\s*(\d{1,2}/\d{1,2}/\d{4})", t)
    if m:
        return date_to_ddmmyyyy(m.group(1))

    # Invoice comercial: Date: Mar. 13th, 2026
    m = re.search(r"\bDATE\s*[:#]?\s*([A-Z]+\.?\s*\d{1,2}(?:ST|ND|RD|TH)?[,]?\s*\d{4})", t)
    if m:
        return date_to_ddmmyyyy(m.group(1))

    return ""


def extract_invoice_value(t, invoice_no=""):
    # Pedimento: factura + fecha + FOB USD + valor
    if invoice_no:
        m = re.search(
            re.escape(invoice_no) + r"\s+\d{1,2}/\d{1,2}/\d{4}\s+(?:FOB|CIF|CFR|EXW|FCA|DAP|DDP)\s+(?:USD|EUR|MXN)\s+([0-9,]+\.\d{2})",
            t
        )
        if m:
            return clean_number(m.group(1))

    # Pedimento: USD 222,715.00 1.00000000 222,715.00
    m = re.search(r"\b(?:USD|EUR|MXN)\s+([0-9,]+\.\d{2})\s+1\.00000000\s+[0-9,]+\.\d{2}", t)
    if m:
        return clean_number(m.group(1))

    # Carta traducción: TOTAL: $222,715.00
    m = re.search(r"TOTAL\s*[:#]?\s*\$?\s*([0-9,]+\.\d{2})", t)
    if m:
        return clean_number(m.group(1))

    # Invoice comercial: TOTAL(FOB XIAMEN): 合计： US$222,715.00
    m = re.search(r"TOTAL\s*\(FOB[^)]*\)\s*[:#]?\s*(?:合计[:#]?)?\s*US\$?\s*([0-9,]+\.\d{2})", t)
    if m:
        return clean_number(m.group(1))

    # Fallback solo valores con US$
    us_values = [clean_number(x) for x in re.findall(r"US\$?\s*([0-9,]+\.\d{2})", t)]
    us_values = [x for x in us_values if x is not None]
    if us_values:
        return max(us_values)

    return None


def extract_weight(t):
    # Packing: TOTAL: ELEVEN(11)PKGS ONLY 73.500CBM 55,480.00KGS
    m = re.search(r"TOTAL\s*[:#]?.*?([0-9,]+\.\d{2})\s*KGS", t)
    if m:
        return clean_number(m.group(1))

    # Pedimento
    m = re.search(r"PESO\s*BRUTO[:\s]*([0-9,]+\.\d{2,3}|[0-9,]+)", t)
    if m:
        return clean_number(m.group(1))

    # DO / BL
    m = re.search(r"TOTAL\s*:\s*\d+X\d+HC\s+([0-9,]+\.\d{3}|[0-9,]+\.\d{2}|[0-9,]+)", t)
    if m:
        return clean_number(m.group(1))

    return None


def extract_common(text):
    t = normalize(text)
    invoice_no = extract_invoice_no(t)

    data = {
        "Factura": invoice_no,
        "Fecha factura": extract_invoice_date(t, invoice_no),
        "Valor factura": extract_invoice_value(t, invoice_no),
        "Incoterm": "",
        "Moneda": "",
        "Peso bruto kg": extract_weight(t),
        "BL": "",
        "Contenedores": "",
        "Series": "",
        "Cantidad series": 0,
        "Cantidad total": None,
    }

    m = re.search(r"\b(FOB|CIF|CFR|EXW|FCA|DAP|DDP|CPT|CIP)\b", t)
    if m:
        data["Incoterm"] = m.group(1)

    if "US$" in t or " USD " in f" {t} " or "US DOLLARS" in t:
        data["Moneda"] = "USD"
    else:
        m = re.search(r"\b(USD|EUR|MXN|CNY|RMB|JPY)\b", t)
        data["Moneda"] = m.group(1) if m else ""

    m = re.search(r"\b(ZIM[A-Z0-9]{8,}|ONEY[A-Z0-9]+|MAEU[A-Z0-9]+|HLCU[A-Z0-9]+|MEDU[A-Z0-9]+|CMDU[A-Z0-9]+)\b", t)
    if m:
        data["BL"] = m.group(1)

    data["Contenedores"] = ", ".join(sorted(set(re.findall(r"\b[A-Z]{4}\d{7}\b", t))))

    series = sorted(set(re.findall(r"\b(?:25|26)\d{6}\b", t)))
    data["Series"] = ", ".join(series)
    data["Cantidad series"] = len(series)

    # Cantidades de líneas comerciales: evita contar fechas
    qtys = []
    for m in re.finditer(r"\b(\d+)\s*(?:PIEZA|PIEZAS|UNIT|UNITS|PKG|PKGS)\b", t):
        try:
            qtys.append(int(m.group(1)))
        except Exception:
            pass
    data["Cantidad total"] = sum(qtys) if qtys else None

    return data


def extract_pedimento(text):
    t = normalize(text)
    data = extract_common(text)

    m = re.search(r"NUM\.?\s*PEDIMENTO[:\s]*([0-9]{2}\s+[0-9]{2}\s+[0-9]{4}\s+[0-9]{7}|[0-9 ]{15,25})", t)
    data["Pedimento"] = m.group(1).strip() if m else ""

    m = re.search(r"\bCVE\.?\s*PEDIM(?:ENTO)?[:\s]*([A-Z0-9]{2})\b", t)
    data["Clave pedimento"] = m.group(1) if m else ""

    m = re.search(r"\bRFC[:\s]*([A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3})\b", t)
    data["RFC importador"] = m.group(1) if m else ""

    m = re.search(r"FRACCION.*?(\d{8})", t)
    data["Fracción"] = m.group(1) if m else ""

    m = re.search(r"FLETE\s*MAR[IÍ]TIMO[:\s]*([0-9,]+\.\d{2}|[0-9,]+)\s*USD", t)
    data["Flete USD"] = clean_number(m.group(1)) if m else None

    m = re.search(r"SEGUROS[:\s]*([0-9,]+\.\d{2}|[0-9,]+)\s*USD", t)
    data["Seguro USD"] = clean_number(m.group(1)) if m else None

    m = re.search(r"UMC\s+CANTIDAD\s+UMC.*?\b6\s+([0-9]+\.\d+)", t)
    if m:
        data["Cantidad total"] = clean_number(m.group(1))
    elif data.get("Cantidad series"):
        data["Cantidad total"] = data["Cantidad series"]

    data["Borrador"] = "SI" if "BORRADOR SIN VALIDEZ" in t else "NO"

    return data


def extract_merchandise(text, doc_name):
    t = normalize(text)
    rows = []

    # Invoice inglés
    pattern_en = r"(ELECTRIC FORKLIFT\s+FBL\d+).*?SERIAL NO\.?\s*([0-9;,\s]+).*?(\d+)\s+US\$?([0-9,]+\.\d{2})\s+US\$?([0-9,]+\.\d{2})"
    for m in re.finditer(pattern_en, t):
        desc, serial_text, qty, unit, total = m.groups()
        series = sorted(set(re.findall(r"\b(?:25|26)\d{6}\b", serial_text)))
        rows.append({
            "Documento": doc_name,
            "Descripción": desc,
            "Series": ", ".join(series),
            "Cantidad": clean_number(qty),
            "Precio unitario USD": clean_number(unit),
            "Total USD": clean_number(total),
        })

    # Carta español
    pattern_es = r"(MONTACARGAS ELECTRICO\s+[0-9.]+\s*TON.*?FUNCIONAMIENTO)\s+(\d+)\s+PIEZA\s+([0-9,]+\.\d{2})\s+([0-9,]+\.\d{2})"
    for m in re.finditer(pattern_es, t):
        desc, qty, unit, total = m.groups()
        rows.append({
            "Documento": doc_name,
            "Descripción": desc,
            "Series": "",
            "Cantidad": clean_number(qty),
            "Precio unitario USD": clean_number(unit),
            "Total USD": clean_number(total),
        })

    return rows


# ============================================================
# COMPARACIÓN
# ============================================================
def compare_field(field, ped_value, doc_values, mode="exact", tolerance=0.02):
    present = {k: v for k, v in doc_values.items() if v not in [None, "", " "]}

    if not present:
        return "⚠️ No localizado", "No se encontró en soportes"

    ok_list = []
    diff_list = []

    for name, val in present.items():
        if mode == "number":
            ok = ped_value not in [None, ""] and abs(float(ped_value or 0) - float(val or 0)) <= tolerance
            shown = fmt_money(val)
        elif mode == "set":
            ok = same_set(ped_value, val)
            shown = val
        else:
            ok = normalize(ped_value) == normalize(val)
            shown = val

        if ok:
            ok_list.append(f"{name}: {shown}")
        else:
            diff_list.append(f"{name}: {shown}")

    if diff_list and not ok_list:
        return "❌ Diferencia", "; ".join(diff_list)
    if diff_list and ok_list:
        return "⚠️ Parcial", "Coincide: " + "; ".join(ok_list) + " | Diferente: " + "; ".join(diff_list)
    return "✔️ Coincide", "; ".join(ok_list)


def build_glosa(ped_data, docs_data, tolerance):
    fields = [
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
        ("Cantidad total", "number", "MEDIO"),
    ]

    rows = []
    for field, mode, risk in fields:
        doc_vals = {name: data.get(field) for name, data in docs_data.items()}
        status, detail = compare_field(field, ped_data.get(field), doc_vals, mode, tolerance)
        rows.append({
            "Riesgo": risk,
            "Campo": field,
            "Pedimento": fmt_money(ped_data.get(field)) if mode == "number" else str(ped_data.get(field) or ""),
            "Estatus": status,
            "Soportes / Observaciones": detail,
        })

    return pd.DataFrame(rows)


def build_audit(ped_data, merch_df):
    rows = []

    def add(name, status, risk, obs):
        rows.append({
            "Validación agencia": name,
            "Estatus": status,
            "Riesgo": risk,
            "Observación": obs,
        })

    add(
        "Pedimento definitivo",
        "❌ Revisar" if ped_data.get("Borrador") == "SI" else "✔️ OK",
        "CRITICO" if ped_data.get("Borrador") == "SI" else "BAJO",
        "El documento indica BORRADOR SIN VALIDEZ" if ped_data.get("Borrador") == "SI" else "No se detectó leyenda de borrador",
    )

    if ped_data.get("Incoterm") == "FOB":
        flete = ped_data.get("Flete USD")
        seguro = ped_data.get("Seguro USD")
        ok = (flete or 0) > 0 and (seguro or 0) > 0
        add(
            "Incrementables para FOB",
            "✔️ OK" if ok else "⚠️ Revisar",
            "MEDIO",
            f"Flete USD={fmt_money(flete)}, Seguro USD={fmt_money(seguro)}",
        )

    if merch_df is not None and not merch_df.empty:
        total = pd.to_numeric(merch_df["Total USD"], errors="coerce").sum()
        ped_val = ped_data.get("Valor factura") or 0
        diff = abs(total - ped_val)
        add(
            "Suma de partidas vs valor factura",
            "✔️ OK" if diff <= 0.02 else "❌ Revisar",
            "CRITICO" if diff > 0.02 else "BAJO",
            f"Suma partidas USD={total:,.2f}; pedimento USD={ped_val:,.2f}; diferencia={diff:,.2f}",
        )
    else:
        add(
            "Detalle de mercancía estructurado",
            "⚠️ Revisar",
            "MEDIO",
            "No se logró estructurar partidas; revisar visualmente factura/packing",
        )

    return pd.DataFrame(rows)


def score(glosa_df, audit_df):
    statuses = list(glosa_df["Estatus"]) + list(audit_df["Estatus"])
    bad = sum("❌" in x for x in statuses)
    warn = sum("⚠️" in x for x in statuses)
    ok = sum("✔️" in x for x in statuses)
    total = max(len(statuses), 1)
    pct = round(ok / total * 100, 1)

    if bad:
        return "🔴 ALTO RIESGO", pct, bad, warn, ok
    if warn:
        return "🟡 REVISAR", pct, bad, warn, ok
    return "🟢 LIBERABLE", pct, bad, warn, ok


# ============================================================
# INTERFAZ
# ============================================================
with st.sidebar:
    st.header("Configuración")
    tolerance = st.number_input("Tolerancia importes/cantidades", 0.00, 20.00, 0.02, 0.01)
    show_text = st.checkbox("Mostrar texto extraído", value=False)

ped_file = st.file_uploader("1) PEDIMENTO PDF", type=["pdf"])
support_files = st.file_uploader("2) Documentos soporte PDF", type=["pdf"], accept_multiple_files=True)

if not ped_file:
    st.info("Carga el PEDIMENTO para iniciar.")
    st.stop()

if not support_files:
    st.info("Carga factura, packing list, BL/DO, carta traducción u otros soportes.")
    st.stop()

with st.spinner("Procesando glosa..."):
    ped_text = read_pdf(ped_file)
    ped_data = extract_pedimento(ped_text)

    docs_data = {}
    raw_texts = {"PEDIMENTO.pdf": ped_text}
    merch_rows = []

    for f in support_files:
        text = read_pdf(f)
        raw_texts[f.name] = text
        docs_data[f.name] = extract_common(text)
        merch_rows.extend(extract_merchandise(text, f.name))

    merch_df = pd.DataFrame(merch_rows) if merch_rows else pd.DataFrame()
    glosa_df = build_glosa(ped_data, docs_data, tolerance)
    audit_df = build_audit(ped_data, merch_df)
    sem, pct, bad, warn, ok = score(glosa_df, audit_df)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Semáforo", sem)
c2.metric("Score", f"{pct}%")
c3.metric("Críticas", bad)
c4.metric("Advertencias", warn)
c5.metric("OK", ok)

tabs = st.tabs([
    "📋 Resumen ejecutivo",
    "✅ Glosa comparativa",
    "🧠 Validaciones agencia",
    "📦 Mercancía",
    "📄 Pedimento",
    "📎 Soportes",
    "📝 Texto extraído",
])

with tabs[0]:
    st.subheader("Resumen ejecutivo")
    st.write(f"**Resultado:** {sem}")
    st.write(f"**Coincidencia general:** {pct}%")

    issues1 = glosa_df[glosa_df["Estatus"].str.contains("❌|⚠️", regex=True)]
    issues2 = audit_df[audit_df["Estatus"].str.contains("❌|⚠️", regex=True)]

    if issues1.empty and issues2.empty:
        st.success("No se detectaron diferencias relevantes.")
    else:
        st.warning("Se detectaron puntos para revisión antes de validar/liberar.")
        output_issues = []
        if not issues1.empty:
            output_issues.append(
                issues1.rename(columns={"Campo": "Concepto", "Soportes / Observaciones": "Observación"})[
                    ["Riesgo", "Concepto", "Estatus", "Observación"]
                ]
            )
        if not issues2.empty:
            output_issues.append(
                issues2.rename(columns={"Validación agencia": "Concepto"})[
                    ["Riesgo", "Concepto", "Estatus", "Observación"]
                ]
            )
        st.dataframe(pd.concat(output_issues, ignore_index=True), use_container_width=True)

with tabs[1]:
    st.subheader("Glosa comparativa")
    st.dataframe(glosa_df, use_container_width=True)

with tabs[2]:
    st.subheader("Validaciones nivel agencia")
    st.dataframe(audit_df, use_container_width=True)

with tabs[3]:
    st.subheader("Mercancía detectada")
    if merch_df.empty:
        st.info("No se estructuró detalle de mercancía.")
    else:
        st.dataframe(merch_df, use_container_width=True)

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

# Excel
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

    pd.DataFrame({
        "Documento": list(raw_texts.keys()),
        "Texto extraido": list(raw_texts.values())
    }).to_excel(writer, index=False, sheet_name="Texto")

st.download_button(
    "⬇️ Descargar reporte Excel nivel agencia",
    output.getvalue(),
    file_name=f"glosa_agencia_aduanal_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
