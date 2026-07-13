"""
Portfolio Manager - Overview
Dashboard principale: valore totale, P&L, allocazione, tabella posizioni.
Dati da Yahoo Finance (yfinance), delay tipico 15-20 minuti. Solo a scopo
informativo: non e' consulenza finanziaria e non esegue operazioni.
"""
import datetime as dt

import pandas as pd
import plotly.express as px
import streamlit as st

from src import data_provider as dp
from src import portfolio as pf
from src.auth import check_password

st.set_page_config(page_title="Portfolio Manager", page_icon="\U0001F4C8", layout="wide")

if not check_password():
    st.stop()

st.title("\U0001F4C8 Portfolio Manager")
st.caption(
    f"Ultimo aggiornamento: {dt.datetime.now().strftime('%d/%m/%Y %H:%M')} "
    "· Dati Yahoo Finance, delay ~15-20 min · Solo a scopo informativo"
)

CSV_PATH = "data/portfolio.csv"

try:
    raw = pf.load_portfolio(CSV_PATH)
except Exception as e:
    st.error(f"Errore nel caricare {CSV_PATH}: {e}")
    st.stop()

with st.spinner("Recupero prezzi live..."):
    enriched = pf.enrich_with_prices(raw)

summary = pf.portfolio_summary(enriched)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Valore totale", f"{summary['total_value']:,.2f}" if summary['total_value'] else "n/d")
col2.metric("Costo totale", f"{summary['total_cost']:,.2f}" if summary['total_cost'] else "n/d")
col3.metric(
    "P&L totale",
    f"{summary['total_pl']:,.2f}" if summary['total_pl'] is not None else "n/d",
    f"{summary['total_pl_pct']:.2f}%" if summary['total_pl_pct'] is not None else None,
)
if summary["best"] is not None:
    col4.metric(
        "Miglior titolo",
        summary["best"]["ticker"],
        f"{summary['best']['pl_pct']:.2f}%",
    )

st.divider()

c1, c2 = st.columns([1, 1])
with c1:
    st.subheader("Allocazione per titolo")
    if enriched["market_value"].notna().any():
        fig = px.pie(enriched, values="market_value", names="ticker", hole=0.4)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Nessun prezzo disponibile per calcolare l'allocazione.")

with c2:
    if "category" in enriched.columns and enriched["category"].notna().any():
        st.subheader("Allocazione per categoria")
        fig2 = px.pie(enriched, values="market_value", names="category", hole=0.4)
        st.plotly_chart(fig2, use_container_width=True)

st.subheader("Posizioni")
display_cols = [
    "ticker", "name", "quantity", "buy_price", "price", "price_source",
    "market_value", "pl_abs", "pl_pct", "day_change_pct", "weight_pct",
]
display_cols = [c for c in display_cols if c in enriched.columns]
st.dataframe(
    enriched[display_cols].style.format({
        "buy_price": "{:.2f}", "price": "{:.2f}", "market_value": "{:,.2f}",
        "pl_abs": "{:,.2f}", "pl_pct": "{:.2f}%", "day_change_pct": "{:.2f}%",
        "weight_pct": "{:.1f}%",
    }, na_rep="n/d"),
    use_container_width=True,
    hide_index=True,
)
if "price_source" in enriched.columns and (enriched["price_source"] != "live").any():
    st.caption(
        "price_source 'manuale' = prezzo inserito a mano (tipico per obbligazioni non "
        "coperte da Yahoo Finance) · 'n/d' = nessun prezzo disponibile, dato mancante."
    )

st.caption(
    "Per aggiungere, modificare o eliminare posizioni usa la pagina "
    "**Gestisci Portafoglio** nel menu a sinistra — non serve toccare alcun file."
)
