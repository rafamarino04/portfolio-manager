"""Confronta l'allocazione attuale con quella target e suggerisce
cosa comprare/vendere per riportare il portafoglio in equilibrio."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import portfolio as pf
from src import rebalancing as rb
from src import report_config as cfg
from src.auth import check_password
from src.theme import apply_theme, badge

st.set_page_config(page_title="Ribilanciamento", page_icon="⚖️", layout="wide")
apply_theme()

if not check_password():
    st.stop()

st.title("⚖️ Ribilanciamento")
st.caption(
    "Confronto tra l'allocazione target impostata in **Impostazioni Report** e "
    "quella attuale del portafoglio, con l'importo indicativo da muovere per riequilibrare."
)

settings = cfg.load_settings()

try:
    raw = pf.load_portfolio("data/portfolio.csv")
except Exception as e:
    st.error(f"Errore nel caricare il portafoglio: {e}")
    st.stop()

with st.spinner("Calcolo allocazione..."):
    enriched = pf.enrich_with_prices(raw)

table = rb.compute_rebalancing(
    enriched,
    settings["target_allocation"],
    tolerance_pct=settings["rebalance_tolerance_pct"],
)

if table.empty:
    st.info("Nessuna categoria con target o posizioni da confrontare.")
    st.stop()

fig = go.Figure()
fig.add_bar(name="Target", x=table["category"], y=table["target_pct"])
fig.add_bar(name="Attuale", x=table["category"], y=table["actual_pct"])
fig.update_layout(barmode="group", yaxis_title="% del portafoglio", title="Target vs Attuale")
st.plotly_chart(fig, use_container_width=True)

st.subheader("Dettaglio e azioni suggerite")
for _, row in table.iterrows():
    kind = "ok" if row["action"] == "In linea" else ("warn" if "Vendi" in row["action"] else "bad")
    cols = st.columns([2, 1, 1, 1, 2])
    cols[0].markdown(f"**{row['category']}**")
    cols[1].markdown(f"Target: {row['target_pct']:.1f}%")
    cols[2].markdown(f"Attuale: {row['actual_pct']:.1f}%")
    cols[3].markdown(f"Scarto: {row['drift_pct']:+.1f}%")
    action_html = badge(row["action"], kind)
    if row["amount_to_trade"] > 0:
        action_html += f" &nbsp; ~{row['amount_to_trade']:,.0f}"
    cols[4].markdown(action_html, unsafe_allow_html=True)

st.caption(
    f"Banda di tolleranza attuale: ±{settings['rebalance_tolerance_pct']}%. "
    "Sotto questa soglia lo scarto è considerato fisiologico e non segnalato come da correggere. "
    "Modifica target e tolleranza nella pagina **Impostazioni Report**."
)
