
# RFT Automatico - V9.6

Versão com nova aba **Pareto de Falhas**.

Inclui:
- Top 10 falhas em gráfico Pareto
- gráfico com barras de quantidade e linha de % acumulado
- filtro separado para QG09 e QG07
- demais postos são ignorados
- uso da coluna de falha diretamente do arquivo Excel/CSV no upload
- detecção automática da coluna de falha ou escolha manual no upload
- histórico preservado com a falha salva no banco local

Mantém:
- calendário e modos Diário / Semanal / Mensal / Anual
- RFT YTD no dashboard
- cálculo anual corrigido: fechamento a partir de 10/12 até o último dia trabalhado de dezembro
- design corporativo da V9.5

## Como rodar
```bash
pip install -r requirements_v9_6.txt
streamlit run app_rft_streamlit_v9_6.py
```
