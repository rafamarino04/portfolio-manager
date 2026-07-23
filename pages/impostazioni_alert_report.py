"""Impostazioni Alert e Report: cosa entra nel report periodico generato
automaticamente ogni lunedì (GitHub Actions) e, in futuro, le regole per
gli alert. L'allocazione target e il benchmark si impostano invece nella
pagina Portafoglio Personale, accanto a dove si usano."""
import datetime as dt

import streamlit as st

from src import github_sync
from src import report_config as cfg
from src.theme import apply_theme

apply_theme()

st.title("Impostazioni Alert e Report")
st.caption(
    "L'allocazione target e il benchmark si configurano nella pagina Portafoglio Personale, "
    "accanto ai grafici che li usano. Qui resta il contenuto del report periodico automatico — "
    "e, in futuro, le regole degli alert."
)

settings = cfg.load_settings()

st.subheader("Contenuto del report periodico")
selected_sections = []
for key, label in cfg.ALL_SECTIONS.items():
    checked = st.checkbox(label, value=key in settings["report_sections"], key=f"section_{key}")
    if checked:
        selected_sections.append(key)

period = st.selectbox(
    "Periodicità (informativo — la cadenza reale è impostata nel workflow GitHub Actions)",
    options=["weekly", "monthly"],
    index=["weekly", "monthly"].index(settings.get("report_period", "weekly")),
    format_func=lambda x: "Settimanale" if x == "weekly" else "Mensile",
)

st.divider()
with st.container(border=True):
    st.markdown("**Alert**")
    st.caption(
        "Non ancora configurabili da qui — arriveranno in una prossima iterazione (soglie di "
        "prezzo, eventi tecnici sui preferiti, scostamenti di ribilanciamento, notifiche invece "
        "del solo controllo manuale in-app)."
    )

st.divider()
if st.button("Salva impostazioni", type="primary"):
    new_settings = dict(settings)
    new_settings["report_sections"] = selected_sections
    new_settings["report_period"] = period
    cfg.save_settings(new_settings)
    st.success("Impostazioni salvate localmente.")

    if github_sync.is_configured():
        ok, msg = github_sync.push_csv(
            "data/settings.json", "data/settings.json",
            f"Aggiorna impostazioni - {dt.date.today().isoformat()}",
        )
        (st.success if ok else st.error)(msg)
    else:
        st.warning(
            "GitHub non collegato: questa modifica potrebbe andare persa al prossimo "
            "riavvio dell'app. Configura GITHUB_TOKEN e GITHUB_REPO nei secrets per "
            "renderla permanente (vedi README)."
        )
    st.rerun()
