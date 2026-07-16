"""Configura allocazione target, tolleranza di ribilanciamento, benchmark
e sezioni incluse nel report periodico — senza toccare codice."""
import datetime as dt

import streamlit as st

from src import github_sync
from src import rebalancing as rb
from src import report_config as cfg
from src.auth import check_password
from src.portfolio import CATEGORIES
from src.theme import apply_theme

st.set_page_config(page_title="Impostazioni Report", page_icon="⚙️", layout="wide")
apply_theme()

if not check_password():
    st.stop()

st.title("⚙️ Impostazioni Report")

settings = cfg.load_settings()

st.subheader("Allocazione target (per ribilanciamento)")
st.caption("Deve sommare a 100%. Usata nella pagina Ribilanciamento per calcolare gli scarti.")

new_target = {}
cols = st.columns(len(CATEGORIES))
for col, cat in zip(cols, CATEGORIES):
    new_target[cat] = col.number_input(
        cat, min_value=0, max_value=100,
        value=int(settings["target_allocation"].get(cat, 0)),
        step=1, key=f"target_{cat}",
    )

total = sum(new_target.values())
if total == 100:
    st.success(f"Totale: {total}%")
else:
    st.warning(f"Totale: {total}% — deve fare 100% prima di salvare.")

tolerance = st.slider(
    "Banda di tolleranza per il ribilanciamento (%)",
    min_value=1, max_value=20, value=int(settings["rebalance_tolerance_pct"]),
)

st.divider()
st.subheader("Benchmark di riferimento")
preset_labels = [f"{v} ({k})" for k, v in cfg.BENCHMARK_PRESETS.items()]
preset_keys = list(cfg.BENCHMARK_PRESETS.keys())
current_idx = preset_keys.index(settings["benchmark_ticker"]) if settings["benchmark_ticker"] in preset_keys else None

choice = st.selectbox(
    "Scegli un benchmark comune, o inseriscine uno personalizzato sotto",
    options=["(personalizzato)"] + preset_labels,
    index=(current_idx + 1) if current_idx is not None else 0,
)
if choice == "(personalizzato)":
    custom_ticker = st.text_input("Ticker benchmark personalizzato", value=settings["benchmark_ticker"])
    benchmark_ticker = custom_ticker.strip()
    benchmark_name = benchmark_ticker
else:
    benchmark_ticker = preset_keys[preset_labels.index(choice)]
    benchmark_name = cfg.BENCHMARK_PRESETS[benchmark_ticker]

st.divider()
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
if st.button("💾 Salva impostazioni", type="primary"):
    if total != 100:
        st.error("L'allocazione target deve sommare a 100% prima di salvare.")
    elif not benchmark_ticker:
        st.error("Inserisci un ticker benchmark valido.")
    else:
        new_settings = {
            "target_allocation": new_target,
            "rebalance_tolerance_pct": tolerance,
            "benchmark_ticker": benchmark_ticker,
            "benchmark_name": benchmark_name,
            "report_sections": selected_sections,
            "report_period": period,
        }
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
