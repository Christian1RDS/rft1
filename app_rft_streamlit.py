import io
from datetime import datetime, time
from typing import Tuple, Dict, Any

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Cálculo de RFT", page_icon="📊", layout="wide")

REQUIRED_COLUMNS = ["NR_WO", "DT_HR_INSPECAO", "C_DPU_QG_AMARELO"]


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().replace("\ufeff", "") for c in df.columns]
    return df


def try_read_csv(file_bytes: bytes) -> pd.DataFrame:
    encodings = ["utf-8-sig", "utf-16", "latin1"]
    separators = [None, ";", ",", "\t"]
    last_err = None

    for enc in encodings:
        for sep in separators:
            try:
                if sep is None:
                    df = pd.read_csv(io.BytesIO(file_bytes), encoding=enc, sep=None, engine="python")
                else:
                    df = pd.read_csv(io.BytesIO(file_bytes), encoding=enc, sep=sep)
                df = normalize_columns(df)
                if len(df.columns) >= 3:
                    return df
            except Exception as e:
                last_err = e
                continue
    raise ValueError(f"Não foi possível ler o CSV. Erro: {last_err}")


def load_file(uploaded_file) -> pd.DataFrame:
    suffix = uploaded_file.name.lower().split(".")[-1]
    file_bytes = uploaded_file.getvalue()

    if suffix == "csv":
        df = try_read_csv(file_bytes)
    elif suffix in ["xlsx", "xls"]:
        engine = "openpyxl" if suffix == "xlsx" else "xlrd"
        df = pd.read_excel(io.BytesIO(file_bytes), engine=engine)
        df = normalize_columns(df)
    else:
        raise ValueError("Formato não suportado. Use .xlsx, .xls ou .csv")

    return df


def parse_datetime_series(series: pd.Series) -> pd.Series:
    # 1) tentativa direta (funciona para datetime, Excel, formatos US/ISO comuns)
    dt = pd.to_datetime(series, errors="coerce")

    # 2) fallback dayfirst para itens que sobraram como string BR
    mask = dt.isna() & series.notna()
    if mask.any():
        dt2 = pd.to_datetime(series[mask], errors="coerce", dayfirst=True)
        dt.loc[mask] = dt2

    return dt


def validate_dataframe(df: pd.DataFrame) -> Tuple[bool, str]:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        return False, (
            "A planilha não contém as colunas obrigatórias: "
            + ", ".join(missing)
        )
    return True, ""


def calculate_rft(df: pd.DataFrame, data_inicial: datetime, data_final: datetime) -> Dict[str, Any]:
    work = df.copy()

    work["DT_HR_INSPECAO"] = parse_datetime_series(work["DT_HR_INSPECAO"])
    work["C_DPU_QG_AMARELO"] = pd.to_numeric(work["C_DPU_QG_AMARELO"], errors="coerce").fillna(0)
    work["NR_WO"] = work["NR_WO"].astype(str).str.strip()

    start_dt = datetime.combine(data_inicial.date(), time(0, 0, 0))
    end_dt = datetime.combine(data_final.date(), time(23, 59, 59))

    filtered = work[(work["DT_HR_INSPECAO"] >= start_dt) & (work["DT_HR_INSPECAO"] <= end_dt)].copy()

    if filtered.empty:
        return {
            "periodo": f"{data_inicial.strftime('%d/%m/%Y')} até {data_final.strftime('%d/%m/%Y')}",
            "linhas_no_periodo": 0,
            "total_wos": 0,
            "wos_sem_defeito": 0,
            "wos_com_defeito": 0,
            "media_exata": None,
            "percentual_exato": None,
            "conferencia": "Sem dados no período",
            "tabela_wo": pd.DataFrame(columns=["NR_WO", "SOMA_C_DPU_QG_AMARELO", "RFT"]),
            "wos_boas": []
        }

    tabela_wo = (
        filtered.groupby("NR_WO", as_index=False)["C_DPU_QG_AMARELO"]
        .sum()
        .rename(columns={"C_DPU_QG_AMARELO": "SOMA_C_DPU_QG_AMARELO"})
    )

    tabela_wo["RFT"] = (tabela_wo["SOMA_C_DPU_QG_AMARELO"] == 0).astype(int)

    total_wos = int(len(tabela_wo))
    wos_sem_defeito = int(tabela_wo["RFT"].sum())
    wos_com_defeito = int(total_wos - wos_sem_defeito)
    media_exata = float(tabela_wo["RFT"].mean())
    percentual_exato = float(media_exata * 100)
    wos_boas = tabela_wo.loc[tabela_wo["RFT"] == 1, "NR_WO"].tolist()

    return {
        "periodo": f"{data_inicial.strftime('%d/%m/%Y')} até {data_final.strftime('%d/%m/%Y')}",
        "linhas_no_periodo": int(len(filtered)),
        "total_wos": total_wos,
        "wos_sem_defeito": wos_sem_defeito,
        "wos_com_defeito": wos_com_defeito,
        "media_exata": media_exata,
        "percentual_exato": percentual_exato,
        "conferencia": f"{wos_sem_defeito} / {total_wos} = {media_exata}",
        "tabela_wo": tabela_wo.sort_values(["RFT", "NR_WO"], ascending=[False, True]).reset_index(drop=True),
        "wos_boas": wos_boas
    }


def result_to_text(resultado: Dict[str, Any], tipo_calculo: str) -> str:
    linhas = [
        f"Cálculo de RFT - {tipo_calculo.capitalize()}",
        f"Período analisado: {resultado['periodo']}",
        f"Linhas no período: {resultado['linhas_no_periodo']}",
        f"Total de WOs: {resultado['total_wos']}",
        f"WOs sem defeito (RFT=1): {resultado['wos_sem_defeito']}",
        f"WOs com defeito (RFT=0): {resultado['wos_com_defeito']}",
        f"Média exata: {resultado['media_exata']}",
        f"Porcentagem exata: {resultado['percentual_exato']}%",
        f"Conferência matemática: {resultado['conferencia']}",
    ]

    if resultado["wos_boas"]:
        linhas.append("WOs com RFT=1: " + ", ".join(map(str, resultado["wos_boas"])))
    else:
        linhas.append("WOs com RFT=1: nenhuma")

    return "\n".join(linhas)


def result_to_excel_bytes(resultado: Dict[str, Any], tipo_calculo: str) -> bytes:
    output = io.BytesIO()
    resumo = pd.DataFrame([
        ["Tipo de cálculo", tipo_calculo.capitalize()],
        ["Período analisado", resultado["periodo"]],
        ["Linhas no período", resultado["linhas_no_periodo"]],
        ["Total de WOs", resultado["total_wos"]],
        ["WOs sem defeito", resultado["wos_sem_defeito"]],
        ["WOs com defeito", resultado["wos_com_defeito"]],
        ["Média exata", resultado["media_exata"]],
        ["Porcentagem exata", resultado["percentual_exato"]],
        ["Conferência matemática", resultado["conferencia"]],
    ], columns=["Campo", "Valor"])

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        resumo.to_excel(writer, index=False, sheet_name="Resumo")
        resultado["tabela_wo"].to_excel(writer, index=False, sheet_name="Tabela_WO")

    return output.getvalue()


def main():
    st.title("📊 Cálculo de RFT")
    st.caption("Ferramenta interna para cálculo exato de RFT por período, agrupando por NR_WO.")

    with st.expander("Como o cálculo funciona", expanded=False):
        st.markdown(
            """
            **Regra de cálculo do RFT:**
            1. Filtrar os registros pela coluna `DT_HR_INSPECAO` no período informado.
            2. Agrupar por `NR_WO`.
            3. Somar `C_DPU_QG_AMARELO` por WO.
            4. Aplicar a regra:
               - Se soma = 0 → RFT = 1
               - Se soma > 0 → RFT = 0
            5. Calcular a média dos valores de RFT.
            6. Converter a média para porcentagem.
            """
        )

    col1, col2 = st.columns([1.2, 1])

    with col1:
        uploaded_file = st.file_uploader(
            "Envie a planilha (.xlsx, .xls ou .csv)",
            type=["xlsx", "xls", "csv"]
        )

    with col2:
        tipo_calculo = st.radio(
            "Tipo de cálculo",
            ["diário", "semanal", "mensal"],
            horizontal=True
        )

    c1, c2 = st.columns(2)
    with c1:
        data_inicial = st.date_input("Data inicial", format="DD/MM/YYYY")
    with c2:
        if tipo_calculo == "diário":
            data_final = st.date_input("Data final", value=data_inicial, format="DD/MM/YYYY", disabled=True)
        else:
            data_final = st.date_input("Data final", value=data_inicial, format="DD/MM/YYYY")

    calcular = st.button("Calcular RFT", type="primary", use_container_width=True)

    if calcular:
        if uploaded_file is None:
            st.error("Selecione uma planilha antes de calcular.")
            st.stop()

        if data_inicial > data_final:
            st.error("A data inicial não pode ser maior que a data final.")
            st.stop()

        try:
            df = load_file(uploaded_file)
        except Exception as e:
            st.error(f"Erro ao ler o arquivo: {e}")
            st.stop()

        ok, msg = validate_dataframe(df)
        if not ok:
            st.error(msg)
            st.stop()

        try:
            resultado = calculate_rft(df, pd.Timestamp(data_inicial), pd.Timestamp(data_final))
        except Exception as e:
            st.error(f"Erro ao processar o cálculo: {e}")
            st.stop()

        st.success("Cálculo realizado com sucesso.")

        st.subheader("Resultado do cálculo")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Linhas no período", resultado["linhas_no_periodo"])
        m2.metric("Total de WOs", resultado["total_wos"])
        m3.metric("WOs sem defeito", resultado["wos_sem_defeito"])
        m4.metric("WOs com defeito", resultado["wos_com_defeito"])

        if resultado["media_exata"] is not None:
            m5, m6 = st.columns(2)
            m5.metric("Média exata", f"{resultado['media_exata']}")
            m6.metric("RFT (%)", f"{resultado['percentual_exato']}%")
        else:
            st.warning("Sem dados no período informado.")

        st.markdown(f"**Período analisado:** {resultado['periodo']}")
        st.markdown(f"**Conferência matemática:** {resultado['conferencia']}")

        st.subheader("Tabela por WO")
        st.dataframe(resultado["tabela_wo"], use_container_width=True, hide_index=True)

        txt_bytes = result_to_text(resultado, tipo_calculo).encode("utf-8")
        xlsx_bytes = result_to_excel_bytes(resultado, tipo_calculo)

        d1, d2 = st.columns(2)
        with d1:
            st.download_button(
                label="Baixar resultado em TXT",
                data=txt_bytes,
                file_name=f"RFT_{tipo_calculo}_{pd.Timestamp(data_inicial).strftime('%Y-%m-%d')}.txt",
                mime="text/plain",
                use_container_width=True
            )
        with d2:
            st.download_button(
                label="Baixar resultado em Excel",
                data=xlsx_bytes,
                file_name=f"RFT_{tipo_calculo}_{pd.Timestamp(data_inicial).strftime('%Y-%m-%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )


if __name__ == "__main__":
    main()
