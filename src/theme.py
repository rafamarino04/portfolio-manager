"""
Stile condiviso: palette scura ispirata ai terminali finanziari (sfondo
quasi nero, card a bordo sottile invece di ombre, cifre in monospace,
accento ambra), template Plotly coerente, badge a contorno. Un unico
posto da cambiare per aggiornare il look dell'intera app. Nessuna emoji:
gli unici indicatori visivi sono colore, tipografia e bordo.
"""
import plotly.io as pio
import streamlit as st

# --- Palette --------------------------------------------------------------
BG = "#05070A"            # sfondo pagina
SURFACE = "#0F1318"        # card, tabelle, expander
SURFACE_RAISED = "#171A1F"  # hover / stato attivo
BORDER = "#1F252B"
BORDER_STRONG = "#2B323A"

TEXT_PRIMARY = "#E7E9EC"
TEXT_SECONDARY = "#838B96"
TEXT_MUTED = "#5B6169"

ACCENT = "#E8A33D"          # ambra, l'unico accento "di richiamo"
BLUE = "#5AA9E6"
TEAL = "#3FA796"
PURPLE = "#9B7FD4"
CLAY = "#C97B5C"
GREEN = "#2FBF71"
RED = "#E5484D"

# Alias retro-compatibili (usati da moduli piu' vecchi)
NAVY = TEXT_PRIMARY
NAVY_LIGHT = SURFACE_RAISED
GOLD = ACCENT
GRAY = TEXT_SECONDARY
BG_SOFT = SURFACE

CATEGORY_COLORS = {
    "Azione": ACCENT,
    "ETF": BLUE,
    "Obbligazione": TEAL,
    "Fondo/SICAV": PURPLE,
    "Liquidità": TEXT_MUTED,
    "Altro": CLAY,
}

_PLOTLY_TEMPLATE = {
    "layout": {
        "colorway": [ACCENT, BLUE, TEAL, PURPLE, CLAY, GREEN, RED, TEXT_MUTED],
        "font": {"family": "Inter, -apple-system, sans-serif", "color": TEXT_PRIMARY},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "title": {"font": {"size": 16, "color": TEXT_PRIMARY}},
        "legend": {"bgcolor": "rgba(0,0,0,0)", "font": {"color": TEXT_SECONDARY}},
        "xaxis": {"gridcolor": BORDER, "linecolor": BORDER, "zerolinecolor": BORDER},
        "yaxis": {"gridcolor": BORDER, "linecolor": BORDER, "zerolinecolor": BORDER},
    }
}
pio.templates["portfolio_manager"] = _PLOTLY_TEMPLATE
pio.templates.default = "plotly_dark+portfolio_manager"


def apply_theme():
    st.markdown(
        f"""
        <style>
        .block-container {{ padding-top: 2rem; max-width: 1200px; }}

        html, body, [class*="css"] {{ font-family: 'Inter', -apple-system, sans-serif; }}

        h1 {{ font-weight: 600; font-size: 1.65rem; color: {TEXT_PRIMARY}; letter-spacing: -0.01em; }}
        h2, h3 {{ font-weight: 600; color: {TEXT_PRIMARY}; }}
        p, span, label {{ color: {TEXT_PRIMARY}; }}
        [data-testid="stCaptionContainer"], .stCaption {{ color: {TEXT_MUTED} !important; }}

        /* --- Metriche: card a bordo sottile, valore in monospace --- */
        [data-testid="stMetric"] {{
            background-color: {SURFACE};
            border: 1px solid {BORDER};
            border-radius: 10px;
            padding: 0.9rem 1.1rem 0.7rem 1.1rem;
            transition: border-color 0.15s ease;
        }}
        [data-testid="stMetric"]:hover {{ border-color: {BORDER_STRONG}; }}
        [data-testid="stMetricLabel"] {{
            color: {TEXT_SECONDARY}; font-weight: 500; font-size: 0.72rem;
            letter-spacing: 0.04em; text-transform: uppercase;
        }}
        [data-testid="stMetricValue"] {{
            color: {TEXT_PRIMARY}; font-family: 'JetBrains Mono', 'SFMono-Regular', ui-monospace, monospace;
            font-size: 1.35rem; font-weight: 500;
        }}
        [data-testid="stMetricDelta"] {{ font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 0.85rem; }}

        /* --- Badge a contorno, non a sfondo pieno --- */
        .pm-badge {{
            display: inline-block; padding: 0.15rem 0.65rem; border-radius: 999px;
            font-size: 0.74rem; font-weight: 500; margin-right: 0.3rem;
            border: 1px solid; letter-spacing: 0.01em;
        }}
        .pm-badge-ok {{ background: rgba(47,191,113,0.08); color: {GREEN}; border-color: rgba(47,191,113,0.35); }}
        .pm-badge-warn {{ background: rgba(232,163,61,0.08); color: {ACCENT}; border-color: rgba(232,163,61,0.35); }}
        .pm-badge-bad {{ background: rgba(229,72,77,0.08); color: {RED}; border-color: rgba(229,72,77,0.35); }}
        .pm-badge-info {{ background: rgba(90,169,230,0.08); color: {BLUE}; border-color: rgba(90,169,230,0.35); }}

        .pm-disclaimer {{
            background: {SURFACE}; border-left: 2px solid {ACCENT}; border-radius: 0 8px 8px 0;
            padding: 0.8rem 1.1rem; font-size: 0.86rem; color: {TEXT_SECONDARY}; margin-top: 1rem;
        }}

        /* --- Sidebar --- */
        [data-testid="stSidebar"] {{ background-color: {BG}; border-right: 1px solid {BORDER}; }}
        [data-testid="stSidebarNav"] a {{
            border-radius: 6px; color: {TEXT_SECONDARY} !important; font-size: 0.88rem;
            transition: background-color 0.15s ease, color 0.15s ease;
        }}
        [data-testid="stSidebarNav"] a:hover {{ background-color: {SURFACE}; color: {TEXT_PRIMARY} !important; }}
        [data-testid="stSidebarNav"] a[aria-current="page"] {{
            background-color: {SURFACE_RAISED}; color: {ACCENT} !important;
            border-left: 2px solid {ACCENT};
        }}

        /* --- Expander (le "tendine") --- */
        [data-testid="stExpander"] {{
            border: 1px solid {BORDER}; border-radius: 10px; background: {SURFACE};
            overflow: hidden;
        }}
        [data-testid="stExpander"] summary {{ transition: background-color 0.15s ease; }}
        [data-testid="stExpander"] summary:hover {{ background-color: {SURFACE_RAISED}; }}

        /* --- Container a bordo (st.container(border=True)) --- */
        [data-testid="stVerticalBlockBorderWrapper"] > div {{ border-color: {BORDER} !important; }}

        /* --- Bottoni: outline, hover con accento --- */
        .stButton button, .stDownloadButton button {{
            border: 1px solid {BORDER_STRONG}; border-radius: 8px; color: {TEXT_PRIMARY};
            transition: border-color 0.15s ease, color 0.15s ease;
        }}
        .stButton button:hover, .stDownloadButton button:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
        .stButton button[kind="primary"] {{ background: {ACCENT}; color: {BG}; border: none; }}
        .stButton button[kind="primary"]:hover {{ background: {ACCENT}; opacity: 0.9; }}

        /* --- Tabelle/dataframe: intestazione discreta --- */
        [data-testid="stDataFrame"] {{ border: 1px solid {BORDER}; border-radius: 8px; }}

        /* --- Tabs --- */
        [data-baseweb="tab-list"] {{ border-bottom: 1px solid {BORDER}; gap: 1.5rem; }}
        [data-baseweb="tab"] {{ color: {TEXT_SECONDARY}; }}
        [aria-selected="true"][data-baseweb="tab"] {{ color: {ACCENT} !important; }}
        [data-baseweb="tab-highlight"] {{ background-color: {ACCENT} !important; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def badge(text: str, kind: str = "info") -> str:
    return f'<span class="pm-badge pm-badge-{kind}">{text}</span>'


def disclaimer(text: str):
    st.markdown(f'<div class="pm-disclaimer">{text}</div>', unsafe_allow_html=True)
