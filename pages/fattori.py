"""Fattori (§12 di Specifica_Analisi_Tecnica_Murphy.md): non il grafico
del singolo titolo, ma la classificazione dei titoli in portafoglio e
preferiti rispetto a un universo (+ peer di settore) sui 5 fattori
accademici con premio storico documentato — Value, Momentum, Quality,
Low Volatility, Size. Il ponte tra Analisi Tecnica (timing) e
Fundamental Score (qualità/valore di medio termine): selezione con
fondamentali+fattori, timing con la tecnica."""
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import data_provider as dp
from src import factors as fac
from src import portfolio as pf
from src import watchlist as wl
from src.portfolio import CASH_CATEGORY
from src.theme import GOLD, NAVY, apply_theme, disclaimer

apply_theme()

st.title("Fattori")
st.caption(
    "Value, Momentum, Quality, Low Volatility, Size: dove si posiziona ogni titolo rispetto a un "
    "universo di confronto (portafoglio + preferiti + peer di settore), non rispetto al proprio "
    "grafico. Serve alla **selezione** dei titoli, non al timing."
)
st.info(
    "**Da non confondere**: il *Momentum-fattore* qui è cross-sezionale e di medio termine (total "
    "return a 12-1 mesi tra titoli diversi — quali titoli comprare) — è un concetto diverso dagli "
    "*oscillatori di momentum* dell'Analisi Tecnica (RSI/Stocastico/MACD, rate-of-change di breve sul "
    "singolo titolo — quando entrare). Un titolo forte su fondamentali e fattori ma teso sulla tecnica "
    "(ipercomprato, resistenza vicina) è un 'aspetta il pullback'; forte su tutti e tre è un setup più pulito."
)

PORTFOLIO_PATH = "data/portfolio.csv"
WATCHLIST_PATH = "data/watchlist.csv"


def _build_radar(radar: dict, color: str = NAVY) -> go.Figure:
    values = radar["values"] + radar["values"][:1]
    axes = radar["axes"] + radar["axes"][:1]
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(r=values, theta=axes, fill="toself",
                                   line=dict(color=color), name=radar["symbol"]))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        showlegend=False, height=420, margin=dict(t=30, b=30),
    )
    return fig


# --- Universo: titoli in portafoglio + preferiti ---
positions = pd.DataFrame()
if os.path.exists(PORTFOLIO_PATH):
    positions = pf.load_portfolio(PORTFOLIO_PATH)
    if "category" in positions.columns:
        positions = positions[positions["category"] != CASH_CATEGORY]
portfolio_tickers = sorted(positions["ticker"].unique()) if not positions.empty else []

watch_df = wl.load_watchlist(WATCHLIST_PATH)
watchlist_tickers = sorted(watch_df["ticker"].unique()) if not watch_df.empty else []

target_tickers = sorted(set(portfolio_tickers) | set(watchlist_tickers))

if not target_tickers:
    st.info(
        "Nessun titolo in portafoglio o nei preferiti: aggiungine dal Registro Transazioni o "
        "dall'Analisi Tecnica per vedere qui la loro classificazione sui fattori."
    )
    st.stop()

c1, c2 = st.columns([2, 1])
with c1:
    st.caption(f"Titoli considerati: {', '.join(target_tickers)}")
with c2:
    weight_profile = st.selectbox("Profilo di peso", list(fac.TILT_PROFILES.keys()), key="factor_profile")

include_peers = st.checkbox("Includi peer di settore nell'universo di confronto (consigliato)",
                             value=True, key="factor_include_peers")

with st.spinner("Calcolo fattori sull'universo di confronto..."):
    sectors = []
    if include_peers:
        for t in target_tickers:
            sec = dp.get_info(t).get("sector")
            if sec:
                sectors.append(sec)
    universe_tickers = fac.build_universe(portfolio_tickers, watchlist_tickers,
                                           sectors=sectors, include_sector_peers=include_peers)
    report = fac.build_factor_report(target_tickers, universe_tickers,
                                      weight_profile=weight_profile, use_cache=True, sync_cache=False)

st.caption(f"Universo di confronto: {report['universe_size']} titoli · profilo pesi: {report['weight_profile']}.")

st.markdown("### Ranking")
st.caption("Percentile 0-100 per fattore (più alto = meglio, sempre relativo a questo universo) + composite pesato.")
rows = []
for r in report["ranking"]:
    rows.append({
        "Ticker": r["ticker"],
        "Composite": f"{r['composite']:.0f}" if r["composite"] is not None else "n/d",
        **{fac.FACTOR_LABELS_IT[f]: (f"{r.get(f):.0f}" if r.get(f) is not None else "n/d") for f in fac.FACTORS},
    })
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, key="factor_ranking_table")

st.markdown("### Dettaglio per titolo")
chosen = st.selectbox("Titolo", target_tickers, key="factor_detail_ticker")
percentiles = report["percentiles"].get(chosen, {})
metrics = report["metrics"].get(chosen, {})
composite = report["composites"].get(chosen)

d1, d2 = st.columns([1, 1])
with d1:
    radar = fac.radar_data(chosen, report["percentiles"])
    st.plotly_chart(_build_radar(radar, GOLD if (composite or 0) >= 60 else NAVY),
                     use_container_width=True, key="factor_radar_chart")
with d2:
    st.metric("Composite factor score", f"{composite:.0f}/100" if composite is not None else "n/d")
    for f in fac.FACTORS:
        p = percentiles.get(f)
        st.metric(fac.FACTOR_LABELS_IT[f], f"{p:.0f}° percentile" if p is not None else "n/d")

with st.expander("Metriche grezze (per verificare i percentili)"):
    label_map = {
        "earnings_yield": "Earnings yield (E/P) %", "fcf_yield": "FCF yield %",
        "ev_ebit_yield": "EV/EBIT yield %", "book_to_price": "Book-to-price %",
        "momentum_12_1": "Total return 12-1 mesi %", "momentum_vol_adj": "Momentum risk-adjusted",
        "roic": "ROIC %", "gross_profits_to_assets": "Gross profit/Attivo %",
        "accruals_ratio": "Accruals ratio %", "volatility_12m": "Volatilità 12m %",
        "beta": "Beta", "market_cap": "Capitalizzazione",
    }
    raw_rows = [(label_map.get(k, k), f"{v:,.2f}" if isinstance(v, (int, float)) else "n/d")
                for k, v in metrics.items()]
    st.dataframe(pd.DataFrame(raw_rows, columns=["Metrica", "Valore"]), use_container_width=True, hide_index=True)

disclaimer(
    "I fattori sono premi statistici di lungo periodo documentati in letteratura accademica (Fama-French, "
    "Novy-Marx, Asness/AQR, Jegadeesh-Titman) — non garanzie: possono sottoperformare per anni (il value "
    "2010-2020 è l'esempio classico). Il percentile è sempre relativo all'universo di confronto scelto: "
    "cambiando l'universo (es. escludendo i peer di settore) i percentili cambiano. Il composite è una "
    "media pesata dei fattori disponibili, ridistribuita se qualcuno manca per dati insufficienti. Non è "
    "consulenza finanziaria personalizzata né un segnale operativo."
)
