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

    # Caso típico: NO4110001016088 -> 4110001016088
    if re.match(r"^NO\d{8,}$", value):
        value = value[2:]

    # Si viene con NO pegado al inicio, pero no forma parte real del ID
    value = re.sub(r"^NO(?=[0-9]{8,})", "", value)

    # Si viene con NO al final
    value = re.sub(r"NO$", "", value)

    return value.strip()


def clean_provider_name(value: str) -> str:
    value = str(value or "").strip(" .,:;-")
    value = re.sub(r"\s+", " ", value)

    # Limpia basura común
    value = re.sub(r"^(ID\.?\s*FISCAL|NOMBRE|DENOMINACION|RAZON SOCIAL)\s+", "", value, flags=re.IGNORECASE).strip()

    return value


def split_name_and_address(raw: str) -> tuple:
    """
    Separa proveedor/dirección.
    Regla:
    1) Si detecta razón social completa con INC / LLC / CORP / CO LTD / SA DE CV, corta ahí.
    2) Si no, corta donde empiece una dirección fuerte.
    """
    raw = re.sub(r"\s+", " ", str(raw or "")).strip(" .,:;-")

    # 1) Terminaciones de razón social. Incluye INC. para no cortar "AEROSERVICIOS USA, INC."
    entity_patterns = [
        r"^(.+?\bS\.?A\.?\s*DE\s*C\.?V\.?)\b(.*)$",
        r"^(.+?\bSA\s*DE\s*CV\b)(.*)$",
        r"^(.+?\bS\.?A\.?)\b(.*)$",
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
            proveedor = clean_provider_name(m.group(1))
            direccion = m.group(2).strip(" .,:;-")
            return proveedor, direccion

    # 2) Cortes fuertes de dirección.
    address_breakers = [
        r"\bNO\.\s*EXT\b",
        r"\bNO\.\b",
        r"\bNO\b\s+\d",
        r"\bRM\b",
        r"\bROOM\b",
        r"\bBUILDING\b",
        r"\bBLDG\b",
        r"\bFLOOR\b",
        r"\bSTREET\b",
        r"\bAVENUE\b",
        r"\bROAD\b",
        r"\bNISHI\b",
        r"\bSHINJUKU\b",
        r"\bMIAMI\b",
        r"\bFLORIDA\b",
        r"\bTOKYO\b",
        r"\bC\.P\.\b",
        r"\bCP\b",
    ]

    cut_positions = []
    for pattern in address_breakers:
        m = re.search(pattern, raw, flags=re.IGNORECASE)
        if m:
            cut_positions.append(m.start())

    if cut_positions:
        cut = min(cut_positions)
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
        r"ID\.?\s*FISCAL\s+NOMBRE.*?DOMICILIO:?",
        "",
        block,
        flags=re.IGNORECASE
    ).strip(" .,:;-")

    parts = re.split(r"\bVINCULACION\b", block, maxsplit=1, flags=re.IGNORECASE)

    before = parts[0].strip(" .,:;-") if parts else ""
    after = parts[1].strip(" .,:;-") if len(parts) > 1 else ""

    # Quitar ID fiscal si viene al inicio de before
    before = re.sub(r"^[A-Z0-9\-]{8,25}\s+", "", before).strip(" .,:;-")

    # Caso especial: si before ya trae nombre + dirección, separar aquí
    proveedor, direccion_from_before = split_name_and_address(before)

    # After normalmente contiene: TAXID DIRECCION NO
    after = re.sub(r"^(NO|SI)\s+", "", after, flags=re.IGNORECASE).strip(" .,:;-")

    # Tax ID: aceptar con guiones, o NO pegado si el extractor lo tomó así.
    tax_match = re.search(r"\b((?:NO)?[A-Z0-9\-]{8,25})\b", after, flags=re.IGNORECASE)

    direccion_from_after = ""
    if tax_match:
        result["Tax ID"] = clean_tax_id(tax_match.group(1))
        direccion_from_after = after[tax_match.end():].strip(" .,:;-")
    else:
        direccion_from_after = after

    # Quitar NO/SI de vinculación si quedó antes/después
    direccion_from_after = re.sub(r"^(NO|SI)\s+", "", direccion_from_after, flags=re.IGNORECASE).strip(" .,:;-")
    direccion_from_after = re.sub(r"\s+\b(NO|SI)\b$", "", direccion_from_after, flags=re.IGNORECASE).strip(" .,:;-")

    result["Proveedor"] = proveedor
    result["Dirección proveedor"] = direccion_from_after or direccion_from_before

    # Limpieza final
    result["Proveedor"] = re.sub(r"\s+", " ", result["Proveedor"]).strip(" .,:;-")
    result["Dirección proveedor"] = re.sub(r"\s+", " ", result["Dirección proveedor"]).strip(" .,:;-")

    return result


uploaded = st.file_uploader("Sube pedimento PDF", type="pdf")

if uploaded:
    text = read_pdf(uploaded)
    data = extract_pedimento_supplier_block(text)

    st.write("### Resultado")
    st.write(data)
