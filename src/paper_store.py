"""
Persistenza dello stato del forward paper trading — src/paper_store.py

Lo stato del paper trading è l'unica cosa che il forward produce, e si
accumula lentamente: mesi per arrivare a un campione utile. Perderlo
significa ricominciare da zero, quindi qui la persistenza non è un
dettaglio ma il punto.

Tre file in `data/`, tutti versionabili nel repository:
  paper_open_positions.csv — posizioni virtuali aperte
  paper_closed_trades.csv  — registro dei trade chiusi (alimenta le
                             metriche e la calibrazione)
  paper_meta.json          — equity, date di avvio/ultima esecuzione e
                             i parametri congelati

Perché CSV/JSON committati e non un database: il job schedulato di GitHub
Actions può ricommittarli nel repository dopo ogni esecuzione, e il
repository è l'unico posto che sopravvive ai riavvii di Streamlit Cloud
(vedi `src/persistence.py` per il perché — è già costato la perdita dei
Preferiti e dell'Universo Trading).

I parametri congelati (`frozen_at`) vivono qui e non nella pagina proprio
perché devono essere fissati una volta sola: la specifica è esplicita nel
dire che ritoccarli mentre il forward gira lo trasforma nell'ennesimo
backtest ottimizzato, e la data di congelamento è ciò che permette di
accorgersene a posteriori.
"""
from __future__ import annotations

import json
import os

import pandas as pd

from src.engine import paper

OPEN_POSITIONS_PATH = "data/paper_open_positions.csv"
CLOSED_TRADES_PATH = "data/paper_closed_trades.csv"
META_PATH = "data/paper_meta.json"


def _read_csv(path: str, columns: list[str]) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame(columns=columns)
    try:
        df = pd.read_csv(path)
    except Exception:
        return pd.DataFrame(columns=columns)
    return df.reindex(columns=columns)


def load_state(open_path: str | None = None, closed_path: str | None = None,
                meta_path: str | None = None) -> paper.PaperState:
    """I percorsi si risolvono a ogni chiamata, non come valori di default
    legati alla definizione della funzione: altrimenti ridefinire le
    costanti del modulo (come fanno i test, per non scrivere dentro
    `data/` che è versionata) non avrebbe alcun effetto."""
    open_path = open_path or OPEN_POSITIONS_PATH
    closed_path = closed_path or CLOSED_TRADES_PATH
    meta_path = meta_path or META_PATH
    open_df = _read_csv(open_path, paper.OPEN_POSITIONS_COLUMNS)
    closed_df = _read_csv(closed_path, paper.CLOSED_TRADES_COLUMNS)
    meta = {}
    if os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            meta = {}
    return paper.state_from_frames(open_df, closed_df, meta)


def load_config(meta_path: str | None = None) -> paper.PaperConfig:
    meta_path = meta_path or META_PATH
    if not os.path.exists(meta_path):
        return paper.PaperConfig()
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        return paper.PaperConfig()
    return paper.config_from_dict(meta.get("config"))


def save_state(state: paper.PaperState, config: paper.PaperConfig,
                open_path: str | None = None, closed_path: str | None = None,
                meta_path: str | None = None) -> None:
    open_path = open_path or OPEN_POSITIONS_PATH
    closed_path = closed_path or CLOSED_TRADES_PATH
    meta_path = meta_path or META_PATH
    open_df, closed_df, meta = paper.state_to_frames(state)
    for path in (open_path, closed_path, meta_path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    open_df.to_csv(open_path, index=False)
    closed_df.to_csv(closed_path, index=False)
    meta["config"] = paper.config_to_dict(config)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2, default=str)


def is_started(state: paper.PaperState) -> bool:
    return bool(state.started_at)


def paths() -> list[str]:
    """I percorsi da committare dopo un'esecuzione del job."""
    return [OPEN_POSITIONS_PATH, CLOSED_TRADES_PATH, META_PATH]
