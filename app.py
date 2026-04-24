import re
import io
from datetime import datetime
from typing import Any, Dict, List, Tuple

import pandas as pd
import streamlit as st
from pypdf import PdfReader

try:
    import pdfplumber
except Exception:
    pdfplumber = None

st.set_page_config(page_title="Auditoría Agencia Aduanal", page_icon="🛃", layout="wide")
st.title("🛃 Auditoría Agencia Aduanal")
st.caption("Pedimento vs factura, carta 318, packing list, BL/DO y partidas. Sin fracción ni incrementables.")

# ================= UTILIDADES =================
def normalize(text: Any) -> str:
    if text is None:
        return ""
    text = str(text).upper()
    repl = {"；":";", "，":",", "：":":", "（":"(", "）":")", "\u00a0":" ", "Á":"A", "É":"E", "Í":"I", "Ó":"O", "Ú":"U", "®":""}
    for a, b in repl.items():
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip()

def clean_number(value):
    if value in [None, ""]:
        return None
    s = str(value).upper().replace(",", "")
    for token in ["US$", "USD", "US", "$", "KGS", "KG", "MXN", "EUR", "CBM", "PCS", "PIEZAS", "PIEZA", "PACKAGES", "PACKAGE", "PKGS", "PKG"]:
        s = s.replace(token, "")
    s = re.sub(r"[^0-9.\-]", "", s)
    try:
        return float(s)
    except Exception:
        return None

def fmt_num(value):
    if value in [None, ""]:
        return ""
    try:
        return f"{float(value):,.2f}"
    except Exception:
        return str(value)

def date_to_ddmmyyyy(text):
    if not text:
        return ""
    t = normalize(text)
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", t)
    if m:
        return f"{int(m.group(1)):02d}/{int(m.group(2)):02d}/{m.group(3)}"
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", t)
    if m:
        return f"{int(m.group(3)):02d}/{int(m.group(2)):02d}/{m.group(1)}"
    months = {"JAN":"01", "JANUARY":"01", "FEB":"02", "FEBRUARY":"02", "MAR":"03", "MARCH":"03", "APR":"04", "APRIL":"04", "MAY":"05", "JUN":"06", "JUNE":"06", "JUL":"07", "JULY":"07", "AUG":"08", "AUGUST":"08", "SEP":"09", "SEPTEMBER":"09", "OCT":"10", "OCTOBER":"10", "NOV":"11", "NOVEMBER":"11", "DEC":"12", "DECEMBER":"12"}
    m = re.search(r"(JANUARY|JAN|FEBRUARY|FEB|MARCH|MAR|APRIL|APR|MAY|JUNE|JUN|JULY|JUL|AUGUST|AUG|SEPTEMBER|SEP|OCTOBER|OCT|NOVEMBER|NOV|DECEMBER|DEC)\.?\s*(\d{1,2})(?:ST|ND|RD|TH)?[,]?\s*(\d{2,4})", t)
    if m:
        year = m.group(3)
        if len(year) == 2:
            year = "20" + year
        return f"{int(m.group(2)):02d}/{months[m.group(1)]}/{year}"
    return ""

def split_values(value):
    if not value:
        return []
    return sorted(set([x.strip() for x in str(value).replace(";", ",").split(",") if x.strip()]))

def same_set(a, b):
    return set(split_values(a)) == set(split_values(b))

# ================= PDF =================
def read_pdf_pypdf(uploaded_file):
    uploaded_file.seek(0)
    reader = PdfReader(uploaded_file)
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            pages.append(f"\n--- PAGINA {i} ---\n" + (page.extract_text() or ""))
        except Exception:
            pages.append(f"\n--- PAGINA {i} ---\n")
    return "\n".join(pages)

def read_pdf_pdfplumber(uploaded_file):
    if pdfplumber is None:
        return ""
    uploaded_file.seek(0)
    pages = []
    try:
        with pdfplumber.open(uploaded_file) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
                table_text = ""
                try:
                    for table in page.extract_tables() or []:
                        for row in table:
                            table_text += " | ".join(str(c or "") for c in row) + "\n"
                except Exception:
                    pass
                pages.append(f"\n--- PAGINA {i} ---\n{text}\n{table_text}")
    except Exception:
        return ""
    return "\n".join(pages)

def read_pdf(uploaded_file):
    a = read_pdf_pypdf(uploaded_file)
    b = read_pdf_pdfplumber(uploaded_file)
    return b if len(b) > len(a) else a

# ================= CLASIFICACIÓN =================
def classify_doc(text: str, filename: str = "") -> str:
    t = normalize(text + " " + filename)
    if "NUM. PEDIMENTO" in t or "ANEXO DEL PEDIMENTO" in t:
        return "PEDIMENTO"
    if "DELIVERY ORDER" in t or "B/L NO" in t or "BILL OF LADING" in t or "CONOCIMIENTO MARITIMO" in t or "HAPAG-LLOYD" in t:
        return "BL_DO"
    if "PACKING LIST" in t or "LISTA DE EMPAQUE" in t:
        if "COMMERCIAL INVOICE" in t or "INVOICE NO" in t:
            return "INVOICE_PACKING"
        return "PACKING"
    if "FACTURA(S)" in t and "TAX ID" in t:
        return "CARTA_318"
    if "COMMERCIAL INVOICE" in t or "INVOICE NO" in t or "PROFORMA INVOICE" in t or "FACTURA" in t:
        return "INVOICE"
    return "SOPORTE"

# ================= EXTRACTORES =================
def get_invoice_candidates(t: str) -> List[str]:
    candidates = []
    patterns = [
        r"(?:INVOICE\s*NO\.?|INVOICE\s*NUMBER|PROFORMA\s*INVOICE\s*NO\.?|FACTURA\(S\)\s*NO\.?|FACTURA\s*NO\.?|NO\.?\s*FACTURA|NUMERO\s*DE\s*FACTURA)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-\/]{4,})",
        r"\b([A-Z]{1,8}\d{4,}[A-Z0-9\-\/]{0,})\b",
    ]
    for pat in patterns:
        for m in re.findall(pat, t):
            val = m.strip().strip(":")
            if len(val) >= 5:
                candidates.append(val)
    filtered = []
    for c in candidates:
        if re.match(r"^[A-Z]{4}\d{7}$", c):
            continue
        if c.startswith(("ZIM", "HLCU", "MAEU", "ONEY", "CMDU", "MEDU")) and len(c) > 8:
            continue
        if c not in filtered:
            filtered.append(c)
    return filtered

def choose_invoice(candidates: List[str]) -> str:
    if not candidates:
        return ""
    scored = []
    for c in candidates:
        score = 0
        if "-" in c:
            score += 6
        if re.search(r"[A-Z]", c) and re.search(r"\d", c):
            score += 4
        if c.startswith(("HF", "INV", "CI", "FAC", "SW")):
            score += 4
        scored.append((score, c))
    scored.sort(reverse=True)
    return scored[0][1]

def extract_pedimento_invoice_block(t: str) -> Dict[str, Any]:
    result = {"Factura": "", "Fecha factura": "", "Incoterm": "", "Moneda": "", "Total factura": None}
    m = re.search(r"\b([A-Z]{1,8}\d{4,}[A-Z0-9\-\/]*)\s+(\d{1,2}/\d{1,2}/\d{4})\s+(FOB|CIF|CFR|EXW|FCA|DAP|DDP|CPT|CIP)\s+(USD|EUR|MXN)\s+([0-9,]+\.\d{2})", t)
    if m:
        result.update({"Factura": m.group(1), "Fecha factura": date_to_ddmmyyyy(m.group(2)), "Incoterm": m.group(3), "Moneda": m.group(4), "Total factura": clean_number(m.group(5))})
        return result
    inv = choose_invoice(get_invoice_candidates(t))
    if inv:
        idx = t.find(inv)
        if idx >= 0:
            window = t[idx:idx+500]
            m2 = re.search(r"(\d{1,2}/\d{1,2}/\d{4})\s+(FOB|CIF|CFR|EXW|FCA|DAP|DDP|CPT|CIP)\s+(USD|EUR|MXN)\s+([0-9,]+\.\d{2})", window)
            if m2:
                result.update({"Factura": inv, "Fecha factura": date_to_ddmmyyyy(m2.group(1)), "Incoterm": m2.group(2), "Moneda": m2.group(3), "Total factura": clean_number(m2.group(4))})
    return result

def extract_date(t: str, invoice_no: str = "") -> str:
    if invoice_no:
        idx = t.find(invoice_no)
        if idx >= 0:
            d = date_to_ddmmyyyy(t[idx:idx+450])
            if d:
                return d
    m = re.search(r"(?:INVOICE\s*DATE|DATE|FECHA\(S\)|FECHA\s*FACTURA|FECHA)\s*[:#]?\s*([A-Z]+\.?\s*\d{1,2}(?:ST|ND|RD|TH)?[,]?\s*\d{2,4}|\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})", t)
    return date_to_ddmmyyyy(m.group(1)) if m else ""

def extract_total_invoice(t: str, doc_type: str, invoice_no: str = ""):
    if doc_type == "PEDIMENTO":
        block = extract_pedimento_invoice_block(t)
        if block.get("Total factura") is not None:
            return block["Total factura"]
    compact = re.sub(r"\s+", " ", t)
    if invoice_no:
        idx = compact.find(invoice_no)
        if idx >= 0:
            window = compact[idx:idx+3000]
            m = re.search(r"\d{1,2}/\d{1,2}/\d{4}\s+(?:FOB|CIF|CFR|EXW|FCA|DAP|DDP|CPT|CIP)\s+(?:USD|EUR|MXN)\s+([0-9,]+\.\d{2})", window)
            if m:
                return clean_number(m.group(1))
            m = re.search(r"(?:GRAND\s*TOTAL|TOTAL\s*AMOUNT|TOTAL|SUB\s*TOTAL\s*AMOUNT|VALOR\s*DE\s*LA\s*MERCANCIA).{0,250}?(?:US\$|USD|\$)?\s*([0-9,]+\.\d{2})", window)
            if m:
                return clean_number(m.group(1))
    patterns = [
        r"TOTAL\s*\([^)]*\)\s*[:#]?\s*(?:合计[:#]?)?\s*(?:US\$|USD|\$)?\s*([0-9,]+\.\d{2})",
        r"(?:GRAND\s*TOTAL|TOTAL\s+AMOUNT|TOTAL|SUB\s*TOTAL\s*AMOUNT|VALOR\s*DE\s*LA\s*MERCANCIA)\s*[:#]?\s*(?:US\$|USD|\$)?\s*([0-9,]+\.\d{2})",
        r"(?:GRAND\s*TOTAL|TOTAL\s+AMOUNT|TOTAL|SUB\s*TOTAL\s*AMOUNT|VALOR\s*DE\s*LA\s*MERCANCIA).{0,160}?(?:US\$|USD|\$)\s*([0-9,]+\.\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, compact)
        if m:
            return clean_number(m.group(1))
    vals = [clean_number(x) for x in re.findall(r"(?:US\$|USD|\$)\s*([0-9,]+\.\d{2})", compact)]
    vals = [x for x in vals if x is not None]
    return max(vals) if vals else None

def extract_incoterm(t):
    m = re.search(r"\b(FOB|CIF|CFR|EXW|FCA|DAP|DDP|DDU|CPT|CIP)\b", t)
    return m.group(1) if m else ""

def extract_currency(t):
    if "US$" in t or "US DOLLARS" in t or " USD " in f" {t} ":
        return "USD"
    m = re.search(r"\b(USD|EUR|MXN|CNY|RMB|JPY)\b", t)
    return m.group(1) if m else ""

def extract_provider_name(t, doc_type):
    if doc_type == "CARTA_318":
        m = re.search(r"DATOS DEL PROVEEDOR.*?NOMBRE Y/O RAZON SOCIAL[:.\s]+(.*?)(?:DIRECCION|TAX ID)", t)
        if m: return m.group(1).strip(" .:")
    if doc_type == "PEDIMENTO":
        m = re.search(r"DATOS DEL PROVEEDOR.*?NOMBRE,\s*DENOMINACION\s*O\s*RAZON\s*SOCIAL\s+DOMICILIO[:\s]*(.*?)(?:VINCULACION|NO\s+)", t)
        if m: return m.group(1).strip(" .:")
    m = re.search(r"([A-Z0-9 .,&\-]+CO\.?,?\s*LTD\.?|[A-Z0-9 .,&\-]+LIMITED).*?(?:COMMERCIAL INVOICE|TO MESSRS|ADDRESS)", t)
    return m.group(1).strip(" .:") if m else ""

def extract_provider_address(t, doc_type):
    if doc_type == "CARTA_318":
        m = re.search(r"DATOS DEL PROVEEDOR.*?DIRECCION[:.\s]+(.*?)(?:TAX ID|FACTURA)", t)
        if m: return m.group(1).strip(" .:")
    if doc_type == "PEDIMENTO":
        m = re.search(r"DATOS DEL PROVEEDOR.*?DOMICILIO[:\s]*(.*?)(?:NUM\. CFDI|TRANSPORTE|VINCULACION)", t)
        if m: return m.group(1).strip(" .:")
    m = re.search(r"(NO\.?\s*[0-9].*?CHINA|ADDRESS[:\s].*?CHINA|[A-Z0-9 .,\-]+HUNAN,?CHINA|[A-Z0-9 .,\-]+XIAMEN CITY,?CHINA)", t)
    return m.group(1).strip(" .:") if m else ""

def extract_tax_id(t):
    m = re.search(r"TAX\s*ID\.?\s*[:#]?\s*([A-Z0-9\-]+)", t)
    if m: return m.group(1)
    m = re.search(r"ID\.?\s*FISCAL\s+([A-Z0-9\-]+)", t)
    return m.group(1) if m else ""

def extract_bl(t):
    for pat in [r"(?:B/L\s*NO\.?|BL\s*NO\.?|BILL\s*OF\s*LADING\s*NO\.?|NO\.?\s*\(GUIA/ORDEN EMBARQUE\)/ID)\s*[:#]?\s*([A-Z0-9]{8,})", r"\b(ZIM[A-Z0-9]{8,}|HLCU[A-Z0-9]{8,}|ONEY[A-Z0-9]+|MAEU[A-Z0-9]+|MEDU[A-Z0-9]+|CMDU[A-Z0-9]+|OOLU[A-Z0-9]+|COSU[A-Z0-9]+)\b"]:
        m = re.search(pat, t)
        if m: return m.group(1)
    return ""

def extract_containers(t):
    return ", ".join(sorted(set(re.findall(r"\b[A-Z]{4}\d{7}\b", t))))

def extract_bultos(t, doc_type):
    compact = re.sub(r"\s+", " ", t)
    if doc_type == "PEDIMENTO":
        m = re.search(r"MARCAS,\s*NUMEROS\s*Y\s*TOTAL\s*DE\s*BULTOS[:\s].{0,140}?(\d{1,6})\b", compact)
        if m: return clean_number(m.group(1))
    for pat in [r"ALL\s+ABOVE\s+MENTIONED\s+GOODS\s+ARE\s+(\d+)\s+PACKAGES", r"TOTAL[:\s].{0,120}?(\d+)\s+(?:PACKAGES|PACKAGE|PKGS|PKG|BULTOS)", r"(\d+)\s+(?:PACKAGES|PACKAGE|PKGS|PKG|BULTOS)", r"NO\.?\s*OF\s*PKGS\.?\s*[:#]?\s*(\d+)"]:
        m = re.search(pat, compact)
        if m: return clean_number(m.group(1))
    return None

def extract_gross_weight(t, doc_type):
    compact = re.sub(r"\s+", " ", t)
    for pat in [r"GROSS\s*WEIGHT\s*[:#]?\s*([0-9,]+\.\d{2,3}|[0-9,]+)\s*KGS?", r"TOTAL\s*[:#]?.{0,220}?CBM\s+([0-9,]+\.\d{2,3}|[0-9,]+)\s*KGS?", r"GROSS\s*WEIGHT.*?([0-9,]+\.\d{2,3}|[0-9,]+)\s*KG", r"PESO\s*BRUTO[:\s]*([0-9,]+\.\d{2,3}|[0-9,]+)", r"TOTAL\s*:\s*\d+X\d+HC\s+([0-9,]+\.\d{2,3}|[0-9,]+)"]:
        m = re.search(pat, compact)
        if m: return clean_number(m.group(1))
    return None

def extract_quantity_total(t, doc_type):
    qtys = []
    for m in re.finditer(r"\b(\d+)\s*(?:PIEZA|PIEZAS|PCS|PIECES|UNIT|UNITS)\b", t):
        try: qtys.append(int(m.group(1)))
        except Exception: pass
    return sum(qtys) if qtys else None

def extract_descriptions(text):
    t = normalize(text)
    descs = []
    for pat in [r"(EXCAVADORA HIDRAULICA|FILTROS? DE TRANSMISION|SPARE PARTS FOR EXCAVATOR|SUNWARD HYDRAULIC EXCAVATOR [A-Z0-9\-]+|MONTACARGAS ELECTRICO[^0-9$]+)"]:
        for val in re.findall(pat, t):
            val = re.sub(r"\s+", " ", val).strip()
            if val and val not in descs: descs.append(val)
    return " | ".join(descs[:10])

def extract_merchandise(text, filename, doc_type):
    t = normalize(text)
    rows = []
    for pat in [r"([A-Z0-9\s\-/\.,]{5,100})\s+(\d+)\s*(?:PIEZA|PIEZAS|PCS|UNIT|UNITS)\s+\$?([0-9,]+\.\d{2})\s+\$?([0-9,]+\.\d{2})", r"([A-Z0-9 \-/\.]{3,100})\s+(\d+)\s+\$?([0-9,]+\.\d{2})\s+\$?([0-9,]+\.\d{2})"]:
        for m in re.finditer(pat, t):
            desc, qty, unit, total = m.groups()
            desc = desc.strip()
            if len(desc) < 3 or "TOTAL" in desc: continue
            rows.append({"Documento": filename, "Descripción": desc, "Cantidad": clean_number(qty), "Precio unitario": clean_number(unit), "Total": clean_number(total)})
    return rows

def extract_fields(text, filename=""):
    t = normalize(text)
    doc_type = classify_doc(text, filename)
    invoice_no = choose_invoice(get_invoice_candidates(t))
    data = {
        "Tipo documento": doc_type, "Factura": invoice_no, "Fecha factura": extract_date(t, invoice_no),
        "Proveedor": extract_provider_name(t, doc_type), "Dirección proveedor": extract_provider_address(t, doc_type), "Tax ID": extract_tax_id(t, doc_type),
        "Incoterm": extract_incoterm(t), "Moneda": extract_currency(t), "Total factura": extract_total_invoice(t, doc_type, invoice_no),
        "Descripción partidas": extract_descriptions(text), "BL": extract_bl(t), "Bultos": extract_bultos(t, doc_type),
        "Peso bruto kg": extract_gross_weight(t, doc_type), "Contenedores": extract_containers(t), "Cantidad total": extract_quantity_total(t, doc_type),
    }
    if doc_type == "PEDIMENTO":
        block = extract_pedimento_invoice_block(t)
        for key in ["Factura", "Fecha factura", "Incoterm", "Moneda", "Total factura"]:
            if block.get(key) not in [None, ""]: data[key] = block[key]
        m = re.search(r"NUM\.?\s*PEDIMENTO[:\s]*([0-9]{2}\s+[0-9]{2}\s+[0-9]{4}\s+[0-9]{7}|[0-9 ]{15,25})", t)
        data["Pedimento"] = m.group(1).strip() if m else ""
        data["Borrador"] = "SI" if "BORRADOR SIN VALIDEZ" in t else "NO"
    return data

# ================= AUDITORÍA =================
def compare_exact(values):
    present = {k: v for k, v in values.items() if v not in [None, "", " "]}
    if len(present) <= 1: return "⚠️ No suficiente", "Solo hay una fuente o no se localizó", ""
    norm = {k: normalize(v) for k, v in present.items()}
    if len(set(norm.values())) == 1: return "✔️ Coincide", "; ".join([f"{k}: {v}" for k, v in present.items()]), ""
    counts = {}
    for v in norm.values(): counts[v] = counts.get(v, 0) + 1
    suspect = [k for k, v in norm.items() if counts[v] == 1]
    return "❌ Diferencia", "; ".join([f"{k}: {v}" for k, v in present.items()]), ", ".join(suspect)

def compare_number(values, tolerance=0.02):
    present = {k: v for k, v in values.items() if v not in [None, "", " "]}
    if len(present) <= 1: return "⚠️ No suficiente", "Solo hay una fuente o no se localizó", ""
    nums = {k: float(v) for k, v in present.items()}
    ref = list(nums.values())[0]
    if all(abs(v-ref) <= tolerance for v in nums.values()): return "✔️ Coincide", "; ".join([f"{k}: {fmt_num(v)}" for k, v in nums.items()]), ""
    rounded = {k: round(v, 2) for k, v in nums.items()}
    counts = {}
    for v in rounded.values(): counts[v] = counts.get(v, 0)+1
    suspect = [k for k, v in rounded.items() if counts[v] == 1]
    return "❌ Diferencia", "; ".join([f"{k}: {fmt_num(v)}" for k, v in nums.items()]), ", ".join(suspect)

def compare_set(values):
    present = {k: v for k, v in values.items() if v not in [None, "", " "]}
    if len(present) <= 1: return "⚠️ No suficiente", "Solo hay una fuente o no se localizó", ""
    sets = {k: set(split_values(v)) for k, v in present.items()}
    first = list(sets.values())[0]
    if all(s == first for s in sets.values()): return "✔️ Coincide", "; ".join([f"{k}: {', '.join(sorted(v))}" for k, v in sets.items()]), ""
    return "❌ Diferencia", "; ".join([f"{k}: {', '.join(sorted(v))}" for k, v in sets.items()]), "Revisar dato faltante/diferente"

def audit_agency(ped_data, docs_data, tolerance):
    rows = []
    all_docs = {"PEDIMENTO": ped_data, **docs_data}
    def add(risk, area, field, status, obs, suspect="", rule=""):
        rows.append({"Riesgo": risk, "Área": area, "Campo": field, "Estatus": status, "Observación": obs, "Documento probable a corregir": suspect, "Regla": rule})
    for label, key, mode in [("Factura","Factura","exact"),("Fecha factura","Fecha factura","exact"),("Total factura","Total factura","number"),("Moneda","Moneda","exact"),("Incoterm","Incoterm","exact"),("BL","BL","exact"),("Contenedores","Contenedores","set")]:
        values = {name: data.get(key) for name, data in all_docs.items()}
        if mode == "number": status, obs, suspect = compare_number(values, tolerance)
        elif mode == "set": status, obs, suspect = compare_set(values)
        else: status, obs, suspect = compare_exact(values)
        add("CRITICO", "Glosa principal", label, status, obs, suspect, "Debe coincidir en pedimento y soportes")
    logistics = {"PEDIMENTO": ped_data, **{n:d for n,d in docs_data.items() if d.get("Tipo documento") in ["PACKING","INVOICE_PACKING","BL_DO"]}}
    for label, key, tol in [("Peso bruto kg","Peso bruto kg",1.0),("Bultos","Bultos",0.01)]:
        values = {name: data.get(key) for name, data in logistics.items()}
        status, obs, suspect = compare_number(values, tol)
        if key == "Bultos" and "❌" in status:
            non_ped = {k:v for k,v in values.items() if k != "PEDIMENTO" and v not in [None,"", " "]}
            st2, obs2, sus2 = compare_number(non_ped, 0.01)
            if "✔️" in st2:
                status = "⚠️ Advertencia"
                obs += " | Packing/BL coinciden; pedimento puede declarar UMC/cantidad distinta a packages."
                suspect = "Revisar bultos vs UMC"
        add("MEDIO", "Logística", label, status, obs, suspect, "Peso y bultos deben coincidir principalmente entre Packing y BL/DO")
    documentary = {"PEDIMENTO": ped_data, **{n:d for n,d in docs_data.items() if d.get("Tipo documento") in ["INVOICE","INVOICE_PACKING","CARTA_318"]}}
    for label, key in [("Proveedor","Proveedor"),("Dirección proveedor","Dirección proveedor"),("Tax ID","Tax ID"),("Descripción partidas","Descripción partidas")]:
        values = {name: data.get(key) for name, data in documentary.items()}
        status, obs, suspect = compare_exact(values)
        if "❌" in status: status = "⚠️ Revisar"
        add("BAJO", "Documental", label, status, obs, suspect, "Validación documental; no bloquea por sí sola")
    qty_values = {name: data.get("Cantidad total") for name, data in all_docs.items()}
    status, obs, suspect = compare_number(qty_values, 0.01)
    if "❌" in status: status = "⚠️ Revisar"
    add("MEDIO", "Partidas", "Cantidad total vs documentos", status, obs, suspect, "Cantidad total razonable entre factura/carta/pedimento; bultos no son piezas")
    return pd.DataFrame(rows)

def score_audit(audit_df):
    critical_bad = audit_df[(audit_df["Riesgo"] == "CRITICO") & (audit_df["Estatus"].str.contains("❌", regex=False))]
    any_bad = audit_df[audit_df["Estatus"].str.contains("❌", regex=False)]
    warns = audit_df[audit_df["Estatus"].str.contains("⚠️", regex=False)]
    oks = audit_df[audit_df["Estatus"].str.contains("✔️", regex=False)]
    scored = audit_df[~audit_df["Estatus"].str.contains("No suficiente", regex=False)]
    pct = round(len(oks)/max(len(scored),1)*100,1)
    if not critical_bad.empty: result = "🔴 ALTO RIESGO – NO LIBERAR"
    elif not any_bad.empty or not warns.empty: result = "🟡 REVISAR – POSIBLE AJUSTE"
    else: result = "🟢 EXPEDIENTE LIBERABLE"
    return result, pct, len(critical_bad), len(warns), len(oks)

# ================= UI =================
with st.sidebar:
    st.header("Configuración")
    tolerance = st.number_input("Tolerancia importes", 0.00, 50.00, 0.02, 0.01)
    show_text = st.checkbox("Mostrar texto extraído", value=False)
    st.info("No valida fracción arancelaria ni incrementables. Sí valida cantidades vs partidas.")

ped_file = st.file_uploader("1) Carga el PEDIMENTO PDF", type=["pdf"])
support_files = st.file_uploader("2) Carga documentos soporte PDF", type=["pdf"], accept_multiple_files=True)
if not ped_file:
    st.info("Carga el PEDIMENTO para iniciar."); st.stop()
if not support_files:
    st.info("Carga factura, carta 318, packing list, BL/DO u otros soportes."); st.stop()

with st.spinner("Leyendo expediente..."):
    ped_text = read_pdf(ped_file)
    ped_detected = extract_fields(ped_text, ped_file.name)
    docs_detected = {}
    raw_texts = {ped_file.name: ped_text}
    merch_rows = []
    for f in support_files:
        txt = read_pdf(f)
        raw_texts[f.name] = txt
        data = extract_fields(txt, f.name)
        docs_detected[f.name] = data
        merch_rows.extend(extract_merchandise(txt, f.name, data.get("Tipo documento")))

st.subheader("1) Revisión de datos detectados")
st.caption("Corrige manualmente cualquier campo antes de ejecutar auditoría. Esto permite manejar proveedores y formatos nuevos.")
with st.expander("📄 Pedimento", expanded=True):
    ped_edit_df = st.data_editor(pd.DataFrame([ped_detected]), num_rows="fixed", use_container_width=True, key="ped_editor")
with st.expander("📎 Soportes", expanded=True):
    docs_edit_df = pd.DataFrame.from_dict(docs_detected, orient="index").reset_index().rename(columns={"index":"Archivo"})
    docs_edit_df = st.data_editor(docs_edit_df, num_rows="fixed", use_container_width=True, key="docs_editor")
merch_df = pd.DataFrame(merch_rows) if merch_rows else pd.DataFrame(columns=["Documento","Descripción","Cantidad","Precio unitario","Total"])
with st.expander("📦 Partidas detectadas / editables", expanded=False):
    merch_df = st.data_editor(merch_df, num_rows="dynamic", use_container_width=True, key="merch_editor")

ped_data = ped_edit_df.iloc[0].to_dict()
docs_data = {}
for _, row in docs_edit_df.iterrows():
    docs_data[row.get("Archivo")] = row.drop(labels=["Archivo"]).to_dict()

st.subheader("2) Auditoría")
if st.button("🛃 Ejecutar Auditoría Agencia", type="primary"):
    audit_df = audit_agency(ped_data, docs_data, tolerance)
    extra_rows = []
    if not merch_df.empty:
        merch_total = pd.to_numeric(merch_df["Total"], errors="coerce").sum()
        merch_qty = pd.to_numeric(merch_df["Cantidad"], errors="coerce").sum()
        ped_total = ped_data.get("Total factura") or 0
        ped_qty = ped_data.get("Cantidad total") or 0
        status_total = "✔️ Coincide" if abs(merch_total-float(ped_total or 0)) <= tolerance else "❌ Diferencia"
        extra_rows.append({"Riesgo":"CRITICO","Área":"Partidas","Campo":"Suma de partidas vs total factura","Estatus":status_total,"Observación":f"Suma partidas={fmt_num(merch_total)}; Pedimento total={fmt_num(ped_total)}","Documento probable a corregir":"Factura/Carta/Pedimento" if "❌" in status_total else "","Regla":"La suma de partidas debe coincidir contra total factura/pedimento"})
        status_qty = "✔️ Coincide" if abs(merch_qty-float(ped_qty or 0)) <= 0.01 else "⚠️ Revisar"
        extra_rows.append({"Riesgo":"MEDIO","Área":"Partidas","Campo":"Cantidad partidas vs pedimento","Estatus":status_qty,"Observación":f"Suma cantidad partidas={fmt_num(merch_qty)}; Pedimento cantidad={fmt_num(ped_qty)}","Documento probable a corregir":"Revisar UMC vs cantidad comercial" if "⚠️" in status_qty else "","Regla":"La cantidad de partidas debe ser razonable contra pedimento"})
    if extra_rows:
        audit_df = pd.concat([audit_df, pd.DataFrame(extra_rows)], ignore_index=True)
    result, pct, critical_bad, warns, oks = score_audit(audit_df)
    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("Resultado", result); c2.metric("Score", f"{pct}%"); c3.metric("Críticas", critical_bad); c4.metric("Advertencias", warns); c5.metric("OK", oks)
    tabs = st.tabs(["📋 Resumen ejecutivo","✅ Auditoría","📦 Partidas","📊 Datos detectados","📝 Texto"])
    with tabs[0]:
        st.write(f"### {result}"); st.write(f"**Score:** {pct}%")
        issues = audit_df[audit_df["Estatus"].str.contains("❌|⚠️", regex=True)]
        if issues.empty: st.success("Expediente liberable conforme a las validaciones configuradas.")
        else: st.warning("Se detectaron puntos para revisión."); st.dataframe(issues, use_container_width=True)
    with tabs[1]: st.dataframe(audit_df, use_container_width=True)
    with tabs[2]: st.dataframe(merch_df, use_container_width=True)
    with tabs[3]:
        col1,col2 = st.columns(2)
        with col1: st.write("**Pedimento**"); st.dataframe(pd.DataFrame([ped_data]), use_container_width=True)
        with col2: st.write("**Soportes**"); st.dataframe(pd.DataFrame.from_dict(docs_data, orient="index"), use_container_width=True)
    with tabs[4]:
        if show_text:
            selected = st.selectbox("Documento", list(raw_texts.keys()))
            st.text_area("Texto extraído", raw_texts[selected], height=520)
        else: st.info("Activa 'Mostrar texto extraído' en la barra lateral.")
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame({"Resultado":[result],"Score":[pct],"Críticas":[critical_bad],"Advertencias":[warns],"OK":[oks],"Fecha reporte":[datetime.now().strftime("%d/%m/%Y %H:%M")]}).to_excel(writer,index=False,sheet_name="Resumen")
        audit_df.to_excel(writer,index=False,sheet_name="Auditoria")
        pd.DataFrame([ped_data]).to_excel(writer,index=False,sheet_name="Pedimento")
        pd.DataFrame.from_dict(docs_data, orient="index").to_excel(writer,sheet_name="Soportes")
        merch_df.to_excel(writer,index=False,sheet_name="Partidas")
        pd.DataFrame({"Documento":list(raw_texts.keys()),"Texto extraido":list(raw_texts.values())}).to_excel(writer,index=False,sheet_name="Texto")
    st.download_button("⬇️ Descargar auditoría Excel", output.getvalue(), file_name=f"auditoria_agencia_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
else:
    st.info("Revisa/corrige los datos detectados y presiona **Ejecutar Auditoría Agencia**.")
