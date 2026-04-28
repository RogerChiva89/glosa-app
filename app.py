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


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" .,:;-")


def is_sn_variant(value: str) -> bool:
    v = str(value or "").upper().strip()
    v = v.replace("Í", "I").replace("Ú", "U").replace("Ñ", "N")
    compact = re.sub(r"[\s\.\-/]+", "", v)

    return compact in {
        "SN",
        "NA",
        "NOSN",       # NO + S/N pegado por vinculación
        "NONA",       # NO + N/A pegado por vinculación
        "NOAPLICA",
        "SINNUMERO",
        "SINNO",
        "SINNRO",
        "SINID",
        "SINREGISTRO",
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
    return clean_text(value)


def split_name_and_address(raw: str) -> tuple:
    raw = clean_text(raw)

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
            return clean_provider_name(m.group(1)), clean_text(m.group(2))

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
        return clean_provider_name(raw[:cut]), clean_text(raw[cut:])

    return clean_provider_name(raw), ""


def extract_sn_from_start(value: str):
    """
    Detecta variantes de S/N al inicio del bloque posterior a VINCULACION.
    También corrige cuando viene pegado como NOS/N por el NO de vinculación.
    """
    text = clean_text(value)

    # Primero arreglar casos pegados:
    # NOS/N AIA CENTRAL -> S/N + AIA CENTRAL
    # NOSN AIA CENTRAL -> S/N + AIA CENTRAL
    glued = re.match(r"^(NO\s*)?(S\s*/\s*N|S\s*-\s*N|S\s+N|SN|N\s*/\s*A|N\s*-\s*A|N\s+A|NA)\b(.*)$", text, flags=re.IGNORECASE)
    if glued:
        return "S/N", clean_text(glued.group(3))

    # Caso sin separador por extracción: NOS/N o NOSN
    glued2 = re.match(r"^(NOS\s*/\s*N|NOSN|NON\s*/\s*A|NONA)(.*)$", text, flags=re.IGNORECASE)
    if glued2:
        return "S/N", clean_text(glued2.group(2))

    # Frases equivalentes
    phrase = re.match(
        r"^(NO\s+APLICA|SIN\s+NUMERO|SIN\s+NÚMERO|SIN\s+NO|SIN\s+NRO|SIN\s+ID|SIN\s+REGISTRO)\b(.*)$",
        text,
        flags=re.IGNORECASE
    )
    if phrase:
        return "S/N", clean_text(phrase.group(2))

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

    block = clean_text(match.group(1))

    # Quitar encabezado
    block = re.sub(
        r"ID\.?\s*FISCAL\s+NOMBRE,\s*DENOMINACION\s*O\s*RAZON\s*SOCIAL\s+DOMICILIO:?",
        "",
        block,
        flags=re.IGNORECASE
    ).strip(" .,:;-")

    parts = re.split(r"\bVINCULACION\b", block, maxsplit=1, flags=re.IGNORECASE)

    before = clean_text(parts[0]) if parts else ""
    after = clean_text(parts[1]) if len(parts) > 1 else ""

    # Quitar ID fiscal si viniera al inicio del nombre
    before = re.sub(r"^(S\s*/?\s*N|N\s*/?\s*A|SN|NA|NO\s+APLICA|SIN\s+NUMERO|SIN\s+NÚMERO)\s+", "", before, flags=re.IGNORECASE).strip(" .,:;-")
    before = re.sub(r"^(?=[A-Z0-9\-]*\d)[A-Z0-9\-]{8,25}\s+", "", before).strip(" .,:;-")

    proveedor, direccion_from_before = split_name_and_address(before)

    # NO quitar NO antes de evaluar S/N, porque puede venir como NO S/N o NOS/N.
    sn_tax, after_without_sn = extract_sn_from_start(after)

    if sn_tax:
        result["Tax ID"] = sn_tax
        direccion_from_after = after_without_sn
    else:
        # Si after empieza con NO o SI de vinculación, quitarlo solo si no era S/N
        after_clean = re.sub(r"^(NO|SI)\s+", "", after, flags=re.IGNORECASE).strip(" .,:;-")

        # Tax ID solo si empieza con un valor que contiene números.
        # Evita tomar palabras de dirección como SUDIRMAN.
        tax_match = re.match(r"^((?:NO)?(?=[A-Z0-9\-]*\d)[A-Z0-9\-]{8,25})\b(.*)$", after_clean, flags=re.IGNORECASE)
        if tax_match:
            result["Tax ID"] = normalize_tax_id(tax_match.group(1))
            direccion_from_after = clean_text(tax_match.group(2))
        else:
            direccion_from_after = after_clean

    direccion_from_after = re.sub(r"^(NO|SI)\s+", "", direccion_from_after, flags=re.IGNORECASE).strip(" .,:;-")
    direccion_from_after = re.sub(r"\s+\b(NO|SI)\b$", "", direccion_from_after, flags=re.IGNORECASE).strip(" .,:;-")

    result["Proveedor"] = clean_text(proveedor)
    result["Dirección proveedor"] = clean_text(direccion_from_after or direccion_from_before)

    return result


uploaded = st.file_uploader("Sube pedimento PDF", type="pdf")

if uploaded:
    text = read_pdf(uploaded)
    data = extract_pedimento_supplier_block(text)
    st.write("### Resultado")
    st.write(data)
