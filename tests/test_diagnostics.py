"""Test della diagnostica (src/engine/diagnostics.py).

La diagnostica serve a distinguere "il segnale non funziona" da "il
segnale funziona ma la struttura attorno gli distrugge il valore": sono
due diagnosi opposte che portano a due lavori diversi. Se sbaglia, si
lavora sulla cosa sbagliata per settimane.

I test costruiscono quindi casi con la risposta nota per costruzione — un
insieme di trade in cui il problema sono *solo* i costi, uno in cui sono
*solo* le uscite — e verificano che la diagnosi punti al posto giusto.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.engine import diagnostics as diag
from src.engine.ledger import ClosedTrade


def _trade(net_pnl=100.0, net_r=1.0, costs=2.0, risk=100.0, mfe_r=1.2, mae_r=0.3,
            planned_rr=2.0, rr_unfavorable=False, stop_source="livello",
            target_source="livello", symbol="TEST", exit_reason="target") -> ClosedTrade:
    return ClosedTrade(
        symbol=symbol, direction="long", signal_date=date(2024, 1, 1),
        entry_date=date(2024, 1, 2), entry_price=100.0, exit_date=date(2024, 1, 10),
        exit_price=110.0, exit_reason=exit_reason, size=10.0, risk_per_unit=5.0,
        initial_risk_eur=risk, confidence=70.0, leverage=1.0,
        gross_pnl_eur=net_pnl + costs, costs_eur=costs, net_pnl_eur=net_pnl,
        gross_r=net_r + costs / risk, net_r=net_r, mae_r=mae_r, mfe_r=mfe_r,
        bars_held=8, gapped_exit=False, target=110.0, planned_rr=planned_rr,
        rr_unfavorable=rr_unfavorable, stop_source=stop_source, target_source=target_source,
    )


# ---------------------------------------------------------------------------
# Costi
# ---------------------------------------------------------------------------

def test_costo_in_r_calcolato_sul_rischio_non_sul_controvalore():
    """20 euro di costo su 100 di rischio sono 0,2R, sempre — la
    dimensione del trade non c'entra."""
    d = diag.cost_drag([_trade(costs=20.0, risk=100.0)])
    assert d.mean_cost_r == pytest.approx(0.2)


def test_costi_elevati_producono_un_verdetto_di_allarme():
    d = diag.cost_drag([_trade(costs=50.0, risk=100.0) for _ in range(10)])
    assert d.mean_cost_r == pytest.approx(0.5)
    assert "expectancy" in d.verdict
    assert "stop" in d.verdict          # indica la leva su cui agire


def test_costi_bassi_non_vengono_indicati_come_problema():
    d = diag.cost_drag([_trade(costs=2.0, risk=100.0) for _ in range(10)])
    assert d.mean_cost_r == pytest.approx(0.02)
    assert "non sono loro il problema" in d.verdict


def test_costi_aggregati_per_simbolo():
    trades = [_trade(symbol="A", costs=50.0), _trade(symbol="B", costs=2.0),
              _trade(symbol="B", costs=2.0)]
    d = diag.cost_drag(trades)
    assert len(d.by_symbol) == 2
    # Ordinato per costo medio decrescente: il peggiore in cima.
    assert d.by_symbol.iloc[0]["symbol"] == "A"


def test_cost_drag_su_lista_vuota():
    d = diag.cost_drag([])
    assert d.n_trades == 0 and d.mean_cost_r is None


# ---------------------------------------------------------------------------
# Uscite
# ---------------------------------------------------------------------------

def test_uscite_premature_riconosciute():
    """Vincenti che toccano 3R e chiudono a 0,8R: il problema sono le
    uscite, e la diagnosi deve dirlo."""
    trades = [_trade(net_pnl=80.0, net_r=0.8, mfe_r=3.0) for _ in range(10)]
    d = diag.exit_quality(trades)
    assert d.mean_gap_r == pytest.approx(2.2)
    assert "uscite a buttarla via" in d.verdict


def test_uscite_efficienti_non_segnalate():
    """Vincenti che chiudono vicino al proprio massimo: le uscite non sono
    il collo di bottiglia."""
    trades = [_trade(net_pnl=200.0, net_r=2.0, mfe_r=2.1) for _ in range(10)]
    d = diag.exit_quality(trades)
    assert d.mean_gap_r == pytest.approx(0.1)
    assert "non sembrano essere il collo di bottiglia" in d.verdict


def test_gap_calcolato_solo_sui_vincenti():
    """L'MFE dei perdenti non c'entra con 'quanto ho lasciato sul tavolo':
    un perdente che non è mai andato a favore non è un'uscita prematura."""
    trades = [_trade(net_pnl=100.0, net_r=1.0, mfe_r=3.0),
              _trade(net_pnl=-100.0, net_r=-1.0, mfe_r=0.0)]
    d = diag.exit_quality(trades)
    assert d.n_winners == 1
    assert d.mean_gap_r == pytest.approx(2.0)


def test_rapporto_vincita_perdita():
    trades = [_trade(net_pnl=200.0, net_r=2.0), _trade(net_pnl=-100.0, net_r=-1.0)]
    d = diag.exit_quality(trades)
    assert d.win_loss_size_ratio == pytest.approx(2.0)


def test_conteggio_motivi_di_uscita():
    trades = ([_trade(exit_reason="stop") for _ in range(3)]
              + [_trade(exit_reason="target") for _ in range(2)])
    d = diag.exit_quality(trades)
    reasons = dict(zip(d.exit_reasons["motivo"], d.exit_reasons["trade"]))
    assert reasons["stop"] == 3 and reasons["target"] == 2


def test_exit_quality_senza_vincenti():
    d = diag.exit_quality([_trade(net_pnl=-100.0, net_r=-1.0) for _ in range(5)])
    assert d.mean_gap_r is None
    assert "Nessun trade vincente" in d.verdict


# ---------------------------------------------------------------------------
# Geometria dei piani
# ---------------------------------------------------------------------------

def test_quota_di_piani_sfavorevoli():
    trades = ([_trade(rr_unfavorable=True, planned_rr=0.6) for _ in range(8)]
              + [_trade(rr_unfavorable=False, planned_rr=2.0) for _ in range(2)])
    d = diag.plan_quality(trades)
    assert d.share_unfavorable_pct == pytest.approx(80.0)
    assert d.median_planned_rr == pytest.approx(0.6, abs=0.3)
    assert "sfavorevole" in d.verdict


def test_quota_di_stop_dal_ripiego_ad_atr():
    trades = ([_trade(stop_source="atr") for _ in range(3)]
              + [_trade(stop_source="livello") for _ in range(7)])
    d = diag.plan_quality(trades)
    assert d.share_stop_from_atr_pct == pytest.approx(30.0)


def test_distribuzione_del_rr():
    trades = [_trade(planned_rr=rr) for rr in (0.3, 0.7, 1.2, 1.7, 2.5, 4.0)]
    d = diag.plan_quality(trades)
    assert d.rr_distribution["trade"].sum() == 6


def test_plan_quality_senza_dati_di_piano():
    """Backtest eseguiti prima dell'introduzione dei campi diagnostici: la
    diagnosi deve dirlo, non fingere di sapere."""
    trades = [_trade(planned_rr=None, rr_unfavorable=None, stop_source=None,
                      target_source=None) for _ in range(5)]
    d = diag.plan_quality(trades)
    assert d.share_unfavorable_pct is None
    assert "non disponibili" in d.verdict


# ---------------------------------------------------------------------------
# Qualità del segnale, isolata da uscite e costi
# ---------------------------------------------------------------------------

def _history(n=400, drift=0.0, seed=1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.01, n)))
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    return pd.DataFrame({
        "Open": close * (1 + rng.normal(0, 0.002, n)),
        "High": np.maximum(close, np.roll(close, 1)) * 1.005,
        "Low": np.minimum(close, np.roll(close, 1)) * 0.995,
        "Close": close, "Volume": 1e6}, index=idx)


def test_signal_quality_confronta_segnale_e_baseline():
    out = diag.signal_quality({"SYN": _history()}, forward_bars=10)
    assert out.n_baseline > 0
    if out.n_signals > 0:
        assert out.mean_signal_return_pct is not None
        assert out.edge_pct == pytest.approx(
            out.mean_signal_return_pct - out.mean_baseline_return_pct)
        assert out.verdict


def test_signal_quality_su_storico_troppo_corto():
    out = diag.signal_quality({"SYN": _history(n=50)}, forward_bars=20)
    assert out.n_signals == 0
    assert "insufficienti" in out.verdict


def test_signal_quality_usa_l_apertura_successiva_non_il_close():
    """Misurare dal close del bar del segnale introdurrebbe il look-ahead
    che il motore evita per costruzione. Il test verifica che spostando
    solo le APERTURE il risultato cambi: se usasse i close, sarebbe
    insensibile."""
    hist = _history(n=300, seed=4)
    base = diag.signal_quality({"SYN": hist}, forward_bars=10)

    shifted = hist.copy()
    shifted["Open"] = shifted["Open"] * 1.05
    moved = diag.signal_quality({"SYN": shifted}, forward_bars=10)

    if base.n_baseline and moved.n_baseline:
        assert base.mean_baseline_return_pct != pytest.approx(moved.mean_baseline_return_pct)


# ---------------------------------------------------------------------------
# Sintesi
# ---------------------------------------------------------------------------

def test_sintesi_elenca_le_cause_dominanti():
    cost = diag.cost_drag([_trade(costs=50.0, risk=100.0) for _ in range(10)])
    exits = diag.exit_quality([_trade(net_pnl=80.0, net_r=0.8, mfe_r=3.0) for _ in range(10)])
    plans = diag.plan_quality([_trade(rr_unfavorable=True) for _ in range(10)])
    text = diag.overall_diagnosis(cost, exits, plans, beats_random=True)
    assert "costi" in text and "uscite premature" in text and "sfavorevoli" in text
    assert "batte l'entrata casuale" in text


def test_sintesi_quando_non_batte_il_caso():
    cost = diag.cost_drag([_trade(costs=1.0, risk=100.0)])
    exits = diag.exit_quality([_trade(net_pnl=200.0, net_r=2.0, mfe_r=2.05)])
    plans = diag.plan_quality([_trade(rr_unfavorable=False)])
    text = diag.overall_diagnosis(cost, exits, plans, beats_random=False)
    assert "non viene dal segnale" in text


def test_sintesi_senza_cause_dominanti():
    cost = diag.cost_drag([_trade(costs=1.0, risk=100.0)])
    exits = diag.exit_quality([_trade(net_pnl=200.0, net_r=2.0, mfe_r=2.05)])
    plans = diag.plan_quality([_trade(rr_unfavorable=False)])
    text = diag.overall_diagnosis(cost, exits, plans, beats_random=None)
    assert "Nessuna delle cause strutturali" in text
