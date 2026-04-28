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


def normalize_tax_id(value: str) -> str:
    raw = str(value or "").strip().upper()
    raw = raw.replace("Í", "I").replace("Ú", "U").replace("Ñ", "N")
    raw_clean_spaces = re.sub(r"\s+", " ", raw).strip()

    # Variantes que equivalen a SIN NÚMERO
    sn_variants = {
        "S/N", "SN", "S N", "S / N", "S/ N", "S /N", "S-N", "S - N",
        "SIN NUMERO", "SIN NÚMERO", "SIN NO", "SIN NRO", "SIN ID",
        "N/A", "NA", "N.A.", "NO APLICA", "NO APL.", "SIN REGISTRO"
    }

    raw_compact = re.sub(r"[\s\.-]+", "", raw_clean_spaces)

    if raw_clean_spaces in sn_variants or raw_compact in ["SN", "S/N", "NA", "N/A", "NOAPLICA", "SINNUMERO"]:
        return "S/N"

    # Limpieza normal
    value = re.sub(r"[^A-Z0-9\-]", "", raw_clean_spaces)

    # Quita el NO de vinculación cuando viene pegado al ID fiscal:
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

    # PRIORIDAD 1: ID fiscal explícito dentro del bloque del proveedor.
    # Soporta: S/N, SN, S / N, N/A, etc.
    explicit_tax = re.search(
        r"ID\.?\s*FISCAL\s+NOMBRE.*?DOMICILIO:?\s*([A-Z0-9\/\-\.\s]{1,30})",
        block,
        flags=re.IGNORECASE
    )

    if explicit_tax:
        candidate = explicit_tax.group(1).strip()
        # Toma solo el primer token significativo si después viene el proveedor.
        # Casos:
        # S/N PT. SOUTH...
        # 65-0711500 AEROSERVICIOS...
        # 91330402MA2JFYMK6X WESTRON...
        m_first = re.match(r"((?:S\s*/?\s*N)|(?:N\s*/?\s*A)|(?:SN)|(?:NA)|(?:NO\s+APLICA)|(?:SIN\s+NUMERO)|(?:SIN\s+NÚMERO)|[A-Z0-9\-]{8,25})", candidate, flags=re.IGNORECASE)
        if m_first:
            result["Tax ID"] = normalize_tax_id(m_first.group(1))

    # Quitar encabezado.
    block = re.sub(
        r"ID\.?\s*FISCAL\s+NOMBRE,\s*DENOMINACION\s*O\s*RAZON\s*SOCIAL\s+DOMICILIO:?",
        "",
        block,
        flags=re.IGNORECASE
    ).strip(" .,:;-")

    parts = re.split(r"\bVINCULACION\b", block, maxsplit=1, flags=re.IGNORECASE)
    before = parts[0].strip(" .,:;-") if parts else ""
    after = parts[1].strip(" .,:;-") if len(parts) > 1 else ""

    # Si before inicia con Tax ID real o S/N, quitarlo del nombre.
    before = re.sub(r"^(S\s*/?\s*N|N\s*/?\s*A|SN|NA|NO\s+APLICA|SIN\s+NUMERO|SIN\s+NÚMERO)\s+", "", before, flags=re.IGNORECASE).strip(" .,:;-")
    before = re.sub(r"^(?=[A-Z0-9\-]*\d)[A-Z0-9\-]{8,25}\s+", "", before).strip(" .,:;-")

    proveedor, direccion_from_before = split_name_and_address(before)

    after = re.sub(r"^(NO|SI)\s+", "", after, flags=re.IGNORECASE).strip(" .,:;-")

    # Fallback tax desde after SOLO si no se obtuvo explícito.
    if not result["Tax ID"]:
        tax_match = re.search(r"\b((?:NO)?[A-Z0-9\-]{8,25})\b", after, flags=re.IGNORECASE)
        if tax_match:
            result["Tax ID"] = normalize_tax_id(tax_match.group(1))
            direccion_from_after = after[tax_match.end():].strip(" .,:;-")
        else:
            direccion_from_after = after
    else:
        # Si el Tax ID ya salió del encabezado, no volver a tomar palabras de dirección como SUDIRMAN.
        direccion_from_after = after
        # Quitar tax al inicio del after si viene repetido.
        direccion_from_after = re.sub(r"^(S\s*/?\s*N|N\s*/?\s*A|SN|NA|NO\s+APLICA|SIN\s+NUMERO|SIN\s+NÚMERO)\s+", "", direccion_from_after, flags=re.IGNORECASE).strip(" .,:;-")
        direccion_from_after = re.sub(r"^(?=[A-Z0-9\-]*\d)[A-Z0-9\-]{8,25}\s+", "", direccion_from_after).strip(" .,:;-")

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
