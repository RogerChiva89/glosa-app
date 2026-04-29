
import re
import streamlit as st
from pypdf import PdfReader

st.set_page_config(page_title="Glosa V3.1 - Facturas robustas", layout="wide")
st.title("Glosa Auditoría V3.1 - Facturas robustas")

def read_pdf(file):
    reader = PdfReader(file)
    text = ""
    for p in reader.pages:
        text += "\n" + (p.extract_text() or "")
    return re.sub(r"\s+", " ", text).strip()

def clean_text(v):
    return re.sub(r"\s+", " ", str(v or "")).strip(" .,:;-")

def normalize_date(v):
    v = clean_text(v)

    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", v)
    if m:
        return f"{int(m.group(1)):02d}/{int(m.group(2)):02d}/{m.group(3)}"

    m = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", v)
    if m:
        return f"{int(m.group(3)):02d}/{int(m.group(2)):02d}/{m.group(1)}"

    return ""

def money_to_float(v):
    if not v:
        return None
    s = str(v).replace(",", "")
    s = re.sub(r"[^0-9.\-]", "", s)
    try:
        return float(s)
    except Exception:
        return None

def format_money(v):
    if v is None:
        return ""
    try:
        return f"{float(v):,.2f}"
    except Exception:
        return str(v)

def extract_invoice_number(text):
    patterns = [
        r"Invoice\s*n[°ºo\.]*\s*[:#]?\s*([A-Z0-9][A-Z0-9\-\/]+)",
        r"Invoice\s*No\.?\s*[:#]?\s*([A-Z0-9][A-Z0-9\-\/]+)",
        r"Factura\s*[:#]?\s*([A-Z0-9][A-Z0-9\-\/]+)",
    ]

    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return m.group(1).upper().strip()

    return ""

def extract_invoice_date(text):
    # Prioridad: fecha junto a "Date:"
    m = re.search(
        r"Date\s*[:#]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}[./-]\d{1,2}[./-]\d{1,2})",
        text,
        flags=re.IGNORECASE
    )
    if m:
        return normalize_date(m.group(1))

    # Fallback: cualquier fecha
    m = re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}[./-]\d{1,2}[./-]\d{1,2})", text)
    if m:
        return normalize_date(m.group(1))

    return ""

def extract_currency(text):
    if re.search(r"\bUSD\b|US\$|\$", text, flags=re.IGNORECASE):
        return "USD"
    m = re.search(r"\b(EUR|MXN|JPY|CNY|RMB)\b", text, flags=re.IGNORECASE)
    return m.group(1).upper() if m else ""

def extract_incoterm(text):
    m = re.search(r"\b(FOB|CIF|CFR|EXW|FCA|DAP|DDP|CPT|CIP)\b", text, flags=re.IGNORECASE)
    return m.group(1).upper() if m else ""

def extract_total(text):
    # Prioridad: línea de TOTAL con cantidad + monto.
    # Ejemplo: TOTAL 1090 $20,383.00
    total_matches = re.findall(
        r"\bTOTAL\b\s*[:#]?\s*(?:[0-9,]+)?\s*(?:USD|US\$|\$)?\s*([0-9,]+\.\d{2})",
        text,
        flags=re.IGNORECASE
    )

    values = [money_to_float(x) for x in total_matches]
    values = [x for x in values if x is not None]

    if values:
        return max(values)

    # Fallback: todos los importes con decimales; tomar el mayor.
    all_values = [money_to_float(x) for x in re.findall(r"(?:USD|US\$|\$)?\s*([0-9,]+\.\d{2})", text)]
    all_values = [x for x in all_values if x is not None]
    return max(all_values) if all_values else None

def split_supplier_and_address(block):
    block = clean_text(block)

    entity_patterns = [
        r"^(.+?\bTRADING\s+CO\.?,?\s*LTD\.?)\b(.*)$",
        r"^(.+?\bCO\.?,?\s*LTD\.?)\b(.*)$",
        r"^(.+?\bLIMITED\b)(.*)$",
        r"^(.+?\bINC\.?)\b(.*)$",
        r"^(.+?\bCORP\.?)\b(.*)$",
        r"^(.+?\bLLC\b)(.*)$",
        r"^(.+?\bS\.?A\.?\s*DE\s*C\.?V\.?)\b(.*)$",
    ]

    for pat in entity_patterns:
        m = re.search(pat, block, flags=re.IGNORECASE)
        if m:
            return clean_text(m.group(1)).upper(), clean_text(m.group(2))

    return "", ""

def extract_supplier_and_address(text):
    # Caso VLEAD:
    # TOTAL 1090 $20,383.00 VLEAD LEATHER LIMITED N° 39... INVOICE Buyer:
    m = re.search(
        r"\bTOTAL\b.*?([A-Z0-9 .,&'\-()]+?(?:TRADING\s+CO\.?,?\s*LTD\.?|CO\.?,?\s*LTD\.?|LIMITED|INC\.?|CORP\.?|LLC))\s+(.*?)(?:\bINVOICE\b|\bBuyer\b|\bPO\s*N|$)",
        text,
        flags=re.IGNORECASE
    )

    if m:
        supplier = clean_text(m.group(1)).upper()
        address = clean_text(m.group(2))

        # Limpia si se coló "TOTAL"
        supplier = re.sub(r"^TOTAL\s+", "", supplier, flags=re.IGNORECASE).strip()
        return supplier, address

    # Fallback: buscar razón social en cualquier parte y tomar texto después como dirección
    candidates = list(re.finditer(
        r"([A-Z0-9 .,&'\-()]+?(?:TRADING\s+CO\.?,?\s*LTD\.?|CO\.?,?\s*LTD\.?|LIMITED|INC\.?|CORP\.?|LLC))",
        text,
        flags=re.IGNORECASE
    ))

    if candidates:
        m = candidates[-1]
        supplier = clean_text(m.group(1)).upper()
        after = text[m.end():]
        address = re.split(r"\b(INVOICE|Buyer|PO\s*N|TOTAL QTY)\b", after, flags=re.IGNORECASE)[0]
        return supplier, clean_text(address)

    return "", ""

def extract_tax_id(text):
    m = re.search(r"Tax\s*Id\s*[:#]?\s*([A-Z0-9\-\/]+)", text, flags=re.IGNORECASE)
    return m.group(1).upper().strip() if m else ""

def parse_invoice(text):
    supplier, address = extract_supplier_and_address(text)
    total = extract_total(text)
    currency = extract_currency(text)

    return {
        "Proveedor": supplier,
        "Dirección": address,
        "Tax ID": extract_tax_id(text),
        "Factura": extract_invoice_number(text),
        "Fecha": extract_invoice_date(text),
        "Incoterm": extract_incoterm(text),
        "Moneda": currency,
        "Total": format_money(total),
        "Total numérico": total,
    }

file = st.file_uploader("Sube factura PDF", type=["pdf"])

if file:
    txt = read_pdf(file)
    data = parse_invoice(txt)

    st.subheader("Resultado")
    st.json(data)

    with st.expander("Texto extraído"):
        st.text_area("Texto", txt, height=350)
