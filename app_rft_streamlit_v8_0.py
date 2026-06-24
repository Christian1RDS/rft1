
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

st.set_page_config(page_title='RFT Qualidade - V8.0', page_icon='Q', layout='wide', initial_sidebar_state='expanded')

DB = 'rft_v61_local.db'
REQ = ['NR_WO', 'DT_HR_INSPECAO', 'C_DPU_QG_AMARELO', 'CD_POSTO_CN']
POSTOS = ['QG09', 'QG07']
POSTO_PADRAO = 'QG09'
LS_PREFIX = 'rft_v80_'
DEFAULT_META_RFT = 95.0
CUTOFF_MONTH = 12
CUTOFF_DAY = 12

# -------------------- local storage --------------------
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

# -------------------- database --------------------
def get_conn():
    return sqlite3.connect(DB, check_same_thread=False)


def init_db(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS upload_log (id INTEGER PRIMARY KEY AUTOINCREMENT, file_name TEXT NOT NULL, uploaded_at TEXT NOT NULL, total_rows INTEGER NOT NULL, status TEXT NOT NULL, message TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS raw_inspections (id INTEGER PRIMARY KEY AUTOINCREMENT, upload_id INTEGER NOT NULL, nr_wo TEXT, dt_hr_inspecao TEXT, c_dpu_qg_amarelo REAL, cd_posto_cn TEXT)')
    conn.commit()


def create_upload(conn, file_name, total_rows, status='RECEBIDO', message=''):
    cur = conn.execute(
        'INSERT INTO upload_log (file_name, uploaded_at, total_rows, status, message) VALUES (?, ?, ?, ?, ?)',
        (file_name, datetime.now().isoformat(timespec='seconds'), int(total_rows), status, message),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_upload(conn, upload_id, status, message=''):
    conn.execute('UPDATE upload_log SET status=?, message=? WHERE id=?', (status, message, int(upload_id)))
    conn.commit()


def save_raw(conn, upload_id, df):
    rows = []
    for _, r in df.iterrows():
        rows.append((int(upload_id), r['NR_WO'], r['DT_HR_INSPECAO'].isoformat(sep=' ', timespec='seconds'), float(r['C_DPU_QG_AMARELO']), r['CD_POSTO_CN']))
    conn.executemany('INSERT INTO raw_inspections (upload_id, nr_wo, dt_hr_inspecao, c_dpu_qg_amarelo, cd_posto_cn) VALUES (?, ?, ?, ?, ?)', rows)
    conn.commit()


def uploads_table(conn):
    return pd.read_sql_query('SELECT id, file_name, uploaded_at, total_rows, status, message FROM upload_log ORDER BY id DESC LIMIT 500', conn)


def upload_info(conn, upload_id):
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT * FROM upload_log WHERE id=?', (int(upload_id),)).fetchone()
    conn.row_factory = None
    return row


def detail_upload_df(conn, upload_id):
    df = pd.read_sql_query('SELECT nr_wo AS NR_WO, dt_hr_inspecao AS DT_HR_INSPECAO, c_dpu_qg_amarelo AS C_DPU_QG_AMARELO, cd_posto_cn AS CD_POSTO_CN FROM raw_inspections WHERE upload_id=? ORDER BY dt_hr_inspecao, nr_wo', conn, params=[int(upload_id)])
    if not df.empty:
        df['DT_HR_INSPECAO'] = pd.to_datetime(df['DT_HR_INSPECAO'], errors='coerce')
    return df


def delete_upload(conn, upload_id):
    conn.execute('DELETE FROM raw_inspections WHERE upload_id=?', (int(upload_id),))
    conn.execute('DELETE FROM upload_log WHERE id=?', (int(upload_id),))
    conn.commit()


def reprocess_upload(conn, upload_id):
    df = detail_upload_df(conn, upload_id)
    if df.empty:
        update_upload(conn, upload_id, 'ERRO', 'Upload sem linhas brutas para reprocessar.')
        return None
    info = upload_info(conn, upload_id)
    new_name = f"REPROCESSADO_{info['file_name']}" if info else f'REPROCESSADO_{upload_id}'
    new_id = create_upload(conn, new_name, len(df), message=f'Reprocessado a partir do upload {upload_id}.')
    save_raw(conn, new_id, df[['NR_WO', 'DT_HR_INSPECAO', 'C_DPU_QG_AMARELO', 'CD_POSTO_CN']])
    update_upload(conn, new_id, 'PROCESSADO', f'Upload {upload_id} reprocessado com sucesso.')
    return new_id

# -------------------- parse / prepare --------------------
def normalize_columns(df):
    out = df.copy()
    out.columns = [str(x).strip().replace('﻿', '') for x in out.columns]
    return out


def read_file(uploaded_file):
    ext = uploaded_file.name.lower().split('.')[-1]
    content = uploaded_file.getvalue()
    if ext == 'csv':
        last_err = None
        for enc in ['utf-8-sig', 'utf-16', 'latin1']:
            for sep in [None, ';', ',', '	']:
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
    missing = [c for c in REQ if c not in df.columns]
    return len(missing) == 0, missing


def parse_dt(series):
    dt = pd.to_datetime(series, errors='coerce')
    mask = dt.isna() & series.notna()
    if mask.any():
        dt.loc[mask] = pd.to_datetime(series[mask], errors='coerce', dayfirst=True)
    return dt


def norm_posto(v):
    txt = str(v).upper().strip()
    if 'QG09' in txt:
        return 'QG09'
    if 'QG07' in txt:
        return 'QG07'
    return txt


def prepare(df):
    w = df.copy()
    w['DT_HR_INSPECAO'] = parse_dt(w['DT_HR_INSPECAO'])
    w['C_DPU_QG_AMARELO'] = pd.to_numeric(w['C_DPU_QG_AMARELO'], errors='coerce').fillna(0)
    w['NR_WO'] = w['NR_WO'].astype(str).str.strip()
    w['CD_POSTO_CN'] = w['CD_POSTO_CN'].astype(str).map(norm_posto)
    return w[w['DT_HR_INSPECAO'].notna()].copy()

# -------------------- consolidated data helpers --------------------
def available_years(conn, posto):
    df = pd.read_sql_query("SELECT DISTINCT CAST(strftime('%Y', dt_hr_inspecao) AS INT) AS ano FROM raw_inspections WHERE cd_posto_cn=? ORDER BY ano", conn, params=[posto])
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
    conn.execute(
        "DELETE FROM raw_inspections WHERE cd_posto_cn=? AND strftime('%Y', dt_hr_inspecao)=? AND datetime(dt_hr_inspecao) BETWEEN datetime(?) AND datetime(?)",
        (posto, str(year), datetime.combine(start_date, time(0,0,0)).isoformat(sep=' '), datetime.combine(end_date, time(23,59,59)).isoformat(sep=' ')),
    )
    conn.commit()


def delete_year_for_posto(conn, posto, year):
    conn.execute("DELETE FROM raw_inspections WHERE cd_posto_cn=? AND strftime('%Y', dt_hr_inspecao)=?", (posto, str(year)))
    conn.commit()


def upload_overlap_warning(conn, df):
    warnings = []
    if df is None or df.empty:
        return warnings
    for (year, posto), part in df.groupby([df['DT_HR_INSPECAO'].dt.year, 'CD_POSTO_CN']):
        new_min = part['DT_HR_INSPECAO'].dt.date.min()
        new_max = part['DT_HR_INSPECAO'].dt.date.max()
        old_min, old_max = existing_range_for_posto_year(conn, posto, int(year))
        if old_min is None:
            continue
        overlap_start = max(new_min, old_min)
        overlap_end = min(new_max, old_max)
        if overlap_start <= overlap_end:
            warnings.append({'texto': f'Este arquivo cobre datas ja existentes entre {overlap_start.strftime("%d/%m")} e {overlap_end.strftime("%d/%m")}.', 'posto': posto, 'ano': int(year)})
    return warnings


def preview_file_impact(conn, df):
    if df is None or df.empty:
        return pd.DataFrame(), []
    overlaps = upload_overlap_warning(conn, df)
    overlap_keys = {(x['posto'], x['ano']) for x in overlaps}
    rows = []
    for (year, posto), part in df.groupby([df['DT_HR_INSPECAO'].dt.year, 'CD_POSTO_CN']):
        rows.append({'Posto': posto, 'Ano': int(year), 'Data minima do arquivo': part['DT_HR_INSPECAO'].dt.date.min().strftime('%d/%m/%Y'), 'Data maxima do arquivo': part['DT_HR_INSPECAO'].dt.date.max().strftime('%d/%m/%Y'), 'Linhas do arquivo': int(len(part)), 'Sobreposicao': 'Sim' if (posto, int(year)) in overlap_keys else 'Nao'})
    return pd.DataFrame(rows), overlaps


def apply_import_mode(conn, df, mode):
    affected = []
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


def load_merged_year_df(conn, posto, year):
    df = pd.read_sql_query("SELECT id, upload_id, nr_wo AS NR_WO, dt_hr_inspecao AS DT_HR_INSPECAO, c_dpu_qg_amarelo AS C_DPU_QG_AMARELO, cd_posto_cn AS CD_POSTO_CN FROM raw_inspections WHERE cd_posto_cn=? AND strftime('%Y', dt_hr_inspecao)=? ORDER BY upload_id ASC, id ASC", conn, params=[posto, str(year)])
    if df.empty:
        return df
    df['DT_HR_INSPECAO'] = pd.to_datetime(df['DT_HR_INSPECAO'], errors='coerce')
    df['C_DPU_QG_AMARELO'] = pd.to_numeric(df['C_DPU_QG_AMARELO'], errors='coerce').fillna(0)
    df['CD_POSTO_CN'] = df['CD_POSTO_CN'].astype(str).map(norm_posto)
    df['NR_WO'] = df['NR_WO'].astype(str).str.strip()
    df = df[df['DT_HR_INSPECAO'].notna()].copy()
    return df.drop_duplicates(subset=['NR_WO', 'DT_HR_INSPECAO', 'CD_POSTO_CN'], keep='last').reset_index(drop=True)


def load_merged_all_df(conn, posto):
    df = pd.read_sql_query("SELECT id, upload_id, nr_wo AS NR_WO, dt_hr_inspecao AS DT_HR_INSPECAO, c_dpu_qg_amarelo AS C_DPU_QG_AMARELO, cd_posto_cn AS CD_POSTO_CN FROM raw_inspections WHERE cd_posto_cn=? ORDER BY upload_id ASC, id ASC", conn, params=[posto])
    if df.empty:
        return df
    df['DT_HR_INSPECAO'] = pd.to_datetime(df['DT_HR_INSPECAO'], errors='coerce')
    df['C_DPU_QG_AMARELO'] = pd.to_numeric(df['C_DPU_QG_AMARELO'], errors='coerce').fillna(0)
    df['CD_POSTO_CN'] = df['CD_POSTO_CN'].astype(str).map(norm_posto)
    df['NR_WO'] = df['NR_WO'].astype(str).str.strip()
    df = df[df['DT_HR_INSPECAO'].notna()].copy()
    return df.drop_duplicates(subset=['NR_WO', 'DT_HR_INSPECAO', 'CD_POSTO_CN'], keep='last').reset_index(drop=True)


def format_pct(v):
    return 'Sem dados' if v is None or pd.isna(v) else f'{v:.2f}'.replace('.', ',') + '%'


def main():
    conn = get_conn()
    init_db(conn)
    st.title('Qualidade | RFT Automatico - V8.0')
    st.caption('Versão final em arquivo único com RFT completo + Rolling 12 separado + YTD restaurado.')

    with st.sidebar:
        default_posto = ls_get('posto', POSTO_PADRAO)
        posto = st.radio('Posto', POSTOS, index=POSTOS.index(default_posto) if default_posto in POSTOS else 0, horizontal=True)
        ls_set('posto', posto)
        years = available_years(conn, posto)
        if years:
            prev_year = ls_get('ano', None)
            try:
                prev_year = int(prev_year) if prev_year is not None else None
            except Exception:
                prev_year = None
            ano = st.selectbox('Ano', years, index=years.index(prev_year) if prev_year in years else len(years)-1)
            ls_set('ano', ano)
        else:
            ano = None
            st.info('Sem dados salvos para este posto.')
        modes = ['Diario', 'Semanal', 'Mensal', 'Anual']
        default_mode = ls_get('modo', 'Diario')
        mode = st.radio('Modo de visualização', modes, index=modes.index(default_mode) if default_mode in modes else 0)
        ls_set('modo', mode)
        saved_meta = ls_get('meta_rft', DEFAULT_META_RFT)
        try:
            saved_meta = float(str(saved_meta).replace(',', '.'))
        except Exception:
            saved_meta = DEFAULT_META_RFT
        meta = st.number_input('Meta RFT (%)', min_value=0.0, max_value=100.0, value=float(saved_meta), step=0.1)
        st.session_state['meta_rft'] = meta
        ls_set('meta_rft', meta)

    tabs = st.tabs(['Dashboard', 'Tendencias', 'Rolling 12', 'Base & Upload', 'Historico', 'Sobre'])
    latest = latest_upload_id_for_year(conn, posto, ano) if ano is not None else None
    info = upload_info(conn, latest) if latest is not None else None
    year_df = load_merged_year_df(conn, posto, ano) if latest is not None else pd.DataFrame()
    all_df = load_merged_all_df(conn, posto) if latest is not None else pd.DataFrame()

    with tabs[0]:
        if year_df.empty:
            st.info('Sem histórico válido para esse posto/ano.')
        else:
            ok_ano, status_label = year_status(year_df, ano)
            _, _, selected_label, selected_range, valid = resolve_period_selection(year_df, ano, mode)
            if not valid:
                st.info('Nenhum período disponível para o modo selecionado.')
            else:
                max_date = year_df['DT_HR_INSPECAO'].dt.date.max()
                cards = compute_rft_cards(year_df, ano, mode, selected_range, ok_ano, max_date)
                cols = st.columns(5)
                labels = [('Diario','Dia selecionado','daily'), ('Semanal','Semana','weekly'), ('Mensal','Mês','monthly'), ('Anual','Ano até 12/12','yearly'), ('YTD','Ano até data','ytd')]
                for col, (title, sub, key) in zip(cols, labels):
                    with col:
                        res = cards[key]
                        if res is None:
                            st.metric(title, 'Sem dados', sub)
                        else:
                            st.metric(title, format_pct(res['rft_pct']), f"{sub} | Bons: {res['good']} | Ruins: {res['bad']} | Total: {res['total']}")
                st.caption(f"Recorte: {selected_label} | Fechamento: {status_label} | Arquivo: {info['file_name'] if info else '-'} | Meta: {str(meta).replace('.', ',')}%")

    with tabs[1]:
        if year_df.empty:
            st.info('Sem histórico válido para tendências.')
        else:
            mt = monthly_trend(year_df, ano)
            wt = weekly_trend(year_df, ano)
            c1, c2 = st.columns(2)
            with c1:
                if mt.empty:
                    st.info('Sem dados mensais.')
                else:
                    st.subheader('Mensal (colunas)')
                    st.bar_chart(mt.set_index('Mes')[['RFT']], use_container_width=True)
                    mt_show = mt.copy(); mt_show['RFT'] = mt_show['RFT'].map(lambda x: f'{x:.2f}'.replace('.', ',') + '%')
                    st.dataframe(mt_show, use_container_width=True, hide_index=True)
            with c2:
                if wt.empty:
                    st.info('Sem dados semanais.')
                else:
                    st.subheader('Semanal (colunas)')
                    st.bar_chart(wt.set_index('Semana')[['RFT']], use_container_width=True)
                    wt_show = wt.copy(); wt_show['RFT'] = wt_show['RFT'].map(lambda x: f'{x:.2f}'.replace('.', ',') + '%')
                    st.dataframe(wt_show, use_container_width=True, hide_index=True)

    with tabs[2]:
        if all_df.empty or year_df.empty:
            st.info('Sem histórico válido para compor o Rolling 12.')
        else:
            rolling12, rolling12_table = compute_roll12_from_monthly(all_df, year_df['DT_HR_INSPECAO'].dt.date.max())
            c1, c2 = st.columns(2)
            with c1:
                if rolling12['rft_pct'] is None:
                    st.metric('Rolling 12 Consolidado', 'Sem dados', '12 meses móveis')
                else:
                    st.metric('Rolling 12 Consolidado', format_pct(rolling12['rft_pct']), f"12 meses móveis | Bons: {rolling12['good']} | Ruins: {rolling12['bad']} | Total: {rolling12['total']}")
            with c2:
                ytd_now = calc_rft(year_df, date(ano,1,1), year_df['DT_HR_INSPECAO'].dt.date.max())
                if ytd_now['rft_pct'] is None:
                    st.metric('YTD atual', 'Sem dados', 'Ano até data')
                else:
                    st.metric('YTD atual', format_pct(ytd_now['rft_pct']), f"Ano até data | Bons: {ytd_now['good']} | Ruins: {ytd_now['bad']} | Total: {ytd_now['total']}")
            st.bar_chart(rolling12_table.set_index('Mes')[['RFT']], use_container_width=True)
            show = rolling12_table.copy(); show['RFT'] = show['RFT'].map(lambda x: '' if pd.isna(x) else f'{x:.2f}'.replace('.', ',') + '%')
            st.dataframe(show, use_container_width=True, hide_index=True)

    with tabs[3]:
        import_mode = st.radio('Modo de importação', ['Somar ao historico', 'Substituir periodo sobreposto', 'Reprocessar o ano inteiro'])
        uploaded = st.file_uploader('Base operacional atual (.xlsx, .xls ou .csv)', type=['xlsx','xls','csv'])
        prepared = None
        if uploaded is not None:
            try:
                raw = read_file(uploaded)
                ok, miss = validate_df(raw)
                if not ok:
                    st.error('Base operacional inválida: ' + ', '.join(miss))
                else:
                    prepared = prepare(raw)
                    impact, overlaps = preview_file_impact(conn, prepared)
                    if not impact.empty:
                        st.dataframe(impact, use_container_width=True, hide_index=True)
                    for item in overlaps:
                        st.warning(item['texto'])
            except Exception as err:
                st.error(f'Erro ao analisar a base: {err}')
        if st.button('Salvar arquivo localmente', type='primary', use_container_width=True):
            if uploaded is None or prepared is None:
                st.error('Selecione um arquivo válido antes de salvar.')
            elif prepared.empty:
                st.error('A base foi lida, mas não restaram linhas válidas após o tratamento.')
            else:
                affected = apply_import_mode(conn, prepared, import_mode)
                uid = create_upload(conn, uploaded.name, len(prepared), message=f'Modo de importacao: {import_mode}.')
                save_raw(conn, uid, prepared)
                msg = 'Base salva com sucesso.' + (' ' + ' | '.join(affected) if affected else '')
                update_upload(conn, uid, 'PROCESSADO', msg)
                st.success(msg)
                st.rerun()

    with tabs[4]:
        hist = uploads_table(conn)
        if hist.empty:
            st.info('Os uploads processados aparecerão aqui.')
        else:
            st.dataframe(hist, use_container_width=True, hide_index=True)
            selected_id = st.selectbox('Selecionar upload', hist['id'].tolist(), format_func=lambda x: f'Upload {x}')
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button('Ver detalhes do upload', use_container_width=True):
                    detail = detail_upload_df(conn, selected_id)
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

    with tabs[5]:
        st.write('Versão V8.0 em arquivo único com YTD restaurado, calendário, Tendências, Rolling 12 separado e correção do bug de importação por ano.')

if __name__ == '__main__':
    main()
