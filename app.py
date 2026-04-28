
import re
import io
from datetime import datetime

import pandas as pd
import streamlit as st
from pypdf import PdfReader

st.set_page_config(page_title="Auditoría Glosa Aduanal", layout="wide")
st.title("🛃 Auditoría Glosa Aduanal")
st.caption("Pedimento multi-proveedor vs facturas, packing list y BL/MBL/DO.")


def read_pdf(file):
    reader = PdfReader(file)
    text = ""
    for page in reader.pages:
        text += "\n" + (page.extract_text() or "")
    text = re.sub(r"---\s*PAGINA\s*\d+\s*---", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text)


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip(" .,:;-")


def normalize_money(value):
    if value in [None, ""]:
        return None
    s = str(value).replace(",", "")
    s = re.sub(r"[^0-9.\-]", "", s)
    try:
        return float(s)
    except Exception:
        return None


def fmt_money(value):
    if value in [None, ""]:
        return ""
    try:
        return f"{float(value):,.2f}"
    except Exception:
        return str(value)


def normalize_date(value):
    value = clean_text(value)
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", value)
    if m:
        return f"{int(m.group(1)):02d}/{int(m.group(2)):02d}/{m.group(3)}"

    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", value)
    if m:
        return f"{int(m.group(3)):02d}/{int(m.group(2)):02d}/{m.group(1)}"

    return ""


def norm_key(value):
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def is_sn_variant(value):
    v = str(value or "").upper().strip()
    v = v.replace("Í", "I").replace("Ú", "U").replace("Ñ", "N")
    compact = re.sub(r"[\s\.\-/]+", "", v)
    return compact in {"SN", "NA", "NOSN", "NONA", "NOAPLICA", "SINNUMERO", "SINNO", "SINNRO", "SINID", "SINREGISTRO"}


def normalize_tax_id(value):
    raw = str(value or "").strip().upper()
    raw = raw.replace("Í", "I").replace("Ú", "U").replace("Ñ", "N")
    if is_sn_variant(raw):
        return "S/N"
    value = re.sub(r"[^A-Z0-9\-]", "", raw)
    if re.match(r"^NO(?=\d)", value):
        value = value[2:]
    value = re.sub(r"NO$", "", value)
    return value.strip()


def split_values(value):
    if not value:
        return []
    return sorted(set([v.strip() for v in str(value).replace(";", ",").split(",") if v.strip()]))


def money_equal(a, b, tol=0.05):
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def split_name_and_address(raw):
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
        r"\bNORTH ROAD\b", r"\bTUANYI\b", r"\bHUADU\b",
        r"\bGUANGZHOU\b", r"\bMIAMI\b", r"\bFLORIDA\b",
        r"\bC\.P\.\b", r"\bCP\b",
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


def extract_sn_from_start(value):
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


def extract_supplier_area(text):
    t = re.sub(r"\s+", " ", text)
    start = re.search(r"DATOS DEL PROVEEDOR O COMPRADOR", t, flags=re.IGNORECASE)
    if not start:
        return ""

    area = t[start.end():]
    stop = re.search(
        r"(TRANSPORTE IDENTIFICACION|TRANSPORTISTA RFC|NO\.?\s*\(GUIA|AGENTE ADUANAL|PARTIDAS|CLAVE/COMPL)",
        area,
        flags=re.IGNORECASE
    )
    if stop:
        area = area[:stop.start()]
    return clean_text(area)


def split_supplier_records(area):
    records = []
    pattern = r"ID\.?\s*FISCAL\s+NOMBRE,\s*DENOMINACION\s*O\s*RAZON\s*SOCIAL\s+DOMICILIO:?"
    matches = list(re.finditer(pattern, area, flags=re.IGNORECASE))

    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(area)
        record = clean_text(area[start:end])
        if record:
            records.append(record)
    return records


def parse_invoice_part(record):
    out = {"COVE": "", "Factura": "", "Fecha factura": "", "Incoterm": "", "Moneda": "", "Valor factura": None}

    m_cove = re.search(r"\b(COVE[A-Z0-9]+)\b", record, flags=re.IGNORECASE)
    if m_cove:
        out["COVE"] = m_cove.group(1).upper()

    inv_text = re.sub(
        r"NUM\.?\s*CFDI\s*O\s*DOCUMENTO\s*EQUIVALENTE\s+FECHA\s+INCOTERM\s+MONEDA\s+FACT\s+VAL\.?\s*MON\.?\s*FACT\s+FACTOR\s+MON\.?\s+VAL\.?\s*DOLARES",
        " ",
        record,
        flags=re.IGNORECASE
    )
    inv_text = clean_text(inv_text)

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
        out["Fecha factura"] = normalize_date(m.group(2))
        out["Incoterm"] = m.group(3).upper()
        out["Moneda"] = m.group(4).upper()
        out["Valor factura"] = normalize_money(m.group(5))

    return out


def parse_supplier_record(record, index):
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

    parts = re.split(r"NUM\.?\s*CFDI\s*O\s*DOCUMENTO\s*EQUIVALENTE", record, maxsplit=1, flags=re.IGNORECASE)
    supplier_part = clean_text(parts[0])
    invoice_part = "NUM. CFDI O DOCUMENTO EQUIVALENTE " + parts[1] if len(parts) > 1 else ""

    supplier_parts = re.split(r"\bVINCULACION\b", supplier_part, maxsplit=1, flags=re.IGNORECASE)
    before = clean_text(supplier_parts[0]) if supplier_parts else ""
    after = clean_text(supplier_parts[1]) if len(supplier_parts) > 1 else ""

    before = re.sub(r"^(S\s*/?\s*N|N\s*/?\s*A|SN|NA|NO\s+APLICA|SIN\s+NUMERO|SIN\s+NÚMERO)\s+", "", before, flags=re.IGNORECASE).strip(" .,:;-")
    before = re.sub(r"^(?=[A-Z0-9\-]*\d)[A-Z0-9\-]{8,25}\s+", "", before).strip(" .,:;-")

    proveedor, direccion_from_before = split_name_and_address(before)
    sn_tax, after_without_sn = extract_sn_from_start(after)

    if sn_tax:
        tax_id = sn_tax
        direccion_from_after = after_without_sn
    else:
        after_clean = re.sub(r"^(NO|SI)\s+", "", after, flags=re.IGNORECASE).strip(" .,:;-")
        tax_match = re.match(r"^((?:NO)?(?=[A-Z0-9\-]*\d)[A-Z0-9\-]{6,25})\b(.*)$", after_clean, flags=re.IGNORECASE)
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
    row.update(parse_invoice_part(invoice_part))
    return row


def extract_multiple_suppliers_from_pedimento(text):
    area = extract_supplier_area(text)
    records = split_supplier_records(area)
    rows = [parse_supplier_record(record, i) for i, record in enumerate(records, start=1)]
    return pd.DataFrame(rows)


def classify_support(text, filename):
    t = (text + " " + filename).upper()
    if any(x in t for x in ["BILL OF LADING", "B/L NO", "BL NO", "SEA WAYBILL", "WAYBILL", "DELIVERY ORDER"]):
        return "BL/MBL/DO"
    if "PACKING LIST" in t or "LISTA DE EMPAQUE" in t:
        if "INVOICE" in t or "FACTURA" in t:
            return "FACTURA/PACKING"
        return "PACKING"
    if "FACTURA(S)" in t or "CARTA TRADUCCION" in t or "TAX ID" in t:
        return "CARTA 318"
    if "COMMERCIAL INVOICE" in t or "INVOICE" in t or "FACTURA" in t:
        return "FACTURA"
    return "SOPORTE"


def extract_support_invoice(text, filename):
    t = re.sub(r"\s+", " ", text)
    data = {
        "Archivo": filename,
        "Tipo": classify_support(text, filename),
        "Factura": "",
        "Fecha factura": "",
        "Proveedor": "",
        "Tax ID": "",
        "Incoterm": "",
        "Moneda": "",
        "Valor factura": None,
        "BL": "",
        "Bultos": None,
        "Peso bruto kg": None,
        "Contenedores": "",
    }

    candidates = []
    invoice_patterns = [
        r"(?:INVOICE\s*NO\.?|FACTURA\s*/?\s*INVOICE\s*NO\.?|FACTURA\s*NO\.?|NO\.?\s*FACTURA)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-\/]{2,})",
        r"\b([A-Z0-9]+-[A-Z0-9\-\/]+)\b",
        r"\b([A-Z]{2,}[0-9]{3,}[A-Z0-9\-\/]*)\b",
    ]
    for pat in invoice_patterns:
        for m in re.findall(pat, t, flags=re.IGNORECASE):
            cand = str(m).upper().strip()
            if not cand.startswith(("COVE", "HLCU", "ZIMU", "ONEY", "MAEU", "MEDU", "CMDU")):
                candidates.append(cand)
    if candidates:
        candidates = sorted(set(candidates), key=lambda x: ("-" not in x, len(x)))
        data["Factura"] = candidates[0]

    m_date = re.search(r"(?:DATE|FECHA|INVOICE DATE|FECHA/DATE)\s*[:#]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})", t, flags=re.IGNORECASE)
    if m_date:
        data["Fecha factura"] = normalize_date(m_date.group(1))
    else:
        m_date2 = re.search(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})\b", t)
        if m_date2:
            data["Fecha factura"] = normalize_date(m_date2.group(1))

    m_inc = re.search(r"\b(FOB|CIF|CFR|EXW|FCA|DAP|DDP|CPT|CIP)\b", t, flags=re.IGNORECASE)
    if m_inc:
        data["Incoterm"] = m_inc.group(1).upper()

    if re.search(r"\bUSD\b|US\$|\$", t, flags=re.IGNORECASE):
        data["Moneda"] = "USD"
    else:
        m_cur = re.search(r"\b(EUR|MXN|JPY|CNY)\b", t, flags=re.IGNORECASE)
        if m_cur:
            data["Moneda"] = m_cur.group(1).upper()

    values = []
    total_patterns = [
        r"(?:GRAND\s*TOTAL|TOTAL\s*AMOUNT|TOTAL|VALOR\s*DE\s*LA\s*MERCANCIA)\s*[:#]?\s*(?:USD|US\$|\$)?\s*([0-9,]+\.\d{2})",
        r"(?:USD|US\$|\$)\s*([0-9,]+\.\d{2})",
    ]
    for pat in total_patterns:
        for m in re.findall(pat, t, flags=re.IGNORECASE):
            val = normalize_money(m)
            if val:
                values.append(val)
    if values:
        data["Valor factura"] = max(values)

    m_tax = re.search(r"TAX\s*ID\.?\s*[:#]?\s*([A-Z0-9\-\/]+)", t, flags=re.IGNORECASE)
    if m_tax:
        data["Tax ID"] = normalize_tax_id(m_tax.group(1))

    m_prov = re.search(r"([A-Z0-9 .,&'\-()]+?(?:TRADING\s+CO\.?,?\s*LTD\.?|CO\.?,?\s*LTD\.?|LIMITED|INC\.?|CORP\.?|LLC))", t, flags=re.IGNORECASE)
    if m_prov:
        prov = clean_text(m_prov.group(1))
        prov = re.sub(r"^PAGINA\s+\d+\s*", "", prov, flags=re.IGNORECASE)
        data["Proveedor"] = prov

    bl_patterns = [
        r"(?:BILL\s*OF\s*LADING\s*NO\.?|B/L\s*NO\.?|BL\s*NO\.?|WAYBILL\s*NO\.?)\s*[:#]?\s*([A-Z0-9\-]{6,})",
        r"\b(ZIM[A-Z0-9]{6,}|ONEY[A-Z0-9]{6,}|HLCU[A-Z0-9]{6,}|MAEU[A-Z0-9]{6,}|MEDU[A-Z0-9]{6,})\b",
    ]
    for pat in bl_patterns:
        m = re.search(pat, t, flags=re.IGNORECASE)
        if m:
            data["BL"] = m.group(1).upper()
            break

    m_pkg = re.search(r"(\d+)\s+(?:PACKAGES|PACKAGE|PKGS|PKG|BULTOS|PALLETS|PALLET)", t, flags=re.IGNORECASE)
    if m_pkg:
        data["Bultos"] = int(m_pkg.group(1))

    m_weight = re.search(r"(?:GROSS\s*WEIGHT|G\.?W\.?|PESO\s*BRUTO)\s*[:#]?\s*([0-9,]+(?:\.\d+)?)\s*(?:KGS?|KG)", t, flags=re.IGNORECASE)
    if m_weight:
        data["Peso bruto kg"] = normalize_money(m_weight.group(1))
    else:
        weights = [normalize_money(x) for x in re.findall(r"([0-9,]+(?:\.\d+)?)\s*(?:KGS?|KG)", t, flags=re.IGNORECASE)]
        weights = [w for w in weights if w]
        if weights:
            data["Peso bruto kg"] = max(weights)

    containers = sorted(set(re.findall(r"\b[A-Z]{4}\d{7}\b", t)))
    if containers:
        data["Contenedores"] = ", ".join(containers)

    return data


def build_audit(ped_df, support_df):
    rows = []

    def add(riesgo, campo, estatus, observacion, ped="", soporte="", archivo=""):
        rows.append({
            "Riesgo": riesgo,
            "Campo": campo,
            "Estatus": estatus,
            "Pedimento": ped,
            "Soporte": soporte,
            "Archivo soporte": archivo,
            "Observación": observacion,
        })

    if ped_df.empty:
        add("CRITICO", "Pedimento", "❌ Error", "No se detectaron proveedores/facturas en pedimento.")
        return pd.DataFrame(rows)

    supports_by_invoice = {}
    if not support_df.empty:
        for _, s in support_df.iterrows():
            inv = norm_key(s.get("Factura", ""))
            if inv:
                supports_by_invoice.setdefault(inv, []).append(s)

    for _, p in ped_df.iterrows():
        factura = str(p.get("Factura", "") or "")
        factura_key = norm_key(factura)

        if not factura:
            add("CRITICO", "Factura", "❌ No localizada", "No se detectó factura en un proveedor del pedimento.")
            continue

        related = supports_by_invoice.get(factura_key, [])

        if not related:
            add("CRITICO", "Factura", "❌ No encontrada en soportes", f"No se encontró soporte para factura {factura}.", ped=factura)
            continue

        add("CRITICO", "Factura", "✔️ Coincide", f"Factura {factura} localizada en soportes.", ped=factura, soporte=factura, archivo=", ".join([r["Archivo"] for r in related]))

        for s in related:
            archivo = s.get("Archivo", "")

            checks = [
                ("Fecha factura", p.get("Fecha factura", ""), s.get("Fecha factura", ""), "CRITICO", "date"),
                ("Incoterm", p.get("Incoterm", ""), s.get("Incoterm", ""), "CRITICO", "text"),
                ("Moneda", p.get("Moneda", ""), s.get("Moneda", ""), "CRITICO", "text"),
            ]

            for campo, ped_val, sop_val, riesgo, tipo in checks:
                if ped_val and sop_val:
                    equal = normalize_date(ped_val) == normalize_date(sop_val) if tipo == "date" else str(ped_val).upper() == str(sop_val).upper()
                    add(riesgo, campo, "✔️ Coincide" if equal else "❌ Diferencia", "OK" if equal else "Diferencia detectada.", ped=ped_val, soporte=sop_val, archivo=archivo)
                else:
                    add("MEDIO", campo, "⚠️ No suficiente", "Falta dato en pedimento o soporte.", ped=ped_val, soporte=sop_val, archivo=archivo)

            ped_val = p.get("Valor factura", None)
            sop_val = s.get("Valor factura", None)
            if ped_val is not None and sop_val is not None:
                equal = money_equal(ped_val, sop_val)
                add("CRITICO", "Valor factura", "✔️ Coincide" if equal else "❌ Diferencia", "OK" if equal else "Valor diferente.", ped=fmt_money(ped_val), soporte=fmt_money(sop_val), archivo=archivo)
            else:
                add("MEDIO", "Valor factura", "⚠️ No suficiente", "Falta valor en pedimento o soporte.", ped=fmt_money(ped_val), soporte=fmt_money(sop_val), archivo=archivo)

            ped_prov = norm_key(p.get("Proveedor", ""))
            sop_prov = norm_key(s.get("Proveedor", ""))
            if ped_prov and sop_prov:
                equal = ped_prov in sop_prov or sop_prov in ped_prov
                add("BAJO", "Proveedor", "✔️ Coincide" if equal else "⚠️ Revisar", "Comparación flexible.", ped=p.get("Proveedor", ""), soporte=s.get("Proveedor", ""), archivo=archivo)

    if not support_df.empty:
        bl_docs = support_df[support_df["Tipo"].isin(["BL/MBL/DO", "PACKING", "FACTURA/PACKING"])]
        if not bl_docs.empty:
            bls = sorted(set([x for x in bl_docs["BL"].dropna().astype(str) if x]))
            containers = sorted(set(sum([split_values(x) for x in bl_docs["Contenedores"].dropna().astype(str)], [])))
            weights = [x for x in bl_docs["Peso bruto kg"].dropna().tolist() if x]
            packages = [x for x in bl_docs["Bultos"].dropna().tolist() if x]

            add("CRITICO", "BL", "✔️ Detectado" if bls else "⚠️ No localizado", ", ".join(bls) if bls else "No se detectó BL.", soporte=", ".join(bls))
            add("CRITICO", "Contenedores", "✔️ Detectado" if containers else "⚠️ No localizado", ", ".join(containers) if containers else "No se detectaron contenedores.", soporte=", ".join(containers))
            add("MEDIO", "Peso bruto kg", "✔️ Detectado" if weights else "⚠️ No localizado", ", ".join([fmt_money(w) for w in weights]) if weights else "No se detectó peso.", soporte=", ".join([fmt_money(w) for w in weights]))
            add("MEDIO", "Bultos", "✔️ Detectado" if packages else "⚠️ No localizado", ", ".join([str(int(p)) for p in packages]) if packages else "No se detectaron bultos.", soporte=", ".join([str(int(p)) for p in packages]))

    return pd.DataFrame(rows)


def score_audit(audit_df):
    if audit_df.empty:
        return "SIN DATOS", 0
    bad_critical = audit_df[(audit_df["Riesgo"] == "CRITICO") & audit_df["Estatus"].str.contains("❌", regex=False)]
    bad_any = audit_df[audit_df["Estatus"].str.contains("❌", regex=False)]
    warn = audit_df[audit_df["Estatus"].str.contains("⚠️", regex=False)]
    ok = audit_df[audit_df["Estatus"].str.contains("✔️", regex=False)]
    score = round(len(ok) / max(len(audit_df), 1) * 100, 1)
    if len(bad_critical) > 0:
        return "🔴 ALTO RIESGO", score
    if len(bad_any) > 0 or len(warn) > 0:
        return "🟡 REVISAR", score
    return "🟢 LIBERABLE", score


ped_file = st.file_uploader("1) Sube PEDIMENTO PDF", type="pdf")
support_files = st.file_uploader("2) Sube SOPORTES PDF", type="pdf", accept_multiple_files=True)

if not ped_file:
    st.info("Sube primero el pedimento.")
    st.stop()

ped_text = read_pdf(ped_file)
ped_df = extract_multiple_suppliers_from_pedimento(ped_text)

st.subheader("1) Proveedores / facturas detectadas en pedimento")
if ped_df.empty:
    st.warning("No se detectaron proveedores/facturas en pedimento.")
else:
    ped_df = st.data_editor(ped_df, use_container_width=True, num_rows="dynamic", key="ped_editor")

support_rows = []
raw_texts = {ped_file.name: ped_text}

if support_files:
    for f in support_files:
        txt = read_pdf(f)
        raw_texts[f.name] = txt
        support_rows.append(extract_support_invoice(txt, f.name))

support_df = pd.DataFrame(support_rows)

st.subheader("2) Datos detectados en soportes")
if support_df.empty:
    st.info("Sube soportes PDF para comparar contra el pedimento.")
else:
    support_df = st.data_editor(support_df, use_container_width=True, num_rows="dynamic", key="support_editor")

st.subheader("3) Auditoría")
if st.button("Ejecutar auditoría", type="primary"):
    audit_df = build_audit(ped_df, support_df)
    result, score = score_audit(audit_df)

    c1, c2 = st.columns(2)
    c1.metric("Resultado", result)
    c2.metric("Coincidencia", f"{score}%")

    st.dataframe(audit_df, use_container_width=True)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame({"Resultado": [result], "Score": [score], "Fecha": [datetime.now().strftime("%d/%m/%Y %H:%M")]}).to_excel(writer, index=False, sheet_name="Resumen")
        ped_df.to_excel(writer, index=False, sheet_name="Pedimento")
        support_df.to_excel(writer, index=False, sheet_name="Soportes")
        audit_df.to_excel(writer, index=False, sheet_name="Auditoria")

    st.download_button(
        "Descargar auditoría Excel",
        data=output.getvalue(),
        file_name=f"auditoria_glosa_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

with st.expander("Ver texto extraído"):
    selected = st.selectbox("Documento", list(raw_texts.keys()))
    st.text_area("Texto", raw_texts[selected], height=350)
