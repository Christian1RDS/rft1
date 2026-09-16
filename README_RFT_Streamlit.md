# Site de Cálculo de RFT (Streamlit)

Aplicação web interna para calcular o **RFT** a partir de planilhas `.xlsx`, `.xls` ou `.csv`.

## O que a aplicação faz

- Upload da planilha
- Seleção do tipo de cálculo: **diário / semanal / mensal**
- Escolha do período
- Cálculo exato do RFT com a regra:
  - Agrupar por `NR_WO`
  - Somar `C_DPU_QG_AMARELO`
  - Se soma = 0 → `RFT = 1`
  - Se soma > 0 → `RFT = 0`
  - Média do RFT = média dos 0 e 1
  - Percentual = média × 100
- Exibição da tabela detalhada por WO
- Exportação para **TXT** e **Excel**

## Colunas obrigatórias da planilha

A planilha precisa conter estas colunas:

- `NR_WO`
- `DT_HR_INSPECAO`
- `C_DPU_QG_AMARELO`

## Como rodar

### 1. Instale os pacotes

```bash
pip install -r requirements.txt
```

### 2. Execute a aplicação

```bash
streamlit run app_rft_streamlit.py
```

### 3. Abra no navegador

O Streamlit normalmente abre automaticamente.
Se não abrir, copie o endereço mostrado no terminal, geralmente algo como:

```text
http://localhost:8501
```

## Observações

- Para cálculo **diário**, a data final é igual à data inicial.
- Para **semanal** e **mensal**, informe o intervalo desejado.
- Se não houver dados no período informado, a aplicação retorna **Sem dados no período**.
- A aplicação tenta interpretar datas tanto em formato Excel quanto em texto.
