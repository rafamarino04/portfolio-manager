"""
Portfolio Manager — bootstrap. Un solo punto in cui si imposta la pagina
e si passa il cancello password, prima di costruire la navigazione: chi
non è autenticato vede solo la schermata di accesso, non la barra
laterale con le sezioni. Le sezioni vere vivono in pages/, qui si
definiscono solo titolo e ordine (nessuna emoji, nessun numero in coda
al nome del file da cui dipendere).
"""
import streamlit as st

from src.auth import check_password
from src.theme import apply_theme

st.set_page_config(page_title="Portfolio Manager", layout="wide")
apply_theme()

if not check_password():
    st.stop()

pages = [
    st.Page("pages/portafoglio_personale.py", title="Portafoglio Personale", default=True),
    st.Page("pages/analisi_tecnica.py", title="Analisi Tecnica"),
    st.Page("pages/analisi_fondamentale.py", title="Analisi Fondamentale"),
    st.Page("pages/fattori.py", title="Fattori"),
    st.Page("pages/impostazioni_alert_report.py", title="Impostazioni Alert e Report"),
]

st.navigation(pages).run()
