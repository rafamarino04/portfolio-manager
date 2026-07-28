"""
Esecuzione schedulata del forward paper trading.

Lanciato da .github/workflows/paper_trading.yml a mercato aperto, nei
giorni feriali. Gira su GitHub Actions e non dentro l'app: il paper
trading deve avanzare anche quando l'app è chiusa, e lo stato deve
finire nel repository, che è l'unico posto permanente.

Perché a mercato aperto e non dopo la chiusura come gli alert: il fill
avviene al **prezzo corrente** nel momento in cui il segnale scatta
(scelta dichiarata, vedi src/engine/paper.py). A mercato chiuso non
esiste un prezzo a cui si sarebbe potuto eseguire, quindi un job serale
registrerebbe entrate impossibili.

Il segnale resta calcolato solo su barre **complete**: la seduta in corso
viene esclusa, perché il suo "close" è solo il prezzo dell'istante.

Uso:
    PYTHONPATH=. python scripts/run_paper_trading.py
"""
from __future__ import annotations

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import pandas as pd  # noqa: E402

from src import paper_store  # noqa: E402
from src import trading_universe as tu  # noqa: E402
from src import watchlist as wl  # noqa: E402
from src.engine import paper  # noqa: E402

UNIVERSE_PATH = os.path.join(BASE_DIR, "data", "trading_universe.csv")
WATCHLIST_PATH = os.path.join(BASE_DIR, "data", "watchlist.csv")


def _resolve(path: str) -> str:
    return os.path.join(BASE_DIR, path)


def collect_symbols() -> list[str]:
    """Universo Trading + Preferiti.

    L'unione è una scelta dichiarata: accumula trade più in fretta (il
    campione statistico è il vincolo stringente di un sistema daily), al
    prezzo di operare su una lista più ampia di quella usata dal backtest,
    il che rende il confronto tra i due un po' meno pulito."""
    symbols: set[str] = set()
    try:
        symbols.update(tu.tickers(tu.load_universe(UNIVERSE_PATH)))
    except Exception as exc:
        print(f"Universo Trading non leggibile: {exc}")
    try:
        watch = wl.load_watchlist(WATCHLIST_PATH)
        if not watch.empty:
            symbols.update(watch["ticker"].astype(str).str.strip().str.upper().tolist())
    except Exception as exc:
        print(f"Preferiti non leggibili: {exc}")
    return sorted(s for s in symbols if s and s.lower() != "nan")


def main() -> int:
    symbols = collect_symbols()
    if not symbols:
        print("Nessun titolo in Universo Trading o Preferiti: niente da fare.")
        return 0

    print(f"Titoli monitorati ({len(symbols)}): {', '.join(symbols)}")

    state = paper_store.load_state(_resolve(paper_store.OPEN_POSITIONS_PATH),
                                    _resolve(paper_store.CLOSED_TRADES_PATH),
                                    _resolve(paper_store.META_PATH))
    config = paper_store.load_config(_resolve(paper_store.META_PATH))

    if not config.frozen_at:
        # Primo avvio: i parametri si congelano ora e la data resta agli
        # atti. Serve a poter dire, più avanti, se il forward è stato
        # eseguito con regole fissate prima o ritoccate in corsa.
        import datetime as dt
        config.frozen_at = dt.datetime.now().isoformat(timespec="seconds")
        print(f"Parametri congelati il {config.frozen_at}")

    before_open = len(state.open_positions)
    before_closed = len(state.closed_trades)

    state, events = paper.step(symbols, state, config)

    for event in events:
        print(f"[{event.kind}] {event.symbol}: {event.message}")

    paper_store.save_state(state, config,
                            _resolve(paper_store.OPEN_POSITIONS_PATH),
                            _resolve(paper_store.CLOSED_TRADES_PATH),
                            _resolve(paper_store.META_PATH))

    print(f"Posizioni aperte: {before_open} -> {len(state.open_positions)}")
    print(f"Trade chiusi: {before_closed} -> {len(state.closed_trades)}")
    print(f"Equity: {state.equity_eur:,.2f} EUR")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
