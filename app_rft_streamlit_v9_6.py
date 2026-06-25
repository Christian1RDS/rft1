
import io
import sqlite3
from datetime import date, datetime, time, timedelta
from calendar import monthrange

import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

try:
    from streamlit_local_storage import LocalStorage
except Exception:
    LocalStorage = None

st.set_page_config(page_title='RFT Automatico - V9.6', page_icon='R', layout='wide', initial_sidebar_state='expanded')

DB = 'rft_v61_local.db'
REQ = ['NR_WO', 'DT_HR_INSPECAO', 'C_DPU_QG_AMARELO', 'CD_POSTO_CN']
POSTOS = ['QG09', 'QG07']
POSTO_PADRAO = 'QG09'
LS_PREFIX = 'rft_v96_'
DEFAULT_META_RFT = 95.0
YEAR_CLOSE_DAY = 10

FALHA_CANDIDATES = [
    'FALHA', 'DEFEITO', 'DS_DEFEITO', 'NM_DEFEITO', 'TIPO_FALHA', 'DESCRICAO_DEFEITO',
    'DESCRIÇÃO_DEFEITO', 'DESC_DEFEITO', 'NOME_FALHA', 'DS_FALHA', 'NM_FALHA',
    'TIPO_DEFEITO', 'CAUSA', 'DESCRICAO', 'DESCRIÇÃO', 'OBS_DEFEITO'
]

CSS = """
<style>
:root { --bg:#0b1220; --line:rgba(148,163,184,.18); --txt:#e5e7eb; --muted:#94a3b8; --ok:#22c55e; --bad:#ef4444; --blue:#3b82f6; }
html, body, [data-testid="stAppViewContainer"], .stApp { background: radial-gradient(circle at top left, #13213d 0%, #0b1220 35%, #09101c 100%); color: var(--txt); }
[data-testid="stHeader"] { background: rgba(11,18,32,.76); border-bottom: 1px solid var(--line); }
[data-testid="stSidebar"] { background: linear-gradient(180deg,#0f172a 0%, #101827 100%); border-right: 1px solid var(--line); }
[data-testid="stSidebar"] * { color: var(--txt) !important; }
.block-container { padding-top: .8rem; padding-bottom: 2rem; }
h1,h2,h3,h4,h5,h6,p,label,div,span { color: var(--txt); }
.hero { background: linear-gradient(135deg, rgba(24,34,53,.97), rgba(16,24,40,.98)); border:1px solid var(--line); border-radius:22px; padding:1.15rem 1.25rem; box-shadow: 0 12px 36px rgba(0,0,0,.24); margin-bottom:1rem; }
.panel { background: linear-gradient(180deg, rgba(34,48,73,.96), rgba(21,31,47,.98)); border:1px solid var(--line); border-radius:18px; padding:1rem; box-shadow: 0 10px 30px rgba(0,0,0,.18); margin-bottom:1rem; }
.metric-box { border:1px solid var(--line); background: linear-gradient(180deg, rgba(36,50,74,.96), rgba(25,36,54,.98)); border-radius:18px; padding:1rem; min-height:155px; box-shadow: 0 10px 24px rgba(0,0,0,.18); }
.kv { display:flex; justify-content:space-between; gap:1rem; padding:.6rem .75rem; border-radius:14px; background: rgba(255,255,255,.03); border:1px solid rgba(148,163,184,.10); margin-bottom:.5rem; }
.pill { display:inline-flex; align-items:center; gap:.35rem; padding:.45rem .8rem; border-radius:999px; background:rgba(59,130,246,.12); border:1px solid rgba(59,130,246,.28); margin-right:.35rem; margin-bottom:.35rem; }
.muted { color: var(--muted); font-size:.83rem; }
.ok { color: var(--ok); }
.bad { color: var(--bad); }
.neutral { color: var(--txt); }
[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:18px; overflow:hidden; }
</style>
"""

# ---------- Persistência local ----------
def get_local_storage():
    if LocalStorage is None:
        return None
    try:
        return LocalStorage()
    except Exception:
        return None


def ls_get(key, default=None):
    ls = get_local_storage()
    if ls is None:
        return default
    try:
        val = ls.getItem(LS_PREFIX + key, key=f'get_{key}')
        return default if val in (None, '', 'null', 'None') else val
    except Exception:
        return default


def ls_set(key, value):
    ls = get_local_storage()
    if ls is None:
        return
    try:
        ls.setItem(LS_PREFIX + key, str(value), key=f'set_{key}')
    except Exception:
        pass

# ---------- Banco ----------
def get_conn():
    return sqlite3.connect(DB, check_same_thread=False)


def ensure_column(conn, table, column, sql_type):
    cols = [r[1] for r in conn.execute(f'PRAGMA table_info({table})').fetchall()]
    if column not in cols:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {sql_type}')
        conn.commit()


def init_db(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS upload_log (id INTEGER PRIMARY KEY AUTOINCREMENT, file_name TEXT NOT NULL, uploaded_at TEXT NOT NULL, total_rows INTEGER NOT NULL, status TEXT NOT NULL, message TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS raw_inspections (id INTEGER PRIMARY KEY AUTOINCREMENT, upload_id INTEGER NOT NULL, nr_wo TEXT, dt_hr_inspecao TEXT, c_dpu_qg_amarelo REAL, cd_posto_cn TEXT)')
    ensure_column(conn, 'raw_inspections', 'falha', 'TEXT')
    conn.commit()


def create_upload(conn, file_name, total_rows, status='RECEBIDO', message=''):
    cur = conn.execute('INSERT INTO upload_log (file_name, uploaded_at, total_rows, status, message) VALUES (?, ?, ?, ?, ?)', (file_name, datetime.now().isoformat(timespec='seconds'), int(total_rows), status, message))
    conn.commit()
    return int(cur.lastrowid)


def update_upload(conn, upload_id, status, message=''):
    conn.execute('UPDATE upload_log SET status=?, message=? WHERE id=?', (status, message, int(upload_id)))
    conn.commit()


def save_raw(conn, upload_id, df):
    rows=[]
    for _, row in df.iterrows():
        rows.append((int(upload_id), row['NR_WO'], row['DT_HR_INSPECAO'].isoformat(sep=' ', timespec='seconds'), float(row['C_DPU_QG_AMARELO']), row['CD_POSTO_CN'], row.get('FALHA_PARETO', '')))
    conn.executemany('INSERT INTO raw_inspections (upload_id, nr_wo, dt_hr_inspecao, c_dpu_qg_amarelo, cd_posto_cn, falha) VALUES (?, ?, ?, ?, ?, ?)', rows)
    conn.commit()


def uploads_table(conn):
    return pd.read_sql_query('SELECT id, file_name, uploaded_at, total_rows, status, message FROM upload_log ORDER BY id DESC LIMIT 300', conn)


def upload_info(conn, upload_id):
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT * FROM upload_log WHERE id=?', (int(upload_id),)).fetchone()
    conn.row_factory = None
    return row


def upload_detail_df(conn, upload_id):
    df = pd.read_sql_query('SELECT nr_wo AS NR_WO, dt_hr_inspecao AS DT_HR_INSPECAO, c_dpu_qg_amarelo AS C_DPU_QG_AMARELO, cd_posto_cn AS CD_POSTO_CN, COALESCE(falha, "") AS FALHA_PARETO FROM raw_inspections WHERE upload_id=? ORDER BY dt_hr_inspecao, nr_wo', conn, params=[int(upload_id)])
    if not df.empty:
        df['DT_HR_INSPECAO'] = pd.to_datetime(df['DT_HR_INSPECAO'], errors='coerce')
    return df


def delete_upload(conn, upload_id):
    conn.execute('DELETE FROM raw_inspections WHERE upload_id=?', (int(upload_id),))
    conn.execute('DELETE FROM upload_log WHERE id=?', (int(upload_id),))
    conn.commit()


def reprocess_upload(conn, upload_id):
    df = upload_detail_df(conn, upload_id)
    if df.empty:
        update_upload(conn, upload_id, 'ERRO', 'Upload sem linhas brutas para reprocessar.')
        return None
    info = upload_info(conn, upload_id)
    new_name = f"REPROCESSADO_{info['file_name']}" if info else f'REPROCESSADO_{upload_id}'
    new_id = create_upload(conn, new_name, len(df), message=f'Reprocessado a partir do upload {upload_id}.')
    save_raw(conn, new_id, df[['NR_WO', 'DT_HR_INSPECAO', 'C_DPU_QG_AMARELO', 'CD_POSTO_CN', 'FALHA_PARETO']])
    update_upload(conn, new_id, 'PROCESSADO', f'Upload {upload_id} reprocessado com sucesso.')
    return new_id


def available_years(conn, posto):
    df = pd.read_sql_query("SELECT DISTINCT CAST(strftime('%Y', dt_hr_inspecao) AS INT) AS ano FROM raw_inspections WHERE cd_posto_cn=? ORDER BY ano", conn, params=[posto])
    return [int(x) for x in df['ano'].dropna().tolist()] if not df.empty else []


def available_years_any(conn):
    df = pd.read_sql_query("SELECT DISTINCT CAST(strftime('%Y', dt_hr_inspecao) AS INT) AS ano FROM raw_inspections WHERE cd_posto_cn IN ('QG09','QG07') ORDER BY ano", conn)
    return [int(x) for x in df['ano'].dropna().tolist()] if not df.empty else []


def latest_upload_id_for_year(conn, posto, year):
    df = pd.read_sql_query("SELECT MAX(upload_id) AS upload_id FROM raw_inspections WHERE cd_posto_cn=? AND strftime('%Y', dt_hr_inspecao)=?", conn, params=[posto, str(year)])
    if df.empty or pd.isna(df.loc[0, 'upload_id']):
        return None
    return int(df.loc[0, 'upload_id'])


def existing_range_for_posto_year(conn, posto, year):
    df = pd.read_sql_query("SELECT MIN(date(dt_hr_inspecao)) AS min_d, MAX(date(dt_hr_inspecao)) AS max_d FROM raw_inspections WHERE cd_posto_cn=? AND strftime('%Y', dt_hr_inspecao)=?", conn, params=[posto, str(year)])
    if df.empty or pd.isna(df.loc[0, 'min_d']):
        return None, None
    return pd.to_datetime(df.loc[0, 'min_d']).date(), pd.to_datetime(df.loc[0, 'max_d']).date()


def delete_overlapped_period(conn, posto, year, start_date, end_date):
    conn.execute("DELETE FROM raw_inspections WHERE cd_posto_cn=? AND strftime('%Y', dt_hr_inspecao)=? AND datetime(dt_hr_inspecao) BETWEEN datetime(?) AND datetime(?)", (posto, str(year), datetime.combine(start_date, time(0,0,0)).isoformat(sep=' '), datetime.combine(end_date, time(23,59,59)).isoformat(sep=' ')))
    conn.commit()


def delete_year_for_posto(conn, posto, year):
    conn.execute("DELETE FROM raw_inspections WHERE cd_posto_cn=? AND strftime('%Y', dt_hr_inspecao)=?", (posto, str(year)))
    conn.commit()


def apply_import_mode(conn, df, mode):
    affected=[]
    if df is None or df.empty or mode == 'Somar ao historico':
        return affected
    for (year, posto), part in df.groupby([df['DT_HR_INSPECAO'].dt.year, 'CD_POSTO_CN']):
        if mode == 'Substituir periodo sobreposto':
            start_date = part['DT_HR_INSPECAO'].dt.date.min(); end_date = part['DT_HR_INSPECAO'].dt.date.max()
            delete_overlapped_period(conn, posto, int(year), start_date, end_date)
            affected.append(f'{posto}/{year}: substituido periodo {start_date.strftime("%d/%m/%Y")} a {end_date.strftime("%d/%m/%Y")}')
        elif mode == 'Reprocessar o ano inteiro':
            delete_year_for_posto(conn, posto, int(year))
            affected.append(f'{posto}/{year}: reprocessado ano inteiro')
    return affected

# ---------- leitura e preparo ----------
def normalize_columns(df):
    out = df.copy()
    out.columns = [str(x).strip().replace('\ufeff', '') for x in out.columns]
    return out


def read_file(uploaded_file):
    ext = uploaded_file.name.lower().split('.')[-1]
    content = uploaded_file.getvalue()
    if ext == 'csv':
        last_err = None
        for enc in ['utf-8-sig','utf-16','latin1']:
            for sep in [None,';',',','\t']:
                try:
                    if sep is None:
                        df = pd.read_csv(io.BytesIO(content), encoding=enc, sep=None, engine='python')
                    else:
                        df = pd.read_csv(io.BytesIO(content), encoding=enc, sep=sep)
                    return normalize_columns(df)
                except Exception as err:
                    last_err = err
        raise ValueError(f'Nao foi possivel ler o CSV. Detalhe: {last_err}')
    if ext in ['xlsx','xls']:
        engine = 'openpyxl' if ext == 'xlsx' else 'xlrd'
        return normalize_columns(pd.read_excel(io.BytesIO(content), engine=engine))
    raise ValueError('Formato nao suportado. Use .xlsx, .xls ou .csv')


def validate_df(df):
    missing=[c for c in REQ if c not in df.columns]
    return len(missing)==0, missing


def parse_dt(series):
    dt = pd.to_datetime(series, errors='coerce')
    mask = dt.isna() & series.notna()
    if mask.any():
        dt.loc[mask] = pd.to_datetime(series[mask], errors='coerce', dayfirst=True)
    return dt


def norm_posto(value):
    txt = str(value).upper().strip()
    if 'QG09' in txt: return 'QG09'
    if 'QG07' in txt: return 'QG07'
    return txt


def detect_falha_col(df):
    cols_norm = {str(c).strip().upper(): c for c in df.columns}
    for cand in FALHA_CANDIDATES:
        if cand.upper() in cols_norm:
            return cols_norm[cand.upper()]
    for c in df.columns:
        cu = str(c).strip().upper()
        if 'FALHA' in cu or 'DEFEITO' in cu:
            return c
    return None


def prepare(df, falha_col=None):
    work = df.copy()
    work['DT_HR_INSPECAO'] = parse_dt(work['DT_HR_INSPECAO'])
    work['C_DPU_QG_AMARELO'] = pd.to_numeric(work['C_DPU_QG_AMARELO'], errors='coerce').fillna(0)
    work['NR_WO'] = work['NR_WO'].astype(str).str.strip()
    work['CD_POSTO_CN'] = work['CD_POSTO_CN'].astype(str).map(norm_posto)
    if falha_col and falha_col in work.columns:
        work['FALHA_PARETO'] = work[falha_col].fillna('').astype(str).str.strip()
    else:
        detected = detect_falha_col(work)
        work['FALHA_PARETO'] = work[detected].fillna('').astype(str).str.strip() if detected else ''
    work = work[work['CD_POSTO_CN'].isin(POSTOS)].copy()
    return work[work['DT_HR_INSPECAO'].notna()].copy()


def upload_overlap_warning(conn, df):
    warnings=[]
    if df is None or df.empty: return warnings
    for (year, posto), part in df.groupby([df['DT_HR_INSPECAO'].dt.year, 'CD_POSTO_CN']):
        new_min = part['DT_HR_INSPECAO'].dt.date.min(); new_max = part['DT_HR_INSPECAO'].dt.date.max()
        old_min, old_max = existing_range_for_posto_year(conn, posto, int(year))
        if old_min is None: continue
        overlap_start = max(new_min, old_min); overlap_end = min(new_max, old_max)
        if overlap_start <= overlap_end:
            warnings.append({'texto': f'Este arquivo cobre datas ja existentes entre {overlap_start.strftime("%d/%m")} e {overlap_end.strftime("%d/%m")}.', 'posto': posto, 'ano': int(year)})
    return warnings


def preview_file_impact(conn, df):
    if df is None or df.empty: return pd.DataFrame(), []
    overlaps = upload_overlap_warning(conn, df)
    overlap_keys = {(x['posto'],x['ano']) for x in overlaps}
    rows=[]
    for (year, posto), part in df.groupby([df['DT_HR_INSPECAO'].dt.year, 'CD_POSTO_CN']):
        rows.append({'Posto': posto, 'Ano': int(year), 'Data minima do arquivo': part['DT_HR_INSPECAO'].dt.date.min().strftime('%d/%m/%Y'), 'Data maxima do arquivo': part['DT_HR_INSPECAO'].dt.date.max().strftime('%d/%m/%Y'), 'Linhas do arquivo': int(len(part)), 'Falhas preenchidas': int((part['FALHA_PARETO'].astype(str).str.strip() != '').sum()), 'Sobreposicao': 'Sim' if (posto, int(year)) in overlap_keys else 'Nao'})
    return pd.DataFrame(rows), overlaps


def load_merged_year_df(conn, posto, year):
    df = pd.read_sql_query("SELECT upload_id, nr_wo AS NR_WO, dt_hr_inspecao AS DT_HR_INSPECAO, c_dpu_qg_amarelo AS C_DPU_QG_AMARELO, cd_posto_cn AS CD_POSTO_CN, COALESCE(falha, '') AS FALHA_PARETO FROM raw_inspections WHERE cd_posto_cn=? AND strftime('%Y', dt_hr_inspecao)=? ORDER BY upload_id ASC, id ASC", conn, params=[posto, str(year)])
    if df.empty: return df
    df['DT_HR_INSPECAO'] = pd.to_datetime(df['DT_HR_INSPECAO'], errors='coerce')
    df['C_DPU_QG_AMARELO'] = pd.to_numeric(df['C_DPU_QG_AMARELO'], errors='coerce').fillna(0)
    df['CD_POSTO_CN'] = df['CD_POSTO_CN'].astype(str).map(norm_posto)
    df['NR_WO'] = df['NR_WO'].astype(str).str.strip()
    df['FALHA_PARETO'] = df['FALHA_PARETO'].fillna('').astype(str).str.strip()
    df = df[df['DT_HR_INSPECAO'].notna()].copy()
    return df.drop_duplicates(subset=['NR_WO','DT_HR_INSPECAO','CD_POSTO_CN'], keep='last').reset_index(drop=True)


def load_pareto_df(conn, posto, year):
    df = pd.read_sql_query("SELECT nr_wo AS NR_WO, dt_hr_inspecao AS DT_HR_INSPECAO, c_dpu_qg_amarelo AS C_DPU_QG_AMARELO, cd_posto_cn AS CD_POSTO_CN, COALESCE(falha, '') AS FALHA_PARETO FROM raw_inspections WHERE cd_posto_cn=? AND strftime('%Y', dt_hr_inspecao)=?", conn, params=[posto, str(year)])
    if df.empty: return df
    df['DT_HR_INSPECAO'] = pd.to_datetime(df['DT_HR_INSPECAO'], errors='coerce')
    df['FALHA_PARETO'] = df['FALHA_PARETO'].fillna('').astype(str).str.strip()
    df['CD_POSTO_CN'] = df['CD_POSTO_CN'].astype(str).map(norm_posto)
    return df[(df['CD_POSTO_CN'].isin(POSTOS)) & (df['FALHA_PARETO'] != '')].copy()

# ---------- cálculos ----------
def calc_rft(df, start_date, end_date):
    sdt = datetime.combine(start_date, time(0,0,0)); edt = datetime.combine(end_date, time(23,59,59))
    filt = df[(df['DT_HR_INSPECAO'] >= sdt) & (df['DT_HR_INSPECAO'] <= edt)].copy()
    if filt.empty:
        return {'rft_pct': None, 'total': 0, 'good': 0, 'bad': 0}
    grp = filt.groupby('NR_WO', as_index=False)['C_DPU_QG_AMARELO'].sum().rename(columns={'C_DPU_QG_AMARELO':'SOMA'})
    grp['RFT'] = (grp['SOMA'] == 0).astype(int)
    total=int(len(grp)); good=int(grp['RFT'].sum()); bad=int(total-good)
    pct=round((good/total)*100,2) if total else None
    return {'rft_pct': pct,'total': total,'good': good,'bad': bad}


def year_close_info(df, year):
    ydf = df[df['DT_HR_INSPECAO'].dt.year == year]
    if ydf.empty: return False, None, 'Sem dados'
    max_d = ydf['DT_HR_INSPECAO'].dt.date.max(); cutoff = date(year, 12, YEAR_CLOSE_DAY)
    if max_d >= cutoff: return True, max_d, 'Fechado em ' + max_d.strftime('%d/%m/%Y')
    return False, None, 'Ate ' + max_d.strftime('%d/%m/%Y')


def week_options(df, year):
    ydf = df[df['DT_HR_INSPECAO'].dt.year == year].copy()
    if ydf.empty: return []
    dates = sorted(ydf['DT_HR_INSPECAO'].dt.date.unique().tolist())
    mondays = sorted({d - timedelta(days=d.weekday()) for d in dates})
    return [(f'Semana {idx:02d} - {m.strftime("%d/%m/%Y")} a {(m+timedelta(days=6)).strftime("%d/%m/%Y")}', m, m+timedelta(days=6)) for idx,m in enumerate(mondays, start=1)]


def month_options(df, year):
    ydf = df[df['DT_HR_INSPECAO'].dt.year == year].copy()
    if ydf.empty: return []
    opts=[]
    for month in sorted(ydf['DT_HR_INSPECAO'].dt.month.unique().tolist()):
        start=date(year,int(month),1); end=date(year,int(month),monthrange(year,int(month))[1])
        opts.append((f'{start.strftime("%m/%Y")} - {start.strftime("%d/%m/%Y")} a {end.strftime("%d/%m/%Y")}', start, end))
    return opts


def resolve_period_selection(df, ano, mode):
    min_date=df['DT_HR_INSPECAO'].dt.date.min(); max_date=df['DT_HR_INSPECAO'].dt.date.max()
    selected_label=f'Ano {ano}'; selected_range=(date(ano,1,1), max_date)
    if mode=='Diario':
        saved_day=ls_get('dia','')
        try: default_day=datetime.fromisoformat(saved_day).date() if saved_day else max_date
        except Exception: default_day=max_date
        if default_day<min_date or default_day>max_date: default_day=max_date
        selected=st.sidebar.date_input('Dia', value=default_day, min_value=min_date, max_value=max_date, format='DD/MM/YYYY', key='day_v96')
        ls_set('dia', selected.isoformat())
        selected_label=selected.strftime('%d/%m/%Y'); selected_range=(selected,selected)
    elif mode=='Semanal':
        opts=week_options(df, ano); labels=[x[0] for x in opts]
        if not labels: return min_date,max_date,selected_label,selected_range,False
        saved=ls_get('semana_label',''); idx=labels.index(saved) if saved in labels else len(labels)-1
        label=st.sidebar.selectbox('Semana do ano', labels, index=idx, key='week_v96')
        ls_set('semana_label', label)
        found=next(x for x in opts if x[0]==label)
        selected_label=label; selected_range=(found[1], found[2])
    elif mode=='Mensal':
        opts=month_options(df, ano); labels=[x[0] for x in opts]
        if not labels: return min_date,max_date,selected_label,selected_range,False
        saved=ls_get('mes_label',''); idx=labels.index(saved) if saved in labels else len(labels)-1
        label=st.sidebar.selectbox('Mes do ano', labels, index=idx, key='month_v96')
        ls_set('mes_label', label)
        found=next(x for x in opts if x[0]==label)
        selected_label=label; selected_range=(found[1], found[2])
    return min_date,max_date,selected_label,selected_range,True


def compute_selected_metrics(df, ano, mode, selected_range, closed_year, year_end, max_date):
    daily = weekly = monthly = yearly = ytd = None
    start,end = selected_range
    if mode=='Diario':
        selected=start
        daily=calc_rft(df, selected, selected)
        ws=selected-timedelta(days=selected.weekday()); we=ws+timedelta(days=6)
        weekly=calc_rft(df, ws, we)
        ms=date(ano, selected.month,1); me=date(ano, selected.month,monthrange(ano, selected.month)[1])
        monthly=calc_rft(df, ms, me)
        yearly=calc_rft(df, date(ano,1,1), year_end) if closed_year and year_end is not None else None
        ytd=calc_rft(df, date(ano,1,1), selected)
    elif mode=='Semanal':
        ws,we=start,end
        weekly=calc_rft(df, ws, we); yearly=calc_rft(df, date(ano,1,1), year_end) if closed_year and year_end is not None else None; ytd=calc_rft(df, date(ano,1,1), min(we, max_date))
    elif mode=='Mensal':
        ms,me=start,end
        monthly=calc_rft(df, ms, me); yearly=calc_rft(df, date(ano,1,1), year_end) if closed_year and year_end is not None else None; ytd=calc_rft(df, date(ano,1,1), min(me, max_date))
    else:
        yearly=calc_rft(df, date(ano,1,1), year_end) if closed_year and year_end is not None else None; ytd=calc_rft(df, date(ano,1,1), max_date)
    return {'daily':daily,'weekly':weekly,'monthly':monthly,'yearly':yearly,'ytd':ytd}


def monthly_trend(df, year, meta):
    ydf=df[df['DT_HR_INSPECAO'].dt.year == year].copy()
    if ydf.empty: return pd.DataFrame(columns=['Mes','RFT','Meta'])
    rows=[]
    for month in sorted(ydf['DT_HR_INSPECAO'].dt.month.unique().tolist()):
        start=date(year,int(month),1); end=date(year,int(month),monthrange(year,int(month))[1])
        res=calc_rft(ydf,start,end)
        rows.append({'Mes': start.strftime('%m/%Y'), 'RFT': res['rft_pct'] or 0, 'Meta': meta})
    return pd.DataFrame(rows)


def weekly_trend(df, year):
    ydf=df[df['DT_HR_INSPECAO'].dt.year == year].copy()
    if ydf.empty: return pd.DataFrame(columns=['Semana','RFT'])
    rows=[]
    for label,ws,we in week_options(ydf, year):
        res=calc_rft(ydf, ws, we)
        rows.append({'Semana': label.split('-')[0].strip(), 'RFT': res['rft_pct'] or 0})
    return pd.DataFrame(rows)


def day_history_df(df):
    if df.empty: return pd.DataFrame(columns=['Dia','RFT'])
    rows=[]
    for d in sorted(df['DT_HR_INSPECAO'].dt.date.unique().tolist()):
        res=calc_rft(df, d, d)
        rows.append({'Dia': d.strftime('%d/%m/%Y'), 'RFT': res['rft_pct'] or 0})
    return pd.DataFrame(rows)


def pareto_table(df):
    if df.empty:
        return pd.DataFrame(columns=['Rank','Falha','Quantidade','%','% Acumulado'])
    counts = df['FALHA_PARETO'].value_counts().head(10).reset_index()
    counts.columns = ['Falha', 'Quantidade']
    total = counts['Quantidade'].sum()
    counts['%'] = (counts['Quantidade'] / total * 100).round(2) if total else 0
    counts['% Acumulado'] = counts['%'].cumsum().round(2)
    counts.insert(0, 'Rank', range(1, len(counts)+1))
    return counts

# ---------- UI ----------
def format_pct(v):
    return 'Sem dados' if v is None or pd.isna(v) else f'{v:.2f}'.replace('.', ',') + '%'

def status_css(value, meta):
    if value is None or pd.isna(value): return 'neutral'
    return 'ok' if value >= meta else 'bad'

def metric_card_html(title, result, subtitle, meta):
    if result is None or result['rft_pct'] is None:
        value='Sem dados'; css='neutral'; aux=subtitle
    else:
        value=format_pct(result['rft_pct']); css=status_css(result['rft_pct'], meta); aux=f"{subtitle}<br>WOs boas: {result['good']} | ruins: {result['bad']} | total: {result['total']}"
    return f'<div class="metric-box"><div class="muted">{title}</div><div style="font-size:2rem;font-weight:900;margin:.35rem 0;" class="{css}">{value}</div><div class="muted">{aux}</div></div>'

def render_meta_resultado(metrics, meta):
    current=metrics['ytd'] if metrics['ytd'] is not None else metrics['monthly']
    current_pct=None if current is None else current['rft_pct']
    diff='Sem dados' if current_pct is None else f"{(current_pct - meta):+.2f}".replace('.', ',') + ' p.p.'
    css=status_css(current_pct, meta); val='Sem dados' if current_pct is None else f"{current_pct:.2f}".replace('.', ',') + '%'
    html = '<div class="panel">' + '<div style="font-size:1.08rem;font-weight:800;">Meta x resultado</div>' + '<div class="muted">Regra visual aplicada conforme sua configuracao.</div>' + f'<div style="font-size:2.15rem;font-weight:900;margin:.5rem 0;" class="{css}">{val}</div>' + f'<div class="muted">Meta: <b>{str(meta).replace(".", ",")}%</b><br>Diferenca: <b>{diff}</b><br>Regra: abaixo da meta = vermelho | acima ou igual a meta = verde</div>' + '</div>'
    st.markdown(html, unsafe_allow_html=True)

def render_resumo(info, posto, ano, min_date, max_date, selected_label, meta):
    file_name=info['file_name'] if info else '-'; uploaded_at=info['uploaded_at'] if info else '-'
    st.markdown('<div class="panel"><div style="font-size:1.08rem;font-weight:800;">Resumo executivo do recorte</div>', unsafe_allow_html=True)
    rows=[('Recorte',selected_label), ('Ultimo arquivo salvo',file_name), ('Ultimo upload',uploaded_at), ('Posto',posto), ('Ano',str(ano)), ('Janela consolidada',f'{min_date.strftime("%d/%m/%Y")} ate {max_date.strftime("%d/%m/%Y")}'), ('Meta ativa',str(meta).replace('.', ',') + '%')]
    for label,value in rows:
        st.markdown(f'<div class="kv"><div class="muted">{label}</div><div><strong>{value}</strong></div></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

def render_pareto_chart(pt, posto, ano):
    if pt.empty:
        st.info('Não há falhas preenchidas para montar o Pareto desse posto/ano.')
        return
    fig, ax1 = plt.subplots(figsize=(11, 5))
    labels = pt['Falha'].astype(str).tolist()
    x = range(len(labels))
    ax1.bar(x, pt['Quantidade'], color='#3b82f6')
    ax1.set_ylabel('Quantidade')
    ax1.set_title(f'Pareto de Falhas - Top 10 | {posto} | {ano}')
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(labels, rotation=45, ha='right')
    ax2 = ax1.twinx()
    ax2.plot(x, pt['% Acumulado'], color='#f59e0b', marker='o')
    ax2.set_ylabel('% Acumulado')
    ax2.set_ylim(0, 110)
    ax2.axhline(80, color='#ef4444', linestyle='--', linewidth=1)
    fig.tight_layout()
    st.pyplot(fig)

# ---------- main ----------
def main():
    conn = get_conn(); init_db(conn)
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown('<div class="hero"><div style="font-size:1.75rem;font-weight:900;">RFT Automatico - V9.6</div><div class="muted">Nova aba Pareto de Falhas com Top 10 por posto, mantendo calendário, YTD e design corporativo.</div></div>', unsafe_allow_html=True)

    with st.sidebar:
        default_posto=ls_get('posto', POSTO_PADRAO)
        posto_idx=POSTOS.index(default_posto) if default_posto in POSTOS else 0
        posto=st.radio('Posto', POSTOS, index=posto_idx, horizontal=True)
        ls_set('posto', posto)
        anos=available_years(conn, posto)
        if anos:
            prev_year=ls_get('ano', None)
            try: prev_year=int(prev_year) if prev_year is not None else None
            except Exception: prev_year=None
            ano_idx=anos.index(prev_year) if prev_year in anos else len(anos)-1
            ano=st.selectbox('Ano', anos, index=ano_idx)
            ls_set('ano', ano)
        else:
            ano=None
            st.info('Sem dados salvos para este posto.')
        modes=['Diario','Semanal','Mensal','Anual']
        default_mode=ls_get('modo','Diario')
        mode_idx=modes.index(default_mode) if default_mode in modes else 0
        mode=st.radio('Modo', modes, index=mode_idx)
        ls_set('modo', mode)
        saved_meta=ls_get('meta_rft', DEFAULT_META_RFT)
        try: saved_meta=float(str(saved_meta).replace(',', '.'))
        except Exception: saved_meta=DEFAULT_META_RFT
        meta=st.number_input('Meta RFT (%)', min_value=0.0, max_value=100.0, value=float(saved_meta), step=0.1)
        st.session_state['meta_rft']=float(meta)
        ls_set('meta_rft', meta)
        st.caption('Regra visual: abaixo da meta = vermelho | acima ou igual a meta = verde')

    tabs=st.tabs(['Dashboard','Tendencia','Pareto de Falhas','Base & Upload','Historico','Sobre'])
    latest_upload_id=latest_upload_id_for_year(conn, posto, ano) if ano is not None else None
    info=upload_info(conn, latest_upload_id) if latest_upload_id is not None else None
    df=load_merged_year_df(conn, posto, ano) if latest_upload_id is not None else pd.DataFrame()

    with tabs[0]:
        if ano is None or df.empty:
            st.info('Sem histórico para esse ano/posto.')
        else:
            closed_year, year_end, status_label = year_close_info(df, ano)
            min_date,max_date,selected_label,selected_range,valid = resolve_period_selection(df, ano, mode)
            if not valid:
                st.info('Nenhum período disponível para o modo selecionado.')
            else:
                metrics=compute_selected_metrics(df, ano, mode, selected_range, closed_year, year_end, max_date)
                st.markdown(f'<div class="pill">Posto: <strong>{posto}</strong></div><div class="pill">Ano: <strong>{ano}</strong></div><div class="pill">Fechamento: <strong>{status_label}</strong></div><div class="pill">Meta: <strong>{str(meta).replace(".", ",")}%</strong></div>', unsafe_allow_html=True)
                cols=st.columns(5)
                items=[('RFT Diario','Dia selecionado','daily'), ('RFT Semanal','Consolidacao semanal','weekly'), ('RFT Mensal','Consolidacao mensal','monthly'), ('RFT Anual','Ano até o último dia trabalhado de dezembro','yearly'), ('RFT YTD','Acumulado até o recorte','ytd')]
                for col,(title,subtitle,key) in zip(cols,items):
                    with col:
                        st.markdown(metric_card_html(title, metrics[key], subtitle, meta), unsafe_allow_html=True)
                left,right=st.columns([1.15,1.0])
                with left: render_resumo(info, posto, ano, min_date, max_date, selected_label, meta)
                with right: render_meta_resultado(metrics, meta)
                hist_day=day_history_df(df)
                st.markdown('<div class="panel"><div style="font-size:1.08rem;font-weight:800;">Leitura diaria do RFT</div><div class="muted">Historico dia a dia dentro da base consolidada.</div>', unsafe_allow_html=True)
                if hist_day.empty: st.info('Sem dados diários disponíveis.')
                else: st.line_chart(hist_day.set_index('Dia'), use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)

    with tabs[1]:
        if ano is None or df.empty:
            st.info('Sem histórico válido para a tendência.')
        else:
            monthly_df=monthly_trend(df, ano, meta); weekly_df=weekly_trend(df, ano)
            c1,c2=st.columns(2)
            with c1:
                st.markdown('<div class="panel"><div style="font-size:1.08rem;font-weight:800;">Tendencia mensal</div><div class="muted">Consolidacao por mes em barras/colunas, com meta no mesmo grafico.</div>', unsafe_allow_html=True)
                if monthly_df.empty: st.info('Sem dados mensais disponíveis.')
                else:
                    st.bar_chart(monthly_df.set_index('Mes')[['RFT','Meta']], use_container_width=True)
                    monthly_show=monthly_df.copy(); monthly_show['RFT']=monthly_show['RFT'].map(lambda x: f'{x:.2f}'.replace('.', ',') + '%'); monthly_show['Meta']=monthly_show['Meta'].map(lambda x: f'{x:.2f}'.replace('.', ',') + '%')
                    st.dataframe(monthly_show, use_container_width=True, hide_index=True)
                st.markdown('</div>', unsafe_allow_html=True)
            with c2:
                st.markdown('<div class="panel"><div style="font-size:1.08rem;font-weight:800;">Tendencia semanal</div><div class="muted">Leitura do desempenho por semana do ano em barras/colunas.</div>', unsafe_allow_html=True)
                if weekly_df.empty: st.info('Sem dados semanais disponíveis.')
                else:
                    st.bar_chart(weekly_df.set_index('Semana'), use_container_width=True)
                    weekly_show=weekly_df.copy(); weekly_show['RFT']=weekly_show['RFT'].map(lambda x: f'{x:.2f}'.replace('.', ',') + '%')
                    st.dataframe(weekly_show, use_container_width=True, hide_index=True)
                st.markdown('</div>', unsafe_allow_html=True)

    with tabs[2]:
        st.markdown('<div class="panel"><div style="font-size:1.08rem;font-weight:800;">Pareto de Falhas</div><div class="muted">Top 10 falhas, separado por QG09 e QG07. Demais postos são ignorados.</div>', unsafe_allow_html=True)
        anos_pareto = available_years_any(conn)
        if not anos_pareto:
            st.info('Sem dados para Pareto. Faça upload de uma base com coluna de falha/defeito.')
        else:
            default_year = ano if ano in anos_pareto else anos_pareto[-1]
            p_ano = st.selectbox('Ano do Pareto', anos_pareto, index=anos_pareto.index(default_year), key='pareto_year_v96')
            p_posto = st.radio('Posto do Pareto', POSTOS, index=0, horizontal=True, key='pareto_posto_v96')
            p_df = load_pareto_df(conn, p_posto, p_ano)
            pt = pareto_table(p_df)
            render_pareto_chart(pt, p_posto, p_ano)
            if not pt.empty:
                show = pt.copy()
                show['%'] = show['%'].map(lambda x: f'{x:.2f}'.replace('.', ',') + '%')
                show['% Acumulado'] = show['% Acumulado'].map(lambda x: f'{x:.2f}'.replace('.', ',') + '%')
                st.dataframe(show, use_container_width=True, hide_index=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with tabs[3]:
        st.markdown('<div class="panel"><div style="font-size:1.08rem;font-weight:800;">Base & Upload</div><div class="muted">Atualização da base com tratamento de sobreposição por posto/ano e histórico preservado.</div>', unsafe_allow_html=True)
        import_mode=st.radio('Modo de importação', ['Somar ao historico','Substituir periodo sobreposto','Reprocessar o ano inteiro'], key='import_mode_v96')
        uploaded=st.file_uploader('Base operacional atual (.xlsx, .xls ou .csv)', type=['xlsx','xls','csv'], key='file_uploader_v96')
        prepared=None
        if uploaded is not None:
            try:
                raw=read_file(uploaded)
                ok,miss=validate_df(raw)
                if not ok:
                    st.error('Base operacional invalida: ' + ', '.join(miss))
                else:
                    detected = detect_falha_col(raw)
                    falha_options = ['Detectar automaticamente / sem coluna'] + [c for c in raw.columns if c not in REQ]
                    default_idx = falha_options.index(detected) if detected in falha_options else 0
                    selected_falha = st.selectbox('Coluna para Pareto de Falhas', falha_options, index=default_idx, key='falha_col_v96')
                    falha_col = None if selected_falha == 'Detectar automaticamente / sem coluna' else selected_falha
                    prepared=prepare(raw, falha_col=falha_col)
                    impact,overlaps=preview_file_impact(conn, prepared)
                    st.success(f'Arquivo carregado: {uploaded.name} | Linhas válidas QG09/QG07: {len(prepared)}')
                    if detected or falha_col:
                        st.info(f'Coluna de falha usada no Pareto: {falha_col or detected}')
                    else:
                        st.warning('Nenhuma coluna de falha detectada. O RFT será salvo normalmente, mas o Pareto ficará vazio para esse upload.')
                    if not impact.empty: st.dataframe(impact, use_container_width=True, hide_index=True)
                    for item in overlaps: st.warning(item['texto'])
            except Exception as err:
                st.error(f'Erro ao ler a base operacional: {err}')
        if st.button('Salvar arquivo localmente', type='primary', use_container_width=True, key='save_upload_v96'):
            if uploaded is None:
                st.error('Selecione um arquivo antes de salvar.')
            elif prepared is None:
                st.error('O arquivo foi anexado, mas houve erro na leitura. Corrija e tente novamente.')
            elif prepared.empty:
                st.error('A base foi lida, mas não restaram linhas válidas após o tratamento.')
            else:
                affected=apply_import_mode(conn, prepared, import_mode)
                uid=create_upload(conn, uploaded.name, len(prepared), message='Base recebida e salva localmente.')
                save_raw(conn, uid, prepared)
                msg='Arquivo salvo com sucesso.' + (' ' + ' | '.join(affected) if affected else '')
                update_upload(conn, uid, 'PROCESSADO', msg)
                st.success(msg)
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    with tabs[4]:
        st.markdown('<div class="panel"><div style="font-size:1.08rem;font-weight:800;">Historico</div><div class="muted">Auditoria dos uploads, com opção de detalhar, reprocessar e excluir.</div>', unsafe_allow_html=True)
        hist=uploads_table(conn)
        if hist.empty:
            st.info('Os uploads processados aparecerão aqui.')
        else:
            st.dataframe(hist, use_container_width=True, hide_index=True)
            selected_id=st.selectbox('Selecionar upload', hist['id'].tolist(), format_func=lambda x: f'Upload {x}', key='history_select_v96')
            c1,c2,c3=st.columns(3)
            with c1:
                if st.button('Ver detalhes do upload', use_container_width=True, key='history_view_v96'):
                    detail=upload_detail_df(conn, selected_id)
                    if detail.empty: st.warning('Upload sem detalhes disponíveis.')
                    else:
                        sel=upload_info(conn, selected_id)
                        st.info(f"Arquivo: {sel['file_name'] if sel else '-'} | Upload: {sel['uploaded_at'] if sel else '-'} | Linhas: {len(detail)}")
                        detail_show=detail.copy(); detail_show['DT_HR_INSPECAO']=detail_show['DT_HR_INSPECAO'].dt.strftime('%d/%m/%Y %H:%M:%S')
                        st.dataframe(detail_show.head(200), use_container_width=True, hide_index=True)
            with c2:
                if st.button('Reprocessar upload', use_container_width=True, key='history_reprocess_v96'):
                    new_id=reprocess_upload(conn, selected_id)
                    st.success(f'Upload reprocessado com sucesso. Novo upload: {new_id}.' if new_id else 'Não foi possível reprocessar o upload.')
                    st.rerun()
            with c3:
                if st.button('Excluir upload específico', use_container_width=True, key='history_delete_v96'):
                    delete_upload(conn, selected_id)
                    st.success('Upload excluído com sucesso.')
                    st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    with tabs[5]:
        st.markdown('<div class="panel"><div style="font-size:1.08rem;font-weight:800;">Sobre</div><div class="muted">Versão V9.6 com nova aba Pareto de Falhas. O sistema usa os dados do Excel/CSV no upload, detecta ou permite selecionar a coluna de falha, salva essa informação no histórico e monta o Top 10 por QG09 ou QG07. Outros postos são ignorados.</div></div>', unsafe_allow_html=True)

if __name__ == '__main__':
    main()
