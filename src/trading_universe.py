"""
Universo Trading: la short-list dei titoli selezionati per il trading
tecnico, distinta dai Preferiti (src/watchlist.py).

La differenza non è cosmetica ed è il motivo per cui sono due liste
separate invece di un flag sulla stessa:
  - I **Preferiti** sono i titoli che segui/monitori per qualunque
    ragione (interesse, valutazione fondamentale, attesa di un prezzo).
  - L'**Universo Trading** è il sottoinsieme che hai giudicato
    STRUTTURALMENTE adatto a un sistema di trading tecnico
    trend-following, tipicamente dopo averlo vagliato col Technical
    Tradeability Score (src/tradeability.py).

Un titolo può stare in una lista, nell'altra, in entrambe o in nessuna:
un'azienda eccellente che gappa di continuo resta un buon Preferito e un
pessimo candidato di trading, e viceversa un ETF noioso ma liquidissimo e
pulito nei trend può meritare l'Universo Trading senza essere un
Preferito.

Oltre al ticker, ogni riga conserva:
  - `note`: perché l'hai inserito (campo libero).
  - `tts_at_add` + `tts_date`: il Technical Tradeability Score congelato
    al momento dell'inserimento, con la data in cui è stato congelato.
    La data è indispensabile perché il punteggio storico sia
    interpretabile: senza sapere a quando risale, confrontarlo col TTS
    attuale non direbbe nulla. La tradabilità cambia nel tempo — un
    titolo entrato a 78 che oggi vale 51 è esattamente il caso che
    questo confronto deve far emergere.
"""
from __future__ import annotations

import datetime as dt
import os

import pandas as pd

TRADING_UNIVERSE_PATH = "data/trading_universe.csv"
COLUMNS = ["ticker", "note", "tts_at_add", "tts_date"]


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Colonne sempre tutte presenti e con dtype `object` stabile.

    Il dtype object non è un dettaglio estetico: `tts_at_add` e `tts_date`
    restano vuote per i titoli inseriti senza punteggio congelato, e
    aggiungere una riga a un DataFrame con colonne tutte-NA fa reinferire
    i dtype a pandas (FutureWarning, comportamento destinato a cambiare).
    Fissando object a monte, inserimenti e aggiornamenti sono stabili
    qualunque combinazione di campi valorizzati ci sia."""
    out = df.copy()
    for col in COLUMNS:
        if col not in out.columns:
            out[col] = None
    return out[COLUMNS].astype(object)


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Versione pubblica di `_normalize`, per i dati che arrivano da fuori
    (es. il ripristino da un file di backup caricato dall'utente): un CSV
    con colonne mancanti o in ordine diverso va reso conforme prima di
    essere salvato, invece di far fallire la scrittura."""
    out = _normalize(df)
    out["ticker"] = out["ticker"].astype(str).str.strip().str.upper()
    return out


def load_universe(path: str | None = None) -> pd.DataFrame:
    """Il percorso si risolve a ogni chiamata, non come valore di default
    legato alla definizione della funzione: così i test possono redirigere
    `TRADING_UNIVERSE_PATH` su una cartella temporanea invece di scrivere
    dentro `data/`, che è versionata e finirebbe nei commit."""
    path = path or TRADING_UNIVERSE_PATH
    if not os.path.exists(path):
        return _normalize(pd.DataFrame(columns=COLUMNS))
    df = _normalize(pd.read_csv(path))
    df["ticker"] = df["ticker"].astype(str).str.strip()
    return df


def save_universe(df: pd.DataFrame, path: str | None = None) -> None:
    path = path or TRADING_UNIVERSE_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    df[COLUMNS].to_csv(path, index=False)


def add_ticker(df: pd.DataFrame, ticker: str, note: str = "",
               tts_at_add: float | None = None) -> pd.DataFrame:
    """Aggiunge (o aggiorna) un titolo nell'universo. Il TTS congelato si
    aggiorna SOLO se ne viene passato uno nuovo: rinominare una nota non
    deve cancellare silenziosamente il punteggio storico, che è l'unico
    riferimento per capire se la tradabilità è peggiorata dall'inserimento."""
    ticker = ticker.strip().upper()
    df = _normalize(df)
    mask = df["ticker"].astype(str).str.upper() == ticker
    today = dt.date.today().isoformat()

    if mask.any():
        idx = df.index[mask][0]
        df = df.copy()
        df.loc[idx, "note"] = note
        if tts_at_add is not None:
            df.loc[idx, "tts_at_add"] = float(tts_at_add)
            df.loc[idx, "tts_date"] = today
        return df

    new_row = {
        "ticker": ticker,
        "note": note,
        "tts_at_add": float(tts_at_add) if tts_at_add is not None else None,
        "tts_date": today if tts_at_add is not None else None,
    }
    if df.empty:
        return pd.DataFrame([new_row], columns=COLUMNS)
    # Inserimento via .loc su un indice normalizzato invece di pd.concat:
    # concatenare una riga con campi None produce colonne tutte-NA, su cui
    # pandas emette un FutureWarning per il cambio di inferenza dei dtype
    # (un titolo aggiunto senza TTS congelato ricade esattamente in quel caso).
    out = df.reset_index(drop=True).copy()
    out.loc[len(out)] = new_row
    return out[COLUMNS]


def remove_ticker(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    ticker = ticker.strip().upper()
    return df[df["ticker"].astype(str).str.upper() != ticker].reset_index(drop=True)


def is_in_universe(df: pd.DataFrame, ticker: str) -> bool:
    if df.empty:
        return False
    return ticker.strip().upper() in df["ticker"].astype(str).str.upper().values


def _field_for(df: pd.DataFrame, ticker: str, column: str):
    if df.empty:
        return None
    mask = df["ticker"].astype(str).str.upper() == ticker.strip().upper()
    if not mask.any():
        return None
    val = df.loc[mask, column].iloc[0]
    return None if val is None or pd.isna(val) else val


def note_for(df: pd.DataFrame, ticker: str) -> str | None:
    val = _field_for(df, ticker, "note")
    return str(val) if val is not None else None


def tts_at_add_for(df: pd.DataFrame, ticker: str) -> float | None:
    val = _field_for(df, ticker, "tts_at_add")
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def tts_date_for(df: pd.DataFrame, ticker: str) -> str | None:
    val = _field_for(df, ticker, "tts_date")
    return str(val) if val is not None else None


def tickers(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return []
    return sorted(df["ticker"].astype(str).str.upper().unique())
