"""AppTest sulla pagina Backtest: nessuna eccezione a runtime e presenza
dei guardrail anti-autoinganno richiesti dalla specifica.

I test non verificano solo che la pagina "non esploda", ma che i guardrail
ci siano davvero: sono il motivo per cui la pagina esiste. Una pagina di
backtest che mostra una bella curva senza intervallo di confidenza, senza
benchmark e senza il conteggio dei trade è peggio che inutile — è
persuasiva.
"""
import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src import data_provider as dp
from src import trading_universe as tu


def _synthetic_history(n=900, seed=11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    third = n // 3
    drift = np.concatenate([np.full(third, 0.0012), np.full(third, -0.0010),
                            np.full(n - 2 * third, 0.0009)])
    steps = rng.normal(drift, 0.011, n)
    close = 100 * np.exp(np.cumsum(steps))
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    high = np.maximum(close, np.roll(close, 1)) * (1 + rng.uniform(0.001, 0.008, n))
    low = np.minimum(close, np.roll(close, 1)) * (1 - rng.uniform(0.001, 0.008, n))
    open_ = close * (1 + rng.normal(0, 0.002, n))
    volume = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close,
                          "Volume": volume}, index=idx)


class _FakeTicker:
    def __init__(self, info):
        self.info = info


@pytest.fixture
def universo_con_un_titolo(tmp_path, monkeypatch):
    """Universo Trading su file temporaneo: i test non devono scrivere in
    data/, che è versionata."""
    path = tmp_path / "trading_universe.csv"
    path.write_text("ticker,note,tts_at_add,tts_date\nSYNTEST,test,75.0,2026-01-10\n",
                    encoding="utf-8")
    monkeypatch.setattr(tu, "TRADING_UNIVERSE_PATH", str(path))
    return path


@pytest.fixture(autouse=True)
def _mock_network(monkeypatch):
    hist = _synthetic_history()
    monkeypatch.setattr(dp, "get_history", lambda s, period="10y", interval="1d": hist)
    monkeypatch.setattr(dp, "get_ticker", lambda s: _FakeTicker({"currency": "EUR"}))
    yield


@pytest.fixture
def universo_vuoto(tmp_path, monkeypatch):
    path = tmp_path / "vuoto.csv"
    path.write_text("ticker,note,tts_at_add,tts_date\n", encoding="utf-8")
    monkeypatch.setattr(tu, "TRADING_UNIVERSE_PATH", str(path))
    return path


def test_pagina_si_ferma_con_universo_vuoto(universo_vuoto):
    """Senza universo non c'è nulla da testare: la pagina deve spiegarlo,
    non mostrare una configurazione inutilizzabile."""
    at = AppTest.from_file("pages/backtest.py")
    at.run(timeout=60)
    assert not at.exception
    text = "\n".join(i.value for i in at.info)
    assert "Universo Trading" in text


def test_pagina_configurazione_senza_eccezioni(universo_con_un_titolo):
    at = AppTest.from_file("pages/backtest.py")
    at.run(timeout=60)
    assert not at.exception

    keys = {w.key for w in at.selectbox} | {w.key for w in at.multiselect}
    assert "bt_symbols" in keys
    assert "bt_horizon" in keys


def test_orizzonte_lungo_non_e_offerto(universo_con_un_titolo):
    """Il lungo termine usa barre settimanali e non è supportato dal
    motore: non deve essere selezionabile, invece di fallire a runtime."""
    at = AppTest.from_file("pages/backtest.py")
    at.run(timeout=60)
    horizon = [s for s in at.selectbox if s.key == "bt_horizon"][0]
    assert "lungo" not in list(horizon.options)


def test_leva_dichiarata_disattivata(universo_con_un_titolo):
    at = AppTest.from_file("pages/backtest.py")
    at.run(timeout=60)
    text = "\n".join(c.value for c in at.caption)
    assert "disattivata" in text.lower()


def test_esecuzione_backtest_mostra_verdetto_e_guardrail(universo_con_un_titolo):
    at = AppTest.from_file("pages/backtest.py")
    at.run(timeout=120)
    assert not at.exception

    run_buttons = [b for b in at.button if b.key == "bt_run"]
    assert run_buttons, "pulsante di esecuzione non trovato"
    run_buttons[0].click().run(timeout=600)
    assert not at.exception

    markdown = "\n".join(m.value for m in at.markdown)
    captions = "\n".join(c.value for c in at.caption)
    infos = "\n".join(i.value for i in at.info)
    metric_labels = [m.label for m in at.metric]

    # Guardrail 8: verdetto in linguaggio piano.
    assert any(word in markdown for word in ("Edge", "Nessun edge"))

    # Guardrail 7: expectancy in R in evidenza.
    assert any("Expectancy per trade (R)" in label for label in metric_labels)

    # Guardrail 1: lordo accanto al netto.
    assert "Rendimento lordo" in " ".join(metric_labels)
    assert "Rendimento netto" in " ".join(metric_labels)

    # Guardrail 5: entrambi i benchmark obbligatori.
    joined = markdown + captions + infos + " ".join(metric_labels)
    assert "Buy-and-hold" in joined
    assert "casuale" in joined.lower()

    # Guardrail 6: costi e configurazioni provate dichiarati.
    assert "configurazioni provate" in captions

    # Guardrail 3: se ci sono trade, il win rate porta con sé Wilson e n.
    if any("Win rate" in label for label in metric_labels):
        assert "Wilson" in captions or "Wilson" in markdown
