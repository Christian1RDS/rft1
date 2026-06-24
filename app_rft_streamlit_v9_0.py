# V9.0

No arquivo app_rft_streamlit_v6_2.py substitua:

st.line_chart(monthly_df.set_index('Mes')[['RFT', 'Meta']])

por:

st.bar_chart(monthly_df.set_index('Mes')[['RFT', 'Meta']])

Salvar como app_rft_streamlit_v9_0.py
