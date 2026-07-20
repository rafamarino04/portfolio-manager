"""
Rendering condiviso dei grafici di analisi tecnica (candele + overlay,
oscillatori) a partire da uno snapshot di src/technical.py. Usato da
pages/4_Analisi_Tecnica.py (portafoglio/preferiti/ricerca) per tenere la
logica di disegno separata dalla logica della pagina.
"""
from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src import technical as tech
from src.theme import GOLD, GRAY, GREEN, NAVY, RED


def build_price_chart(snap: dict, title: str | None = None) -> go.Figure:
    """Candele giornaliere/settimanali con medie mobili, bande di
    Bollinger, trendlines, supporti/resistenze e marker delle candele
    riconosciute — disegnati direttamente sul grafico."""
    hist = snap["hist"]
    ma = snap["moving_averages"]
    boll = snap["bollinger"]
    params = tech.HORIZONS[snap["horizon"]]

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=hist.index, open=hist["Open"], high=hist["High"], low=hist["Low"], close=hist["Close"],
        name=snap["symbol"], increasing_line_color=GREEN, decreasing_line_color=RED,
    ))
    fig.add_trace(go.Scatter(x=hist.index, y=ma["fast"], name=f"Media {params['ma_fast']}",
                              line=dict(color=GOLD, width=1)))
    fig.add_trace(go.Scatter(x=hist.index, y=ma["mid"], name=f"Media {params['ma_mid']}",
                              line=dict(color=NAVY, width=1)))
    fig.add_trace(go.Scatter(x=hist.index, y=ma["slow"], name=f"Media {params['ma_slow']}",
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
    """RSI, Stocastico %K/%D e MACD in tre pannelli sovrapposti sull'asse
    temporale, con le soglie standard 70/30 e 80/20."""
    hist = snap["hist"]
    osc = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.06,
        subplot_titles=("RSI", "Stocastico %K/%D", "MACD"),
        row_heights=[0.33, 0.33, 0.34],
    )
    osc.add_trace(go.Scatter(x=hist.index, y=snap["rsi_series"], line=dict(color=NAVY, width=1.3), name="RSI"),
                  row=1, col=1)
    osc.add_hline(y=70, line=dict(color=RED, width=1, dash="dot"), row=1, col=1)
    osc.add_hline(y=30, line=dict(color=GREEN, width=1, dash="dot"), row=1, col=1)

    stoch = snap["stochastic"]
    osc.add_trace(go.Scatter(x=hist.index, y=stoch["k"], line=dict(color=GOLD, width=1.3), name="%K"), row=2, col=1)
    osc.add_trace(go.Scatter(x=hist.index, y=stoch["d"], line=dict(color=NAVY, width=1.3), name="%D"), row=2, col=1)
    osc.add_hline(y=80, line=dict(color=RED, width=1, dash="dot"), row=2, col=1)
    osc.add_hline(y=20, line=dict(color=GREEN, width=1, dash="dot"), row=2, col=1)

    macd_res = snap["macd"]
    hist_colors = ["#1E8E5A" if v is not None and v >= 0 else "#C0392B" for v in macd_res["hist"].fillna(0)]
    osc.add_trace(go.Bar(x=hist.index, y=macd_res["hist"], marker_color=hist_colors, name="Istogramma"),
                  row=3, col=1)
    osc.add_trace(go.Scatter(x=hist.index, y=macd_res["macd"], line=dict(color=NAVY, width=1.2), name="MACD"),
                  row=3, col=1)
    osc.add_trace(go.Scatter(x=hist.index, y=macd_res["signal"], line=dict(color=GOLD, width=1.2), name="Segnale"),
                  row=3, col=1)

    osc.update_layout(height=520, showlegend=False, margin=dict(t=40))
    return osc
