"""
Contesto macro: tassi, volatilità di mercato, forma della curva dei
rendimenti, e news di politica monetaria rilevanti. Sempre calcolato su
dati live — nessun valore fisso nel codice, perché tassi e contesto di
mercato cambiano continuamente e un valore scritto a mano diventerebbe
falso nel giro di settimane.
"""
from __future__ import annotations

import re

from src import data_provider as dp

MACRO_TICKERS = {
    "ten_year": "^TNX",   # rendimento treasury 10 anni (USA, proxy per i tassi globali)
    "three_month": "^IRX",  # rendimento treasury 3 mesi
    "vix": "^VIX",         # indice di volatilità/paura
}

POLICY_KEYWORDS = [
    "fed", "federal reserve", "fomc", "powell",
    "ecb", "bce", "lagarde",
    "interest rate", "tassi", "tasso", "rate hike", "rate cut",
    "inflation", "inflazione", "cpi", "pil", "gdp", "recession", "recessione",
]


def get_macro_snapshot() -> dict:
    out = {
        "ten_year_yield": None, "three_month_yield": None, "curve_spread": None,
        "vix": None, "vix_regime": None, "curve_regime": None,
    }
    ten_year = dp.get_current_price(MACRO_TICKERS["ten_year"])
    three_month = dp.get_current_price(MACRO_TICKERS["three_month"])
    vix = dp.get_current_price(MACRO_TICKERS["vix"])

    out["ten_year_yield"] = ten_year
    out["three_month_yield"] = three_month
    out["vix"] = vix

    if ten_year is not None and three_month is not None:
        spread = ten_year - three_month
        out["curve_spread"] = spread
        out["curve_regime"] = "invertita (segnale di cautela)" if spread < 0 else "normale"

    if vix is not None:
        if vix >= 25:
            out["vix_regime"] = "alta volatilità (risk-off)"
        elif vix <= 15:
            out["vix_regime"] = "bassa volatilità (risk-on)"
        else:
            out["vix_regime"] = "normale"

    return out


def macro_score(snapshot: dict) -> float | None:
    """Punteggio sintetico da -1 (contesto sfavorevole) a +1 (favorevole)."""
    parts = []
    if snapshot.get("curve_spread") is not None:
        parts.append(-1.0 if snapshot["curve_spread"] < 0 else 0.3)
    if snapshot.get("vix") is not None:
        vix = snapshot["vix"]
        if vix >= 25:
            parts.append(-1.0)
        elif vix <= 15:
            parts.append(0.5)
        else:
            parts.append(0.0)
    if not parts:
        return None
    return sum(parts) / len(parts)


def get_policy_news(limit: int = 6) -> list[dict]:
    """News generali filtrate per rilevanza di politica monetaria."""
    all_news = dp.get_market_news(limit=30)
    relevant = []
    pattern = re.compile("|".join(re.escape(k) for k in POLICY_KEYWORDS), re.IGNORECASE)
    for item in all_news:
        title = item.get("title") or ""
        if pattern.search(title):
            relevant.append(item)
        if len(relevant) >= limit:
            break
    return relevant


def summary_lines(snapshot: dict) -> list[str]:
    lines = []
    if snapshot.get("ten_year_yield") is not None:
        lines.append(f"Rendimento Treasury 10 anni: {snapshot['ten_year_yield']:.2f}%")
    if snapshot.get("curve_spread") is not None:
        lines.append(
            f"Curva dei rendimenti (10 anni - 3 mesi): {snapshot['curve_spread']:+.2f}% "
            f"— {snapshot['curve_regime']}"
        )
    if snapshot.get("vix") is not None:
        lines.append(f"VIX: {snapshot['vix']:.1f} — {snapshot['vix_regime']}")
    return lines
