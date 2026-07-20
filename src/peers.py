"""
Concorrenti: un piccolo elenco persistito di ticker "peer" per ogni
titolo, usato dall'Analisi Fondamentale per un confronto diretto di
multipli/margini/crescita più preciso del solo ETF di settore.
"""
from __future__ import annotations

import os

import pandas as pd

PEERS_PATH = "data/peers.csv"
COLUMNS = ["ticker", "peers"]


def load_peers(path: str = PEERS_PATH) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(path)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    return df[COLUMNS]


def save_peers(df: pd.DataFrame, path: str = PEERS_PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    df[COLUMNS].to_csv(path, index=False)


def get_peers(df: pd.DataFrame, ticker: str) -> list[str]:
    ticker = ticker.strip().upper()
    mask = df["ticker"] == ticker
    if not mask.any():
        return []
    raw = df.loc[mask, "peers"].iloc[0]
    if not raw or pd.isna(raw):
        return []
    return [p.strip().upper() for p in str(raw).split(",") if p.strip()]


def set_peers(df: pd.DataFrame, ticker: str, peers: list[str]) -> pd.DataFrame:
    ticker = ticker.strip().upper()
    peers_str = ", ".join(sorted({p.strip().upper() for p in peers if p.strip()}))
    mask = df["ticker"] == ticker
    if mask.any():
        idx = df.index[mask][0]
        df = df.copy()
        df.loc[idx, "peers"] = peers_str
        return df
    new_row = {"ticker": ticker, "peers": peers_str}
    if df.empty:
        return pd.DataFrame([new_row])
    return pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
