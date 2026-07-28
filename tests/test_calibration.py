"""Test della calibrazione della confidenza (src/engine/calibration.py).

La calibrazione è il cancello empirico che precede qualunque uso della
leva scalata sulla confidenza. Deve quindi sbagliare per eccesso di
prudenza: negare il via libera quando il campione è sottile è corretto,
concederlo su rumore è il modo in cui un conto salta.

I test verificano soprattutto che il cancello **non si apra** nei casi in
cui non deve: pochi trade, bande troppo sottili, confidenza che non
corrisponde al win rate realizzato.
"""
import numpy as np
import pandas as pd
import pytest

from src.engine import calibration as cal


def _trades(confidence: float, n: int, win_rate: float) -> pd.DataFrame:
    """n trade con la confidenza data e un win rate esatto."""
    wins = int(round(n * win_rate))
    losses = n - wins
    return pd.DataFrame({
        "confidence": [confidence] * n,
        "net_pnl_eur": [100.0] * wins + [-100.0] * losses,
        "net_r": [1.0] * wins + [-1.0] * losses,
    })


def _ben_calibrato() -> pd.DataFrame:
    return pd.concat([_trades(60, 25, 0.60), _trades(77, 25, 0.77), _trades(92, 25, 0.92)],
                      ignore_index=True)


# ---------------------------------------------------------------------------
# Il cancello non deve aprirsi quando non deve
# ---------------------------------------------------------------------------

def test_nessun_trade_nessuna_calibrazione():
    report = cal.build_calibration(pd.DataFrame())
    assert report.leverage_gate_passed is False
    assert report.n_trades == 0
    assert report.gate_reason


def test_campione_totale_insufficiente_blocca_il_cancello():
    report = cal.build_calibration(_trades(75, 10, 0.75))
    assert report.leverage_gate_passed is False
    assert str(cal.MIN_TOTAL_TRADES_FOR_GATE) in report.gate_reason


def test_bande_troppo_sottili_bloccano_il_cancello():
    """Campione totale sufficiente ma distribuito su bande sotto la soglia
    di interpretabilità: nessuna banda dice nulla di affidabile."""
    df = pd.concat([_trades(60, 19, 0.60), _trades(77, 19, 0.77), _trades(92, 19, 0.92)],
                    ignore_index=True)
    report = cal.build_calibration(df)
    assert report.n_with_confidence >= cal.MIN_TOTAL_TRADES_FOR_GATE
    assert all(not b.is_interpretable for b in report.buckets)
    assert report.leverage_gate_passed is False
    assert "interpretabile" in report.gate_reason


def test_confidenza_che_non_vale_blocca_il_cancello():
    """Il caso che il cancello esiste per intercettare: la banda alta
    promette il 92% e realizza il 30%."""
    df = pd.concat([_trades(60, 25, 0.60), _trades(77, 25, 0.77), _trades(92, 25, 0.30)],
                    ignore_index=True)
    report = cal.build_calibration(df)
    assert report.leverage_gate_passed is False
    assert "85-100" in report.gate_reason


def test_cancello_superato_solo_con_tutte_le_condizioni():
    report = cal.build_calibration(_ben_calibrato())
    assert report.leverage_gate_passed is True
    assert all(b.is_calibrated for b in report.buckets if b.is_interpretable)
    assert report.mean_absolute_error is not None
    assert report.mean_absolute_error < 0.05


# ---------------------------------------------------------------------------
# Bucket e intervalli
# ---------------------------------------------------------------------------

def test_bucket_vuoto_non_e_calibrato_ne_interpretabile():
    report = cal.build_calibration(_trades(60, 25, 0.60))
    alta = [b for b in report.buckets if b.label == "85-100"][0]
    assert alta.n_trades == 0
    assert alta.is_interpretable is False
    assert alta.is_calibrated is False
    assert alta.realized_win_rate is None


def test_intervallo_di_wilson_contiene_il_win_rate_realizzato():
    report = cal.build_calibration(_trades(77, 40, 0.75))
    banda = [b for b in report.buckets if b.label == "70-84"][0]
    assert banda.ci_low <= banda.realized_win_rate <= banda.ci_high


def test_banda_non_interpretabile_non_viene_dichiarata_calibrata():
    """Con pochi trade l'intervallo è larghissimo e quasi tutto ci
    cadrebbe dentro: è il punto in cui un diagramma di affidabilità
    inganna più facilmente."""
    report = cal.build_calibration(_trades(77, 5, 0.80))
    banda = [b for b in report.buckets if b.label == "70-84"][0]
    assert banda.n_trades == 5
    assert banda.is_interpretable is False
    assert banda.is_calibrated is False


def test_errore_di_calibrazione_ha_il_segno_giusto():
    report = cal.build_calibration(_trades(77, 30, 0.50))
    banda = [b for b in report.buckets if b.label == "70-84"][0]
    assert banda.error < 0            # realizza meno di quanto promette
    assert banda.predicted_win_rate == pytest.approx(0.77, abs=0.01)


def test_r_medio_per_banda():
    report = cal.build_calibration(_trades(77, 30, 0.50))
    banda = [b for b in report.buckets if b.label == "70-84"][0]
    assert banda.avg_r == pytest.approx(0.0, abs=0.05)   # metà +1R, metà −1R


# ---------------------------------------------------------------------------
# Robustezza dell'ingresso
# ---------------------------------------------------------------------------

def test_trade_senza_confidenza_sono_contati_ma_esclusi_e_dichiarati():
    df = pd.concat([_ben_calibrato(),
                    pd.DataFrame({"confidence": [None] * 5,
                                  "net_pnl_eur": [100.0] * 5, "net_r": [1.0] * 5})],
                    ignore_index=True)
    report = cal.build_calibration(df)
    assert report.n_trades == 80
    assert report.n_with_confidence == 75
    assert any("non hanno una confidenza" in n for n in report.notes)


def test_vincente_giudicato_sul_netto():
    """Un trade positivo al lordo ma negativo dopo i costi non è una
    vittoria: contarlo tale gonfierebbe il win rate realizzato."""
    df = pd.DataFrame({"confidence": [77] * 20,
                        "net_pnl_eur": [-1.0] * 20,   # tutti in perdita al netto
                        "net_r": [0.5] * 20})          # ma positivi in R lordo
    report = cal.build_calibration(df)
    banda = [b for b in report.buckets if b.label == "70-84"][0]
    assert banda.realized_win_rate == 0.0


def test_confidenza_non_numerica_non_rompe_il_calcolo():
    df = pd.DataFrame({"confidence": ["alta", None, 77],
                        "net_pnl_eur": [100.0, 100.0, 100.0],
                        "net_r": [1.0, 1.0, 1.0]})
    report = cal.build_calibration(df)
    assert report.n_trades == 3
    assert report.n_with_confidence == 1


def test_reliability_points_ha_una_riga_per_banda():
    points = cal.reliability_points(cal.build_calibration(_ben_calibrato()))
    assert len(points) == len(cal.CONFIDENCE_BUCKETS)
    assert set(["Banda", "Trade", "Confidenza predetta", "Win rate realizzato"]).issubset(points.columns)


def test_bande_allineate_alla_mappa_della_leva():
    """Calibrare su intervalli diversi da quelli su cui si deciderebbe la
    leva non direbbe nulla di utile."""
    from src.engine.risk import CONFIDENCE_LEVERAGE_BANDS

    operative = [(lo, hi) for lo, hi, mult in CONFIDENCE_LEVERAGE_BANDS if mult > 0]
    calibrate = [(lo, hi) for lo, hi, _ in cal.CONFIDENCE_BUCKETS]
    assert operative == calibrate
