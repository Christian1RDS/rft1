
# RFT Automatico - V9.5.1

Versão com refinamento visual corporativo e ajuste no cálculo anual.

Mantém:
- calendário e modos Diário / Semanal / Mensal / Anual
- RFT YTD no dashboard
- gráfico mensal da aba Tendência em barras/colunas, igual ao semanal
- fluxo corrigido de upload na aba Base & Upload
- blocos Meta x resultado, Resumo executivo do recorte e Leitura diária do RFT no Dashboard

Regra visual:
- abaixo da meta = vermelho
- acima ou igual à meta = verde

Ajuste do anual:
- o ano é considerado encerrado se houver dados de dezembro a partir do dia 10
- o cálculo anual termina no último dia trabalhado disponível em dezembro

## Como rodar
```bash
pip install -r requirements_v9_5_1.txt
streamlit run app_rft_streamlit_v9_5_1.py
```
