"""Config condivisa dei test: repo root su sys.path (stesso schema di
`PYTHONPATH=.` usato dagli script in scripts/), così i test girano anche
senza impostare la variabile d'ambiente a mano."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import pytest  # noqa: E402

from src.engine import strategies as _strategies  # noqa: E402

FAKE_STRATEGY_KEY = "test_fake"


@pytest.fixture
def strategia_finta(monkeypatch):
    """Registra una strategia di comodo e la rende quella predefinita.

    Serve ai test del **motore**, che devono verificare esecuzione, sizing
    e contabilità con segnali costruiti a mano perché l'esito sia
    calcolabile a mente. Prima i test aggiravano il problema
    monkeypatchando `signals.generate_signal`, cioè bucando l'unica
    strategia esistente; ora che le strategie passano da un registro, la
    via pulita è registrarne una.

    Uso:
        def test_x(strategia_finta):
            strategia_finta(mia_funzione_segnale, warmup=5)
    """
    def _registra(generate_fn, warmup: int = 5, allowed_currencies=None):
        strategia = _strategies.Strategy(
            key=FAKE_STRATEGY_KEY, label="Strategia di test",
            description="Segnali costruiti a mano per i test del motore.",
            generate=lambda symbol, hist, horizon: generate_fn(symbol, hist, horizon=horizon),
            warmup_bars=lambda horizon: warmup,
            allowed_currencies=allowed_currencies,
        )
        registro = dict(_strategies.STRATEGIES)
        registro[FAKE_STRATEGY_KEY] = strategia
        monkeypatch.setattr(_strategies, "STRATEGIES", registro)
        return FAKE_STRATEGY_KEY

    return _registra
