# APP COMPLETO CORREGIDO (PROVEEDOR ROBUSTO)

import re
import streamlit as st
from pypdf import PdfReader

st.title("Glosa Aduanal")

def read_pdf(file):
    reader = PdfReader(file)
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    text = re.sub(r"---\s*PAGINA\s*\d+\s*---", " ", text, flags=re.IGNORECASE)
    return text


def extract_pedimento_supplier_block(text: str) -> dict:
    result = {"Proveedor": "", "Dirección proveedor": "", "Tax ID": ""}

    t = re.sub(r"\s+", " ", text)

    match = re.search(
        r"DATOS DEL PROVEEDOR O COMPRADOR(.*?)(?:NUM\.?\s*CFDI|TRANSPORTE IDENTIFICACION|AGENTE ADUANAL)",
        t
    )

    if not match:
        return result

    block = match.group(1)

    block = re.sub(
        r"ID\.?\s*FISCAL\s+NOMBRE.*?DOMICILIO:?",
        "",
        block
    ).strip()

    parts = re.split(r"\bVINCULACION\b", block, maxsplit=1)

    before = parts[0].strip()
    after = parts[1].strip() if len(parts) > 1 else ""

    tax_match = re.search(r"\b([A-Z0-9]{10,25})\b", after)
   if tax_match:
    tax_id = tax_match.group(1)
    tax_id = re.sub(r"\bNO\b$", "", tax_id).strip()
    result["Tax ID"] = tax_id

    before = re.sub(r"^[A-Z0-9]{8,25}\s+", "", before).strip()

    address_breakers = [
        r"\bNO\.\b",
        r"\bNO\b\s+\d",
        r"\bRM\b",
        r"\bROOM\b",
        r"\bBUILDING\b",
        r"\bBLDG\b",
        r"\bFLOOR\b",
        r"\bINT\b",
        r"\bC\.P\.\b",
        r"\bCP\b"
    ]

    cut_pos = None
    for pattern in address_breakers:
        m = re.search(pattern, before)
        if m:
            cut_pos = m.start()
            break

    if cut_pos:
        proveedor = before[:cut_pos].strip(" ,.-")
        direccion_pre = before[cut_pos:].strip(" ,.-")
    else:
        proveedor = before.strip(" ,.-")
        direccion_pre = ""

    direccion = after
    direccion = re.sub(r"^(NO|SI)\s+", "", direccion).strip()

    if tax_match:
        direccion = direccion[tax_match.end():].strip()
direccion = re.sub(r"^\bNO\b\s*", "", direccion).strip()

    if not direccion:
        direccion = direccion_pre

    result["Proveedor"] = proveedor
    result["Dirección proveedor"] = direccion

    return result


uploaded = st.file_uploader("Sube pedimento PDF", type="pdf")

if uploaded:
    text = read_pdf(uploaded)
    data = extract_pedimento_supplier_block(text)

    st.write("### Resultado")
    st.write(data)
