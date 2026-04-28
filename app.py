import re, io
from datetime import datetime
import pandas as pd
import streamlit as st
from pypdf import PdfReader

st.set_page_config(page_title='Auditoría Glosa Aduanal', layout='wide')
st.title('🛃 Auditoría Glosa Aduanal')
st.caption('Pedimento multi-proveedor vs facturas, packing list y BL/MBL/DO.')

def read_pdf(file):
    reader = PdfReader(file)
    text = ''
    for page in reader.pages:
        text += '\n' + (page.extract_text() or '')
    text = re.sub(r'---\s*PAGINA\s*\d+\s*---', ' ', text, flags=re.I)
    return re.sub(r'\s+', ' ', text)

def clean(x):
    return re.sub(r'\s+', ' ', str(x or '')).strip(' .,:;-')

def money(x):
    if x in [None, '']: return None
    s = re.sub(r'[^0-9.\-]', '', str(x).replace(',', ''))
    try: return float(s)
    except: return None

def fmt(x):
    if x in [None, '']: return ''
    try: return f'{float(x):,.2f}'
    except: return str(x)

def nkey(x):
    return re.sub(r'[^A-Z0-9]', '', str(x or '').upper())

def ndate(x):
    x = clean(x)
    m = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', x)
    if m: return f'{int(m.group(1)):02d}/{int(m.group(2)):02d}/{m.group(3)}'
    m = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', x)
    if m: return f'{int(m.group(3)):02d}/{int(m.group(2)):02d}/{m.group(1)}'
    return ''

def is_sn(v):
    v = str(v or '').upper().replace('Í','I').replace('Ú','U').replace('Ñ','N')
    c = re.sub(r'[\s\./-]+', '', v)
    return c in {'SN','NA','NOSN','NONA','NOAPLICA','SINNUMERO','SINNO','SINNRO','SINID','SINREGISTRO'}

def tax_norm(v):
    raw = str(v or '').upper().replace('Í','I').replace('Ú','U').replace('Ñ','N').strip()
    if is_sn(raw): return 'S/N'
    val = re.sub(r'[^A-Z0-9\-]', '', raw)
    if re.match(r'^NO(?=\d)', val): val = val[2:]
    val = re.sub(r'NO$', '', val)
    return val.strip()

def sn_from_start(v):
    text = clean(v)
    m = re.match(r'^(NO\s*)?(S\s*/\s*N|S\s*-\s*N|S\s+N|SN|N\s*/\s*A|N\s*-\s*A|N\s+A|NA)\b(.*)$', text, flags=re.I)
    if m: return 'S/N', clean(m.group(3))
    m = re.match(r'^(NOS\s*/\s*N|NOSN|NON\s*/\s*A|NONA)(.*)$', text, flags=re.I)
    if m: return 'S/N', clean(m.group(2))
    m = re.match(r'^(NO\s+APLICA|SIN\s+NUMERO|SIN\s+NÚMERO|SIN\s+NO|SIN\s+NRO|SIN\s+ID|SIN\s+REGISTRO)\b(.*)$', text, flags=re.I)
    if m: return 'S/N', clean(m.group(2))
    return '', text

def split_name_address(raw):
    raw = clean(raw)
    pats = [
        r'^(.+?\bS\.?A\.?\s*DE\s*C\.?V\.?)\b(.*)$', r'^(.+?\bSA\s*DE\s*CV\b)(.*)$',
        r'^(.+?\bTRADING\s+CO\.?,?\s*LTD\.?)\b(.*)$', r'^(.+?\bCO\.?,?\s*LTD\.?)\b(.*)$',
        r'^(.+?\bLIMITED\b)(.*)$', r'^(.+?\bCORPORATION\b)(.*)$', r'^(.+?\bCORP\.?)\b(.*)$',
        r'^(.+?\bINC\.?)\b(.*)$', r'^(.+?\bLLC\b)(.*)$', r'^(.+?\bL\.?L\.?C\.?)\b(.*)$']
    for p in pats:
        m = re.search(p, raw, flags=re.I)
        if m: return clean(m.group(1)), clean(m.group(2))
    breakers = [r'\bNO\.\s*EXT\b',r'\bNO\.\b',r'\bNO\b\s+\d',r'\bRM\b',r'\bROOM\b',r'\bBUILDING\b',r'\bBLDG\b',r'\bFLOOR\b',r'\bSTREET\b',r'\bAVENUE\b',r'\bROAD\b',r'\bNORTH ROAD\b',r'\bTUANYI\b',r'\bHUADU\b',r'\bGUANGZHOU\b',r'\bMIAMI\b',r'\bFLORIDA\b',r'\bC\.P\.\b',r'\bCP\b']
    pos=[]
    for p in breakers:
        m=re.search(p, raw, flags=re.I)
        if m: pos.append(m.start())
    if pos:
        c=min(pos); return clean(raw[:c]), clean(raw[c:])
    return raw, ''

def supplier_area(text):
    t = re.sub(r'\s+', ' ', text)
    m = re.search(r'DATOS DEL PROVEEDOR O COMPRADOR', t, flags=re.I)
    if not m: return ''
    area = t[m.end():]
    stop = re.search(r'(TRANSPORTE IDENTIFICACION|TRANSPORTISTA RFC|NO\.?\s*\(GUIA|AGENTE ADUANAL|PARTIDAS|CLAVE/COMPL)', area, flags=re.I)
    return clean(area[:stop.start()] if stop else area)

def split_records(area):
    pat = r'ID\.?\s*FISCAL\s+NOMBRE,\s*DENOMINACION\s*O\s*RAZON\s*SOCIAL\s+DOMICILIO:?'
    ms = list(re.finditer(pat, area, flags=re.I))
    rec=[]
    for i,m in enumerate(ms):
        end = ms[i+1].start() if i+1<len(ms) else len(area)
        s = clean(area[m.end():end])
        if s: rec.append(s)
    return rec

def invoice_part(record):
    out={'COVE':'','Factura':'','Fecha factura':'','Incoterm':'','Moneda':'','Valor factura':None}
    mc = re.search(r'\b(COVE[A-Z0-9]+)\b', record, flags=re.I)
    if mc: out['COVE']=mc.group(1).upper()
    inv = re.sub(r'NUM\.?\s*CFDI\s*O\s*DOCUMENTO\s*EQUIVALENTE\s+FECHA\s+INCOTERM\s+MONEDA\s+FACT\s+VAL\.?\s*MON\.?\s*FACT\s+FACTOR\s+MON\.?\s+VAL\.?\s*DOLARES',' ',record,flags=re.I)
    inv = clean(inv)
    m = re.search(r'(?:COVE[A-Z0-9]+\s+)?([A-Z0-9][A-Z0-9\-/]{2,})\s+(\d{1,2}/\d{1,2}/\d{4})\s+(FOB|CIF|CFR|EXW|FCA|DAP|DDP|CPT|CIP)\s+(USD|EUR|MXN|JPY|CNY)\s+([0-9,]+\.\d{2})', inv, flags=re.I)
    if m:
        if not m.group(1).upper().startswith('COVE'): out['Factura']=m.group(1).upper()
        out['Fecha factura']=ndate(m.group(2)); out['Incoterm']=m.group(3).upper(); out['Moneda']=m.group(4).upper(); out['Valor factura']=money(m.group(5))
    return out

def parse_record(record, idx):
    row={'Bloque':idx,'Proveedor':'','Tax ID':'','Dirección proveedor':'','COVE':'','Factura':'','Fecha factura':'','Incoterm':'','Moneda':'','Valor factura':None}
    parts = re.split(r'NUM\.?\s*CFDI\s*O\s*DOCUMENTO\s*EQUIVALENTE', record, maxsplit=1, flags=re.I)
    supp = clean(parts[0]); inv = 'NUM. CFDI O DOCUMENTO EQUIVALENTE '+parts[1] if len(parts)>1 else ''
    sp = re.split(r'\bVINCULACION\b', supp, maxsplit=1, flags=re.I)
    before = clean(sp[0]); after = clean(sp[1]) if len(sp)>1 else ''
    before = re.sub(r'^(S\s*/?\s*N|N\s*/?\s*A|SN|NA|NO\s+APLICA|SIN\s+NUMERO|SIN\s+NÚMERO)\s+','', before, flags=re.I).strip(' .,:;-')
    before = re.sub(r'^(?=[A-Z0-9\-]*\d)[A-Z0-9\-]{8,25}\s+', '', before).strip(' .,:;-')
    prov, addr_b = split_name_address(before)
    sn, after2 = sn_from_start(after)
    if sn:
        tax=sn; addr_a=after2
    else:
        ac = re.sub(r'^(NO|SI)\s+', '', after, flags=re.I).strip(' .,:;-')
        mt = re.match(r'^((?:NO)?(?=[A-Z0-9\-]*\d)[A-Z0-9\-]{6,25})\b(.*)$', ac, flags=re.I)
        if mt: tax=tax_norm(mt.group(1)); addr_a=clean(mt.group(2))
        else: tax=''; addr_a=ac
    addr_a = re.sub(r'^(NO|SI)\s+', '', addr_a, flags=re.I).strip(' .,:;-')
    addr_a = re.sub(r'\s+\b(NO|SI)\b$', '', addr_a, flags=re.I).strip(' .,:;-')
    row.update({'Proveedor':prov,'Tax ID':tax,'Dirección proveedor':clean(addr_a or addr_b)})
    row.update(invoice_part(inv))
    return row

def ped_suppliers(text):
    return pd.DataFrame([parse_record(r,i) for i,r in enumerate(split_records(supplier_area(text)),1)])

def classify(text, name):
    t=(text+' '+name).upper()
    if any(x in t for x in ['BILL OF LADING','B/L NO','BL NO','SEA WAYBILL','WAYBILL','DELIVERY ORDER']): return 'BL/MBL/DO'
    if 'PACKING LIST' in t or 'LISTA DE EMPAQUE' in t: return 'FACTURA/PACKING' if ('INVOICE' in t or 'FACTURA' in t) else 'PACKING'
    if 'FACTURA(S)' in t or 'CARTA TRADUCCION' in t or 'TAX ID' in t: return 'CARTA 318'
    if 'COMMERCIAL INVOICE' in t or 'INVOICE' in t or 'FACTURA' in t: return 'FACTURA'
    return 'SOPORTE'

def support_data(text, name):
    t=re.sub(r'\s+',' ',text)
    d={'Archivo':name,'Tipo':classify(text,name),'Factura':'','Fecha factura':'','Proveedor':'','Tax ID':'','Incoterm':'','Moneda':'','Valor factura':None,'BL':'','Bultos':None,'Peso bruto kg':None,'Contenedores':''}
    cands=[]
    for p in [r'(?:INVOICE\s*NO\.?|FACTURA\s*/?\s*INVOICE\s*NO\.?|FACTURA\s*NO\.?|NO\.?\s*FACTURA)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-/]{2,})', r'\b([A-Z0-9]+-[A-Z0-9\-/]+)\b']:
        for m in re.findall(p,t,flags=re.I):
            c=str(m).upper().strip()
            if not c.startswith(('COVE','HLCU','ZIMU','ONEY','MAEU','MEDU','CMDU')): cands.append(c)
    if cands: d['Factura']=sorted(set(cands), key=lambda x:('-' not in x,len(x)))[0]
    md=re.search(r'(?:DATE|FECHA|INVOICE DATE|FECHA/DATE)\s*[:#]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})',t,flags=re.I) or re.search(r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})\b',t)
    if md: d['Fecha factura']=ndate(md.group(1))
    mi=re.search(r'\b(FOB|CIF|CFR|EXW|FCA|DAP|DDP|CPT|CIP)\b',t,flags=re.I)
    if mi: d['Incoterm']=mi.group(1).upper()
    if re.search(r'\bUSD\b|US\$|\$',t,flags=re.I): d['Moneda']='USD'
    vals=[]
    for p in [r'(?:GRAND\s*TOTAL|TOTAL\s*AMOUNT|TOTAL|VALOR\s*DE\s*LA\s*MERCANCIA)\s*[:#]?\s*(?:USD|US\$|\$)?\s*([0-9,]+\.\d{2})', r'(?:USD|US\$|\$)\s*([0-9,]+\.\d{2})']:
        vals += [money(x) for x in re.findall(p,t,flags=re.I)]
    vals=[v for v in vals if v]
    if vals: d['Valor factura']=max(vals)
    mt=re.search(r'TAX\s*ID\.?\s*[:#]?\s*([A-Z0-9\-/]+)',t,flags=re.I)
    if mt: d['Tax ID']=tax_norm(mt.group(1))
    mp=re.search(r'([A-Z0-9 .,&\'\-()]+?(?:TRADING\s+CO\.?,?\s*LTD\.?|CO\.?,?\s*LTD\.?|LIMITED|INC\.?|CORP\.?|LLC))',t,flags=re.I)
    if mp: d['Proveedor']=re.sub(r'^PAGINA\s+\d+\s*','',clean(mp.group(1)),flags=re.I)
    for p in [r'(?:BILL\s*OF\s*LADING\s*NO\.?|B/L\s*NO\.?|BL\s*NO\.?|WAYBILL\s*NO\.?)\s*[:#]?\s*([A-Z0-9\-]{6,})', r'\b(ZIM[A-Z0-9]{6,}|ONEY[A-Z0-9]{6,}|HLCU[A-Z0-9]{6,}|MAEU[A-Z0-9]{6,}|MEDU[A-Z0-9]{6,})\b']:
        m=re.search(p,t,flags=re.I)
        if m: d['BL']=m.group(1).upper(); break
    mpkg=re.search(r'(\d+)\s+(?:PACKAGES|PACKAGE|PKGS|PKG|BULTOS|PALLETS|PALLET)',t,flags=re.I)
    if mpkg: d['Bultos']=int(mpkg.group(1))
    mw=re.search(r'(?:GROSS\s*WEIGHT|G\.?W\.?|PESO\s*BRUTO)\s*[:#]?\s*([0-9,]+(?:\.\d+)?)\s*(?:KGS?|KG)',t,flags=re.I)
    if mw: d['Peso bruto kg']=money(mw.group(1))
    else:
        ws=[money(x) for x in re.findall(r'([0-9,]+(?:\.\d+)?)\s*(?:KGS?|KG)',t,flags=re.I)]
        ws=[w for w in ws if w]
        if ws: d['Peso bruto kg']=max(ws)
    cont=sorted(set(re.findall(r'\b[A-Z]{4}\d{7}\b',t)))
    if cont: d['Contenedores']=', '.join(cont)
    return d

def build_audit(ped, sup):
    rows=[]
    def add(r,c,e,o,p='',s='',a=''):
        rows.append({'Riesgo':r,'Campo':c,'Estatus':e,'Pedimento':p,'Soporte':s,'Archivo soporte':a,'Observación':o})
    if ped.empty:
        add('CRITICO','Pedimento','❌ Error','No se detectaron proveedores/facturas.'); return pd.DataFrame(rows)
    by={}
    for _,s in sup.iterrows():
        k=nkey(s.get('Factura',''))
        if k: by.setdefault(k,[]).append(s)
    for _,p in ped.iterrows():
        f=str(p.get('Factura','') or ''); rel=by.get(nkey(f),[])
        if not f: add('CRITICO','Factura','❌ No localizada','No se detectó factura en proveedor.'); continue
        if not rel: add('CRITICO','Factura','❌ No encontrada en soportes',f'No se encontró soporte para factura {f}.',p=f); continue
        add('CRITICO','Factura','✔️ Coincide',f'Factura {f} localizada.',p=f,s=f,a=', '.join([r['Archivo'] for r in rel]))
        for s in rel:
            a=s.get('Archivo','')
            checks=[('Fecha factura',p.get('Fecha factura',''),s.get('Fecha factura','')),('Incoterm',p.get('Incoterm',''),s.get('Incoterm','')),('Moneda',p.get('Moneda',''),s.get('Moneda',''))]
            for campo,pv,sv in checks:
                if pv and sv: add('CRITICO',campo,'✔️ Coincide' if str(pv)==str(sv) else '❌ Diferencia','Comparación directa.',p=pv,s=sv,a=a)
                else: add('MEDIO',campo,'⚠️ No suficiente','Falta dato en pedimento o soporte.',p=pv,s=sv,a=a)
            pv=p.get('Valor factura',None); sv=s.get('Valor factura',None)
            if pv is not None and sv is not None: add('CRITICO','Valor factura','✔️ Coincide' if abs(float(pv)-float(sv))<=0.05 else '❌ Diferencia','Comparación de valor.',p=fmt(pv),s=fmt(sv),a=a)
            else: add('MEDIO','Valor factura','⚠️ No suficiente','Falta valor.',p=fmt(pv),s=fmt(sv),a=a)
    if not sup.empty:
        logist=sup[sup['Tipo'].isin(['BL/MBL/DO','PACKING','FACTURA/PACKING'])]
        if not logist.empty:
            bls=sorted(set([x for x in logist['BL'].dropna().astype(str) if x])); cont=sorted(set(sum([[v.strip() for v in str(x).split(',') if v.strip()] for x in logist['Contenedores'].dropna().astype(str)],[])))
            ws=[x for x in logist['Peso bruto kg'].dropna().tolist() if x]; pk=[x for x in logist['Bultos'].dropna().tolist() if x]
            add('CRITICO','BL','✔️ Detectado' if bls else '⚠️ No localizado',', '.join(bls) if bls else 'No se detectó BL.',s=', '.join(bls))
            add('CRITICO','Contenedores','✔️ Detectado' if cont else '⚠️ No localizado',', '.join(cont) if cont else 'No se detectaron contenedores.',s=', '.join(cont))
            add('MEDIO','Peso bruto kg','✔️ Detectado' if ws else '⚠️ No localizado',', '.join([fmt(w) for w in ws]) if ws else 'No se detectó peso.',s=', '.join([fmt(w) for w in ws]))
            add('MEDIO','Bultos','✔️ Detectado' if pk else '⚠️ No localizado',', '.join([str(int(p)) for p in pk]) if pk else 'No se detectaron bultos.',s=', '.join([str(int(p)) for p in pk]))
    return pd.DataFrame(rows)

def score(df):
    if df.empty: return 'SIN DATOS',0
    ok=df[df['Estatus'].str.contains('✔️',regex=False)]; badc=df[(df['Riesgo']=='CRITICO') & df['Estatus'].str.contains('❌',regex=False)]; warn=df[df['Estatus'].str.contains('⚠️',regex=False)]
    sc=round(len(ok)/max(len(df),1)*100,1)
    if len(badc): return '🔴 ALTO RIESGO',sc
    if len(warn): return '🟡 REVISAR',sc
    return '🟢 LIBERABLE',sc

ped_file=st.file_uploader('1) Sube PEDIMENTO PDF',type='pdf')
support_files=st.file_uploader('2) Sube SOPORTES PDF',type='pdf',accept_multiple_files=True)
if ped_file:
    ped_text=read_pdf(ped_file); ped_df=ped_suppliers(ped_text)
    st.subheader('1) Proveedores / facturas detectadas en pedimento')
    if ped_df.empty: st.warning('No se detectaron proveedores/facturas.')
    else: ped_df=st.data_editor(ped_df,use_container_width=True,num_rows='dynamic',key='ped')
    rows=[]; raw={ped_file.name:ped_text}
    if support_files:
        for f in support_files:
            txt=read_pdf(f); raw[f.name]=txt; rows.append(support_data(txt,f.name))
    sup_df=pd.DataFrame(rows)
    st.subheader('2) Datos detectados en soportes')
    if sup_df.empty: st.info('Sube soportes para comparar.')
    else: sup_df=st.data_editor(sup_df,use_container_width=True,num_rows='dynamic',key='sup')
    st.subheader('3) Auditoría')
    if st.button('Ejecutar auditoría',type='primary'):
        aud=build_audit(ped_df,sup_df); res,sc=score(aud)
        c1,c2=st.columns(2); c1.metric('Resultado',res); c2.metric('Coincidencia',f'{sc}%')
        st.dataframe(aud,use_container_width=True)
        out=io.BytesIO()
        with pd.ExcelWriter(out,engine='openpyxl') as w:
            pd.DataFrame({'Resultado':[res],'Score':[sc],'Fecha':[datetime.now().strftime('%d/%m/%Y %H:%M')]}).to_excel(w,index=False,sheet_name='Resumen')
            ped_df.to_excel(w,index=False,sheet_name='Pedimento'); sup_df.to_excel(w,index=False,sheet_name='Soportes'); aud.to_excel(w,index=False,sheet_name='Auditoria')
        st.download_button('Descargar auditoría Excel',out.getvalue(),file_name=f'auditoria_glosa_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx',mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    with st.expander('Ver texto extraído'):
        sel=st.selectbox('Documento',list(raw.keys())); st.text_area('Texto',raw[sel],height=350)
else:
    st.info('Sube primero el pedimento.')
