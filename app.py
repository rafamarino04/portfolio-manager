"""
Portfolio Manager — bootstrap. Un solo punto in cui si imposta la pagina
e si passa il cancello password, prima di costruire la navigazione: chi
non è autenticato vede solo la schermata di accesso, non la barra
laterale con le sezioni. Le sezioni vere vivono in pages/, qui si
definiscono solo titolo e ordine (nessuna emoji, nessun numero in coda
al nome del file da cui dipendere).
"""
import streamlit as st

from src import persistence
from src.auth import check_password
from src.theme import apply_theme

st.set_page_config(page_title="Portfolio Manager", layout="wide")
apply_theme()

if not check_password():
    st.stop()

# Stato della persistenza, visibile su OGNI pagina prima di inserire dati.
# Streamlit Cloud ricostruisce l'app da GitHub a ogni riavvio e conserva
# solo ciò che è nel repository: senza il collegamento a GitHub tutto ciò
# che scrivi vive nella sola sessione corrente. Va saputo prima, non dopo
# aver perso dei dati.
persistence.render_global_status_banner()

pages = [
    st.Page("pages/portafoglio_personale.py", title="Portafoglio Personale", default=True),
    st.Page("pages/analisi_tecnica.py", title="Analisi Tecnica"),
    st.Page("pages/backtest.py", title="Backtest"),
    st.Page("pages/analisi_fondamentale.py", title="Analisi Fondamentale"),
    st.Page("pages/fattori.py", title="Fattori"),
    st.Page("pages/impostazioni_alert_report.py", title="Impostazioni Alert e Report"),
]

st.navigation(pages).run()
