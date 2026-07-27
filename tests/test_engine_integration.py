"""Test di integrazione del motore: benchmark, split in-sample/out-of-sample
e pipeline completa col segnale REALE dell'Analisi Tecnica.

Il test più importante qui è quello che gira `trade_plan` vero su una
serie sintetica: verifica che il motore di backtest e il motore di analisi
tecnica si parlino davvero, che è l'intero presupposto del progetto —
testare il piano operativo che l'app mostra, non una sua riscrittura.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from src import data_provider as dp
from src.engine import benchmarks as bm
from src.engine import runner
from src.engine.core import BacktestConfig, run_backtest
from src.engine.costs import CostModel
from src.engine.risk import RiskConfig


def _synthetic_history(n=900, seed=7, start=100.0) -> pd.DataFrame:
    """Serie con tre regimi (rialzo, ribasso, rialzo): un backtest su un
    solo regime non direbbe nulla sulla robustezza."""
    rng = np.random.default_rng(seed)
    third = n // 3
    drift = np.concatenate([
        np.full(third, 0.0012),
        np.full(third, -0.0010),
        np.full(n - 2 * third, 0.0009),
    ])
    steps = rng.normal(drift, 0.011, n)
    close = start * np.exp(np.cumsum(steps))
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    high = np.maximum(close, np.roll(close, 1)) * (1 + rng.uniform(0.001, 0.008, n))
    low = np.minimum(close, np.roll(close, 1)) * (1 - rng.uniform(0.001, 0.008, n))
    open_ = close * (1 + rng.normal(0, 0.002, n))
    volume = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close,
                          "Volume": volume}, index=idx)


def _cheap_config(**kwargs) -> BacktestConfig:
    defaults = dict(
        horizon="medio", initial_equity_eur=10_000.0,
        risk=RiskConfig(risk_pct=1.0),
        costs=CostModel(order_fee_eur=1.0, fx_cost_pct_per_leg=0.0, slippage_bps_per_side=2.0),
    )
    defaults.update(kwargs)
    return BacktestConfig(**defaults)


# ---------------------------------------------------------------------------
# Pipeline completa col segnale reale (trade_plan)
# ---------------------------------------------------------------------------

def test_pipeline_completa_con_segnale_reale_senza_rete():
    """Nessun monkeypatch sul segnale: gira `technical_snapshot` +
    `trade_plan` veri su dati sintetici."""
    hist = _synthetic_history()
    result = run_backtest({"SYN": hist}, config=_cheap_config(), currencies={"SYN": "EUR"})

    assert result.n_signals_evaluated > 0, "il motore non ha valutato alcun segnale"
    assert result.ledger.equity_curve, "nessuna curva di equity prodotta"
    # Ogni trade chiuso deve essere internamente coerente.
    for t in result.ledger.closed_trades:
        assert t.entry_date > t.signal_date, "ingresso non posticipato al bar successivo"
        assert t.risk_per_unit > 0
        assert t.net_pnl_eur <= t.gross_pnl_eur
        assert t.exit_reason in ("stop", "target", "gap_stop", "gap_target", "chiusura_forzata")


def test_nessuna_posizione_resta_aperta_a_fine_backtest():
    hist = _synthetic_history()
    result = run_backtest({"SYN": hist}, config=_cheap_config(), currencies={"SYN": "EUR"})
    assert result.ledger.open_positions == {}


def test_backtest_multi_strumento_condivide_l_equity():
    """Con equity condivisa i cap aggregati devono valere sull'insieme,
    non per strumento."""
    histories = {"A": _synthetic_history(seed=1), "B": _synthetic_history(seed=2)}
    config = _cheap_config(risk=RiskConfig(risk_pct=1.0, max_aggregate_open_risk_pct=3.0))
    result = run_backtest(histories, config=config, currencies={"A": "EUR", "B": "EUR"})
    assert set(result.symbols) == {"A", "B"}
    assert result.ledger.open_risk_eur() == 0.0    # tutto chiuso a fine periodo


# ---------------------------------------------------------------------------
# Periodo operativo e warm-up
# ---------------------------------------------------------------------------

def test_le_barre_prima_dello_start_servono_da_warmup_non_generano_trade():
    """Lo split OOS onesto richiede che il segmento veda lo storico
    precedente per gli indicatori, ma non produca trade nel periodo di
    training."""
    hist = _synthetic_history()
    split = hist.index[600].date()
    result = run_backtest({"SYN": hist}, config=_cheap_config(), currencies={"SYN": "EUR"},
                           start=split)
    assert result.start_date >= split
    for t in result.ledger.closed_trades:
        assert t.entry_date >= split


def test_periodo_operativo_vuoto_non_esplode():
    hist = _synthetic_history(n=400)
    result = run_backtest({"SYN": hist}, config=_cheap_config(), currencies={"SYN": "EUR"},
                           start=date(2100, 1, 1))
    assert result.ledger.closed_trades == []
    assert result.diagnostics


def test_storico_vuoto_gestito():
    result = run_backtest({}, config=_cheap_config())
    assert result.ledger.closed_trades == []
    assert result.diagnostics


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

def test_buy_and_hold_su_serie_crescente_e_positivo():
    n = 300
    idx = pd.bdate_range("2022-01-01", periods=n)
    close = np.linspace(100, 200, n)
    hist = pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1,
                          "Close": close, "Volume": 1e6}, index=idx)
    result = bm.buy_and_hold({"UP": hist}, 10_000.0,
                              costs=CostModel(order_fee_eur=0.0, fx_cost_pct_per_leg=0.0,
                                              slippage_bps_per_side=0.0),
                              currencies={"UP": "EUR"})
    assert result.total_return_pct > 90        # il prezzo raddoppia circa
    assert len(result.equity_curve) == n


def test_buy_and_hold_paga_i_costi():
    n = 300
    idx = pd.bdate_range("2022-01-01", periods=n)
    close = np.linspace(100, 200, n)
    hist = pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1,
                          "Close": close, "Volume": 1e6}, index=idx)
    gratis = bm.buy_and_hold({"UP": hist}, 10_000.0,
                              costs=CostModel(order_fee_eur=0.0, fx_cost_pct_per_leg=0.0,
                                              slippage_bps_per_side=0.0),
                              currencies={"UP": "EUR"})
    caro = bm.buy_and_hold({"UP": hist}, 10_000.0,
                            costs=CostModel(order_fee_eur=2.0, fx_cost_pct_per_leg=0.5,
                                            slippage_bps_per_side=10.0),
                            currencies={"UP": "USD"})
    assert caro.total_return_pct < gratis.total_return_pct


def test_random_entry_monte_carlo_produce_una_distribuzione():
    from src import technical as tech
    hist = _synthetic_history(n=500)
    atr = {"SYN": tech.atr(hist, period=14)}
    result = bm.random_entry_monte_carlo(
        {"SYN": hist}, n_trades_target=10, initial_equity_eur=10_000.0,
        atr_by_symbol=atr, risk=RiskConfig(risk_pct=1.0),
        costs=CostModel(order_fee_eur=1.0, fx_cost_pct_per_leg=0.0, slippage_bps_per_side=2.0),
        currencies={"SYN": "EUR"}, runs=25,
    )
    assert result.runs == 25
    assert len(result.returns_pct) == 25
    assert result.median_return_pct is not None
    # La varianza tra run è il motivo per cui serve un Monte Carlo e non
    # un singolo run casuale.
    assert len(set(np.round(result.returns_pct, 6))) > 1


def test_percentile_of_posiziona_la_strategia():
    dist = [-5.0, 0.0, 5.0, 10.0]
    assert bm.percentile_of(7.0, dist) == pytest.approx(75.0)
    assert bm.percentile_of(None, dist) is None
    assert bm.percentile_of(1.0, []) is None


def test_beats_confronta_con_la_mediana():
    r = bm.RandomEntryResult(runs=3, returns_pct=[0, 5, 10], expectancy_r=[],
                              median_return_pct=5.0, p95_return_pct=10.0)
    assert r.beats(6.0) is True
    assert r.beats(4.0) is False
    assert r.beats(None) is None


# ---------------------------------------------------------------------------
# Runner: split, orizzonti, contaminazione
# ---------------------------------------------------------------------------

def test_orizzonte_non_supportato_viene_rifiutato_esplicitamente():
    """L'orizzonte lungo usa barre settimanali: va rifiutato con un
    messaggio chiaro invece di essere approssimato con dati daily, che
    produrrebbe risultati diversi da quelli mostrati nell'app."""
    with pytest.raises(ValueError, match="lungo"):
        runner.run_full_backtest(["X"], config=BacktestConfig(horizon="lungo"))


def test_split_date_divide_il_calendario():
    hist = _synthetic_history(n=900)
    split = runner.compute_split_date({"SYN": hist}, oos_fraction=1 / 3)
    dates = sorted(ts.date() for ts in hist.index)
    assert split is not None
    n_before = sum(1 for d in dates if d < split)
    assert n_before == pytest.approx(len(dates) * 2 / 3, rel=0.02)


def test_split_date_none_su_storico_troppo_corto():
    hist = _synthetic_history(n=30)
    assert runner.compute_split_date({"SYN": hist}) is None


def test_avviso_di_contaminazione_quando_oos_migliore_dell_in_sample():
    from src.engine import metrics as mt

    is_m = mt.PerformanceMetrics(label="In-sample", n_trades=100)
    is_m.expectancy_r = 0.20
    oos_m = mt.PerformanceMetrics(label="Out-of-sample", n_trades=60)
    oos_m.expectancy_r = 0.45

    note = runner._check_contamination(is_m, oos_m)
    assert note is not None
    assert "contaminazione" in note


def test_nessun_avviso_di_contaminazione_col_normale_decadimento():
    from src.engine import metrics as mt

    is_m = mt.PerformanceMetrics(label="In-sample", n_trades=100)
    is_m.expectancy_r = 0.40
    oos_m = mt.PerformanceMetrics(label="Out-of-sample", n_trades=60)
    oos_m.expectancy_r = 0.18
    assert runner._check_contamination(is_m, oos_m) is None


def test_load_histories_segnala_i_simboli_scartati(monkeypatch):
    """Un universo silenziosamente ridotto cambia i risultati: gli scarti
    vanno dichiarati."""
    buono = _synthetic_history(n=800)
    monkeypatch.setattr(dp, "get_history",
                         lambda s, period="10y", interval="1d": buono if s == "OK" else pd.DataFrame())
    monkeypatch.setattr(dp, "get_ticker", lambda s: type("T", (), {"info": {"currency": "EUR"}})())

    histories, currencies, skipped = runner.load_histories(["OK", "CORTO"])
    assert "OK" in histories
    assert skipped == ["CORTO"]
    assert currencies["OK"] == "EUR"


def test_run_full_backtest_end_to_end_con_dati_finti(monkeypatch):
    hist = _synthetic_history(n=900)
    monkeypatch.setattr(dp, "get_history", lambda s, period="10y", interval="1d": hist)
    monkeypatch.setattr(dp, "get_ticker", lambda s: type("T", (), {"info": {"currency": "EUR"}})())

    report = runner.run_full_backtest(["SYN"], config=_cheap_config(), monte_carlo_runs=10,
                                       run_out_of_sample=True)

    assert report.in_sample is not None
    assert report.out_of_sample is not None
    assert report.split_date is not None
    assert report.in_sample.verdict.get("verdict")
    assert report.in_sample.buy_and_hold is not None
    assert report.cost_description
