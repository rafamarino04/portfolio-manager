"""Mostra l'ultimo report settimanale generato automaticamente e
l'andamento storico del portafoglio nel tempo."""
import os

import pandas as pd
import plotly.express as px
import streamlit as st

from src.auth import check_password
from src.theme import apply_theme

st.set_page_config(page_title="Report Settimanale", page_icon="\U0001F4C4", layout="wide")
apply_theme()

if not check_password():
    st.stop()

st.title("\U0001F4C4 Report Settimanale")

REPORTS_DIR = "reports"
LATEST = os.path.join(REPORTS_DIR, "latest.md")
HISTORY = os.path.join(REPORTS_DIR, "history.csv")

if os.path.exists(HISTORY):
    hist = pd.read_csv(HISTORY)
    if not hist.empty:
        st.subheader("Andamento nel tempo")
        fig = px.line(hist, x="date", y="total_value", markers=True, title="Valore portafoglio")
        st.plotly_chart(fig, use_container_width=True)

if os.path.exists(LATEST):
    with open(LATEST) as f:
        st.markdown(f.read())
else:
    st.info(
        "Nessun report ancora generato. Il primo verra' creato automaticamente "
        "dal workflow settimanale su GitHub Actions (o lancialo a mano con "
        "`python scripts/generate_weekly_report.py`)."
    )

if os.path.isdir(REPORTS_DIR):
    past = sorted(
        [f for f in os.listdir(REPORTS_DIR) if f.endswith(".md") and f != "latest.md"],
        reverse=True,
    )
    if past:
        st.subheader("Report precedenti")
        choice = st.selectbox("Seleziona una data", past)
        with open(os.path.join(REPORTS_DIR, choice)) as f:
            st.markdown(f.read())
