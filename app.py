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
    return re.sub(r"\s+", " ", text)


def clean_tax_id(value: str) -> str:
    value = str(value or "").strip().upper()
    value = re.sub(r"[^A-Z0-9]", "", value)

    # Quita el NO de VINCULACION cuando se pega al Tax ID:
    # Ejemplo: NO4110001016088 -> 4110001016088
    if re.match(r"^NO\d{8,}$", value):
        value = value[2:]

    # También quita NO si quedó separado al final o inicio
    value = re.sub(r"^NO(?=[A-Z0-9]{8,})", "", value)
    value = re.sub(r"NO$", "", value)

    return value.strip()


def extract_pedimento_supplier_block(text: str) -> dict:
    result = {"Proveedor": "", "Dirección proveedor": "", "Tax ID": ""}

    t = re.sub(r"\s+", " ", text)

    match = re.search(
        r"DATOS DEL PROVEEDOR O COMPRADOR(.*?)(?:NUM\.?\s*CFDI|TRANSPORTE IDENTIFICACION|AGENTE ADUANAL)",
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
    ).strip()

    parts = re.split(r"\bVINCULACION\b", block, maxsplit=1, flags=re.IGNORECASE)

    before = parts[0].strip() if parts else ""
    after = parts[1].strip() if len(parts) > 1 else ""

    before = re.sub(r"^[A-Z0-9]{8,25}\s+", "", before).strip(" .,:")
    after = after.strip(" .,:")
    after = re.sub(r"^(NO|SI)\s+", "", after, flags=re.IGNORECASE).strip()

    # Detecta Tax ID incluso si viene pegado con NO:
    # NO4110001016088 -> 4110001016088
    tax_match = re.search(r"\b((?:NO)?[A-Z0-9]{8,25})\b", after, flags=re.IGNORECASE)
    if tax_match:
        tax_id = clean_tax_id(tax_match.group(1))
        result["Tax ID"] = tax_id
        direccion = after[tax_match.end():].strip(" .,:")
    else:
        direccion = after

    direccion = re.sub(r"^(NO|SI)\s+", "", direccion, flags=re.IGNORECASE).strip()

    # Separar proveedor/dirección. No cortar por RD/CITY/CHINA.
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
        r"\bCP\b",
        r"\bNISHI\b",
        r"\bSHINJUKU\b",
        r"\bTOKYO\b",
    ]

    cut_pos = None
    for pattern in address_breakers:
        m = re.search(pattern, before, flags=re.IGNORECASE)
        if m:
            cut_pos = m.start()
            break

    if cut_pos is not None:
        proveedor = before[:cut_pos].strip(" ,.-")
        direccion_pre = before[cut_pos:].strip(" ,.-")
    else:
        proveedor = before.strip(" ,.-")
        direccion_pre = ""

    if not direccion:
        direccion = direccion_pre

    result["Proveedor"] = re.sub(r"\s+", " ", proveedor).strip()
    result["Dirección proveedor"] = re.sub(r"\s+", " ", direccion).strip()

    return result


uploaded = st.file_uploader("Sube pedimento PDF", type="pdf")

if uploaded:
    text = read_pdf(uploaded)
    data = extract_pedimento_supplier_block(text)

    st.write("### Resultado")
    st.write(data)
