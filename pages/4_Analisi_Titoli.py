"""Ricerca un singolo titolo/ETF: grafico prezzo, statistiche chiave, news."""
import plotly.graph_objects as go
import streamlit as st

from src import data_provider as dp
from src.auth import check_password
from src.theme import apply_theme

st.set_page_config(page_title="Analisi Titoli", page_icon="\U0001F50D", layout="wide")
apply_theme()

if not check_password():
    st.stop()

st.title("\U0001F50D Analisi Titoli / ETF")

symbol = st.text_input(
    "Ticker (es. AAPL, ENI.MI, SWDA.MI, VWCE.DE)", value="AAPL"
).strip().upper()
period = st.selectbox("Periodo", ["1mo", "3mo", "6mo", "1y", "5y"], index=2)

if symbol:
    info = dp.get_info(symbol)
    price = dp.get_current_price(symbol)

    st.subheader(f"{info.get('name', symbol)} ({symbol})")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Prezzo", f"{price:,.2f}" if price else "n/d")
    c2.metric("Settore", info.get("sector") or "n/d")
    c3.metric(
        "Range 52 sett.",
        f"{info.get('week52_low', 0):,.2f} - {info.get('week52_high', 0):,.2f}"
        if info.get("week52_low") else "n/d",
    )
    c4.metric("P/E", f"{info.get('pe_ratio'):.1f}" if info.get("pe_ratio") else "n/d")

    hist = dp.get_history(symbol, period=period)
    if not hist.empty:
        fig = go.Figure(data=[go.Scatter(x=hist.index, y=hist["Close"], mode="lines")])
        fig.update_layout(title=f"Andamento prezzo - {symbol}", xaxis_title="Data", yaxis_title="Prezzo")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Storico prezzi non disponibile per questo ticker.")

    st.subheader("News recenti")
    news = dp.get_news(symbol, limit=6)
    if news:
        for n in news:
            title = n.get("title")
            link = n.get("link")
            publisher = n.get("publisher") or ""
            if link:
                st.markdown(f"- [{title}]({link}) · *{publisher}*")
            else:
                st.markdown(f"- {title} · *{publisher}*")
    else:
        st.info("Nessuna news trovata per questo ticker al momento.")
