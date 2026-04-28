import re
import pandas as pd
import streamlit as st
from pypdf import PdfReader

st.set_page_config(page_title="Glosa Aduanal - Multi Proveedor", layout="wide")
st.title("Glosa Aduanal - Multi Proveedor / Multi Factura")
st.caption("Prueba para detectar varios proveedores dentro de un mismo pedimento.")


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
# LIMPIEZAS
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
        r"\bNO\.\s*EXT\b", r"\bNO\.\b", r"\bNO\b\s+\d",
        r"\bRM\b", r"\bROOM\b", r"\bBUILDING\b", r"\bBLDG\b",
        r"\bFLOOR\b", r"\bSTREET\b", r"\bAVENUE\b", r"\bROAD\b",
        r"\bNISHI\b", r"\bSHINJUKU\b", r"\bMIAMI\b", r"\bFLORIDA\b",
        r"\bTOKYO\b", r"\bC\.P\.\b", r"\bCP\b",
        r"\bAIA\b", r"\bKAV\b", r"\bCALLE\b", r"\bAV\.\b"
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
# EXTRACTORES
# ============================================================
def parse_supplier_block(block: str) -> dict:
    result = {
        "Proveedor": "",
        "Dirección proveedor": "",
        "Tax ID": "",
        "Factura": "",
        "Fecha factura": "",
        "Incoterm": "",
        "Moneda": "",
        "Valor factura": None,
        "COVE": "",
    }

    block = clean_text(block)

    # COVE
    m_cove = re.search(r"\b(COVE[A-Z0-9]+)\b", block, flags=re.IGNORECASE)
    if m_cove:
        result["COVE"] = m_cove.group(1).upper()

    # Separa proveedor de sección factura
    parts_invoice = re.split(
        r"NUM\.?\s*CFDI\s*O\s*DOCUMENTO\s*EQUIVALENTE",
        block,
        maxsplit=1,
        flags=re.IGNORECASE
    )

    supplier_part = parts_invoice[0]
    invoice_part = parts_invoice[1] if len(parts_invoice) > 1 else ""

    # Quitar encabezado proveedor
    supplier_part = re.sub(
        r"ID\.?\s*FISCAL\s+NOMBRE,\s*DENOMINACION\s*O\s*RAZON\s*SOCIAL\s+DOMICILIO:?",
        "",
        supplier_part,
        flags=re.IGNORECASE
    ).strip(" .,:;-")

    # Dividir por vinculación
    parts = re.split(r"\bVINCULACION\b", supplier_part, maxsplit=1, flags=re.IGNORECASE)

    before = clean_text(parts[0]) if parts else ""
    after = clean_text(parts[1]) if len(parts) > 1 else ""

    # Quitar ID fiscal del nombre si viene al inicio
    before = re.sub(
        r"^(S\s*/?\s*N|N\s*/?\s*A|SN|NA|NO\s+APLICA|SIN\s+NUMERO|SIN\s+NÚMERO)\s+",
        "",
        before,
        flags=re.IGNORECASE
    ).strip(" .,:;-")
    before = re.sub(r"^(?=[A-Z0-9\-]*\d)[A-Z0-9\-]{8,25}\s+", "", before).strip(" .,:;-")

    proveedor, direccion_from_before = split_name_and_address(before)

    # Tax ID / dirección después de vinculación
    sn_tax, after_without_sn = extract_sn_from_start(after)

    if sn_tax:
        result["Tax ID"] = sn_tax
        direccion_from_after = after_without_sn
    else:
        after_clean = re.sub(r"^(NO|SI)\s+", "", after, flags=re.IGNORECASE).strip(" .,:;-")
        tax_match = re.match(
            r"^((?:NO)?(?=[A-Z0-9\-]*\d)[A-Z0-9\-]{8,25})\b(.*)$",
            after_clean,
            flags=re.IGNORECASE
        )
        if tax_match:
            result["Tax ID"] = normalize_tax_id(tax_match.group(1))
            direccion_from_after = clean_text(tax_match.group(2))
        else:
            direccion_from_after = after_clean

    direccion_from_after = re.sub(
        r"^(NO|SI)\s+",
        "",
        direccion_from_after,
        flags=re.IGNORECASE
    ).strip(" .,:;-")
    direccion_from_after = re.sub(
        r"\s+\b(NO|SI)\b$",
        "",
        direccion_from_after,
        flags=re.IGNORECASE
    ).strip(" .,:;-")

    result["Proveedor"] = clean_text(proveedor)
    result["Dirección proveedor"] = clean_text(direccion_from_after or direccion_from_before)

    # Factura / fecha / incoterm / moneda / valor
    # Ejemplo:
    # COVE2682CFPR8 HST-LPC-43GDLC 31/03/2026 FOB USD 51,043.55 1.00000000 51,043.55
    inv_text = clean_text(invoice_part)

    m_invoice = re.search(
        r"(?:COVE[A-Z0-9]+\s+)?([A-Z0-9][A-Z0-9\-\/]{2,})\s+(\d{1,2}/\d{1,2}/\d{4})\s+"
        r"(FOB|CIF|CFR|EXW|FCA|DAP|DDP|CPT|CIP)\s+"
        r"(USD|EUR|MXN|JPY|CNY)\s+([0-9,]+\.\d{2})",
        inv_text,
        flags=re.IGNORECASE
    )

    if m_invoice:
        result["Factura"] = m_invoice.group(1).upper()
        result["Fecha factura"] = m_invoice.group(2)
        result["Incoterm"] = m_invoice.group(3).upper()
        result["Moneda"] = m_invoice.group(4).upper()
        result["Valor factura"] = normalize_money(m_invoice.group(5))
    else:
        # Fallback más flexible: factura y luego fecha/incoterm/moneda/valor en algún punto cercano
        m_fact = re.search(r"\b([A-Z0-9][A-Z0-9\-\/]{2,})\b", inv_text)
        m_data = re.search(
            r"(\d{1,2}/\d{1,2}/\d{4})\s+(FOB|CIF|CFR|EXW|FCA|DAP|DDP|CPT|CIP)\s+"
            r"(USD|EUR|MXN|JPY|CNY)\s+([0-9,]+\.\d{2})",
            inv_text,
            flags=re.IGNORECASE
        )

        if m_fact:
            candidate = m_fact.group(1).upper()
            if not candidate.startswith("COVE"):
                result["Factura"] = candidate

        if m_data:
            result["Fecha factura"] = m_data.group(1)
            result["Incoterm"] = m_data.group(2).upper()
            result["Moneda"] = m_data.group(3).upper()
            result["Valor factura"] = normalize_money(m_data.group(4))

    return result


def extract_multiple_suppliers_from_pedimento(text: str) -> pd.DataFrame:
    t = re.sub(r"\s+", " ", text)

    # Ubicar todos los bloques "DATOS DEL PROVEEDOR O COMPRADOR"
    pattern = r"DATOS DEL PROVEEDOR O COMPRADOR"
    starts = [m.start() for m in re.finditer(pattern, t, flags=re.IGNORECASE)]

    rows = []

    if not starts:
        return pd.DataFrame(rows)

    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(t)

        # Cortar antes de transporte/agente/partidas para no contaminar
        block = t[start:end]
        stop = re.search(
            r"(TRANSPORTE IDENTIFICACION|NO\.?\s*\(GUIA|AGENTE ADUANAL|PARTIDAS|CLAVE/COMPL)",
            block,
            flags=re.IGNORECASE
        )
        if stop:
            block = block[:stop.start()]

        row = parse_supplier_block(block)
        row["Bloque"] = i + 1
        rows.append(row)

    return pd.DataFrame(rows)


# ============================================================
# UI
# ============================================================
uploaded = st.file_uploader("Sube pedimento PDF", type="pdf")

if uploaded:
    text = read_pdf(uploaded)

    st.subheader("Resultado multi-proveedor")
    df = extract_multiple_suppliers_from_pedimento(text)

    if df.empty:
        st.warning("No se detectaron proveedores.")
    else:
        cols = [
            "Bloque",
            "Proveedor",
            "Tax ID",
            "Dirección proveedor",
            "COVE",
            "Factura",
            "Fecha factura",
            "Incoterm",
            "Moneda",
            "Valor factura",
        ]
        df = df[[c for c in cols if c in df.columns]]
        st.dataframe(df, use_container_width=True)

        st.download_button(
            "Descargar proveedores detectados en Excel",
            data=df.to_csv(index=False).encode("utf-8-sig"),
            file_name="proveedores_pedimento.csv",
            mime="text/csv"
        )

    with st.expander("Ver texto extraído"):
        st.text_area("Texto", text, height=350)
