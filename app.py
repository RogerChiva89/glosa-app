
import re
import io
import json
from datetime import datetime
from typing import Any, Dict, List, Tuple

import pandas as pd
import streamlit as st
from pypdf import PdfReader

try:
    import pdfplumber
except Exception:
    pdfplumber = None


st.set_page_config(
    page_title="Glosa Aduanal Multi-Proveedor",
    page_icon="🛃",
    layout="wide"
)

st.title("🛃 Glosa Aduanal Multi-Proveedor")
st.caption("Motor genérico + reglas por documento + validación manual antes de comparar.")


# ============================================================
# UTILIDADES
# ============================================================
def normalize(text: Any) -> str:
    if text is None:
        return ""
    text = str(text).upper()
    repl = {
        "；": ";", "，": ",", "：": ":", "（": "(", "）": ")",
        "\u00a0": " ", "Á": "A", "É": "E", "Í": "I", "Ó": "O", "Ú": "U"
    }
    for a, b in repl.items():
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip()


def clean_number(value):
    if value in [None, ""]:
        return None
    s = str(value).upper()
    s = s.replace(",", "").replace("$", "").replace("US", "").replace("USD", "")
    s = s.replace("KGS", "").replace("KG", "").replace("MXN", "").replace("EUR", "")
    s = re.sub(r"[^0-9.\-]", "", s)
    try:
        return float(s)
    except Exception:
        return None


def fmt_num(value):
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

    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", t)
    if m:
        return f"{int(m.group(3)):02d}/{int(m.group(2)):02d}/{m.group(1)}"

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


def split_values(value):
    if not value:
        return []
    return sorted(set([x.strip() for x in str(value).replace(";", ",").split(",") if x.strip()]))


def same_set(a, b):
    return set(split_values(a)) == set(split_values(b))


# ============================================================
# LECTURA DE PDF
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
# CLASIFICACIÓN DE DOCUMENTOS
# ============================================================
def classify_doc(text: str, filename: str = "") -> str:
    t = normalize(text + " " + filename)

    if "NUM. PEDIMENTO" in t or "ANEXO DEL PEDIMENTO" in t:
        return "PEDIMENTO"

    if "COMMERCIAL INVOICE" in t or "INVOICE NO" in t or "FACTURA(S)" in t or "FACTURA" in t:
        if "PACKING LIST" in t:
            return "INVOICE_PACKING"
        return "INVOICE"

    if "PACKING LIST" in t or "LISTA DE EMPAQUE" in t:
        return "PACKING"

    if "DELIVERY ORDER" in t or "B/L NO" in t or "BILL OF LADING" in t or "CONOCIMIENTO MARITIMO" in t:
        return "BL_DO"

    return "SOPORTE"


# ============================================================
# EXTRACTORES GENÉRICOS
# ============================================================
def get_invoice_candidates(t: str) -> List[str]:
    candidates = []

    patterns = [
        r"(?:INVOICE\s*NO\.?|INVOICE\s*NUMBER|FACTURA\(S\)\s*NO\.?|FACTURA\s*NO\.?|NO\.?\s*FACTURA|NUMERO\s*DE\s*FACTURA)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-\/]{4,})",
        r"\b([A-Z]{1,5}\d{4,}[A-Z0-9\-\/]{0,})\b",
    ]

    for pat in patterns:
        for m in re.findall(pat, t):
            val = m.strip().strip(":")
            if len(val) >= 5:
                candidates.append(val)

    # Filtrar cosas que parecen contenedores o BL
    filtered = []
    for c in candidates:
        if re.match(r"^[A-Z]{4}\d{7}$", c):
            continue
        if c.startswith("ZIM") and len(c) > 8:
            continue
        if c not in filtered:
            filtered.append(c)

    return filtered


def choose_invoice(candidates: List[str]) -> str:
    if not candidates:
        return ""
    # Priorizar facturas con guion o prefijo alfanumérico típico
    scored = []
    for c in candidates:
        score = 0
        if "-" in c:
            score += 5
        if re.search(r"[A-Z]", c) and re.search(r"\d", c):
            score += 3
        if c.startswith(("HF", "INV", "CI", "FAC")):
            score += 4
        scored.append((score, c))
    scored.sort(reverse=True)
    return scored[0][1]


def extract_date_near_keywords(t: str, invoice_no: str = "") -> str:
    # 1) Cerca de factura específica
    if invoice_no:
        idx = t.find(invoice_no)
        if idx >= 0:
            window = t[idx:idx + 250]
            d = date_to_ddmmyyyy(window)
            if d:
                return d

    # 2) Keywords
    patterns = [
        r"(?:INVOICE\s*DATE|DATE|FECHA\(S\)|FECHA\s*FACTURA|FECHA)\s*[:#]?\s*([A-Z]+\.?\s*\d{1,2}(?:ST|ND|RD|TH)?[,]?\s*\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})"
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            d = date_to_ddmmyyyy(m.group(1))
            if d:
                return d

    return ""


def extract_total_value(t: str, doc_type: str = "", invoice_no: str = ""):
    # 1) Pedimento, línea de factura: FACTURA FECHA INCOTERM MONEDA VALOR FACTOR VALOR
    if invoice_no:
        pat = re.escape(invoice_no) + r"\s+\d{1,2}/\d{1,2}/\d{4}\s+(?:FOB|CIF|CFR|EXW|FCA|DAP|DDP|CPT|CIP)\s+(?:USD|EUR|MXN)\s+([0-9,]+\.\d{2})"
        m = re.search(pat, t)
        if m:
            return clean_number(m.group(1))

    # 2) Pedimento, patrón monetario tabla
    m = re.search(r"\b(?:USD|EUR|MXN)\s+([0-9,]+\.\d{2})\s+1\.00000000\s+[0-9,]+\.\d{2}", t)
    if m:
        return clean_number(m.group(1))

    # 3) Totales explícitos
    patterns = [
        r"GRAND\s*TOTAL\s*[:#]?\s*(?:US\$|USD|\$)?\s*([0-9,]+\.\d{2})",
        r"TOTAL\s*\([^)]*\)\s*[:#]?\s*(?:合计[:#]?)?\s*(?:US\$|USD|\$)?\s*([0-9,]+\.\d{2})",
        r"TOTAL\s*[:#]?\s*(?:US\$|USD|\$)?\s*([0-9,]+\.\d{2})",
        r"AMOUNT\s*[:#]?\s*(?:US\$|USD|\$)?\s*([0-9,]+\.\d{2})",
        r"VALOR\s*TOTAL\s*[:#]?\s*(?:US\$|USD|\$)?\s*([0-9,]+\.\d{2})",
    ]

    for pat in patterns:
        m = re.search(pat, t)
        if m:
            return clean_number(m.group(1))

    # 4) Suma de partidas si detecta pares unit/amount
    amounts = [clean_number(x) for x in re.findall(r"(?:US\$|USD)\s*([0-9,]+\.\d{2})", t)]
    amounts = [x for x in amounts if x is not None]
    if amounts:
        return max(amounts)

    return None


def extract_incoterm(t: str) -> str:
    m = re.search(r"\b(FOB|CIF|CFR|EXW|FCA|DAP|DDP|DDU|CPT|CIP)\b", t)
    return m.group(1) if m else ""


def extract_currency(t: str) -> str:
    if "US$" in t or "US DOLLARS" in t or " USD " in f" {t} ":
        return "USD"
    m = re.search(r"\b(USD|EUR|MXN|CNY|RMB|JPY)\b", t)
    return m.group(1) if m else ""


def extract_bl(t: str) -> str:
    patterns = [
        r"(?:B/L\s*NO\.?|BL\s*NO\.?|BILL\s*OF\s*LADING\s*NO\.?|NO\.?\s*\(GUIA/ORDEN EMBARQUE\)/ID)\s*[:#]?\s*([A-Z0-9]{8,})",
        r"\b(ZIM[A-Z0-9]{8,}|ONEY[A-Z0-9]+|MAEU[A-Z0-9]+|HLCU[A-Z0-9]+|MEDU[A-Z0-9]+|CMDU[A-Z0-9]+|OOLU[A-Z0-9]+|COSU[A-Z0-9]+)\b",
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            return m.group(1)
    return ""


def extract_containers(t: str) -> str:
    return ", ".join(sorted(set(re.findall(r"\b[A-Z]{4}\d{7}\b", t))))


def extract_series(t: str) -> str:
    # Genérico conservador: series numéricas largas, excluye contenedores y montos.
    # Para maquinaria, muchos proveedores usan series de 7-12 dígitos.
    raw = re.findall(r"\b[A-Z]?\d{7,14}[A-Z]?\b", t)
    filtered = []
    for s in raw:
        if "." in s or "," in s:
            continue
        if len(s) == 8 and s.startswith(("20", "19")):
            # evita fechas/años compactos
            continue
        if s not in filtered:
            filtered.append(s)

    # Para este caso, los números empiezan 25/26 y son 8 dígitos
    machine = re.findall(r"\b(?:25|26)\d{6}\b", t)
    if machine:
        filtered = sorted(set(machine))

    return ", ".join(sorted(set(filtered)))


def extract_weight(t: str):
    patterns = [
        r"PESO\s*BRUTO[:\s]*([0-9,]+\.\d{2,3}|[0-9,]+)",
        r"GROSS\s*WEIGHT\s*\(?KG\)?[:\s]*([0-9,]+\.\d{2,3}|[0-9,]+)",
        r"TOTAL\s*[:#]?.*?([0-9,]+\.\d{2,3}|[0-9,]+)\s*KGS?",
        r"TOTAL\s*:\s*\d+X\d+HC\s+([0-9,]+\.\d{2,3}|[0-9,]+)",
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            return clean_number(m.group(1))
    return None


def extract_quantity(t: str):
    qtys = []
    for m in re.finditer(r"\b(\d+)\s*(?:PIEZA|PIEZAS|PCS|PIECES|UNIT|UNITS|PKG|PKGS|PACKAGE|PACKAGES)\b", t):
        try:
            qtys.append(int(m.group(1)))
        except Exception:
            pass
    return sum(qtys) if qtys else None


# ============================================================
# EXTRACCIÓN PRINCIPAL
# ============================================================
def extract_fields(text: str, filename: str = "") -> Dict[str, Any]:
    t = normalize(text)
    doc_type = classify_doc(text, filename)

    invoice_candidates = get_invoice_candidates(t)
    invoice_no = choose_invoice(invoice_candidates)

    data = {
        "Tipo documento": doc_type,
        "Factura": invoice_no,
        "Fecha factura": extract_date_near_keywords(t, invoice_no),
        "Valor factura": extract_total_value(t, doc_type, invoice_no),
        "Incoterm": extract_incoterm(t),
        "Moneda": extract_currency(t),
        "Peso bruto kg": extract_weight(t),
        "BL": extract_bl(t),
        "Contenedores": extract_containers(t),
        "Series": extract_series(t),
        "Cantidad series": len(split_values(extract_series(t))),
        "Cantidad total": extract_quantity(t),
    }

    if doc_type == "PEDIMENTO":
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
        elif data["Cantidad series"]:
            data["Cantidad total"] = data["Cantidad series"]

        data["Borrador"] = "SI" if "BORRADOR SIN VALIDEZ" in t else "NO"

    return data


def extract_merchandise(text: str, filename: str) -> List[Dict[str, Any]]:
    t = normalize(text)
    rows = []

    # Patrón inglés: descripción + serial no + qty + unit + amount
    pat_en = r"([A-Z][A-Z0-9\s\-/\.]{4,80})\s+SERIAL\s*NO\.?\s*([A-Z0-9;,\s\-]+?)\s+(\d+)\s+(?:US\$|USD|\$)?\s*([0-9,]+\.\d{2})\s+(?:US\$|USD|\$)?\s*([0-9,]+\.\d{2})"
    for m in re.finditer(pat_en, t):
        desc, ser, qty, unit, total = m.groups()
        rows.append({
            "Documento": filename,
            "Descripción": desc.strip(),
            "Series": ", ".join(sorted(set(re.findall(r"\b[A-Z]?\d{7,14}[A-Z]?\b", ser)))),
            "Cantidad": clean_number(qty),
            "Precio unitario": clean_number(unit),
            "Total": clean_number(total),
        })

    # Patrón español: descripción + qty + UMC + unit + total
    pat_es = r"([A-ZÁÉÍÓÚÑ0-9\s\-/\.,]{10,160})\s+(\d+)\s+(?:PIEZA|PIEZAS|PCS|UNIT|UNITS)\s+([0-9,]+\.\d{2})\s+([0-9,]+\.\d{2})"
    for m in re.finditer(pat_es, t):
        desc, qty, unit, total = m.groups()
        rows.append({
            "Documento": filename,
            "Descripción": desc.strip(),
            "Series": "",
            "Cantidad": clean_number(qty),
            "Precio unitario": clean_number(unit),
            "Total": clean_number(total),
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
            shown = fmt_num(val)
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
            "Pedimento": fmt_num(ped_data.get(field)) if mode == "number" else str(ped_data.get(field) or ""),
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

    if ped_data.get("Tipo documento") == "PEDIMENTO":
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
            f"Flete USD={fmt_num(flete)}, Seguro USD={fmt_num(seguro)}",
        )

    if merch_df is not None and not merch_df.empty:
        total = pd.to_numeric(merch_df["Total"], errors="coerce").sum()
        ped_val = ped_data.get("Valor factura") or 0
        diff = abs(total - ped_val)
        add(
            "Suma de partidas vs valor factura",
            "✔️ OK" if diff <= 0.02 else "❌ Revisar",
            "CRITICO" if diff > 0.02 else "BAJO",
            f"Suma partidas={total:,.2f}; pedimento={ped_val:,.2f}; diferencia={diff:,.2f}",
        )
    else:
        add(
            "Detalle de mercancía estructurado",
            "⚠️ Revisar",
            "MEDIO",
            "No se logró estructurar partidas automáticamente.",
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
# UI
# ============================================================
with st.sidebar:
    st.header("Configuración")
    tolerance = st.number_input("Tolerancia importes/cantidades", 0.00, 50.00, 0.02, 0.01)
    show_text = st.checkbox("Mostrar texto extraído", value=False)
    st.info("Flujo recomendado: 1) cargar PDFs, 2) revisar/corregir datos detectados, 3) ejecutar glosa.")

ped_file = st.file_uploader("1) Carga el PEDIMENTO PDF", type=["pdf"])
support_files = st.file_uploader("2) Carga documentos soporte PDF", type=["pdf"], accept_multiple_files=True)

if not ped_file:
    st.info("Carga el PEDIMENTO para iniciar.")
    st.stop()

if not support_files:
    st.info("Carga factura, packing list, BL/DO, carta traducción u otros soportes.")
    st.stop()

# Lectura
with st.spinner("Leyendo PDFs..."):
    ped_text = read_pdf(ped_file)
    ped_detected = extract_fields(ped_text, ped_file.name)

    docs_detected = {}
    raw_texts = {ped_file.name: ped_text}
    merch_rows = []

    for f in support_files:
        txt = read_pdf(f)
        raw_texts[f.name] = txt
        docs_detected[f.name] = extract_fields(txt, f.name)
        merch_rows.extend(extract_merchandise(txt, f.name))

# Validación manual
st.subheader("1) Revisión y corrección manual de datos detectados")
st.caption("Corrige aquí cualquier dato antes de ejecutar la glosa. Esta parte es clave para documentos de distintos proveedores.")

with st.expander("📄 Datos detectados del PEDIMENTO", expanded=True):
    ped_edit_df = pd.DataFrame([ped_detected])
    ped_edit_df = st.data_editor(
        ped_edit_df,
        num_rows="fixed",
        use_container_width=True,
        key="ped_editor"
    )

with st.expander("📎 Datos detectados en documentos soporte", expanded=True):
    docs_edit_df = pd.DataFrame.from_dict(docs_detected, orient="index").reset_index().rename(columns={"index": "Archivo"})
    docs_edit_df = st.data_editor(
        docs_edit_df,
        num_rows="fixed",
        use_container_width=True,
        key="docs_editor"
    )

ped_data = ped_edit_df.iloc[0].to_dict()
docs_data = {}
for _, row in docs_edit_df.iterrows():
    name = row.get("Archivo")
    d = row.drop(labels=["Archivo"]).to_dict()
    docs_data[name] = d

# Mercancía editable
merch_df = pd.DataFrame(merch_rows) if merch_rows else pd.DataFrame(columns=["Documento", "Descripción", "Series", "Cantidad", "Precio unitario", "Total"])

with st.expander("📦 Detalle de mercancía detectado / editable", expanded=False):
    merch_df = st.data_editor(
        merch_df,
        num_rows="dynamic",
        use_container_width=True,
        key="merch_editor"
    )

st.subheader("2) Resultado de glosa")

if st.button("🔎 Ejecutar glosa con datos revisados", type="primary"):
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
        "📝 Texto extraído",
    ])

    with tabs[0]:
        issues1 = glosa_df[glosa_df["Estatus"].str.contains("❌|⚠️", regex=True)]
        issues2 = audit_df[audit_df["Estatus"].str.contains("❌|⚠️", regex=True)]

        st.write(f"**Resultado:** {sem}")
        st.write(f"**Coincidencia general:** {pct}%")

        if issues1.empty and issues2.empty:
            st.success("No se detectaron diferencias relevantes.")
        else:
            st.warning("Se detectaron puntos para revisión.")
            rows = []
            if not issues1.empty:
                rows.append(issues1.rename(columns={"Campo": "Concepto", "Soportes / Observaciones": "Observación"})[["Riesgo", "Concepto", "Estatus", "Observación"]])
            if not issues2.empty:
                rows.append(issues2.rename(columns={"Validación agencia": "Concepto"})[["Riesgo", "Concepto", "Estatus", "Observación"]])
            st.dataframe(pd.concat(rows, ignore_index=True), use_container_width=True)

    with tabs[1]:
        st.dataframe(glosa_df, use_container_width=True)

    with tabs[2]:
        st.dataframe(audit_df, use_container_width=True)

    with tabs[3]:
        st.dataframe(merch_df, use_container_width=True)

    with tabs[4]:
        if show_text:
            selected = st.selectbox("Documento", list(raw_texts.keys()))
            st.text_area("Texto extraído", raw_texts[selected], height=520)
        else:
            st.info("Activa 'Mostrar texto extraído' en la barra lateral.")

    # Exportar Excel
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
        merch_df.to_excel(writer, index=False, sheet_name="Mercancia")
        pd.DataFrame({"Documento": list(raw_texts.keys()), "Texto extraido": list(raw_texts.values())}).to_excel(writer, index=False, sheet_name="Texto")

    st.download_button(
        "⬇️ Descargar reporte Excel",
        output.getvalue(),
        file_name=f"glosa_multiproveedor_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

else:
    st.info("Revisa/corrige los datos detectados y luego presiona **Ejecutar glosa**.")
