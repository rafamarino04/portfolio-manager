"""Analisi tecnica dedicata: trend, medie mobili, bande di Bollinger,
oscillatori, pattern di candlestick e figure di prezzo, organizzata per
orizzonte temporale (breve/medio/lungo termine).

Metodologia basata su John J. Murphy, "Analisi tecnica dei mercati
finanziari" (si veda src/technical.py per il dettaglio delle regole)."""
import streamlit as st

from src import technical as tech
from src import technical_view as tv
from src.auth import check_password
from src.theme import apply_theme, badge, disclaimer

st.set_page_config(page_title="Analisi Tecnica", page_icon="\U0001F4C8", layout="wide")
apply_theme()

if not check_password():
    st.stop()

st.title("\U0001F4C8 Analisi Tecnica")
st.caption(
    "Trend, medie mobili, oscillatori, candlestick e figure di prezzo — "
    "letti automaticamente dal grafico, secondo le tecniche classiche di Murphy."
)

col_a, col_b = st.columns([2, 1])
with col_a:
    symbol = st.text_input(
        "Ticker (es. AAPL, ENI.MI, SWDA.MI, VWCE.DE)", value="AAPL", key="ta_symbol"
    ).strip().upper()
with col_b:
    horizon_label_to_key = {v["label"]: k for k, v in tech.HORIZONS.items()}
    chosen_label = st.selectbox(
        "Orizzonte temporale", list(horizon_label_to_key.keys()), index=1
    )
    horizon = horizon_label_to_key[chosen_label]

if not symbol:
    st.stop()

with st.spinner("Calcolo indicatori..."):
    snap = tech.technical_snapshot(symbol, horizon)

if snap is None:
    st.warning(
        "Dati storici insufficienti per questo ticker/orizzonte. "
        "Prova un altro ticker o un orizzonte diverso."
    )
    st.stop()

score = tech.technical_score(snap)

# --- Riepilogo -------------------------------------------------------------
trend_kind = {"rialzista": "ok", "ribassista": "bad", "laterale": "warn", "indeterminato": "info"}
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Prezzo", f"{snap['price']:,.2f}" if snap["price"] else "n/d")
c2.markdown(f"**Trend**<br>{badge(snap['trend'].capitalize(), trend_kind.get(snap['trend'], 'info'))}", unsafe_allow_html=True)
if score is not None:
    score_kind = "ok" if score > 0.15 else ("bad" if score < -0.15 else "warn")
    c3.markdown(f"**Punteggio tecnico**<br>{badge(f'{score:+.2f}', score_kind)}", unsafe_allow_html=True)
else:
    c3.markdown("**Punteggio tecnico**<br>n/d", unsafe_allow_html=True)
c4.metric("RSI", f"{snap['rsi']:.1f}" if snap["rsi"] is not None else "n/d", snap.get("rsi_signal") or "")
macd_val = snap["macd"].get("hist_val")
c5.metric("MACD (istogramma)", f"{macd_val:+.3f}" if macd_val is not None else "n/d")

st.markdown("")

# --- Grafico principale con overlay -----------------------------------------
fig = tv.build_price_chart(snap)
st.plotly_chart(fig, use_container_width=True, key="ta_price_chart")
st.caption(
    "Linee tratteggiate orizzontali: supporti (verde) e resistenze (rosso). "
    "Linee diagonali: trendline di supporto/resistenza sugli ultimi minimi/massimi. "
    "Frecce: pattern di candlestick rilevati."
)

# --- Oscillatori -------------------------------------------------------------
osc = tv.build_oscillator_chart(snap)
st.plotly_chart(osc, use_container_width=True, key="ta_osc_chart")

# --- Valutazione tecnica -----------------------------------------------------
st.subheader("Valutazione tecnica")
lines = tech.interpret(snap)
if lines:
    for line in lines:
        st.markdown(f"- {line}")
else:
    st.info("Nessun segnale rilevante al momento.")

# --- Confronto tra orizzonti --------------------------------------------------
with st.expander("Confronto rapido tra i tre orizzonti temporali"):
    st.caption("Ricalcola l'analisi sugli altri due orizzonti per un confronto veloce.")
    if st.button("Calcola confronto", key="ta_multi"):
        multi = tech.multi_horizon_analysis(symbol)
        cols = st.columns(3)
        for col, (h, res) in zip(cols, multi.items()):
            with col:
                st.markdown(f"**{tech.HORIZONS[h]['label']}**")
                if res["snapshot"] is None:
                    st.write("Dati insufficienti.")
                    continue
                s = res["score"]
                kind = "ok" if s is not None and s > 0.15 else ("bad" if s is not None and s < -0.15 else "warn")
                st.markdown(badge(f"Trend: {res['snapshot']['trend']}", trend_kind.get(res['snapshot']['trend'], 'info')), unsafe_allow_html=True)
                st.markdown(badge(f"Punteggio: {s:+.2f}" if s is not None else "n/d", kind), unsafe_allow_html=True)

disclaimer(
    "L'analisi tecnica descrive schemi statistici passati nei prezzi, non previsioni certe. "
    "I pattern grafici (doppio massimo/minimo, triangoli, candlestick) sono rilevati in modo "
    "automatico da regole geometriche e possono generare falsi segnali, specialmente in mercati "
    "laterali o poco liquidi. Non è consulenza finanziaria personalizzata."
)
