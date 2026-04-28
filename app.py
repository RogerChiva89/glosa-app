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


def is_sn_variant(value: str) -> bool:
    v = str(value or "").upper().strip()
    v = v.replace("Í", "I").replace("Ú", "U").replace("Ñ", "N")
    v = re.sub(r"\s+", " ", v)
    compact = re.sub(r"[\s\.\-/]+", "", v)
    return compact in {
        "SN", "NA", "NOAPLICA", "SINNUMERO", "SINNO", "SINNRO", "SINID", "SINREGISTRO"
    }


def normalize_tax_id(value: str) -> str:
    raw = str(value or "").strip().upper()
    raw = raw.replace("Í", "I").replace("Ú", "U").replace("Ñ", "N")

    if is_sn_variant(raw):
        return "S/N"

    value = re.sub(r"[^A-Z0-9\-]", "", raw)

    # NO65-0711500 -> 65-0711500
    # NO4110001016088 -> 4110001016088
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
        r"\bAIA\b", r"\bKAV\b"
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


def extract_sn_from_start(value: str):
    """
    Detecta variantes de S/N al inicio de una cadena y devuelve:
    ("S/N", texto_restante)
    """
    text = str(value or "").strip(" .,:;-")

    sn_start = re.match(
        r"^(S\s*/\s*N|S\s*-\s*N|S\s+N|SN|N\s*/\s*A|N\s*-\s*A|N\s+A|NA|NO\s+APLICA|SIN\s+NUMERO|SIN\s+NÚMERO|SIN\s+NO|SIN\s+NRO|SIN\s+ID|SIN\s+REGISTRO)\b(.*)$",
        text,
        flags=re.IGNORECASE
    )

    if sn_start:
        return "S/N", sn_start.group(2).strip(" .,:;-")

    return "", text


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

    # Quitar encabezado
    block = re.sub(
        r"ID\.?\s*FISCAL\s+NOMBRE,\s*DENOMINACION\s*O\s*RAZON\s*SOCIAL\s+DOMICILIO:?",
        "",
        block,
        flags=re.IGNORECASE
    ).strip(" .,:;-")

    parts = re.split(r"\bVINCULACION\b", block, maxsplit=1, flags=re.IGNORECASE)

    before = parts[0].strip(" .,:;-") if parts else ""
    after = parts[1].strip(" .,:;-") if len(parts) > 1 else ""

    # Quitar ID fiscal si viniera al inicio del nombre
    before = re.sub(r"^(S\s*/?\s*N|N\s*/?\s*A|SN|NA|NO\s+APLICA|SIN\s+NUMERO|SIN\s+NÚMERO)\s+", "", before, flags=re.IGNORECASE).strip(" .,:;-")
    before = re.sub(r"^(?=[A-Z0-9\-]*\d)[A-Z0-9\-]{8,25}\s+", "", before).strip(" .,:;-")

    proveedor, direccion_from_before = split_name_and_address(before)

    # Limpia NO/SI de vinculación
    after = re.sub(r"^(NO|SI)\s+", "", after, flags=re.IGNORECASE).strip(" .,:;-")

    # PRIORIDAD 1 DESPUÉS DE VINCULACION:
    # Si after empieza con S/N, SN, N/A, etc., ese ES el Tax ID.
    sn_tax, after_without_sn = extract_sn_from_start(after)
    if sn_tax:
        result["Tax ID"] = sn_tax
        direccion_from_after = after_without_sn
    else:
        # PRIORIDAD 2: si after empieza con un ID que contiene números.
        # Evita agarrar palabras de dirección como SUDIRMAN.
        tax_match = re.match(r"^((?:NO)?(?=[A-Z0-9\-]*\d)[A-Z0-9\-]{8,25})\b(.*)$", after, flags=re.IGNORECASE)
        if tax_match:
            result["Tax ID"] = normalize_tax_id(tax_match.group(1))
            direccion_from_after = tax_match.group(2).strip(" .,:;-")
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
