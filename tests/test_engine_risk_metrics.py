"""Test di sizing, cap di rischio, costi e metriche (src/engine/risk.py,
costs.py, metrics.py).

Due aree critiche coperte qui:

- **I cap di rischio devono mordere davvero.** Un sistema che rispetta
  l'1% per trade ma tiene dieci posizioni aperte sta rischiando il 10%.
  I test verificano che i cap aggregati riducano o rifiutino le nuove
  posizioni invece di essere decorativi.
- **La leva nasce disattivata.** La specifica la sblocca solo dopo la
  calibrazione empirica: finché `leverage_enabled=False`, la confidenza
  non deve poter aumentare la size.
"""
import math
from datetime import date

import numpy as np
import pytest

from src.engine import metrics as mt
from src.engine.costs import CostModel
from src.engine.ledger import ClosedTrade
from src.engine.risk import (HARD_MAX_LEVERAGE, HARD_MAX_RISK_PCT_PER_TRADE, MAX_BASE_RISK_PCT,
                              RiskConfig, leverage_for_confidence, size_position)


# ---------------------------------------------------------------------------
# Sizing a frazione fissa del rischio
# ---------------------------------------------------------------------------

def test_size_rischia_esattamente_la_frazione_richiesta():
    r = size_position(equity_eur=10_000, entry=100, stop=95, confidence=60,
                       config=RiskConfig(risk_pct=1.0))
    assert r.is_tradable
    assert r.initial_risk_eur == pytest.approx(100.0)   # 1% di 10.000
    assert r.size == pytest.approx(20.0)                # 100 EUR / 5 EUR per unità


def test_size_si_adatta_alla_distanza_dello_stop():
    """Stop più lontano -> size più piccola, a parità di rischio in euro.
    È il meccanismo che normalizza il rischio tra strumenti e regimi di
    volatilità diversi."""
    stretto = size_position(10_000, 100, 98, 60, RiskConfig(risk_pct=1.0))
    largo = size_position(10_000, 100, 90, 60, RiskConfig(risk_pct=1.0))
    assert stretto.size > largo.size
    assert stretto.initial_risk_eur == pytest.approx(largo.initial_risk_eur)


def test_stop_coincidente_col_prezzo_viene_rifiutato():
    r = size_position(10_000, 100, 100, 60, RiskConfig())
    assert not r.is_tradable
    assert "stop coincidente" in r.rejected_reason


def test_equity_esaurita_viene_rifiutata():
    assert not size_position(0.0, 100, 95, 60, RiskConfig()).is_tradable


def test_rischio_base_tagliato_al_massimo_consentito():
    config = RiskConfig(risk_pct=5.0)
    assert config.risk_pct == MAX_BASE_RISK_PCT


# ---------------------------------------------------------------------------
# Confidenza → leva
# ---------------------------------------------------------------------------

def test_confidenza_sotto_50_non_opera():
    assert leverage_for_confidence(30, enabled=True) == 0.0
    assert leverage_for_confidence(49, enabled=False) == 0.0
    r = size_position(10_000, 100, 95, 30, RiskConfig())
    assert not r.is_tradable
    assert "soglia operativa" in r.rejected_reason


def test_leva_disattivata_ignora_la_confidenza():
    """Stato previsto finché la calibrazione non è verificata: confidenze
    diverse non devono produrre size diverse."""
    for conf in (50, 70, 85, 100):
        assert leverage_for_confidence(conf, enabled=False) == 1.0
    bassa = size_position(10_000, 100, 95, 55, RiskConfig(leverage_enabled=False))
    alta = size_position(10_000, 100, 95, 95, RiskConfig(leverage_enabled=False))
    assert bassa.size == pytest.approx(alta.size)


def test_leva_attivata_scala_per_bande_ma_mai_oltre_il_cap():
    assert leverage_for_confidence(60, enabled=True) == 1.0
    assert leverage_for_confidence(75, enabled=True) == 1.25
    assert leverage_for_confidence(90, enabled=True) == 1.5
    for conf in range(50, 101):
        assert leverage_for_confidence(conf, enabled=True) <= HARD_MAX_LEVERAGE


def test_rischio_effettivo_non_supera_mai_il_tetto_rigido():
    r = size_position(10_000, 100, 95, 95, RiskConfig(risk_pct=1.0, leverage_enabled=True))
    max_risk_eur = 10_000 * HARD_MAX_RISK_PCT_PER_TRADE / 100
    assert r.initial_risk_eur <= max_risk_eur + 1e-6


# ---------------------------------------------------------------------------
# Cap aggregati
# ---------------------------------------------------------------------------

def test_cap_sul_rischio_aggregato_riduce_il_budget():
    config = RiskConfig(risk_pct=1.0, max_aggregate_open_risk_pct=3.0)
    # Già 280 EUR di rischio aperto su un tetto di 300: resta spazio per 20.
    r = size_position(10_000, 100, 95, 60, config, open_risk_eur=280.0)
    assert r.is_tradable
    assert r.initial_risk_eur == pytest.approx(20.0)
    assert any("rischio aggregato" in w for w in r.warnings)


def test_cap_sul_rischio_aggregato_rifiuta_quando_saturo():
    config = RiskConfig(risk_pct=1.0, max_aggregate_open_risk_pct=3.0)
    r = size_position(10_000, 100, 95, 60, config, open_risk_eur=300.0)
    assert not r.is_tradable
    assert "rischio aggregato" in r.rejected_reason


def test_cap_sull_esposizione_lorda_riduce_la_size():
    config = RiskConfig(risk_pct=1.0, max_gross_exposure=1.0)
    # Esposizione già a 9.500 su un tetto di 10.000: restano 500 EUR.
    r = size_position(10_000, 100, 99, 60, config, open_gross_exposure_eur=9_500.0)
    assert r.is_tradable
    assert r.notional_eur == pytest.approx(500.0)
    assert any("esposizione lorda" in w for w in r.warnings)


def test_cap_sull_esposizione_lorda_rifiuta_quando_saturo():
    config = RiskConfig(max_gross_exposure=1.0)
    r = size_position(10_000, 100, 95, 60, config, open_gross_exposure_eur=10_000.0)
    assert not r.is_tradable
    assert "esposizione lorda" in r.rejected_reason


# ---------------------------------------------------------------------------
# Modello di costo
# ---------------------------------------------------------------------------

def test_costo_fx_applicato_solo_agli_strumenti_non_eur():
    costs = CostModel(order_fee_eur=1.0, fx_cost_pct_per_leg=0.5, slippage_bps_per_side=0.0)
    eur = costs.entry_cost_eur(10_000, "EUR")
    usd = costs.entry_cost_eur(10_000, "USD")
    assert eur == pytest.approx(1.0)
    assert usd == pytest.approx(1.0 + 50.0)     # 0,5% di 10.000


def test_valuta_sconosciuta_assume_il_caso_peggiore():
    """Un costo dimenticato è il modo classico in cui un backtest si
    lusinga da solo: valuta ignota significa costo FX applicato."""
    costs = CostModel(fx_cost_pct_per_leg=0.5)
    assert costs.applies_fx(None) is True


def test_round_trip_somma_entrambe_le_gambe():
    costs = CostModel(order_fee_eur=1.0, fx_cost_pct_per_leg=0.0, slippage_bps_per_side=0.0)
    assert costs.round_trip_cost_eur(1000, 1100, "EUR") == pytest.approx(2.0)


def test_descrizione_costi_dichiara_i_parametri():
    d = CostModel().describe()
    assert "per ordine" in d and "%" in d and "bp" in d


# ---------------------------------------------------------------------------
# Intervallo di Wilson
# ---------------------------------------------------------------------------

def test_wilson_si_stringe_al_crescere_del_campione():
    stretto = mt.wilson_interval(50, 100)
    largo = mt.wilson_interval(10, 20)
    assert (stretto[1] - stretto[0]) < (largo[1] - largo[0])


def test_wilson_ampiezza_attesa_a_meta_su_cento_trade():
    """A p=0,5 con 100 trade l'intervallo è circa ±9,6 punti."""
    lo, hi = mt.wilson_interval(50, 100)
    assert (hi - lo) / 2 == pytest.approx(0.096, abs=0.01)


def test_wilson_resta_dentro_zero_uno_agli_estremi():
    """Dove Wald produrrebbe un intervallo degenere o fuori scala."""
    lo, hi = mt.wilson_interval(0, 10)
    assert lo >= 0.0 and hi <= 1.0 and hi > 0
    lo, hi = mt.wilson_interval(10, 10)
    assert lo < 1.0 and hi <= 1.0


def test_wilson_su_campione_vuoto():
    assert mt.wilson_interval(0, 0) == (0.0, 0.0)


# ---------------------------------------------------------------------------
# Metriche
# ---------------------------------------------------------------------------

def test_max_drawdown_su_serie_nota():
    equity = [100, 120, 90, 110, 80, 130]
    abs_dd, pct_dd = mt.max_drawdown(equity)
    assert abs_dd == pytest.approx(40.0)        # da 120 a 80
    assert pct_dd == pytest.approx(40 / 120)


def test_max_drawdown_serie_monotona_crescente():
    assert mt.max_drawdown([100, 110, 120])[0] == 0.0


def _trade(net_pnl: float, net_r: float, **kwargs) -> ClosedTrade:
    defaults = dict(
        symbol="TEST", direction="long", signal_date=date(2024, 1, 1), entry_date=date(2024, 1, 2),
        entry_price=100.0, exit_date=date(2024, 1, 10), exit_price=105.0, exit_reason="target",
        size=10.0, risk_per_unit=5.0, initial_risk_eur=100.0, confidence=70.0, leverage=1.0,
        gross_pnl_eur=net_pnl, costs_eur=0.0, net_pnl_eur=net_pnl,
        gross_r=net_r, net_r=net_r, mae_r=0.3, mfe_r=1.2, bars_held=8, gapped_exit=False,
    )
    defaults.update(kwargs)
    return ClosedTrade(**defaults)


def test_expectancy_e_profit_factor_su_valori_noti():
    # 2 vincite da +2R, 3 perdite da −1R -> expectancy = (2·2 − 3·1)/5 = +0,2R
    trades = [_trade(200, 2.0), _trade(200, 2.0), _trade(-100, -1.0), _trade(-100, -1.0), _trade(-100, -1.0)]
    m = mt.compute_metrics(trades, [], initial_equity=10_000, label="test")
    assert m.expectancy_r == pytest.approx(0.2)
    assert m.win_rate == pytest.approx(0.4)
    assert m.profit_factor == pytest.approx(400 / 300)


def test_vincente_si_giudica_sul_netto_non_sul_lordo():
    """Un trade positivo al lordo ma negativo dopo i costi non è una
    vittoria: contarlo tale gonfierebbe il win rate."""
    t = _trade(net_pnl=-5.0, net_r=-0.05, gross_pnl_eur=10.0)
    assert t.is_winner is False


def test_profit_factor_non_definito_senza_perdite_viene_segnalato():
    m = mt.compute_metrics([_trade(100, 1.0), _trade(100, 1.0)], [], 10_000)
    assert m.profit_factor is None
    assert any("non definito" in w for w in m.warnings)


def test_avviso_su_profit_factor_alto_con_campione_piccolo():
    trades = [_trade(400, 4.0) for _ in range(9)] + [_trade(-100, -1.0)]
    m = mt.compute_metrics(trades, [], 10_000)
    assert m.profit_factor > 3
    assert any("overfitting o fortuna" in w for w in m.warnings)


def test_gating_del_campione():
    pochi = mt.compute_metrics([_trade(100, 1.0) for _ in range(10)], [], 10_000)
    assert not pochi.sample_is_indicative and not pochi.sample_is_reliable

    medi = mt.compute_metrics([_trade(100, 1.0) for _ in range(60)], [], 10_000)
    assert medi.sample_is_indicative and not medi.sample_is_reliable

    molti = mt.compute_metrics([_trade(100, 1.0) for _ in range(120)], [], 10_000)
    assert molti.sample_is_reliable


def test_sharpe_none_su_serie_troppo_corta():
    assert mt.sharpe_ratio(np.array([0.01])) is None


def test_sortino_supera_lo_sharpe_con_rendimenti_asimmetrici():
    """Firma tipica del trend-following: perdite tagliate, guadagni
    lasciati correre."""
    returns = np.array([-0.002] * 30 + [0.05] * 5 + [0.001] * 20)
    sharpe = mt.sharpe_ratio(returns)
    sortino = mt.sortino_ratio(returns)
    assert sortino is not None and sharpe is not None
    assert sortino > sharpe


# ---------------------------------------------------------------------------
# Verdetto
# ---------------------------------------------------------------------------

def test_verdetto_nessun_edge_con_expectancy_negativa():
    m = mt.compute_metrics([_trade(-100, -1.0) for _ in range(120)], [], 10_000)
    v = mt.build_verdict(m, beats_buy_and_hold=True, beats_random=True)
    assert v["verdict"] == mt.VERDICT_NEGATIVE


def test_verdetto_non_provato_con_campione_insufficiente():
    m = mt.compute_metrics([_trade(200, 2.0) for _ in range(10)], [], 10_000)
    v = mt.build_verdict(m, beats_buy_and_hold=True, beats_random=True)
    assert v["verdict"] == mt.VERDICT_UNPROVEN


def test_verdetto_non_provato_se_non_batte_i_benchmark():
    trades = [_trade(200, 2.0)] * 60 + [_trade(-100, -1.0)] * 60
    m = mt.compute_metrics(trades, [], 10_000)
    v = mt.build_verdict(m, beats_buy_and_hold=False, beats_random=True)
    assert v["verdict"] == mt.VERDICT_UNPROVEN
    assert "buy-and-hold" in v["text"]

    v2 = mt.build_verdict(m, beats_buy_and_hold=True, beats_random=False)
    assert v2["verdict"] == mt.VERDICT_UNPROVEN
    assert "casuale" in v2["text"]


def test_verdetto_marginale_con_campione_indicativo_ma_non_affidabile():
    trades = [_trade(200, 2.0)] * 30 + [_trade(-100, -1.0)] * 40
    m = mt.compute_metrics(trades, [], 10_000)
    v = mt.build_verdict(m, beats_buy_and_hold=True, beats_random=True)
    assert v["verdict"] == mt.VERDICT_MARGINAL


def test_verdetto_stabilito_solo_con_tutte_le_condizioni():
    trades = [_trade(200, 2.0)] * 50 + [_trade(-100, -1.0)] * 70
    m = mt.compute_metrics(trades, [], 10_000)
    v = mt.build_verdict(m, beats_buy_and_hold=True, beats_random=True)
    assert v["verdict"] == mt.VERDICT_ESTABLISHED
    assert m.sample_is_reliable


def test_verdetto_senza_trade():
    m = mt.compute_metrics([], [], 10_000)
    v = mt.build_verdict(m, None, None)
    assert v["verdict"] == mt.VERDICT_UNPROVEN
