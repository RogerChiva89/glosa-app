import re
import streamlit as st
from pypdf import PdfReader

st.title("Glosa Aduanal - Proveedor Pedimento")

def read_pdf(file):
    reader = PdfReader(file)
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    text = re.sub(r"---\s*PAGINA\s*\d+\s*---", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text)


def clean_tax_id(value: str) -> str:
    value = str(value or "").strip().upper()
    value = re.sub(r"[^A-Z0-9\-]", "", value)
    if re.match(r"^NO(?=\d)", value):
        value = value[2:]
    value = re.sub(r"NO$", "", value)
    return value.strip()


def clean_provider_name(value: str) -> str:
    value = str(value or "").strip(" .,:;-")
    return re.sub(r"\s+", " ", value)


def split_name_and_address(raw: str) -> tuple:
    raw = re.sub(r"\s+", " ", str(raw or "")).strip(" .,:;-")

    entity_patterns = [
        r"^(.+?\bS\.?A\.?\s*DE\s*C\.?V\.?)\b(.*)$",
        r"^(.+?\bSA\s*DE\s*CV\b)(.*)$",
        r"^(.+?\bTRADING\s+CO\.?,?\s*LTD\.?)\b(.*)$",
        r"^(.+?\bCO\.?,?\s*LTD\.?)\b(.*)$",
        r"^(.+?\bLIMITED\b)(.*)$",
        r"^(.+?\bCORPORATION\b)(.*)$",
        r"^(.+?\bCORP\.?)\b(.*)$",
        r"^(.+?\bINC\.?)\b(.*)$",
        r"^(.+?\bLLC\b)(.*)$",
        r"^(.+?\bL\.?L\.?C\.?)\b(.*)$",
    ]

    for pat in entity_patterns:
        m = re.search(pat, raw, flags=re.IGNORECASE)
        if m:
            return clean_provider_name(m.group(1)), m.group(2).strip(" .,:;-")

    address_breakers = [
        r"\bNO\.\s*EXT\b", r"\bNO\.\b", r"\bNO\b\s+\d",
        r"\bRM\b", r"\bROOM\b", r"\bBUILDING\b", r"\bBLDG\b",
        r"\bFLOOR\b", r"\bSTREET\b", r"\bAVENUE\b", r"\bROAD\b",
        r"\bNISHI\b", r"\bSHINJUKU\b", r"\bMIAMI\b", r"\bFLORIDA\b",
        r"\bTOKYO\b", r"\bC\.P\.\b", r"\bCP\b",
    ]

    positions = []
    for pattern in address_breakers:
        m = re.search(pattern, raw, flags=re.IGNORECASE)
        if m:
            positions.append(m.start())

    if positions:
        cut = min(positions)
        return clean_provider_name(raw[:cut]), raw[cut:].strip(" .,:;-")

    return clean_provider_name(raw), ""


def extract_pedimento_supplier_block(text: str) -> dict:
    result = {"Proveedor": "", "Dirección proveedor": "", "Tax ID": ""}

    t = re.sub(r"\s+", " ", text)

    match = re.search(
        r"DATOS DEL PROVEEDOR O COMPRADOR(.*?)(?:NUM\.?\s*CFDI|TRANSPORTE IDENTIFICACION|NO\.?\s*\(GUIA|AGENTE ADUANAL)",
        t,
        flags=re.IGNORECASE
    )
    if not match:
        return result

    block = match.group(1).strip()

    block = re.sub(
        r"ID\.?\s*FISCAL\s+NOMBRE,\s*DENOMINACION\s*O\s*RAZON\s*SOCIAL\s+DOMICILIO:?",
        "",
        block,
        flags=re.IGNORECASE
    ).strip(" .,:;-")

    parts = re.split(r"\bVINCULACION\b", block, maxsplit=1, flags=re.IGNORECASE)
    before = parts[0].strip(" .,:;-") if parts else ""
    after = parts[1].strip(" .,:;-") if len(parts) > 1 else ""

    # No eliminar nombres como AEROSERVICIOS. Solo elimina si el primer token contiene números.
    before = re.sub(r"^(?=[A-Z0-9\-]*\d)[A-Z0-9\-]{8,25}\s+", "", before).strip(" .,:;-")

    proveedor, direccion_from_before = split_name_and_address(before)

    after = re.sub(r"^(NO|SI)\s+", "", after, flags=re.IGNORECASE).strip(" .,:;-")

    tax_match = re.search(r"\b((?:NO)?[A-Z0-9\-]{8,25})\b", after, flags=re.IGNORECASE)

    if tax_match:
        result["Tax ID"] = clean_tax_id(tax_match.group(1))
        direccion_from_after = after[tax_match.end():].strip(" .,:;-")
    else:
        direccion_from_after = after

    direccion_from_after = re.sub(r"^(NO|SI)\s+", "", direccion_from_after, flags=re.IGNORECASE).strip(" .,:;-")
    direccion_from_after = re.sub(r"\s+\b(NO|SI)\b$", "", direccion_from_after, flags=re.IGNORECASE).strip(" .,:;-")

    result["Proveedor"] = re.sub(r"\s+", " ", proveedor).strip(" .,:;-")
    result["Dirección proveedor"] = re.sub(r"\s+", " ", (direccion_from_after or direccion_from_before)).strip(" .,:;-")

    return result


uploaded = st.file_uploader("Sube pedimento PDF", type="pdf")

if uploaded:
    text = read_pdf(uploaded)
    data = extract_pedimento_supplier_block(text)
    st.write("### Resultado")
    st.write(data)
