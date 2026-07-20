"""
Contesto settoriale: un ETF di settore (SPDR, gli stessi usati dal
mercato come proxy standard) per capire se il settore nel suo complesso
è in una fase favorevole, la forza relativa del titolo rispetto al
proprio settore, e un confronto diretto con eventuali concorrenti
indicati dall'utente (src/peers.py).

Nessuna dipendenza da src/fundamental.py: il confronto tra peer usa solo
src/data_provider, per evitare un'importazione circolare (fundamental.py
importa questo modulo per la sezione "Contesto settoriale").
"""
from __future__ import annotations

import pandas as pd

from src import data_provider as dp
from src import technical as tech

SECTOR_ETF_MAP = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Industrials": "XLI",
    "Energy": "XLE",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Basic Materials": "XLB",
    "Communication Services": "XLC",
}


def get_sector_etf(sector_name: str | None) -> str | None:
    if not sector_name:
        return None
    return SECTOR_ETF_MAP.get(sector_name.strip())


def _period_return(hist: pd.DataFrame, days: int) -> float | None:
    close = hist["Close"].dropna()
    if len(close) < 2:
        return None
    idx = max(0, len(close) - 1 - days)
    start, end = close.iloc[idx], close.iloc[-1]
    if not start:
        return None
    return (end / start - 1) * 100


def sector_snapshot(sector_name: str | None, period: str = "1y") -> dict | None:
    """Trend e rendimento recente del settore, usando l'ETF di settore
    come proxy e riusando il rilevatore di trend di src/technical.py."""
    etf = get_sector_etf(sector_name)
    if not etf:
        return None
    hist = dp.get_history(etf, period=period)
    if hist is None or hist.empty or len(hist) < 30:
        return None
    swing_highs, swing_lows = tech.find_swing_points(hist, order=4)
    trend = tech.detect_trend(swing_highs, swing_lows)
    return {
        "sector": sector_name, "etf": etf, "trend": trend,
        "return_1m": _period_return(hist, 21),
        "return_3m": _period_return(hist, 63),
        "return_1y": _period_return(hist, 252),
    }


def relative_strength(symbol: str, sector_name: str | None, period: str = "1y") -> dict | None:
    """Rendimento del titolo vs il proprio ETF di settore su più finestre
    temporali: positivo = il titolo batte il settore in quel periodo."""
    etf = get_sector_etf(sector_name)
    if not etf:
        return None
    stock_hist = dp.get_history(symbol, period=period)
    sector_hist = dp.get_history(etf, period=period)
    if stock_hist is None or stock_hist.empty or sector_hist is None or sector_hist.empty:
        return None

    out = {"etf": etf}
    for label, days in (("1m", 21), ("3m", 63), ("1y", 252)):
        stock_ret = _period_return(stock_hist, days)
        sector_ret = _period_return(sector_hist, days)
        out[f"stock_{label}"] = stock_ret
        out[f"sector_{label}"] = sector_ret
        out[f"relative_{label}"] = (
            (stock_ret - sector_ret) if stock_ret is not None and sector_ret is not None else None
        )
    return out


def peer_comparison(symbol: str, peers: list[str]) -> pd.DataFrame:
    """Titolo + concorrenti indicati, fianco a fianco sui multipli e
    ratio principali — solo dati da src/data_provider (no fundamental.py)."""
    tickers = [symbol] + [p for p in peers if p and p.upper() != symbol.upper()]
    rows = []
    for tk in tickers:
        info = dp.get_info(tk)
        pe = info.get("pe_ratio")
        growth = info.get("revenue_growth")
        peg = (pe / (growth * 100)) if pe and growth and growth > 0 else None
        roe = info.get("return_on_equity")
        margins = info.get("profit_margins")
        rows.append({
            "Ticker": tk,
            "P/E": pe,
            "Fwd P/E": info.get("forward_pe"),
            "P/B": info.get("price_to_book"),
            "ROE %": roe * 100 if roe is not None else None,
            "Margine %": margins * 100 if margins is not None else None,
            "Crescita ricavi %": growth * 100 if growth is not None else None,
            "PEG": peg,
            "Debito/Equity": info.get("debt_to_equity"),
        })
    return pd.DataFrame(rows)
