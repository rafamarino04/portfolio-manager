"""
Rendering condiviso dei grafici di analisi tecnica (candele + overlay,
oscillatori, volume/OBV) a partire da uno snapshot di src/technical.py.
Usato da pages/4_Analisi_Tecnica.py (portafoglio/preferiti/ricerca) per
tenere la logica di disegno separata dalla logica della pagina.
"""
from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src import technical as tech
from src.theme import GOLD, GRAY, GREEN, NAVY, RED


def build_price_chart(snap: dict, title: str | None = None) -> go.Figure:
    """Candele giornaliere/settimanali con medie mobili, bande di
    Bollinger, trendlines validate, supporti/resistenze (spessore
    proporzionale alla robustezza) e marker delle candele riconosciute —
    disegnati direttamente sul grafico."""
    hist = snap["hist"]
    ma = snap["moving_averages"]
    boll = snap["bollinger"]

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=hist.index, open=hist["Open"], high=hist["High"], low=hist["Low"], close=hist["Close"],
        name=snap["symbol"], increasing_line_color=GREEN, decreasing_line_color=RED,
    ))
    fig.add_trace(go.Scatter(x=hist.index, y=ma["fast"], name=f"Media {ma['fast_n']}",
                              line=dict(color=GOLD, width=1)))
    fig.add_trace(go.Scatter(x=hist.index, y=ma["mid"], name=f"Media {ma['mid_n']}",
                              line=dict(color=NAVY, width=1)))
    fig.add_trace(go.Scatter(x=hist.index, y=ma["slow"], name=f"Media {ma['slow_n']}",
                              line=dict(color=GRAY, width=1)))
    fig.add_trace(go.Scatter(x=hist.index, y=boll["upper"], name="Bollinger superiore",
                              line=dict(color=GRAY, width=1, dash="dot"), opacity=0.6))
    fig.add_trace(go.Scatter(x=hist.index, y=boll["lower"], name="Bollinger inferiore",
                              line=dict(color=GRAY, width=1, dash="dot"), opacity=0.6,
                              fill="tonexty", fillcolor="rgba(107,114,128,0.06)"))

    shapes, annotations = tech.chart_shapes(snap)
    fig.update_layout(
        title=title or f"{snap['symbol']} — {snap['horizon_label']}",
        xaxis_title="Data", yaxis_title="Prezzo",
        xaxis_rangeslider_visible=False,
        shapes=shapes, annotations=annotations,
        height=480, legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def build_oscillator_chart(snap: dict) -> go.Figure:
    """RSI, Stocastico %K/%D (se previsto per l'orizzonte), MACD e
    Volume/OBV in pannelli sovrapposti sull'asse temporale, con le soglie
    standard 70/30 e 80/20 (§5, §7 della specifica)."""
    hist = snap["hist"]
    has_stoch = snap.get("stochastic") is not None
    titles = ["RSI"] + (["Stocastico %K/%D"] if has_stoch else []) + ["MACD", "Volume / OBV"]
    n_rows = len(titles)
    heights = [1.0 / n_rows] * n_rows

    osc = make_subplots(
        rows=n_rows, cols=1, shared_xaxes=True, vertical_spacing=0.05,
        subplot_titles=tuple(titles), row_heights=heights,
    )

    row = 1
    osc.add_trace(go.Scatter(x=hist.index, y=snap["rsi_series"], line=dict(color=NAVY, width=1.3), name="RSI"),
                  row=row, col=1)
    osc.add_hline(y=70, line=dict(color=RED, width=1, dash="dot"), row=row, col=1)
    osc.add_hline(y=30, line=dict(color=GREEN, width=1, dash="dot"), row=row, col=1)
    row += 1

    if has_stoch:
        stoch = snap["stochastic"]
        osc.add_trace(go.Scatter(x=hist.index, y=stoch["k"], line=dict(color=GOLD, width=1.3), name="%K"), row=row, col=1)
        osc.add_trace(go.Scatter(x=hist.index, y=stoch["d"], line=dict(color=NAVY, width=1.3), name="%D"), row=row, col=1)
        osc.add_hline(y=80, line=dict(color=RED, width=1, dash="dot"), row=row, col=1)
        osc.add_hline(y=20, line=dict(color=GREEN, width=1, dash="dot"), row=row, col=1)
        row += 1

    macd_res = snap["macd"]
    hist_colors = ["#1E8E5A" if v is not None and v >= 0 else "#C0392B" for v in macd_res["hist"].fillna(0)]
    osc.add_trace(go.Bar(x=hist.index, y=macd_res["hist"], marker_color=hist_colors, name="Istogramma"),
                  row=row, col=1)
    osc.add_trace(go.Scatter(x=hist.index, y=macd_res["macd"], line=dict(color=NAVY, width=1.2), name="MACD"),
                  row=row, col=1)
    osc.add_trace(go.Scatter(x=hist.index, y=macd_res["signal"], line=dict(color=GOLD, width=1.2), name="Segnale"),
                  row=row, col=1)
    row += 1

    obv_series = snap.get("volume", {}).get("obv_series")
    if obv_series is not None:
        osc.add_trace(go.Scatter(x=hist.index, y=obv_series, line=dict(color="#4C7A9E", width=1.2), name="OBV"),
                      row=row, col=1)

    osc.update_layout(height=160 * n_rows + 60, showlegend=False, margin=dict(t=40))
    return osc
