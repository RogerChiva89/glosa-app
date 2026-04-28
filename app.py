import re
import pandas as pd
import streamlit as st
from pypdf import PdfReader

st.set_page_config(page_title="Glosa Aduanal - Multi Proveedor", layout="wide")
st.title("Glosa Aduanal - Multi Proveedor / Multi Factura")
st.caption("Detecta varios proveedores/facturas dentro del mismo pedimento.")


# ============================================================
# LECTURA PDF
# ============================================================
def read_pdf(file):
    reader = PdfReader(file)
    text = ""
    for page in reader.pages:
        text += "\n" + (page.extract_text() or "")
    text = re.sub(r"---\s*PAGINA\s*\d+\s*---", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text)


# ============================================================
# UTILIDADES
# ============================================================
def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" .,:;-")


def normalize_money(value: str):
    if not value:
        return None
    s = str(value).replace(",", "")
    s = re.sub(r"[^0-9.\-]", "", s)
    try:
        return float(s)
    except Exception:
        return None


def is_sn_variant(value: str) -> bool:
    v = str(value or "").upper().strip()
    v = v.replace("Í", "I").replace("Ú", "U").replace("Ñ", "N")
    compact = re.sub(r"[\s\.\-/]+", "", v)
    return compact in {
        "SN", "NA", "NOSN", "NONA", "NOAPLICA", "SINNUMERO",
        "SINNO", "SINNRO", "SINID", "SINREGISTRO"
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
            return clean_text(m.group(1)), clean_text(m.group(2))

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
        r"\bNORTH ROAD\b",
        r"\bTUANYI\b",
        r"\bHUADU\b",
        r"\bGUANGZHOU\b",
        r"\bMIAMI\b",
        r"\bFLORIDA\b",
        r"\bC\.P\.\b",
        r"\bCP\b",
    ]

    positions = []
    for pattern in address_breakers:
        m = re.search(pattern, raw, flags=re.IGNORECASE)
        if m:
            positions.append(m.start())

    if positions:
        cut = min(positions)
        return clean_text(raw[:cut]), clean_text(raw[cut:])

    return clean_text(raw), ""


def extract_sn_from_start(value: str):
    text = clean_text(value)

    glued = re.match(
        r"^(NO\s*)?(S\s*/\s*N|S\s*-\s*N|S\s+N|SN|N\s*/\s*A|N\s*-\s*A|N\s+A|NA)\b(.*)$",
        text,
        flags=re.IGNORECASE
    )
    if glued:
        return "S/N", clean_text(glued.group(3))

    glued2 = re.match(r"^(NOS\s*/\s*N|NOSN|NON\s*/\s*A|NONA)(.*)$", text, flags=re.IGNORECASE)
    if glued2:
        return "S/N", clean_text(glued2.group(2))

    phrase = re.match(
        r"^(NO\s+APLICA|SIN\s+NUMERO|SIN\s+NÚMERO|SIN\s+NO|SIN\s+NRO|SIN\s+ID|SIN\s+REGISTRO)\b(.*)$",
        text,
        flags=re.IGNORECASE
    )
    if phrase:
        return "S/N", clean_text(phrase.group(2))

    return "", text


# ============================================================
# EXTRACCIÓN MULTI-PROVEEDOR
# ============================================================
def extract_supplier_area(text: str) -> str:
    """
    Toma el área de proveedores del pedimento.
    Puede contener 1, 2 o más proveedores.
    """
    t = re.sub(r"\s+", " ", text)

    start = re.search(r"DATOS DEL PROVEEDOR O COMPRADOR", t, flags=re.IGNORECASE)
    if not start:
        return ""

    area = t[start.end():]

    # Cortar antes de transporte/agente/partidas para no contaminar.
    stop = re.search(
        r"(TRANSPORTE IDENTIFICACION|TRANSPORTISTA RFC|NO\.?\s*\(GUIA|AGENTE ADUANAL|PARTIDAS|CLAVE/COMPL)",
        area,
        flags=re.IGNORECASE
    )
    if stop:
        area = area[:stop.start()]

    return clean_text(area)


def split_supplier_records(area: str) -> list:
    """
    Divide el área de proveedores en registros.
    En pedimentos multi-proveedor, cada proveedor inicia con:
    ID. FISCAL NOMBRE, DENOMINACION O RAZON SOCIAL DOMICILIO:
    """
    records = []

    pattern = r"ID\.?\s*FISCAL\s+NOMBRE,\s*DENOMINACION\s*O\s*RAZON\s*SOCIAL\s+DOMICILIO:?"
    matches = list(re.finditer(pattern, area, flags=re.IGNORECASE))

    if not matches:
        return records

    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(area)
        record = clean_text(area[start:end])
        if record:
            records.append(record)

    return records


def parse_invoice_part(record: str) -> dict:
    out = {
        "COVE": "",
        "Factura": "",
        "Fecha factura": "",
        "Incoterm": "",
        "Moneda": "",
        "Valor factura": None,
    }

    m_cove = re.search(r"\b(COVE[A-Z0-9]+)\b", record, flags=re.IGNORECASE)
    if m_cove:
        out["COVE"] = m_cove.group(1).upper()

    # Quitar encabezado de factura para facilitar lectura.
    inv_text = re.sub(
        r"NUM\.?\s*CFDI\s*O\s*DOCUMENTO\s*EQUIVALENTE\s+FECHA\s+INCOTERM\s+MONEDA\s+FACT\s+VAL\.?\s*MON\.?\s*FACT\s+FACTOR\s+MON\.?\s+VAL\.?\s*DOLARES",
        " ",
        record,
        flags=re.IGNORECASE
    )
    inv_text = clean_text(inv_text)

    # Patrón flexible con COVE + factura + fecha + incoterm + moneda + valor
    # Ejemplo:
    # COVE267WUXAC5 PI20250818-1 29/12/2025 FOB USD 114,589.00 1.00000000 114,589.00
    m = re.search(
        r"(?:COVE[A-Z0-9]+\s+)?([A-Z0-9][A-Z0-9\-\/]{2,})\s+"
        r"(\d{1,2}/\d{1,2}/\d{4})\s+"
        r"(FOB|CIF|CFR|EXW|FCA|DAP|DDP|CPT|CIP)\s+"
        r"(USD|EUR|MXN|JPY|CNY)\s+"
        r"([0-9,]+\.\d{2})",
        inv_text,
        flags=re.IGNORECASE
    )

    if m:
        fact = m.group(1).upper()
        if not fact.startswith("COVE"):
            out["Factura"] = fact
        out["Fecha factura"] = m.group(2)
        out["Incoterm"] = m.group(3).upper()
        out["Moneda"] = m.group(4).upper()
        out["Valor factura"] = normalize_money(m.group(5))

    return out


def parse_supplier_record(record: str, index: int) -> dict:
    row = {
        "Bloque": index,
        "Proveedor": "",
        "Tax ID": "",
        "Dirección proveedor": "",
        "COVE": "",
        "Factura": "",
        "Fecha factura": "",
        "Incoterm": "",
        "Moneda": "",
        "Valor factura": None,
    }

    # Separar parte proveedor de parte factura.
    parts = re.split(
        r"NUM\.?\s*CFDI\s*O\s*DOCUMENTO\s*EQUIVALENTE",
        record,
        maxsplit=1,
        flags=re.IGNORECASE
    )

    supplier_part = clean_text(parts[0])
    invoice_part = "NUM. CFDI O DOCUMENTO EQUIVALENTE " + parts[1] if len(parts) > 1 else ""

    # Dividir por VINCULACION
    supplier_parts = re.split(r"\bVINCULACION\b", supplier_part, maxsplit=1, flags=re.IGNORECASE)

    before = clean_text(supplier_parts[0]) if supplier_parts else ""
    after = clean_text(supplier_parts[1]) if len(supplier_parts) > 1 else ""

    # Quitar ID fiscal al inicio del nombre si viniera pegado
    before = re.sub(
        r"^(S\s*/?\s*N|N\s*/?\s*A|SN|NA|NO\s+APLICA|SIN\s+NUMERO|SIN\s+NÚMERO)\s+",
        "",
        before,
        flags=re.IGNORECASE
    ).strip(" .,:;-")
    before = re.sub(r"^(?=[A-Z0-9\-]*\d)[A-Z0-9\-]{8,25}\s+", "", before).strip(" .,:;-")

    proveedor, direccion_from_before = split_name_and_address(before)

    # NO quitar NO antes de evaluar S/N, porque puede venir como NOS/N.
    sn_tax, after_without_sn = extract_sn_from_start(after)

    if sn_tax:
        tax_id = sn_tax
        direccion_from_after = after_without_sn
    else:
        after_clean = re.sub(r"^(NO|SI)\s+", "", after, flags=re.IGNORECASE).strip(" .,:;-")

        # Tax ID solo si viene al inicio y contiene número.
        tax_match = re.match(
            r"^((?:NO)?(?=[A-Z0-9\-]*\d)[A-Z0-9\-]{6,25})\b(.*)$",
            after_clean,
            flags=re.IGNORECASE
        )
        if tax_match:
            tax_id = normalize_tax_id(tax_match.group(1))
            direccion_from_after = clean_text(tax_match.group(2))
        else:
            tax_id = ""
            direccion_from_after = after_clean

    direccion_from_after = re.sub(r"^(NO|SI)\s+", "", direccion_from_after, flags=re.IGNORECASE).strip(" .,:;-")
    direccion_from_after = re.sub(r"\s+\b(NO|SI)\b$", "", direccion_from_after, flags=re.IGNORECASE).strip(" .,:;-")

    row["Proveedor"] = clean_text(proveedor)
    row["Tax ID"] = clean_text(tax_id)
    row["Dirección proveedor"] = clean_text(direccion_from_after or direccion_from_before)

    inv = parse_invoice_part(invoice_part)
    row.update(inv)

    return row


def extract_multiple_suppliers_from_pedimento(text: str) -> pd.DataFrame:
    area = extract_supplier_area(text)
    records = split_supplier_records(area)

    rows = []
    for i, record in enumerate(records, start=1):
        rows.append(parse_supplier_record(record, i))

    return pd.DataFrame(rows)


# ============================================================
# UI
# ============================================================
uploaded = st.file_uploader("Sube pedimento PDF", type="pdf")

if uploaded:
    text = read_pdf(uploaded)
    df = extract_multiple_suppliers_from_pedimento(text)

    st.subheader("Resultado multi-proveedor")

    if df.empty:
        st.warning("No se detectaron proveedores.")
    else:
        st.dataframe(df, use_container_width=True)

        st.download_button(
            "Descargar proveedores detectados CSV",
            data=df.to_csv(index=False).encode("utf-8-sig"),
            file_name="proveedores_pedimento.csv",
            mime="text/csv"
        )

    with st.expander("Ver texto extraído"):
        st.text_area("Texto", text, height=350)
