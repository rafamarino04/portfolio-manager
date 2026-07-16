"""Segnali informativi sui titoli in portafoglio: posizione nel range a 52
settimane, target price degli analisti, momentum recente."""
import streamlit as st

from src import opportunities as opp
from src import portfolio as pf
from src.auth import check_password
from src.theme import apply_theme, disclaimer

st.set_page_config(page_title="Opportunità di Mercato", page_icon="🔎", layout="wide")
apply_theme()

if not check_password():
    st.stop()

st.title("🔎 Opportunità di Mercato")

disclaimer(
    "Questi sono <strong>indicatori statistici pubblici</strong> (range di prezzo, target degli "
    "analisti, momentum recente), non una raccomandazione di investimento personalizzata. "
    "Usali come spunto per approfondire, non come segnale da seguire da solo."
)
st.write("")

try:
    raw = pf.load_portfolio("data/portfolio.csv")
except Exception as e:
    st.error(f"Errore nel caricare il portafoglio: {e}")
    st.stop()

with st.spinner("Analisi dei titoli in portafoglio..."):
    enriched = pf.enrich_with_prices(raw)
    scan = opp.scan_holdings(enriched)

if scan.empty:
    st.info(
        "Nessun titolo quotato live da analizzare (le posizioni in liquidità o con prezzo "
        "manuale sono escluse da questa analisi)."
    )
    st.stop()

flagged = scan[scan["flags"] != "Nella norma"]
st.subheader(f"Da monitorare ({len(flagged)} su {len(scan)})")
if not flagged.empty:
    st.dataframe(
        flagged[[
            "ticker", "name", "price", "week52_position_pct",
            "momentum_1m_pct", "target_upside_pct", "recommendation", "flags",
        ]].style.format({
            "price": "{:.2f}", "week52_position_pct": "{:.0f}%",
            "momentum_1m_pct": "{:+.1f}%", "target_upside_pct": "{:+.1f}%",
        }, na_rep="n/d"),
        use_container_width=True, hide_index=True,
    )
else:
    st.info("Nessun titolo con segnali particolari al momento.")

st.divider()
st.subheader("Tutti i titoli analizzati")
st.dataframe(
    scan[[
        "ticker", "name", "price", "week52_position_pct", "momentum_1m_pct",
        "momentum_3m_pct", "pe_ratio", "dividend_yield", "target_mean_price",
        "target_upside_pct", "recommendation", "num_analysts", "flags",
    ]].style.format({
        "price": "{:.2f}", "week52_position_pct": "{:.0f}%",
        "momentum_1m_pct": "{:+.1f}%", "momentum_3m_pct": "{:+.1f}%",
        "pe_ratio": "{:.1f}", "dividend_yield": "{:.2f}%",
        "target_mean_price": "{:.2f}", "target_upside_pct": "{:+.1f}%",
    }, na_rep="n/d"),
    use_container_width=True, hide_index=True,
)

with st.expander("Come leggere questi indicatori"):
    st.markdown(
        "- **Posizione nel range 52 settimane**: 0% = al minimo dell'ultimo anno, "
        "100% = al massimo. Vicino ai minimi non significa automaticamente 'occasione', "
        "va capito il motivo del calo.\n"
        "- **Momentum 1m/3m**: variazione di prezzo negli ultimi 30/90 giorni.\n"
        "- **Target price analisti**: media delle stime di prezzo degli analisti che seguono "
        "il titolo (quando disponibile, copertura migliore su titoli grandi/USA).\n"
        "- **Raccomandazione**: consenso degli analisti (buy/hold/sell), quando disponibile."
    )
