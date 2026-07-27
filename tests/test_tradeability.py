"""Test per il Technical Tradeability Score (src/tradeability.py),
ricostruito da Prompt_Cowork_Technical_Tradeability_Score.md.

Ogni criterio è testato in isolamento su serie storiche sintetiche
costruite per avere una proprietà statistica nota (nessun accesso di
rete/yfinance) — le assert usano soprattutto disuguaglianze (es. "il
punteggio del titolo trending è più alto di quello mean-reverting")
invece di valori assoluti fragili, tranne dove il valore atteso è
deterministico (override FX/crypto, formula di interpolazione).

I sei criteri di validazione della spec sono coperti:
  1. ETF su indice -> TTS alto (liquidità/gap ottimi, no earnings)
  2. Small-cap illiquida -> esclusa dalla regola hard sulla liquidità
  3. Titolo strutturalmente mean-reverting -> Trendiness basso (Hurst<0,5)
  4. Mega-cap con earnings violenti -> penalizzata sul criterio 5
  5. Override FX/crypto sulla liquidità si attivano correttamente
  6. Scomposizione coerente (i sub-score sommano al TTS coi pesi dichiarati)
"""
from unittest import mock

import numpy as np
import pandas as pd
import pytest

from src import data_provider as dp
from src import tradeability as tr


# ---------------------------------------------------------------------------
# Generatori di serie storiche sintetiche
# ---------------------------------------------------------------------------

def _idx(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)


def _make_momentum_history(n=700, phi=0.18, drift=0.0006, noise=0.006, start=50.0,
                            seed=5, volume=8_000_000.0) -> pd.DataFrame:
    """Rendimenti con autocorrelazione positiva (AR(1), phi>0): l'unico
    modo per ottenere davvero un esponente di Hurst > 0,5 con lo
    stimatore a varianza-scaling — un drift costante senza rendimenti
    autocorrelati resta un random walk (H~0,5) anche se il prezzo sale."""
    rng = np.random.default_rng(seed)
    eps = rng.normal(0, noise, n)
    r = np.zeros(n)
    for i in range(1, n):
        r[i] = phi * r[i - 1] + eps[i] + drift
    close = start * np.exp(np.cumsum(r))
    idx = _idx(n)
    high = np.maximum(close, np.roll(close, 1)) * (1 + rng.uniform(0.0005, 0.004, n))
    low = np.minimum(close, np.roll(close, 1)) * (1 - rng.uniform(0.0005, 0.004, n))
    open_ = close * (1 + rng.normal(0, 0.001, n))
    volume_arr = rng.integers(int(volume * 0.8), int(volume * 1.2), n).astype(float)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close,
                          "Volume": volume_arr}, index=idx)


def _make_meanreverting_history(n=700, mu=50.0, kappa=0.25, noise=0.8, seed=4,
                                 volume=8_000_000.0) -> pd.DataFrame:
    """Processo Ornstein-Uhlenbeck: oscilla stretto attorno a `mu`, non si
    allontana mai — strutturalmente ostile al trend-following (ER basso,
    ADX basso, Hurst << 0,5). Il caso 'titolo cattivo' #3 della spec."""
    rng = np.random.default_rng(seed)
    x = np.empty(n)
    x[0] = mu
    for i in range(1, n):
        x[i] = x[i - 1] + kappa * (mu - x[i - 1]) + rng.normal(0, noise)
    idx = _idx(n)
    high = np.maximum(x, np.roll(x, 1)) + rng.uniform(0.05, 0.3, n)
    low = np.minimum(x, np.roll(x, 1)) - rng.uniform(0.05, 0.3, n)
    open_ = x + rng.normal(0, 0.1, n)
    volume_arr = rng.integers(int(volume * 0.8), int(volume * 1.2), n).astype(float)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": x,
                          "Volume": volume_arr}, index=idx)


def _make_flat_history(n=400, pct_range=0.025, start=100.0, volume=3_000_000.0,
                        seed=1) -> pd.DataFrame:
    """Serie piatta con range giornaliero (High-Low) fissato a `pct_range`
    del prezzo — isola l'ATR% al valore voluto per testare Criterio 2."""
    rng = np.random.default_rng(seed)
    close = np.full(n, start) + rng.normal(0, 0.05, n)
    idx = _idx(n)
    half = close * pct_range / 2
    volume_arr = np.full(n, volume)
    return pd.DataFrame({"Open": close, "High": close + half, "Low": close - half,
                          "Close": close, "Volume": volume_arr}, index=idx)


def _make_illiquid_history(n=400, start=10.0, volume=200.0, seed=2) -> pd.DataFrame:
    hist = _make_flat_history(n=n, pct_range=0.02, start=start, volume=volume, seed=seed)
    return hist


# ---------------------------------------------------------------------------
# _piecewise_score — interpolazione lineare a tratti, clamp, curve a campana
# ---------------------------------------------------------------------------

def test_piecewise_score_clamp_sotto_e_sopra_le_ancore():
    anchors = [(0, 0), (10, 50), (20, 100)]
    assert tr._piecewise_score(-5, anchors) == 0
    assert tr._piecewise_score(25, anchors) == 100


def test_piecewise_score_interpolazione_lineare():
    anchors = [(0, 0), (10, 100)]
    assert tr._piecewise_score(5, anchors) == pytest.approx(50.0)


def test_piecewise_score_curva_a_campana_non_monotona():
    # Stessa lista usata per il Criterio 2 (ATR%): non monotona in y, deve
    # comunque interpolare correttamente su entrambi i lati del picco.
    assert tr._piecewise_score(2.5, tr.STANDARD_ATR_ANCHORS) == pytest.approx(100.0)
    assert tr._piecewise_score(0.8, tr.STANDARD_ATR_ANCHORS) == pytest.approx(10.0)
    assert tr._piecewise_score(10.0, tr.STANDARD_ATR_ANCHORS) == pytest.approx(10.0)


def test_piecewise_score_valore_none():
    assert tr._piecewise_score(None, [(0, 0), (1, 100)]) is None


# ---------------------------------------------------------------------------
# Criterio 1 — Liquidità (+ override FX/crypto, criterio di validazione #5)
# ---------------------------------------------------------------------------

def test_liquidita_adv_alto_in_eur_punteggio_alto():
    hist = _make_flat_history(volume=8_000_000.0, start=50.0)
    out = tr._score_liquidity("TEST", hist, "EUR", "EQUITY")
    assert out["score"] > 70
    assert out["override_note"] is None


def test_liquidita_adv_basso_punteggio_basso_sotto_soglia_hard():
    hist = _make_illiquid_history(volume=200.0)
    out = tr._score_liquidity("SMALLCAP", hist, "EUR", "EQUITY")
    assert out["score"] < tr.HARD_EXCLUSION_LIQUIDITY_MIN


def test_liquidita_volume_nullo_non_calcolabile():
    hist = _make_flat_history(volume=0.0)
    out = tr._score_liquidity("NOVOL", hist, "EUR", "EQUITY")
    assert out["score"] is None


def test_override_fx_valore_fisso_dichiarato():
    hist = _make_flat_history()
    out = tr._score_liquidity("EURUSD=X", hist, "USD", "CURRENCY")
    assert out["score"] == tr.FX_LIQUIDITY_OVERRIDE
    assert out["adv_eur"] is None
    assert "FX" in out["override_note"]


def test_override_crypto_major_vs_altcoin():
    hist = _make_flat_history()
    btc = tr._score_liquidity("BTC-USD", hist, "USD", "CRYPTOCURRENCY")
    eth = tr._score_liquidity("ETH-USD", hist, "USD", "CRYPTOCURRENCY")
    doge = tr._score_liquidity("DOGE-USD", hist, "USD", "CRYPTOCURRENCY")
    assert btc["score"] == eth["score"] == tr.CRYPTO_MAJOR_LIQUIDITY_OVERRIDE
    assert doge["score"] == tr.CRYPTO_OTHER_LIQUIDITY_OVERRIDE
    assert doge["score"] < btc["score"]
    for out in (btc, eth, doge):
        assert out["override_note"] is not None  # mai un override silenzioso


def test_liquidita_valuta_non_eur_usa_tasso_di_cambio(monkeypatch):
    hist = _make_flat_history(volume=8_000_000.0, start=50.0)
    monkeypatch.setattr(dp, "get_fx_rate", lambda quote, base="EUR": 2.0)
    out = tr._score_liquidity("TEST", hist, "USD", "EQUITY")
    dollar_adv = float((hist["Volume"] * hist["Close"]).tail(tr.ADV_LOOKBACK_DAYS).mean())
    assert out["adv_eur"] == pytest.approx(dollar_adv / 2.0)


def test_liquidita_tasso_di_cambio_non_disponibile_segnala_nota(monkeypatch):
    hist = _make_flat_history(volume=8_000_000.0, start=50.0)
    monkeypatch.setattr(dp, "get_fx_rate", lambda quote, base="EUR": None)
    out = tr._score_liquidity("TEST", hist, "USD", "EQUITY")
    assert out["override_note"] is not None
    assert "cambio" in out["override_note"].lower()


# ---------------------------------------------------------------------------
# Criterio 2 — Volatilità ATR% (curva a campana)
# ---------------------------------------------------------------------------

def test_volatilita_sweet_spot_punteggio_massimo():
    hist = _make_flat_history(pct_range=0.025)
    atr_series = tr.tech.atr(hist, period=tr.ATR_PERIOD)
    out = tr._score_volatility(hist["Close"], atr_series, "EQUITY")
    assert out["score"] == pytest.approx(100.0, abs=1.0)
    assert out["curve"] == "standard"


def test_volatilita_troppo_quieta_e_troppo_volatile_penalizzate():
    for pct in (0.003, 0.12):
        hist = _make_flat_history(pct_range=pct)
        atr_series = tr.tech.atr(hist, period=tr.ATR_PERIOD)
        out = tr._score_volatility(hist["Close"], atr_series, "EQUITY")
        assert out["score"] == pytest.approx(10.0, abs=1.0)


def test_volatilita_curva_crypto_diversa_dalla_standard():
    # Alla stessa ATR% (5%), la curva standard penalizza fortemente,
    # quella crypto è nel suo sweet spot (spec, adattamento per classe).
    hist = _make_flat_history(pct_range=0.05)
    atr_series = tr.tech.atr(hist, period=tr.ATR_PERIOD)
    standard = tr._score_volatility(hist["Close"], atr_series, "EQUITY")
    crypto = tr._score_volatility(hist["Close"], atr_series, "CRYPTOCURRENCY")
    assert crypto["curve"] == "crypto"
    assert crypto["score"] > standard["score"]


# ---------------------------------------------------------------------------
# Criterio 3 — Trendiness (ER, ADX medio, Hurst) — criterio di validazione #3
# ---------------------------------------------------------------------------

def test_trendiness_momentum_supera_nettamente_mean_reverting():
    trending = _make_momentum_history()
    meanrevert = _make_meanreverting_history()
    t_trend = tr._score_trendiness(trending, trending["Close"])
    t_mr = tr._score_trendiness(meanrevert, meanrevert["Close"])
    assert t_trend["score"] > t_mr["score"] + 20
    assert t_trend["hurst"] > 0.5
    assert t_mr["hurst"] < 0.5
    assert t_mr["score"] < tr.HARD_EXCLUSION_TRENDINESS_MIN + 5  # vicino/sotto la soglia hard


def test_trendiness_media_delle_tre_sottometriche_disponibili():
    hist = _make_momentum_history()
    out = tr._score_trendiness(hist, hist["Close"])
    parts = [out["er_score"], out["adx_score"], out["hurst_score"]]
    assert out["score"] == pytest.approx(sum(parts) / 3, abs=0.01)
    assert out["n_submetrics_missing"] == 0


# ---------------------------------------------------------------------------
# Criterio 4 — Frequenza dei gap
# ---------------------------------------------------------------------------

def test_gap_frequency_nessun_gap_punteggio_alto():
    hist = _make_flat_history(pct_range=0.02)
    atr_series = tr.tech.atr(hist, period=tr.ATR_PERIOD)
    out = tr._score_gap_frequency(hist, atr_series, "EQUITY")
    assert out["gap_frequency_pct"] == pytest.approx(0.0, abs=1.0)
    assert out["score"] > 90


def test_gap_frequency_molti_gap_punteggio_basso():
    hist = _make_flat_history(pct_range=0.02)
    opens = hist["Open"].to_numpy().copy()
    closes = hist["Close"].to_numpy()
    for i in range(5, len(hist), 3):  # gap frequenti: circa un giorno su tre
        opens[i] = closes[i - 1] * (1.06 if i % 2 == 0 else 0.94)
    hist = hist.assign(Open=opens)
    atr_series = tr.tech.atr(hist, period=tr.ATR_PERIOD)
    out = tr._score_gap_frequency(hist, atr_series, "EQUITY")
    assert out["gap_frequency_pct"] > 25
    assert out["score"] < 40


def test_gap_frequency_crypto_non_premiata_a_100_con_rischio_weekend():
    hist = _make_flat_history(pct_range=0.02)
    opens = hist["Open"].to_numpy().copy()
    closes = hist["Close"].to_numpy()
    mondays = np.where(hist.index.weekday == 0)[0]
    for i in mondays:
        if i > 0:
            opens[i] = closes[i - 1] * 1.08  # gap sistematico ogni lunedì
    hist = hist.assign(Open=opens)
    atr_series = tr.tech.atr(hist, period=tr.ATR_PERIOD)
    out = tr._score_gap_frequency(hist, atr_series, "CRYPTOCURRENCY")
    assert out["weekend_gap_frequency_pct"] > 50
    assert out["score"] < 100


# ---------------------------------------------------------------------------
# Criterio 5 — Sensibilità earnings — criterio di validazione #4
# ---------------------------------------------------------------------------

def test_earnings_classe_esente_punteggio_100_senza_rete():
    hist = _make_flat_history()
    for asset_class in ("ETF", "INDEX", "CURRENCY", "CRYPTOCURRENCY", "FUTURE", "MUTUALFUND"):
        out = tr._score_earnings("X", asset_class, hist)
        assert out["score"] == 100.0
        assert out["note"] is not None


def test_earnings_movimenti_violenti_penalizzati_e_prossima_data_riportata(monkeypatch):
    hist = _make_flat_history(n=520, pct_range=0.01, start=50.0)
    past_dates = hist.index[::80][:5]
    future_date = pd.Timestamp.today().normalize() + pd.Timedelta(days=20)
    edf = pd.DataFrame(
        {"Reported EPS": [1.0] * (len(past_dates) + 1)},
        index=pd.DatetimeIndex(list(past_dates) + [future_date]),
    )
    hist_shocked = hist.copy()
    for d in past_dates:
        pos = hist_shocked.index.get_loc(d)
        if pos > 0:
            hist_shocked.iloc[pos, hist_shocked.columns.get_loc("Close")] = (
                hist_shocked.iloc[pos - 1]["Close"] * 1.08
            )
    monkeypatch.setattr(dp, "get_earnings_dates", lambda symbol, limit=16: edf)
    out = tr._score_earnings("MEGACAP", "EQUITY", hist_shocked)
    assert out["avg_move_pct"] > 5
    assert out["score"] < 50
    assert out["next_earnings_date"] == future_date.date().isoformat()


def test_earnings_dati_non_disponibili_riduce_confidenza_non_azzera(monkeypatch):
    hist = _make_flat_history()
    monkeypatch.setattr(dp, "get_earnings_dates", lambda symbol, limit=16: pd.DataFrame())
    out = tr._score_earnings("NODATA", "EQUITY", hist)
    assert out["score"] is None  # mai stimato "a occhio": n/d, non un valore neutro
    assert out["note"] is not None


# ---------------------------------------------------------------------------
# Criterio 6 — Autocorrelazione (sull'orizzonte di posizionamento)
# ---------------------------------------------------------------------------

def test_autocorrelazione_momentum_positiva_supera_mean_reverting():
    trending = _make_momentum_history()
    meanrevert = _make_meanreverting_history()
    ac_trend = tr._score_autocorrelation(trending["Close"])
    ac_mr = tr._score_autocorrelation(meanrevert["Close"])
    assert ac_trend["score"] > ac_mr["score"]


# ---------------------------------------------------------------------------
# Orchestrazione — compute_tradeability / build_tradeability_report
# ---------------------------------------------------------------------------

def test_compute_tradeability_serie_troppo_corta_non_calcolabile(monkeypatch):
    short_hist = _make_flat_history(n=50)
    monkeypatch.setattr(dp, "get_history", lambda symbol, period="6mo", interval="1d": short_hist)
    out = tr.compute_tradeability("TROPPO_CORTO")
    assert out["computable"] is False
    assert "insufficiente" in out["reason"].lower()


def test_compute_tradeability_esclusione_hard_su_illiquidita(monkeypatch):
    hist = _make_illiquid_history(n=400, volume=100.0)
    monkeypatch.setattr(dp, "get_history", lambda symbol, period="6mo", interval="1d": hist)
    monkeypatch.setattr(dp, "get_ticker", lambda symbol: mock.Mock(info={"currency": "EUR", "quoteType": "EQUITY"}))
    monkeypatch.setattr(dp, "get_earnings_dates", lambda symbol, limit=16: pd.DataFrame())
    out = tr.compute_tradeability("SMALLCAP.MI")
    assert out["computable"] is True
    assert out["hard_excluded"] is True
    assert out["band"] == "Inadatto (esclusione hard)"
    assert any("Liquidità" in r for r in out["exclusion_reasons"])


def test_compute_tradeability_etf_indice_punteggio_alto(monkeypatch):
    """Criterio di validazione #1: un ETF su indice — liquidità alta, gap
    minimi, nessuna sensibilità earnings — ottiene un TTS alto."""
    hist = _make_momentum_history(volume=200_000_000.0, phi=0.05, noise=0.004)
    monkeypatch.setattr(dp, "get_history", lambda symbol, period="6mo", interval="1d": hist)
    monkeypatch.setattr(dp, "get_ticker", lambda symbol: mock.Mock(info={"currency": "EUR", "quoteType": "ETF"}))
    out = tr.compute_tradeability("SWDA.MI")
    assert out["computable"] is True
    assert out["sub_scores"]["earnings"] == 100.0
    assert out["sub_scores"]["liquidity"] is not None and out["sub_scores"]["liquidity"] > 90
    assert not out["hard_excluded"]


def test_compute_tradeability_scomposizione_coerente_col_totale(monkeypatch):
    """Criterio di validazione #6: il TTS ricalcolato a mano dai sub-score
    e dai pesi dichiarati deve combaciare con quello riportato."""
    hist = _make_momentum_history(volume=50_000_000.0)
    monkeypatch.setattr(dp, "get_history", lambda symbol, period="6mo", interval="1d": hist)
    monkeypatch.setattr(dp, "get_ticker", lambda symbol: mock.Mock(info={"currency": "EUR", "quoteType": "EQUITY"}))
    monkeypatch.setattr(dp, "get_earnings_dates", lambda symbol, limit=16: pd.DataFrame())
    out = tr.compute_tradeability("TEST.MI")
    s = out["sub_scores"]
    available = {k: v for k, v in s.items() if v is not None}
    total_w = sum(tr.WEIGHTS[k] for k in available)
    expected = sum(v * tr.WEIGHTS[k] for k, v in available.items()) / total_w
    assert out["tts"] == pytest.approx(round(expected, 1), abs=0.05)
    assert 0 <= out["confidence"] <= 1


def test_build_tradeability_report_un_errore_non_blocca_gli_altri(monkeypatch):
    good_hist = _make_momentum_history(volume=50_000_000.0)

    def fake_get_history(symbol, period="6mo", interval="1d"):
        if symbol == "ROTTO":
            raise RuntimeError("ticker non valido")
        return good_hist

    monkeypatch.setattr(dp, "get_history", fake_get_history)
    monkeypatch.setattr(dp, "get_ticker", lambda symbol: mock.Mock(info={"currency": "EUR", "quoteType": "EQUITY"}))
    monkeypatch.setattr(dp, "get_earnings_dates", lambda symbol, limit=16: pd.DataFrame())

    report = tr.build_tradeability_report(["ROTTO", "BUONO.MI"])
    assert report["results"]["ROTTO"]["computable"] is False
    assert report["results"]["BUONO.MI"]["computable"] is True
    assert any(r["symbol"] == "BUONO.MI" for r in report["ranking"])
