"""AppTest sulla pagina Forward Paper Trading.

Verifica che la pagina regga i tre stati in cui si troverà davvero — mai
partita, avviata senza trade chiusi, con trade chiusi — e che i guardrail
onesti ci siano: il win rate sempre con l'intervallo di Wilson, il
campione dichiarato insufficiente sotto i 50 trade, e il cancello della
calibrazione che resta chiuso finché non ci sono i numeri.

Nessun test tocca la rete: storici, prezzi e percorsi dei dati sono
rediretti su file temporanei, come per le altre pagine — i test non
devono mai scrivere in `data/`, che è versionata.
"""
import datetime as dt

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src import data_provider as dp
from src import paper_store
from src import trading_universe as tu
from src import watchlist as wl
from src.engine import paper


class _FakeTicker:
    def __init__(self, info):
        self.info = info


def _history(n=600, seed=3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0008, 0.011, n)
    close = 100 * np.exp(np.cumsum(steps))
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    high = np.maximum(close, np.roll(close, 1)) * (1 + rng.uniform(0.001, 0.006, n))
    low = np.minimum(close, np.roll(close, 1)) * (1 - rng.uniform(0.001, 0.006, n))
    open_ = close * (1 + rng.normal(0, 0.002, n))
    volume = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close,
                          "Volume": volume}, index=idx)


@pytest.fixture(autouse=True)
def _isola_dati(tmp_path, monkeypatch):
    """Redirige tutti i percorsi dati su una cartella temporanea."""
    monkeypatch.setattr(paper_store, "OPEN_POSITIONS_PATH", str(tmp_path / "open.csv"))
    monkeypatch.setattr(paper_store, "CLOSED_TRADES_PATH", str(tmp_path / "closed.csv"))
    monkeypatch.setattr(paper_store, "META_PATH", str(tmp_path / "meta.json"))

    universe = tmp_path / "universe.csv"
    universe.write_text("ticker,note,tts_at_add,tts_date\nSYNTEST,test,75.0,2026-01-10\n",
                        encoding="utf-8")
    monkeypatch.setattr(tu, "TRADING_UNIVERSE_PATH", str(universe))

    watch = tmp_path / "watchlist.csv"
    watch.write_text("ticker,reference_price,note,added_date\n", encoding="utf-8")
    monkeypatch.setattr(wl, "WATCHLIST_PATH", str(watch))

    hist = _history()
    monkeypatch.setattr(dp, "get_history", lambda s, period="2y", interval="1d": hist)
    monkeypatch.setattr(dp, "get_current_price", lambda s: float(hist["Close"].iloc[-1]))
    monkeypatch.setattr(dp, "get_ticker", lambda s: _FakeTicker({"currency": "EUR"}))
    yield tmp_path


def _closed_trades(n: int, confidence: float = 77.0, win_rate: float = 0.5) -> pd.DataFrame:
    wins = int(round(n * win_rate))
    rows = []
    for i in range(n):
        vincente = i < wins
        rows.append({
            "symbol": "SYNTEST", "direction": "long",
            "signal_date": dt.date(2026, 1, 5), "entry_date": dt.date(2026, 1, 6),
            "entry_price": 100.0, "reference_open_price": 99.5,
            "exit_date": dt.date(2026, 1, 10) + dt.timedelta(days=i),
            "exit_price": 110.0 if vincente else 95.0,
            "exit_reason": "target" if vincente else "stop",
            "size": 10.0, "risk_per_unit": 5.0, "initial_risk_eur": 100.0,
            "confidence": confidence, "leverage": 1.0,
            "gross_pnl_eur": 100.0 if vincente else -100.0, "costs_eur": 2.0,
            "net_pnl_eur": 98.0 if vincente else -102.0,
            "gross_r": 1.0 if vincente else -1.0,
            "net_r": 0.98 if vincente else -1.02,
            "mae_r": 0.3, "mfe_r": 1.2, "bars_held": 5,
            "gapped_exit": False, "execution_delay_r": -0.1,
        })
    return pd.DataFrame(rows, columns=paper.CLOSED_TRADES_COLUMNS)


def _scrivi_stato(tmp_path, closed: pd.DataFrame):
    state = paper.PaperState(
        open_positions=pd.DataFrame(columns=paper.OPEN_POSITIONS_COLUMNS),
        closed_trades=closed, equity_eur=10_000.0,
        started_at="2026-01-01T15:00:00", last_run_at="2026-07-28T15:00:00")
    paper_store.save_state(state, paper.PaperConfig(frozen_at="2026-01-01T15:00:00"),
                            paper_store.OPEN_POSITIONS_PATH, paper_store.CLOSED_TRADES_PATH,
                            paper_store.META_PATH)


# ---------------------------------------------------------------------------

def test_pagina_senza_stato_non_va_in_eccezione():
    at = AppTest.from_file("pages/forward_paper.py")
    at.run(timeout=60)
    assert not at.exception

    testo = "\n".join(i.value for i in at.info)
    assert "non è ancora partito" in testo


def test_dichiara_l_esecuzione_al_prezzo_corrente():
    """La differenza di regola rispetto al backtest deve essere sempre
    dichiarata: senza, il confronto tra i due verrebbe letto male."""
    at = AppTest.from_file("pages/forward_paper.py")
    at.run(timeout=60)
    captions = "\n".join(c.value for c in at.caption)
    assert "prezzo corrente" in captions.lower()
    assert "backtest" in captions.lower()


def test_cancello_leva_chiuso_senza_trade():
    at = AppTest.from_file("pages/forward_paper.py")
    at.run(timeout=60)
    assert not at.exception
    warnings = "\n".join(w.value for w in at.warning)
    assert "leva resta a 1,0" in warnings.replace("×", "").replace("x", "")


def test_campione_piccolo_dichiarato_non_interpretabile(_isola_dati):
    _scrivi_stato(_isola_dati, _closed_trades(10))
    at = AppTest.from_file("pages/forward_paper.py")
    at.run(timeout=60)
    assert not at.exception

    errori = "\n".join(e.value for e in at.error)
    assert "sotto i 50" in errori


def test_win_rate_sempre_con_intervallo_di_wilson(_isola_dati):
    _scrivi_stato(_isola_dati, _closed_trades(60))
    at = AppTest.from_file("pages/forward_paper.py")
    at.run(timeout=60)
    assert not at.exception

    labels = [m.label for m in at.metric]
    assert "Win rate" in labels
    captions = "\n".join(c.value for c in at.caption)
    assert "Wilson" in captions


def test_costo_del_ritardo_di_esecuzione_mostrato(_isola_dati):
    _scrivi_stato(_isola_dati, _closed_trades(60))
    at = AppTest.from_file("pages/forward_paper.py")
    at.run(timeout=60)
    labels = " ".join(m.label for m in at.metric)
    assert "Impatto medio" in labels


def test_calibrazione_non_apre_il_cancello_su_una_sola_banda(_isola_dati):
    """60 trade tutti nella stessa banda: le altre restano vuote, quindi
    il cancello non deve aprirsi."""
    _scrivi_stato(_isola_dati, _closed_trades(60, confidence=77.0, win_rate=0.5))
    at = AppTest.from_file("pages/forward_paper.py")
    at.run(timeout=60)
    assert not at.exception
    warnings = "\n".join(w.value for w in at.warning)
    assert "Cancello non superato" in warnings
