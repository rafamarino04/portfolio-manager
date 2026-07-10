"""News: una sezione con le notizie sui titoli in portafoglio e una con
news generali di mercato (RSS, nessuna API key richiesta)."""
import streamlit as st

from src import data_provider as dp
from src import portfolio as pf
from src.auth import check_password

st.set_page_config(page_title="News", page_icon="\U0001F4F0", layout="wide")

if not check_password():
    st.stop()

st.title("\U0001F4F0 News")

st.subheader("Sui tuoi titoli")
try:
    raw = pf.load_portfolio("data/portfolio.csv")
    tickers = raw["ticker"].tolist()
except Exception as e:
    tickers = []
    st.error(f"Impossibile leggere il portafoglio: {e}")

if tickers:
    tabs = st.tabs(tickers)
    for tab, ticker in zip(tabs, tickers):
        with tab:
            news = dp.get_news(ticker, limit=5)
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
                st.info("Nessuna news trovata al momento.")

st.divider()
st.subheader("Mercati in generale")
market_news = dp.get_market_news(limit=10)
if market_news:
    for n in market_news:
        title = n.get("title")
        link = n.get("link")
        publisher = n.get("publisher") or ""
        if link:
            st.markdown(f"- [{title}]({link}) · *{publisher}*")
        else:
            st.markdown(f"- {title} · *{publisher}*")
else:
    st.info("Nessuna news di mercato disponibile al momento.")
