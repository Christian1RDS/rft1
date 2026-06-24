
import io
import sqlite3
from datetime import date, datetime, time, timedelta
from calendar import monthrange

import pandas as pd
import streamlit as st

try:
    from streamlit_local_storage import LocalStorage
except Exception:
    LocalStorage = None

st.set_page_config(page_title='RFT Automatico - V9.0', page_icon='R', layout='wide', initial_sidebar_state='expanded')

DB = 'rft_v61_local.db'
REQ = ['NR_WO', 'DT_HR_INSPECAO', 'C_DPU_QG_AMARELO', 'CD_POSTO_CN']
POSTOS = ['QG09', 'QG07']
POSTO_PADRAO = 'QG09'
LS_PREFIX = 'rft_v90_'
DEFAULT_META_RFT = 95.0
CUTOFF_MONTH = 12
CUTOFF_DAY = 12


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


def current_meta():
    return float(st.session_state.get('meta_rft', DEFAULT_META_RFT))


def get_conn():
    return sqlite3.connect(DB, check_same_thread=False)


def init_db(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS upload_log (id INTEGER PRIMARY KEY AUTOINCREMENT, file_name TEXT NOT NULL, uploaded_at TEXT NOT NULL, total_rows INTEGER NOT NULL, status TEXT NOT NULL, message TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS raw_inspections (id INTEGER PRIMARY KEY AUTOINCREMENT, upload_id INTEGER NOT NULL, nr_wo TEXT, dt_hr_inspecao TEXT, c_dpu_qg_amarelo REAL, cd_posto_cn TEXT)')
    conn.commit()


def create_upload(conn, file_name, total_rows, status='RECEBIDO', message=''):
    cur = conn.execute('INSERT INTO upload_log (file_name, uploaded_at, total_rows, status, message) VALUES (?, ?, ?, ?, ?)', (file_name, datetime.now().isoformat(timespec='seconds'), int(total_rows), status, message))
    conn.commit()
    return int(cur.lastrowid)


def update_upload(conn, upload_id, status, message=''):
    conn.execute('UPDATE upload_log SET status=?, message=? WHERE id=?', (status, message, int(upload_id)))
    conn.commit()


def save_raw(conn, upload_id, df):
    rows = []
    for _, row in df.iterrows():
        rows.append((int(upload_id), row['NR_WO'], row['DT_HR_INSPECAO'].isoformat(sep=' ', timespec='seconds'), float(row['C_DPU_QG_AMARELO']), row['CD_POSTO_CN']))
    conn.executemany('INSERT INTO raw_inspections (upload_id, nr_wo, dt_hr_inspecao, c_dpu_qg_amarelo, cd_posto_cn) VALUES (?, ?, ?, ?, ?)', rows)
    conn.commit()


def uploads_table(conn):
    return pd.read_sql_query('SELECT id, file_name, uploaded_at, total_rows, status, message FROM upload_log ORDER BY id DESC LIMIT 300', conn)


def latest_upload_id_for_year(conn, posto, year):
    df = pd.read_sql_query("SELECT MAX(upload_id) AS upload_id FROM raw_inspections WHERE cd_posto_cn=? AND strftime('%Y', dt_hr_inspecao)=?", conn, params=[posto, str(year)])
    if df.empty or pd.isna(df.loc[0, 'upload_id']):
        return None
    return int(df.loc[0, 'upload_id'])


def upload_info(conn, upload_id):
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT * FROM upload_log WHERE id=?', (int(upload_id),)).fetchone()
    conn.row_factory = None
    return row


def available_years(conn, posto):
    df = pd.read_sql_query("SELECT DISTINCT CAST(strftime('%Y', dt_hr_inspecao) AS INT) AS ano FROM raw_inspections WHERE cd_posto_cn=? ORDER BY ano", conn, params=[posto])
    return [int(x) for x in df['ano'].dropna().tolist()] if not df.empty else []


def upload_detail_df(conn, upload_id):
    df = pd.read_sql_query('SELECT nr_wo AS NR_WO, dt_hr_inspecao AS DT_HR_INSPECAO, c_dpu_qg_amarelo AS C_DPU_QG_AMARELO, cd_posto_cn AS CD_POSTO_CN FROM raw_inspections WHERE upload_id=? ORDER BY dt_hr_inspecao, nr_wo', conn, params=[int(upload_id)])
    if not df.empty:
        df['DT_HR_INSPECAO'] = pd.to_datetime(df['DT_HR_INSPECAO'], errors='coerce')
    return df


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


def reprocess_upload(conn, upload_id):
    df = upload_detail_df(conn, upload_id)
    if df.empty:
        update_upload(conn, upload_id, 'ERRO', 'Upload sem linhas brutas para reprocessar.')
        return None
    info = upload_info(conn, upload_id)
    new_name = f"REPROCESSADO_{info['file_name']}" if info else f'REPROCESSADO_{upload_id}'
    new_id = create_upload(conn, new_name, len(df), message=f'Reprocessado a partir do upload {upload_id}.')
    save_raw(conn, new_id, df[['NR_WO','DT_HR_INSPECAO','C_DPU_QG_AMARELO','CD_POSTO_CN']])
    update_upload(conn, new_id, 'PROCESSADO', f'Upload {upload_id} reprocessado com sucesso.')
    return new_id


def delete_upload(conn, upload_id):
    conn.execute('DELETE FROM raw_inspections WHERE upload_id=?', (int(upload_id),))
    conn.execute('DELETE FROM upload_log WHERE id=?', (int(upload_id),))
    conn.commit()


def normalize_columns(df):
    out = df.copy()
    out.columns = [str(x).strip().replace('\ufeff', '') for x in out.columns]
    return out


def read_file(uploaded_file):
    ext = uploaded_file.name.lower().split('.')[-1]
    content = uploaded_file.getvalue()
    if ext == 'csv':
        last_err = None
        for enc in ['utf-8-sig', 'utf-16', 'latin1']:
            for sep in [None, ';', ',', '\t']:
                try:
                    if sep is None:
                        df = pd.read_csv(io.BytesIO(content), encoding=enc, sep=None, engine='python')
                    else:
                        df = pd.read_csv(io.BytesIO(content), encoding=enc, sep=sep)
                    return normalize_columns(df)
                except Exception as err:
                    last_err = err
        raise ValueError(f'Nao foi possivel ler o CSV. Detalhe: {last_err}')
    if ext in ['xlsx', 'xls']:
        engine = 'openpyxl' if ext == 'xlsx' else 'xlrd'
        return normalize_columns(pd.read_excel(io.BytesIO(content), engine=engine))
    raise ValueError('Formato nao suportado. Use .xlsx, .xls ou .csv')


def validate_df(df):
    missing = [col for col in REQ if col not in df.columns]
    return len(missing) == 0, missing


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


def prepare(df):
    work = df.copy()
    work['DT_HR_INSPECAO'] = parse_dt(work['DT_HR_INSPECAO'])
    work['C_DPU_QG_AMARELO'] = pd.to_numeric(work['C_DPU_QG_AMARELO'], errors='coerce').fillna(0)
    work['NR_WO'] = work['NR_WO'].astype(str).str.strip()
    work['CD_POSTO_CN'] = work['CD_POSTO_CN'].astype(str).map(norm_posto)
    return work[work['DT_HR_INSPECAO'].notna()].copy()


def load_merged_year_df(conn, posto, year):
    df = pd.read_sql_query("SELECT upload_id, nr_wo AS NR_WO, dt_hr_inspecao AS DT_HR_INSPECAO, c_dpu_qg_amarelo AS C_DPU_QG_AMARELO, cd_posto_cn AS CD_POSTO_CN FROM raw_inspections WHERE cd_posto_cn=? AND strftime('%Y', dt_hr_inspecao)=? ORDER BY upload_id ASC, id ASC", conn, params=[posto, str(year)])
    if df.empty:
        return df
    df['DT_HR_INSPECAO'] = pd.to_datetime(df['DT_HR_INSPECAO'], errors='coerce')
    df['C_DPU_QG_AMARELO'] = pd.to_numeric(df['C_DPU_QG_AMARELO'], errors='coerce').fillna(0)
    df['CD_POSTO_CN'] = df['CD_POSTO_CN'].astype(str).map(norm_posto)
    df['NR_WO'] = df['NR_WO'].astype(str).str.strip()
    df = df[df['DT_HR_INSPECAO'].notna()].copy()
    return df.drop_duplicates(subset=['NR_WO', 'DT_HR_INSPECAO', 'CD_POSTO_CN'], keep='last').reset_index(drop=True)


def calc_rft(df, start_date, end_date):
    sdt = datetime.combine(start_date, time(0, 0, 0))
    edt = datetime.combine(end_date, time(23, 59, 59))
    filt = df[(df['DT_HR_INSPECAO'] >= sdt) & (df['DT_HR_INSPECAO'] <= edt)].copy()
    if filt.empty:
        return {'rft_pct': None, 'total': 0, 'good': 0, 'bad': 0}
    grp = filt.groupby('NR_WO', as_index=False)['C_DPU_QG_AMARELO'].sum().rename(columns={'C_DPU_QG_AMARELO': 'SOMA'})
    grp['RFT'] = (grp['SOMA'] == 0).astype(int)
    total = int(len(grp)); good = int(grp['RFT'].sum()); bad = int(total - good)
    pct = round((good / total) * 100, 2) if total else None
    return {'rft_pct': pct, 'total': total, 'good': good, 'bad': bad}


def year_status(df, year):
    ydf = df[df['DT_HR_INSPECAO'].dt.year == year]
    if ydf.empty:
        return False, 'Sem dados'
    max_d = ydf['DT_HR_INSPECAO'].dt.date.max()
    cutoff = date(year, CUTOFF_MONTH, CUTOFF_DAY)
    return (max_d >= cutoff), ('Fechado em 12/12' if max_d >= cutoff else 'Ate ' + max_d.strftime('%d/%m/%Y'))


def week_options(df, year):
    ydf = df[df['DT_HR_INSPECAO'].dt.year == year].copy()
    if ydf.empty: return []
    dates = sorted(ydf['DT_HR_INSPECAO'].dt.date.unique().tolist())
    mondays = sorted({d - timedelta(days=d.weekday()) for d in dates})
    return [(f'Semana {idx:02d} - {m.strftime("%d/%m/%Y")} a {(m + timedelta(days=6)).strftime("%d/%m/%Y")}', m, m + timedelta(days=6)) for idx, m in enumerate(mondays, start=1)]


def month_options(df, year):
    ydf = df[df['DT_HR_INSPECAO'].dt.year == year].copy()
    if ydf.empty: return []
    opts = []
    for month in sorted(ydf['DT_HR_INSPECAO'].dt.month.unique().tolist()):
        start = date(year, int(month), 1)
        end = date(year, int(month), monthrange(year, int(month))[1])
        opts.append((f'{start.strftime("%m/%Y")} - {start.strftime("%d/%m/%Y")} a {end.strftime("%d/%m/%Y")}', start, end))
    return opts


def status_class(value):
    meta = current_meta()
    if value is None or pd.isna(value): return 'normal'
    return 'normal' if value <= meta else 'inverse'


def metric_value(result):
    return 'Sem dados' if result is None or result['rft_pct'] is None else f"{result['rft_pct']:.2f}".replace('.', ',') + '%'


def resolve_period_selection(df, ano, mode):
    min_date = df['DT_HR_INSPECAO'].dt.date.min(); max_date = df['DT_HR_INSPECAO'].dt.date.max()
    selected_label = f'Ano {ano}'; selected_range = (date(ano,1,1), min(max_date, date(ano,12,12)))
    if mode == 'Diario':
        saved_day = ls_get('dia', '')
        try: default_day = datetime.fromisoformat(saved_day).date() if saved_day else max_date
        except Exception: default_day = max_date
        if default_day < min_date or default_day > max_date: default_day = max_date
        selected = st.sidebar.date_input('Dia', value=default_day, min_value=min_date, max_value=max_date, format='DD/MM/YYYY')
        ls_set('dia', selected.isoformat())
        selected_label = selected.strftime('%d/%m/%Y'); selected_range = (selected, selected)
    elif mode == 'Semanal':
        opts = week_options(df, ano); labels = [x[0] for x in opts]
        if not labels: return min_date, max_date, selected_label, selected_range, False
        saved = ls_get('semana_label', '') ; idx = labels.index(saved) if saved in labels else len(labels)-1
        label = st.sidebar.selectbox('Semana do ano', labels, index=idx)
        ls_set('semana_label', label)
        found = next(x for x in opts if x[0] == label)
        selected_label = label; selected_range = (found[1], found[2])
    elif mode == 'Mensal':
        opts = month_options(df, ano); labels = [x[0] for x in opts]
        if not labels: return min_date, max_date, selected_label, selected_range, False
        saved = ls_get('mes_label', '') ; idx = labels.index(saved) if saved in labels else len(labels)-1
        label = st.sidebar.selectbox('Mes do ano', labels, index=idx)
        ls_set('mes_label', label)
        found = next(x for x in opts if x[0] == label)
        selected_label = label; selected_range = (found[1], found[2])
    return min_date, max_date, selected_label, selected_range, True


def compute_selected_metrics(df, ano, mode, selected_range, ok_ano, max_date):
    daily = weekly = monthly = yearly = ytd = None
    start, end = selected_range
    if mode == 'Diario':
        selected = start
        daily = calc_rft(df, selected, selected)
        ws = selected - timedelta(days=selected.weekday()); we = ws + timedelta(days=6)
        weekly = calc_rft(df, ws, we)
        ms = date(ano, selected.month, 1); me = date(ano, selected.month, monthrange(ano, selected.month)[1])
        monthly = calc_rft(df, ms, me)
        yearly = calc_rft(df, date(ano,1,1), date(ano,12,12)) if ok_ano else None
        ytd = calc_rft(df, date(ano,1,1), selected)
    elif mode == 'Semanal':
        ws, we = start, end
        weekly = calc_rft(df, ws, we)
        yearly = calc_rft(df, date(ano,1,1), date(ano,12,12)) if ok_ano else None
        ytd = calc_rft(df, date(ano,1,1), min(we, max_date))
    elif mode == 'Mensal':
        ms, me = start, end
        monthly = calc_rft(df, ms, me)
        yearly = calc_rft(df, date(ano,1,1), date(ano,12,12)) if ok_ano else None
        ytd = calc_rft(df, date(ano,1,1), min(me, max_date))
    else:
        yearly = calc_rft(df, date(ano,1,1), date(ano,12,12)) if ok_ano else None
        ytd = calc_rft(df, date(ano,1,1), min(max_date, date(ano,12,12)))
    return {'daily': daily, 'weekly': weekly, 'monthly': monthly, 'yearly': yearly, 'ytd': ytd}


def monthly_trend(df, year, meta):
    ydf = df[df['DT_HR_INSPECAO'].dt.year == year].copy()
    if ydf.empty: return pd.DataFrame(columns=['Mes','RFT','Meta'])
    rows = []
    for month in sorted(ydf['DT_HR_INSPECAO'].dt.month.unique().tolist()):
        start = date(year, int(month), 1); end = date(year, int(month), monthrange(year, int(month))[1])
        res = calc_rft(ydf, start, end)
        rows.append({'Mes': start.strftime('%m/%Y'), 'RFT': res['rft_pct'] or 0, 'Meta': meta})
    return pd.DataFrame(rows)


def weekly_trend(df, year):
    ydf = df[df['DT_HR_INSPECAO'].dt.year == year].copy()
    if ydf.empty: return pd.DataFrame(columns=['Semana','RFT'])
    rows = []
    for label, ws, we in week_options(ydf, year):
        res = calc_rft(ydf, ws, we)
        rows.append({'Semana': label.split('-')[0].strip(), 'RFT': res['rft_pct'] or 0})
    return pd.DataFrame(rows)


def preview_file_impact(conn, df):
    if df is None or df.empty: return pd.DataFrame(), []
    overlaps = upload_overlap_warning(conn, df)
    overlap_keys = {(x['posto'], x['ano']) for x in overlaps}
    rows = []
    for (year, posto), part in df.groupby([df['DT_HR_INSPECAO'].dt.year, 'CD_POSTO_CN']):
        rows.append({'Posto': posto, 'Ano': int(year), 'Data minima do arquivo': part['DT_HR_INSPECAO'].dt.date.min().strftime('%d/%m/%Y'), 'Data maxima do arquivo': part['DT_HR_INSPECAO'].dt.date.max().strftime('%d/%m/%Y'), 'Linhas do arquivo': int(len(part)), 'Sobreposicao': 'Sim' if (posto, int(year)) in overlap_keys else 'Nao'})
    return pd.DataFrame(rows), overlaps


def main():
    conn = get_conn(); init_db(conn)
    st.title('RFT Automatico - V9.0')
    st.caption('Baseada na V6.2, com o grafico mensal da aba Tendencia em barras/colunas igual ao semanal.')

    with st.sidebar:
        default_posto = ls_get('posto', POSTO_PADRAO)
        posto_idx = POSTOS.index(default_posto) if default_posto in POSTOS else 0
        posto = st.radio('Posto', POSTOS, index=posto_idx, horizontal=True)
        ls_set('posto', posto)
        anos = available_years(conn, posto)
        if anos:
            prev_year = ls_get('ano', None)
            try: prev_year = int(prev_year) if prev_year is not None else None
            except Exception: prev_year = None
            ano_idx = anos.index(prev_year) if prev_year in anos else len(anos)-1
            ano = st.selectbox('Ano', anos, index=ano_idx)
            ls_set('ano', ano)
        else:
            ano = None
            st.info('Sem dados salvos para este posto.')
        modes = ['Diario', 'Semanal', 'Mensal', 'Anual']
        default_mode = ls_get('modo', 'Diario')
        mode_idx = modes.index(default_mode) if default_mode in modes else 0
        mode = st.radio('Modo', modes, index=mode_idx)
        ls_set('modo', mode)
        saved_meta = ls_get('meta_rft', DEFAULT_META_RFT)
        try: saved_meta = float(str(saved_meta).replace(',', '.'))
        except Exception: saved_meta = DEFAULT_META_RFT
        meta = st.number_input('Meta RFT (%)', min_value=0.0, max_value=100.0, value=float(saved_meta), step=0.1)
        st.session_state['meta_rft'] = float(meta)
        ls_set('meta_rft', meta)
        st.caption('RFT <= meta = verde | RFT > meta = vermelho')

    if ano is None:
        tabs = st.tabs(['Base & Upload', 'Historico', 'Sobre'])
        with tabs[0]:
            st.info('Sem base para analisar. Faça um upload.')
        with tabs[1]:
            hist = uploads_table(conn)
            st.dataframe(hist, use_container_width=True, hide_index=True) if not hist.empty else st.info('Os uploads processados aparecerao aqui.')
        with tabs[2]:
            st.write('Versão V9.0 baseada na V6.2. Única mudança: gráfico mensal da Tendência em barras.')
        return

    latest_upload_id = latest_upload_id_for_year(conn, posto, ano)
    info = upload_info(conn, latest_upload_id) if latest_upload_id is not None else None
    df = load_merged_year_df(conn, posto, ano) if latest_upload_id is not None else pd.DataFrame()

    tabs = st.tabs(['Dashboard', 'Tendencia', 'Base & Upload', 'Historico', 'Sobre'])

    with tabs[0]:
        if df.empty:
            st.info('Sem histórico para esse ano/posto.')
        else:
            ok_ano, status_label = year_status(df, ano)
            min_date, max_date, selected_label, selected_range, valid_selection = resolve_period_selection(df, ano, mode)
            if not valid_selection:
                st.info('Nenhum período disponível para o modo selecionado.')
            else:
                metrics = compute_selected_metrics(df, ano, mode, selected_range, ok_ano, max_date)
                cols = st.columns(5)
                items = [('RFT Diario','Dia selecionado','daily'),('RFT Semanal','Consolidacao semanal','weekly'),('RFT Mensal','Consolidacao mensal','monthly'),('RFT Anual','Ano ate 12/12','yearly'),('RFT YTD','Acumulado ate o recorte','ytd')]
                for col,(title,subtitle,key) in zip(cols, items):
                    with col:
                        res = metrics[key]
                        if res is None:
                            st.metric(title, 'Sem dados', subtitle)
                        else:
                            st.metric(title, metric_value(res), f"{subtitle} | WOs boas: {res['good']} | ruins: {res['bad']} | total: {res['total']}")
                st.write(f"Posto: **{posto}** | Ano: **{ano}** | Meta: **{str(meta).replace('.',',')}%** | Fechamento: **{status_label}**")
                st.write(f"Recorte atual: **{selected_label}** | Último arquivo: **{info['file_name'] if info else '-'}** | Último upload: **{info['uploaded_at'] if info else '-'}**")
                day_rows = []
                for d in sorted(df['DT_HR_INSPECAO'].dt.date.unique().tolist()):
                    res = calc_rft(df, d, d)
                    day_rows.append({'Dia': d.strftime('%d/%m/%Y'), 'RFT': res['rft_pct'] or 0})
                day_df = pd.DataFrame(day_rows)
                if not day_df.empty:
                    st.subheader('Leitura diaria do RFT')
                    st.line_chart(day_df.set_index('Dia'), use_container_width=True)

    with tabs[1]:
        if df.empty:
            st.info('Sem histórico válido para a tendência.')
        else:
            monthly_df = monthly_trend(df, ano, meta)
            weekly_df = weekly_trend(df, ano)
            c1, c2 = st.columns(2)
            with c1:
                st.subheader('Tendencia mensal')
                if monthly_df.empty:
                    st.info('Sem dados mensais disponíveis.')
                else:
                    st.bar_chart(monthly_df.set_index('Mes')[['RFT','Meta']], use_container_width=True)
                    st.dataframe(monthly_df, use_container_width=True, hide_index=True)
            with c2:
                st.subheader('Tendencia semanal')
                if weekly_df.empty:
                    st.info('Sem dados semanais disponíveis.')
                else:
                    st.bar_chart(weekly_df.set_index('Semana'), use_container_width=True)
                    st.dataframe(weekly_df, use_container_width=True, hide_index=True)

    with tabs[2]:
        st.subheader('Base & Upload')
        import_mode = st.radio('Modo de importação', ['Somar ao historico', 'Substituir periodo sobreposto', 'Reprocessar o ano inteiro'])
        uploaded = st.file_uploader('Base operacional atual (.xlsx, .xls ou .csv)', type=['xlsx','xls','csv'])
        prepared = None
        if uploaded is not None:
            try:
                raw = read_file(uploaded)
                ok, miss = validate_df(raw)
                if not ok:
                    st.error('Base operacional invalida: ' + ', '.join(miss))
                else:
                    prepared = prepare(raw)
                    impact, overlaps = preview_file_impact(conn, prepared)
                    if not impact.empty:
                        st.dataframe(impact, use_container_width=True, hide_index=True)
                    for item in overlaps:
                        st.warning(item['texto'])
            except Exception as err:
                st.error(f'Erro ao ler a base operacional: {err}')
        if st.button('Salvar arquivo localmente', type='primary', use_container_width=True):
            if uploaded is None or prepared is None:
                st.error('Selecione um arquivo antes de salvar.')
            elif prepared.empty:
                st.error('A base foi lida, mas nao restaram linhas validas após o tratamento.')
            else:
                affected = apply_import_mode(conn, prepared, import_mode)
                uid = create_upload(conn, uploaded.name, len(prepared), message='Base recebida e salva localmente.')
                save_raw(conn, uid, prepared)
                msg = 'Arquivo salvo com sucesso.' + (' ' + ' | '.join(affected) if affected else '')
                update_upload(conn, uid, 'PROCESSADO', msg)
                st.success(msg)
                st.rerun()

    with tabs[3]:
        st.subheader('Historico')
        hist = uploads_table(conn)
        if hist.empty:
            st.info('Os uploads processados aparecerão aqui.')
        else:
            st.dataframe(hist, use_container_width=True, hide_index=True)
            selected_id = st.selectbox('Selecionar upload', hist['id'].tolist(), format_func=lambda x: f'Upload {x}')
            c1,c2,c3 = st.columns(3)
            with c1:
                if st.button('Ver detalhes do upload', use_container_width=True):
                    detail = upload_detail_df(conn, selected_id)
                    if detail.empty:
                        st.warning('Upload sem detalhes disponíveis.')
                    else:
                        sel = upload_info(conn, selected_id)
                        st.info(f"Arquivo: {sel['file_name'] if sel else '-'} | Upload: {sel['uploaded_at'] if sel else '-'} | Linhas: {len(detail)}")
                        detail_show = detail.copy(); detail_show['DT_HR_INSPECAO'] = detail_show['DT_HR_INSPECAO'].dt.strftime('%d/%m/%Y %H:%M:%S')
                        st.dataframe(detail_show.head(200), use_container_width=True, hide_index=True)
            with c2:
                if st.button('Reprocessar upload', use_container_width=True):
                    new_id = reprocess_upload(conn, selected_id)
                    st.success(f'Upload reprocessado com sucesso. Novo upload: {new_id}.' if new_id else 'Não foi possível reprocessar o upload.')
                    st.rerun()
            with c3:
                if st.button('Excluir upload específico', use_container_width=True):
                    delete_upload(conn, selected_id)
                    st.success('Upload excluído com sucesso.')
                    st.rerun()

    with tabs[4]:
        st.subheader('Sobre')
        st.write('Versão V9.0 baseada na V6.2. Única mudança funcional: o gráfico mensal da aba Tendencia agora usa barras/colunas no mesmo estilo do gráfico semanal.')

if __name__ == '__main__':
    main()
