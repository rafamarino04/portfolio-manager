"""Confronta il portafoglio con un benchmark di mercato e mostra quali
posizioni hanno contribuito di più al risultato complessivo."""
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src import benchmark as bm
from src import portfolio as pf
from src import report_config as cfg
from src.auth import check_password
from src.theme import apply_theme

st.set_page_config(page_title="Benchmark e Performance", page_icon="📊", layout="wide")
apply_theme()

if not check_password():
    st.stop()

st.title("📊 Benchmark e Performance")

settings = cfg.load_settings()
benchmark_ticker = settings["benchmark_ticker"]
benchmark_name = settings.get("benchmark_name", benchmark_ticker)
st.caption(
    f"Benchmark attuale: **{benchmark_name}** (`{benchmark_ticker}`) — cambialo in "
    "**Impostazioni Report**."
)

try:
    raw = pf.load_portfolio("data/portfolio.csv")
except Exception as e:
    st.error(f"Errore nel caricare il portafoglio: {e}")
    st.stop()

with st.spinner("Recupero dati..."):
    enriched = pf.enrich_with_prices(raw)
    summary = pf.portfolio_summary(enriched)

st.subheader("Da quando hai iniziato")
since_inception = bm.since_inception_comparison(raw, summary, benchmark_ticker)
if since_inception:
    c1, c2, c3 = st.columns(3)
    c1.metric("Rendimento portafoglio", f"{since_inception['portfolio_return_pct']:.2f}%")
    c2.metric(f"Rendimento {benchmark_name}", f"{since_inception['benchmark_return_pct']:.2f}%")
    c3.metric(
        "Differenza",
        f"{since_inception['difference_pct']:+.2f}%",
        delta=f"{since_inception['difference_pct']:+.2f}%",
    )
    st.caption(
        f"Periodo confrontato da {since_inception['start_date'].strftime('%d/%m/%Y')} ad oggi. "
        "Approssimazione: confronta il rendimento sul costo del portafoglio con quello del "
        "benchmark nello stesso periodo, senza considerare la tempistica esatta di ogni versamento."
    )
else:
    st.info("Dati insufficienti per calcolare il confronto (serve almeno una data di acquisto valida).")

st.divider()
st.subheader("Andamento tracciato nel tempo")
tracked = bm.tracked_history_vs_benchmark("reports/history.csv", benchmark_ticker)
if tracked is not None:
    fig = go.Figure()
    fig.add_scatter(x=tracked["date"], y=tracked["Portafoglio"], name="Portafoglio", mode="lines+markers")
    fig.add_scatter(x=tracked["date"], y=tracked["Benchmark"], name=benchmark_name, mode="lines+markers")
    fig.update_layout(title="Base 100 dal primo snapshot", yaxis_title="Indice (base 100)")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info(
        "Non ci sono ancora abbastanza report settimanali salvati per tracciare l'andamento nel "
        "tempo. Il grafico si arricchirà automaticamente ogni lunedì."
    )

st.divider()
st.subheader("Cosa ha contribuito di più al risultato")
attribution = bm.performance_attribution(enriched)
if not attribution.empty:
    fig2 = px.bar(
        attribution, x="ticker", y="pl_abs", color="pl_abs",
        color_continuous_scale=["#C0392B", "#E3E7EE", "#1E8E5A"],
        labels={"pl_abs": "P&L (valore)", "ticker": "Titolo"},
        title="Contributo al P&L per posizione",
    )
    st.plotly_chart(fig2, use_container_width=True)
    st.dataframe(
        attribution.style.format({
            "pl_abs": "{:,.2f}", "pl_pct": "{:.2f}%", "contribution_pct": "{:.1f}%",
        }),
        use_container_width=True, hide_index=True,
    )
else:
    st.info("Nessun dato sufficiente per l'attribuzione della performance.")
