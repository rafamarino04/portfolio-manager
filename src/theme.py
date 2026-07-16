"""
Stile condiviso: palette colori, CSS per le card, template Plotly coerente
su tutte le pagine. Un unico posto da cambiare per aggiornare il look
dell'intera app.
"""
import plotly.io as pio
import streamlit as st

NAVY = "#1B2A4A"
NAVY_LIGHT = "#2E4266"
GOLD = "#C9A227"
GREEN = "#1E8E5A"
RED = "#C0392B"
GRAY = "#6B7280"
BG_SOFT = "#F4F6F9"

CATEGORY_COLORS = {
    "Azione": NAVY,
    "ETF": GOLD,
    "Obbligazione": "#4C7A9E",
    "Fondo/SICAV": "#8E6FA8",
    "Liquidità": GRAY,
    "Altro": "#B08968",
}

_PLOTLY_TEMPLATE = {
    "layout": {
        "colorway": [NAVY, GOLD, "#4C7A9E", "#8E6FA8", GREEN, RED, GRAY, "#B08968"],
        "font": {"family": "Source Sans Pro, sans-serif", "color": NAVY},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "title": {"font": {"size": 18, "color": NAVY}},
        "legend": {"bgcolor": "rgba(0,0,0,0)"},
    }
}
pio.templates["portfolio_manager"] = _PLOTLY_TEMPLATE
pio.templates.default = "plotly+portfolio_manager"


def apply_theme():
    st.markdown(
        f"""
        <style>
        .block-container {{ padding-top: 2rem; }}

        [data-testid="stMetric"] {{
            background-color: {BG_SOFT};
            border: 1px solid #E3E7EE;
            border-left: 4px solid {NAVY};
            border-radius: 8px;
            padding: 1rem 1rem 0.6rem 1rem;
        }}
        [data-testid="stMetricLabel"] {{ color: {GRAY}; font-weight: 600; }}
        [data-testid="stMetricValue"] {{ color: {NAVY}; }}

        h1, h2, h3 {{ color: {NAVY}; }}

        .pm-badge {{
            display: inline-block; padding: 0.15rem 0.6rem; border-radius: 999px;
            font-size: 0.78rem; font-weight: 600; margin-right: 0.3rem;
        }}
        .pm-badge-ok {{ background: #E3F3EB; color: {GREEN}; }}
        .pm-badge-warn {{ background: #FBEFDD; color: #8A6116; }}
        .pm-badge-bad {{ background: #FBE7E4; color: {RED}; }}
        .pm-badge-info {{ background: #E6ECF5; color: {NAVY}; }}

        .pm-disclaimer {{
            background: {BG_SOFT}; border-left: 4px solid {GOLD};
            padding: 0.75rem 1rem; border-radius: 6px; font-size: 0.9rem; color: {GRAY};
        }}

        [data-testid="stSidebar"] {{ background-color: {NAVY}; }}
        [data-testid="stSidebar"] * {{ color: #F4F6F9 !important; }}
        [data-testid="stSidebar"] [data-testid="stMetric"] {{ background-color: {NAVY_LIGHT}; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def badge(text: str, kind: str = "info") -> str:
    return f'<span class="pm-badge pm-badge-{kind}">{text}</span>'


def disclaimer(text: str):
    st.markdown(f'<div class="pm-disclaimer">{text}</div>', unsafe_allow_html=True)
