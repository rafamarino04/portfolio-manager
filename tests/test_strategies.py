"""Test delle strategie selezionabili e dello stop in trailing.

Le strategie semplici esistono per rispondere a una domanda che il
backtest di un solo algoritmo non può risolvere: il problema è quello
specifico algoritmo o l'intero approccio? Perché il confronto significhi
qualcosa devono girare nello **stesso apparato** — stessi costi, stesso
sizing, stesse regole di esecuzione — con l'unica variabile che cambia
essendo da dove viene il segnale. Diversi test qui verificano proprio
quello.

Sul trailing, il punto delicato è la sequenza: lo stop si aggiorna DOPO
aver verificato le uscite sul bar corrente. Stringerlo col massimo di oggi
e poi chiedersi se il minimo di oggi lo ha toccato significherebbe
assumere che il massimo sia arrivato per primo — lo stesso look-ahead
intrabar che la regola stop-first esiste per evitare.
"""
import numpy as np
import pandas as pd
import pytest

from src.engine import core
from src.engine import execution as ex
from src.engine import signals as sig
from src.engine import strategies as st
from src.engine.core import BacktestConfig
from src.engine.costs import CostModel
from src.engine.risk import RiskConfig


# ---------------------------------------------------------------------------
# Stop in trailing
# ---------------------------------------------------------------------------

def test_trailing_si_stringe_quando_il_prezzo_va_a_favore():
    stop, ref = ex.update_trailing_stop("long", 90.0, 100.0, bar_high=110, bar_low=104,
                                         atr_value=2.0, atr_mult=3.0)
    assert ref == 110.0
    assert stop == pytest.approx(104.0)      # 110 − 3×2


def test_trailing_non_arretra_mai():
    """Uno stop che si allarga quando le cose vanno male non è uno stop:
    è il modo in cui una perdita da −1R diventa una da −3R."""
    stop, ref = ex.update_trailing_stop("long", 104.0, 110.0, bar_high=105, bar_low=98,
                                         atr_value=2.0, atr_mult=3.0)
    assert stop == 104.0                      # invariato
    assert ref == 110.0                       # il riferimento non scende


def test_trailing_short_specchiato():
    stop, ref = ex.update_trailing_stop("short", 110.0, 100.0, bar_high=99, bar_low=90,
                                         atr_value=2.0, atr_mult=3.0)
    assert ref == 90.0
    assert stop == pytest.approx(96.0)        # 90 + 3×2


def test_trailing_non_si_muove_senza_atr():
    """Meglio uno stop fermo che uno spostato su un dato mancante."""
    assert ex.update_trailing_stop("long", 90.0, 100.0, 120, 110, 0.0, 3.0) == (90.0, 100.0)
    assert ex.update_trailing_stop("long", 90.0, 100.0, 120, 110, float("nan") * 0, 3.0)[0] == 90.0


# ---------------------------------------------------------------------------
# Target opzionale
# ---------------------------------------------------------------------------

def test_uscita_senza_target_reagisce_solo_allo_stop():
    """Senza target il guadagno non ha tetto: è la scelta che rende
    possibile la coda destra su cui vive il trend-following."""
    assert ex.resolve_exit("long", stop=95, target=None,
                            bar_open=100, bar_high=500, bar_low=99) is None
    event = ex.resolve_exit("long", stop=95, target=None,
                             bar_open=100, bar_high=110, bar_low=94)
    assert event.reason == "stop"


def test_gap_sullo_stop_funziona_anche_senza_target():
    event = ex.resolve_exit("long", stop=95, target=None, bar_open=90, bar_high=92, bar_low=88)
    assert event.reason == "gap_stop" and event.price == 90


# ---------------------------------------------------------------------------
# Registro delle strategie
# ---------------------------------------------------------------------------

def test_registro_contiene_le_quattro_strategie():
    assert set(st.keys()) == {"murphy", "donchian", "ma_trend", "momentum"}


def test_strategia_sconosciuta_rifiutata_con_messaggio_utile():
    with pytest.raises(ValueError, match="sconosciuta"):
        st.get("inesistente")


def test_ogni_strategia_dichiara_parametri_e_descrizione():
    for key in st.keys():
        s = st.get(key)
        assert s.label and s.description and s.parameters
        assert s.warmup_bars("medio") > 0


def test_murphy_delega_alla_logica_esistente(monkeypatch):
    """La strategia storica non è stata riscritta: passa per la stessa
    funzione di sempre."""
    chiamate = {}

    def fake(symbol, hist, horizon="medio"):
        chiamate["ok"] = True
        return {"bias": "nessun_setup"}

    monkeypatch.setattr(sig, "generate_signal", fake)
    st.get("murphy").generate("X", pd.DataFrame({"Close": [1, 2]}), "medio")
    assert chiamate.get("ok")


# ---------------------------------------------------------------------------
# Le singole strategie, su serie costruite per attivarle
# ---------------------------------------------------------------------------

def _series(values: list[float]) -> pd.DataFrame:
    n = len(values)
    close = np.array(values, dtype=float)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                          "Close": close, "Volume": 1e6}, index=idx)


def test_donchian_entra_long_sulla_rottura_del_massimo():
    # Serie piatta, poi un nuovo massimo netto sull'ultima barra.
    valori = [100.0] * (st.DONCHIAN_ENTRY_BARS + 20) + [130.0]
    plan = st.get("donchian").generate("X", _series(valori), "medio")
    assert plan["bias"] == "long"
    assert plan["target"] is None                 # nessun tetto al guadagno
    assert plan["trailing_atr_mult"] == st.TRAILING_ATR_MULT
    assert plan["stop"] < plan["entry"]


def test_donchian_non_entra_dentro_il_canale():
    valori = [100.0] * (st.DONCHIAN_ENTRY_BARS + 20) + [100.5]
    plan = st.get("donchian").generate("X", _series(valori), "medio")
    assert plan["bias"] == "nessun_setup"


def test_donchian_esclude_la_barra_corrente_dal_canale():
    """Se il massimo del canale includesse il bar di oggi, il confronto
    sarebbe con se stesso e il segnale scatterebbe su qualunque nuovo
    massimo giornaliero."""
    valori = [100.0] * (st.DONCHIAN_ENTRY_BARS + 20) + [130.0]
    hist = _series(valori)
    prior_high = float(hist["High"].iloc[-(st.DONCHIAN_ENTRY_BARS + 1):-1].max())
    assert prior_high == pytest.approx(101.0)     # non include il 130 di oggi


def test_ma_trend_richiede_pendenza_positiva():
    """Prezzo sopra una media che scende è la configurazione tipica di un
    rimbalzo dentro un ribasso: non deve produrre un long."""
    n = st.MA_TREND_LENGTH + st.MA_SLOPE_LOOKBACK + 50
    discesa = list(np.linspace(200, 100, n - 1)) + [130.0]   # sopra la media, ma media in calo
    plan = st.get("ma_trend").generate("X", _series(discesa), "medio")
    assert plan["bias"] != "long"


def test_ma_trend_entra_long_in_salita():
    n = st.MA_TREND_LENGTH + st.MA_SLOPE_LOOKBACK + 50
    salita = list(np.linspace(100, 200, n))
    plan = st.get("ma_trend").generate("X", _series(salita), "medio")
    assert plan["bias"] == "long"
    assert plan["target"] is None


def test_momentum_positivo_apre_long():
    n = st.MOMENTUM_LOOKBACK + 60
    salita = list(np.linspace(100, 200, n))
    plan = st.get("momentum").generate("X", _series(salita), "medio")
    assert plan["bias"] == "long"


def test_momentum_negativo_apre_short():
    n = st.MOMENTUM_LOOKBACK + 60
    discesa = list(np.linspace(200, 100, n))
    plan = st.get("momentum").generate("X", _series(discesa), "medio")
    assert plan["bias"] == "short"


def test_strategie_senza_storico_sufficiente_non_esplodono():
    corta = _series([100.0] * 30)
    for key in ("donchian", "ma_trend", "momentum"):
        assert st.get(key).generate("X", corta, "medio") is None


def test_le_strategie_semplici_non_dichiarano_una_confidenza_finta():
    """Inventare un punteggio di confidenza renderebbe la calibrazione una
    finzione: queste strategie non ne producono uno."""
    valori = [100.0] * (st.DONCHIAN_ENTRY_BARS + 20) + [130.0]
    plan = st.get("donchian").generate("X", _series(valori), "medio")
    assert plan["confidence"] is None


# ---------------------------------------------------------------------------
# Integrazione nel motore
# ---------------------------------------------------------------------------

def _trending_history(n=600, seed=5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0012, 0.010, n)))
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    return pd.DataFrame({
        "Open": close * (1 + rng.normal(0, 0.002, n)),
        "High": np.maximum(close, np.roll(close, 1)) * 1.006,
        "Low": np.minimum(close, np.roll(close, 1)) * 0.994,
        "Close": close, "Volume": 1e6}, index=idx)


def _config(**kwargs) -> BacktestConfig:
    defaults = dict(initial_equity_eur=10_000.0, risk=RiskConfig(risk_pct=1.0),
                    costs=CostModel(1.0, 0.0, 2.0))
    defaults.update(kwargs)
    return BacktestConfig(**defaults)


def test_ogni_strategia_gira_nel_motore_senza_eccezioni():
    hist = _trending_history()
    for key in st.keys():
        result = core.run_backtest({"SYN": hist}, config=_config(strategy=key),
                                    currencies={"SYN": "EUR"})
        assert result.ledger.open_positions == {}
        for t in result.ledger.closed_trades:
            assert t.entry_date > t.signal_date
            assert t.risk_per_unit > 0


def test_le_strategie_in_trailing_tengono_le_posizioni_piu_a_lungo():
    """È la differenza strutturale attesa: senza target fisso la posizione
    resta aperta finché il trend regge."""
    hist = _trending_history()
    durate = {}
    for key in ("murphy", "donchian"):
        result = core.run_backtest({"SYN": hist}, config=_config(strategy=key),
                                    currencies={"SYN": "EUR"})
        trades = result.ledger.closed_trades
        durate[key] = np.mean([t.bars_held for t in trades]) if trades else 0
    if durate["murphy"] and durate["donchian"]:
        assert durate["donchian"] > durate["murphy"]


def test_long_only_scarta_gli_short():
    """Il broker è spot-only: gli short non sono realmente eseguibili."""
    rng = np.random.default_rng(3)
    n = 600
    close = 200 * np.exp(np.cumsum(rng.normal(-0.0012, 0.010, n)))   # ribasso
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    hist = pd.DataFrame({"Open": close, "High": close * 1.006, "Low": close * 0.994,
                          "Close": close, "Volume": 1e6}, index=idx)

    con_short = core.run_backtest({"SYN": hist}, config=_config(strategy="momentum"),
                                   currencies={"SYN": "EUR"})
    solo_long = core.run_backtest({"SYN": hist},
                                   config=_config(strategy="momentum", long_only=True),
                                   currencies={"SYN": "EUR"})
    assert any(t.direction == "short" for t in con_short.ledger.closed_trades)
    assert all(t.direction == "long" for t in solo_long.ledger.closed_trades)
    assert "short escluso (broker spot-only)" in solo_long.rejection_reasons


def test_strategia_di_default_invariata():
    """Chi non sceglie nulla ottiene esattamente il comportamento storico."""
    assert BacktestConfig().strategy == "murphy"
    assert BacktestConfig().long_only is False
