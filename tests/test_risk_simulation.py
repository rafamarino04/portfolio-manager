"""Test del simulatore di rischio (src/engine/risk_simulation.py).

Il modulo serve a scegliere quanto rischiare per trade guardando insieme
rendimento e drawdown. La proprietà più importante da verificare non è un
valore numerico ma una **relazione**: il rapporto rendimento/dolore deve
restare sostanzialmente invariato al variare del rischio. Se il codice
mostrasse un rapporto che migliora alzando il rischio, suggerirebbe che
rischiare di più renda il sistema migliore — che è falso e pericoloso.
"""
import numpy as np
import pytest

from src.engine import risk_simulation as rs


def _trend_following_r(n=120, win_rate=0.35, seed=1) -> list[float]:
    """Distribuzione con la forma tipica del trend-following: molte
    piccole perdite attorno a −1R (con code peggiori per i gap) e pochi
    guadagni grandi e asimmetrici."""
    rng = np.random.default_rng(seed)
    n_win = int(n * win_rate)
    perdite = list(rng.normal(-1.0, 0.25, n - n_win))
    vincite = list(rng.gamma(2.0, 1.4, n_win))
    return perdite + vincite


# ---------------------------------------------------------------------------
# La relazione che conta
# ---------------------------------------------------------------------------

def test_rendimento_e_drawdown_crescono_insieme_col_rischio():
    rep = rs.simulate(_trend_following_r(), trades_per_year=25, paths=800)
    rendimenti = [s.median_annual_return_pct for s in rep.scenarios]
    drawdown = [s.median_max_drawdown_pct for s in rep.scenarios]
    assert rendimenti == sorted(rendimenti)
    assert drawdown == sorted(drawdown)


def test_il_rapporto_rendimento_dolore_non_migliora_alzando_il_rischio():
    """È il punto dell'intero modulo: alzare il rischio non rende il
    sistema migliore, lo rende più grande in entrambe le direzioni."""
    rep = rs.simulate(_trend_following_r(), trades_per_year=25, paths=1500)
    rapporti = [s.return_to_pain for s in rep.scenarios if s.return_to_pain]
    assert len(rapporti) >= 4
    assert max(rapporti) - min(rapporti) < 0.15 * max(rapporti)


def test_probabilita_di_drawdown_grave_cresce_col_rischio():
    rep = rs.simulate(_trend_following_r(), trades_per_year=25, paths=1500)
    prob = [s.prob_drawdown_over[0.20] for s in rep.scenarios]
    assert prob[0] < prob[-1]
    assert all(0 <= p <= 100 for p in prob)


def test_la_coda_e_peggiore_della_mediana():
    rep = rs.simulate(_trend_following_r(), trades_per_year=25, paths=800)
    for s in rep.scenarios:
        assert s.p95_max_drawdown_pct >= s.median_max_drawdown_pct


# ---------------------------------------------------------------------------
# Robustezza
# ---------------------------------------------------------------------------

def test_campione_troppo_piccolo_viene_rifiutato():
    """Con pochi trade la forma della distribuzione non è rappresentata:
    simulare comunque darebbe una falsa precisione."""
    rep = rs.simulate([1.0, -1.0, 2.0], trades_per_year=20)
    assert rep.scenarios == []
    assert any("non è significativa" in n for n in rep.notes)


def test_frequenza_nulla_non_simula():
    rep = rs.simulate(_trend_following_r(), trades_per_year=0)
    assert rep.scenarios == []


def test_valori_non_finiti_ignorati():
    r = _trend_following_r() + [float("nan"), float("inf"), None]
    rep = rs.simulate(r, trades_per_year=25, paths=300)
    assert rep.n_trades_sampled == 120
    assert rep.scenarios


def test_equity_non_diventa_mai_negativa():
    """Una perdita non può portare il capitale sotto zero: il troncamento
    esiste perché l'equity negativa non è una cosa che esiste."""
    catastrofi = [-50.0] * 60 + [1.0] * 60      # R assurdamente negativi
    rep = rs.simulate(catastrofi, trades_per_year=20, risk_grid=(2.0,), paths=200)
    for s in rep.scenarios:
        assert s.median_max_drawdown_pct <= 100.0


def test_deterministico_a_parita_di_seed():
    a = rs.simulate(_trend_following_r(), trades_per_year=25, paths=300, seed=7)
    b = rs.simulate(_trend_following_r(), trades_per_year=25, paths=300, seed=7)
    assert ([s.median_annual_return_pct for s in a.scenarios]
            == [s.median_annual_return_pct for s in b.scenarios])


def test_avverte_che_i_drawdown_reali_sono_peggiori():
    """Il bootstrap indipendente rompe il raggruppamento delle perdite: va
    dichiarato, perché rende la simulazione ottimistica."""
    rep = rs.simulate(_trend_following_r(), trades_per_year=25, paths=300)
    assert any("PEGGIORI" in n for n in rep.notes)


# ---------------------------------------------------------------------------
# Raccomandazione
# ---------------------------------------------------------------------------

def test_raccomandazione_sceglie_il_rischio_piu_alto_entro_la_tolleranza():
    rep = rs.simulate(_trend_following_r(), trades_per_year=25, paths=1500)
    testo = rs.build_recommendation(rep, tolerated_drawdown_pct=25)
    accettabili = [s for s in rep.scenarios if s.p95_max_drawdown_pct <= 25]
    atteso = max(accettabili, key=lambda s: s.risk_pct)
    assert f"{atteso.risk_pct:g}%" in testo


def test_raccomandazione_quando_nessun_livello_e_accettabile():
    rep = rs.simulate(_trend_following_r(), trades_per_year=25, paths=800)
    testo = rs.build_recommendation(rep, tolerated_drawdown_pct=1)
    assert "Nemmeno il rischio più basso" in testo


def test_raccomandazione_usa_la_coda_non_la_mediana():
    """Il drawdown che conta non è quello tipico ma quello che ti fa
    smettere."""
    rep = rs.simulate(_trend_following_r(), trades_per_year=25, paths=1500)
    scelto_su_coda = max([s for s in rep.scenarios if s.p95_max_drawdown_pct <= 20],
                          key=lambda s: s.risk_pct, default=None)
    scelto_su_mediana = max([s for s in rep.scenarios if s.median_max_drawdown_pct <= 20],
                             key=lambda s: s.risk_pct, default=None)
    if scelto_su_coda and scelto_su_mediana:
        assert scelto_su_coda.risk_pct <= scelto_su_mediana.risk_pct


def test_frequenza_dedotta_dal_backtest():
    class T:
        pass
    trades = [T() for _ in range(50)]
    assert rs.trades_per_year_from(trades, span_days=730) == pytest.approx(25.0, rel=0.05)
    assert rs.trades_per_year_from(trades, span_days=0) == 0.0
    assert rs.trades_per_year_from([], span_days=365) == 0.0
