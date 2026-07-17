"""Analisi tecnica dedicata: trend, medie mobili, bande di Bollinger,
oscillatori, pattern di candlestick e figure di prezzo, organizzata per
orizzonte temporale (breve/medio/lungo termine).

Metodologia basata su John J. Murphy, "Analisi tecnica dei mercati
finanziari" (si veda src/technical.py per il dettaglio delle regole)."""
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from src import technical as tech
from src.auth import check_password
from src.theme import GOLD, GRAY, GREEN, NAVY, RED, apply_theme, badge, disclaimer

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
hist = snap["hist"]
ma = snap["moving_averages"]
boll = snap["bollinger"]

fig = go.Figure()
fig.add_trace(go.Candlestick(
    x=hist.index, open=hist["Open"], high=hist["High"], low=hist["Low"], close=hist["Close"],
    name=symbol, increasing_line_color=GREEN, decreasing_line_color=RED,
))
params = tech.HORIZONS[horizon]
fig.add_trace(go.Scatter(x=hist.index, y=ma["fast"], name=f"Media {params['ma_fast']}", line=dict(color=GOLD, width=1)))
fig.add_trace(go.Scatter(x=hist.index, y=ma["mid"], name=f"Media {params['ma_mid']}", line=dict(color=NAVY, width=1)))
fig.add_trace(go.Scatter(x=hist.index, y=ma["slow"], name=f"Media {params['ma_slow']}", line=dict(color=GRAY, width=1)))
fig.add_trace(go.Scatter(x=hist.index, y=boll["upper"], name="Bollinger superiore",
                          line=dict(color=GRAY, width=1, dash="dot"), opacity=0.6))
fig.add_trace(go.Scatter(x=hist.index, y=boll["lower"], name="Bollinger inferiore",
                          line=dict(color=GRAY, width=1, dash="dot"), opacity=0.6,
                          fill="tonexty", fillcolor="rgba(107,114,128,0.06)"))

shapes, annotations = tech.chart_shapes(snap)
fig.update_layout(
    title=f"{symbol} — {snap['horizon_label']}",
    xaxis_title="Data", yaxis_title="Prezzo",
    xaxis_rangeslider_visible=False,
    shapes=shapes, annotations=annotations,
    height=520, legend=dict(orientation="h", yanchor="bottom", y=1.02),
)
st.plotly_chart(fig, use_container_width=True)
st.caption(
    "Linee tratteggiate orizzontali: supporti (verde) e resistenze (rosso). "
    "Linee diagonali: trendline di supporto/resistenza sugli ultimi minimi/massimi. "
    "Frecce: pattern di candlestick rilevati."
)

# --- Oscillatori -------------------------------------------------------------
osc = make_subplots(
    rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.06,
    subplot_titles=("RSI", "Stocastico %K/%D", "MACD"),
    row_heights=[0.33, 0.33, 0.34],
)
osc.add_trace(go.Scatter(x=hist.index, y=snap["rsi_series"], line=dict(color=NAVY, width=1.3), name="RSI"), row=1, col=1)
osc.add_hline(y=70, line=dict(color=RED, width=1, dash="dot"), row=1, col=1)
osc.add_hline(y=30, line=dict(color=GREEN, width=1, dash="dot"), row=1, col=1)

stoch = snap["stochastic"]
osc.add_trace(go.Scatter(x=hist.index, y=stoch["k"], line=dict(color=GOLD, width=1.3), name="%K"), row=2, col=1)
osc.add_trace(go.Scatter(x=hist.index, y=stoch["d"], line=dict(color=NAVY, width=1.3), name="%D"), row=2, col=1)
osc.add_hline(y=80, line=dict(color=RED, width=1, dash="dot"), row=2, col=1)
osc.add_hline(y=20, line=dict(color=GREEN, width=1, dash="dot"), row=2, col=1)

macd_res = snap["macd"]
hist_colors = ["#1E8E5A" if v is not None and v >= 0 else "#C0392B" for v in macd_res["hist"].fillna(0)]
osc.add_trace(go.Bar(x=hist.index, y=macd_res["hist"], marker_color=hist_colors, name="Istogramma"), row=3, col=1)
osc.add_trace(go.Scatter(x=hist.index, y=macd_res["macd"], line=dict(color=NAVY, width=1.2), name="MACD"), row=3, col=1)
osc.add_trace(go.Scatter(x=hist.index, y=macd_res["signal"], line=dict(color=GOLD, width=1.2), name="Segnale"), row=3, col=1)

osc.update_layout(height=560, showlegend=False, margin=dict(t=40))
st.plotly_chart(osc, use_container_width=True)

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
