"""AppTest sulla pagina Analisi Tecnica dopo le modifiche per la gerarchia
dei timeframe (Prompt_Cowork_Gerarchia_Orizzonti.md) e per il Technical
Tradeability Score (Prompt_Cowork_Technical_Tradeability_Score.md):
verifica che la pagina non vada in eccezione a runtime nelle quattro
sezioni (Portafoglio, Preferiti, Cerca, Idoneità al Trading) usando dati
storici sintetici (nessuna rete/yfinance richiesta) e mostri gli elementi
attesi di ciascuna."""
import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from src import data_provider as dp


def _make_synthetic_history(n=900, drift=0.0012, noise=0.006, start=100.0, seed=7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = rng.normal(drift, noise, n)
    close = start * np.exp(np.cumsum(steps))
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    base_high = np.maximum(close, np.roll(close, 1))
    base_low = np.minimum(close, np.roll(close, 1))
    high = base_high * (1 + rng.uniform(0.0005, 0.006, n))
    low = base_low * (1 - rng.uniform(0.0005, 0.006, n))
    open_ = close * (1 + rng.normal(0, 0.002, n))
    volume = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=idx)


class _FakeTicker:
    def __init__(self, info):
        self.info = info


@pytest.fixture(autouse=True)
def _mock_network(monkeypatch):
    synthetic = _make_synthetic_history()
    monkeypatch.setattr(dp, "get_history", lambda symbol, period="6mo", interval="1d": synthetic)
    monkeypatch.setattr(dp, "get_info", lambda symbol: {
        "name": symbol, "sector": "Test", "pe_ratio": 20.0,
        "week52_low": float(synthetic["Close"].min()), "week52_high": float(synthetic["Close"].max()),
    })
    monkeypatch.setattr(dp, "get_news", lambda symbol, limit=6: [])
    monkeypatch.setattr(dp, "get_ticker", lambda symbol: _FakeTicker({"currency": "EUR", "quoteType": "EQUITY"}))
    monkeypatch.setattr(dp, "get_earnings_dates", lambda symbol, limit=16: pd.DataFrame())
    yield


def test_pagina_analisi_tecnica_nessuna_eccezione_tab_portafoglio():
    at = AppTest.from_file("pages/analisi_tecnica.py")
    at.run(timeout=30)
    assert not at.exception


def test_pagina_analisi_tecnica_tab_cerca_mostra_sintesi_multi_orizzonte():
    at = AppTest.from_file("pages/analisi_tecnica.py")
    at.run(timeout=30)
    assert not at.exception

    text_ticker_inputs = [w for w in at.text_input if w.key == "search_ticker"]
    assert text_ticker_inputs, "campo di ricerca ticker non trovato"
    text_ticker_inputs[0].set_value("SYNTEST").run(timeout=30)
    assert not at.exception

    full_text = "\n".join(m.value for m in at.markdown) + "\n".join(c.value for c in at.caption)
    assert "Sintesi multi-orizzonte" in full_text
    assert "Allineamento tra orizzonti" in full_text


def test_pagina_analisi_tecnica_tab_idoneita_trading_nessuna_eccezione():
    at = AppTest.from_file("pages/analisi_tecnica.py")
    at.run(timeout=30)
    assert not at.exception

    full_text = "\n".join(m.value for m in at.markdown) + "\n".join(c.value for c in at.caption)
    assert "Idoneità al Trading" in "\n".join(t.label for t in at.tabs) or "idoneità" in full_text.lower()


def test_pagina_analisi_tecnica_calcolo_tradeability_senza_eccezioni():
    at = AppTest.from_file("pages/analisi_tecnica.py")
    at.run(timeout=30)
    assert not at.exception

    compute_buttons = [b for b in at.button if b.key == "tts_compute"]
    assert compute_buttons, "pulsante di calcolo Technical Tradeability Score non trovato"
    compute_buttons[0].click().run(timeout=60)
    assert not at.exception

    full_text = "\n".join(m.value for m in at.markdown) + "\n".join(c.value for c in at.caption)
    assert "Technical Tradeability Score" in full_text or "Dettaglio per titolo" in full_text
