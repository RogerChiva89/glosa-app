# VERSION V3 - FIX FACTURAS REALES
import re
import streamlit as st
from pypdf import PdfReader

st.title("Glosa Auditoría V3 - Facturas robustas")

def read_pdf(file):
    reader = PdfReader(file)
    text = ""
    for p in reader.pages:
        text += " " + (p.extract_text() or "")
    return re.sub(r"\s+", " ", text)

def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()

def get_invoice(text):
    patterns = [
        r"INVOICE\s*N[O°]*\s*[:]?\s*([A-Z0-9\-]+)",
        r"\b([A-Z]{2,}-?\d{3,})\b"
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            val = m.group(1).upper()
            if not val.startswith("COVE"):
                return val
    return ""

def get_date(text):
    patterns = [
        r"(\d{2}/\d{2}/\d{4})",
        r"(\d{4}\.\d{2}\.\d{2})",
        r"(\d{4}-\d{2}-\d{2})"
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            d = m.group(1)
            if "." in d:
                y,mn,dd = d.split(".")
                return f"{dd}/{mn}/{y}"
            if "-" in d:
                y,mn,dd = d.split("-")
                return f"{dd}/{mn}/{y}"
            return d
    return ""

def get_total(text):
    nums = re.findall(r"\$?\s*([0-9,]+\.\d{2})", text)
    vals = []
    for n in nums:
        try:
            vals.append(float(n.replace(",", "")))
        except:
            pass
    return max(vals) if vals else None

def get_supplier(text):
    lines = text.split(" ")
    candidates = re.findall(r"([A-Z][A-Z\s,&\.\-]+(?:LIMITED|LTD|CO\., LTD|INC|CORP))", text, re.I)
    if candidates:
        return candidates[-1].upper()
    return ""

def parse_invoice(text):
    return {
        "Factura": get_invoice(text),
        "Fecha": get_date(text),
        "Proveedor": get_supplier(text),
        "Total": get_total(text)
    }

file = st.file_uploader("Sube factura PDF")

if file:
    txt = read_pdf(file)
    data = parse_invoice(txt)
    st.write(data)
