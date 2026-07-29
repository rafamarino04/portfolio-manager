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


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Rende conforme un DataFrame che arriva da fuori (ripristino da un
    file di backup caricato dall'utente): colonne mancanti aggiunte, ordine
    fissato, ticker normalizzati. Senza questo, un CSV con colonne diverse
    farebbe fallire `save_watchlist`, che seleziona `df[COLUMNS]`."""
    out = df.copy()
    for col in COLUMNS:
        if col not in out.columns:
            out[col] = None
    out = out[COLUMNS]
    out["ticker"] = out["ticker"].astype(str).str.strip().str.upper()
    return out


def load_watchlist(path: str | None = None) -> pd.DataFrame:
    """Il percorso si risolve a ogni chiamata, non come valore di default
    legato alla definizione della funzione: altrimenti ridefinire
    WATCHLIST_PATH (come fanno i test, per non dipendere dal contenuto di
    `data/`) non avrebbe alcun effetto."""
    path = path or WATCHLIST_PATH
    if not os.path.exists(path):
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(path)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None
    df["ticker"] = df["ticker"].astype(str).str.strip()
    return df[COLUMNS]


def save_watchlist(df: pd.DataFrame, path: str | None = None) -> None:
    path = path or WATCHLIST_PATH
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
