"""
Segnali informativi su ogni posizione: posizione nel range a 52 settimane,
target price medio degli analisti, momentum recente. Sono indicatori
statistici pubblici, non raccomandazioni di investimento personalizzate:
vanno letti come spunto per approfondire, non come un consiglio da seguire
alla lettera.
"""
from __future__ import annotations

import pandas as pd

from src import data_provider as dp


def _week52_position(price, low, high):
    if price is None or low is None or high is None or high == low:
        return None
    return (price - low) / (high - low) * 100


def _momentum_pct(symbol: str, days: int) -> float | None:
    hist = dp.get_history(symbol, period="6mo", interval="1d")
    if hist.empty or len(hist) < 2:
        return None
    cutoff = hist.index.max() - pd.Timedelta(days=days)
    past = hist[hist.index <= cutoff]
    if past.empty:
        return None
    past_price = past["Close"].iloc[-1]
    current_price = hist["Close"].iloc[-1]
    if not past_price:
        return None
    return (current_price - past_price) / past_price * 100


def scan_holdings(enriched: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in enriched.iterrows():
        if row.get("category") == "Liquidità" or row.get("price_source") != "live":
            continue  # segnali di mercato hanno senso solo per strumenti quotati live

        symbol = row["ticker"]
        info = dp.get_info(symbol)
        price = row.get("price")

        pos_52w = _week52_position(price, info.get("week52_low"), info.get("week52_high"))
        momentum_1m = _momentum_pct(symbol, 30)
        momentum_3m = _momentum_pct(symbol, 90)

        target = info.get("target_mean_price")
        upside_pct = ((target - price) / price * 100) if target and price else None

        flags = []
        if pos_52w is not None:
            if pos_52w <= 15:
                flags.append("Vicino ai minimi a 52 settimane")
            elif pos_52w >= 90:
                flags.append("Vicino ai massimi a 52 settimane")
        if upside_pct is not None and upside_pct >= 15:
            flags.append("Target analisti sopra il prezzo attuale")
        if upside_pct is not None and upside_pct <= -15:
            flags.append("Target analisti sotto il prezzo attuale")
        if momentum_1m is not None and momentum_1m <= -10:
            flags.append("Calo marcato nell'ultimo mese")
        if momentum_1m is not None and momentum_1m >= 10:
            flags.append("Rialzo marcato nell'ultimo mese")

        rows.append({
            "ticker": symbol,
            "name": info.get("name", symbol),
            "price": price,
            "week52_position_pct": pos_52w,
            "momentum_1m_pct": momentum_1m,
            "momentum_3m_pct": momentum_3m,
            "pe_ratio": info.get("pe_ratio"),
            "dividend_yield": (info.get("dividend_yield") or 0),
            "target_mean_price": target,
            "target_upside_pct": upside_pct,
            "recommendation": info.get("recommendation_key"),
            "num_analysts": info.get("num_analyst_opinions"),
            "flags": ", ".join(flags) if flags else "Nella norma",
        })
    return pd.DataFrame(rows)
