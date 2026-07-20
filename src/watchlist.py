"""
Watchlist (Preferiti): titoli monitorati anche se non (ancora) in
portafoglio, con un prezzo di riferimento/ingresso pianificato opzionale
per contestualizzare l'analisi tecnica (src/technical.py: entry_context)
e un algoritmo di segnali dedicato (src/alerts.py).
"""
from __future__ import annotations

import datetime as dt
import os

import pandas as pd

WATCHLIST_PATH = "data/watchlist.csv"
COLUMNS = ["ticker", "reference_price", "note", "added_date"]


def load_watchlist(path: str = WATCHLIST_PATH) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(path)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None
    df["ticker"] = df["ticker"].astype(str).str.strip()
    return df[COLUMNS]


def save_watchlist(df: pd.DataFrame, path: str = WATCHLIST_PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    df[COLUMNS].to_csv(path, index=False)


def add_ticker(df: pd.DataFrame, ticker: str, reference_price: float | None = None,
               note: str = "") -> pd.DataFrame:
    ticker = ticker.strip().upper()
    mask = df["ticker"].astype(str).str.upper() == ticker
    if mask.any():
        idx = df.index[mask][0]
        df = df.copy()
        df.loc[idx, "reference_price"] = reference_price
        df.loc[idx, "note"] = note
        return df
    new_row = {
        "ticker": ticker, "reference_price": reference_price, "note": note,
        "added_date": dt.date.today().isoformat(),
    }
    if df.empty:
        return pd.DataFrame([new_row])
    return pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)


def remove_ticker(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    ticker = ticker.strip().upper()
    return df[df["ticker"].astype(str).str.upper() != ticker].reset_index(drop=True)


def is_watched(df: pd.DataFrame, ticker: str) -> bool:
    if df.empty:
        return False
    return ticker.strip().upper() in df["ticker"].astype(str).str.upper().values


def reference_price_for(df: pd.DataFrame, ticker: str) -> float | None:
    ticker = ticker.strip().upper()
    mask = df["ticker"].astype(str).str.upper() == ticker
    if not mask.any():
        return None
    val = df.loc[mask, "reference_price"].iloc[0]
    try:
        return float(val) if val is not None and not pd.isna(val) else None
    except (TypeError, ValueError):
        return None
