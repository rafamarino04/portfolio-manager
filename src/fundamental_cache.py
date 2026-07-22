"""
Cache locale dei fondamentali dei titoli peer, usata dal Fundamental Score
per calcolare percentili sector-relative senza richiamare yfinance per
15-25 titoli ad ogni singola analisi (troppo lento e a rischio rate-limit
su Streamlit Community Cloud).

File JSON in data/fundamentals_cache.json, struttura:
    {
      "AAPL": {"fetched_at": "2026-07-20T10:00:00+00:00", "data": {...}},
      ...
    }

Uno snapshot per ticker resta valido STALE_AFTER_DAYS giorni (default 90,
coerente con la cadenza trimestrale dei bilanci): oltre quella soglia viene
ri-scaricato. Il cache viene anche sincronizzato su GitHub tramite
`github_sync.push_csv()` (generico nonostante il nome — legge qualunque
file come bytes) cosi' i redeploy di Streamlit Cloud non lo perdono.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Callable

CACHE_PATH = "data/fundamentals_cache.json"
STALE_AFTER_DAYS = 90


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_stale(fetched_at: str | None, max_age_days: int = STALE_AFTER_DAYS) -> bool:
    if not fetched_at:
        return True
    try:
        fetched = datetime.fromisoformat(fetched_at)
    except ValueError:
        return True
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - fetched > timedelta(days=max_age_days)


def load_cache(path: str = CACHE_PATH) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(cache: dict, path: str = CACHE_PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, default=str)


def get_or_fetch(
    ticker: str,
    fetch_fn: Callable[[str], dict],
    cache: dict,
    max_age_days: int = STALE_AFTER_DAYS,
) -> tuple[dict, bool]:
    """Ritorna (dati, cache_modificato). Se il ticker manca dal cache o lo
    snapshot e' scaduto, richiama fetch_fn(ticker) e aggiorna `cache` in-place
    (il chiamante resta responsabile di persisterlo con save_cache/
    persist_and_sync)."""
    ticker = ticker.strip().upper()
    entry = cache.get(ticker)
    if entry and not _is_stale(entry.get("fetched_at"), max_age_days):
        return entry.get("data", {}), False

    data = fetch_fn(ticker) or {}
    cache[ticker] = {"fetched_at": _now_iso(), "data": data}
    return data, True


def get_peer_group_data(
    tickers: list[str],
    fetch_fn: Callable[[str], dict],
    cache: dict | None = None,
    max_age_days: int = STALE_AFTER_DAYS,
) -> tuple[dict[str, dict], dict, bool]:
    """Recupera i dati per l'intero gruppo di peer, usando il cache dove
    possibile e richiamando fetch_fn solo per i ticker mancanti/scaduti.
    Ritorna (dati_per_ticker, cache_aggiornato, cambiato_qualcosa) — il
    chiamante decide se e quando persistere il cache aggiornato."""
    cache = cache if cache is not None else load_cache()
    results: dict[str, dict] = {}
    changed = False
    for t in tickers:
        data, updated = get_or_fetch(t, fetch_fn, cache, max_age_days)
        if data:
            results[t] = data
        changed = changed or updated
    return results, cache, changed


def persist_and_sync(cache: dict, path: str = CACHE_PATH, sync_to_github: bool = True) -> tuple[bool, str]:
    """Salva il cache in locale e, se configurato e richiesto, lo
    sincronizza su GitHub — senza, si perderebbe ad ogni redeploy di
    Streamlit Community Cloud (il filesystem non e' persistente tra deploy)."""
    save_cache(cache, path)
    if not sync_to_github:
        return True, "Salvato solo in locale."
    try:
        from src import github_sync
        if not github_sync.is_configured():
            return True, "Salvato solo in locale (GitHub non configurato)."
        return github_sync.push_csv(path, path, "Aggiorna cache fondamentali peer di settore")
    except Exception as e:
        return False, f"Salvato solo in locale — errore sync GitHub: {e}"
