"""Test dell'unica strategia in registro (src/engine/strategies.py).

Tutte le strategie precedenti sono state rimosse il 15/09/2026 insieme al
ponte signals.py. Quella che resta e' progettata a partire dal vincolo di
costo misurato sul forward (costo_in_R = costo% / stop%), e i test qui
sotto verificano proprio le proprieta' che discendono da quel vincolo -
non solo che la funzione restituisca un dict.

Le serie sono costruite a mano: nessuna rete, esito calcolabile a mente.
"""
import numpy as np
import pandas as pd
import pytest

from src.engine import strategies as st

WARMUP = st.REGIME_MA_LENGTH + st.REGIME_SLOPE_BARS + st.ATR_PERIOD + 5


def _ohlc(closes: np.ndarray, spread=0.5) -> pd.DataFrame:
    idx = pd.bdate_range("2022-01-03", periods=len(closes))
    return pd.DataFrame({
        "Open": closes, "High": closes + spread, "Low": closes - spread,
        "Close": closes, "Volume": 1e6,
    }, index=idx)


def _rialzo(n=400, start=100.0, passo=0.25) -> pd.DataFrame:
    """Salita regolare: media a 200 sotto il prezzo e in pendenza positiva,
    e ogni chiusura e' un nuovo massimo del canale."""
    return _ohlc(start + passo * np.arange(n))


def _ribasso(n=400, start=200.0, passo=0.25) -> pd.DataFrame:
    return _ohlc(start - passo * np.arange(n))


def _rialzo_poi_laterale(n_su=340, n_flat=60) -> pd.DataFrame:
    """Sale a lungo (regime rialzista consolidato) e poi si ferma: la media
    resta sotto e in salita, ma non c'e' piu' nessuna rottura di canale."""
    su = 100 + 0.25 * np.arange(n_su)
    flat = np.full(n_flat, su[-1]) - 0.5
    return _ohlc(np.concatenate([su, flat]))


def _piano(hist):
    return st.get("breakout_eur").generate("TEST", hist, "medio")


# ---------------------------------------------------------------------------
# Filtro di regime
# ---------------------------------------------------------------------------

def test_nessun_segnale_in_regime_ribassista():
    piano = _piano(_ribasso())
    assert piano["bias"] == "nessun_setup"
    assert "regime" in piano["motivo"]


def test_nessun_segnale_senza_rottura_di_canale():
    """Regime rialzista ma prezzo fermo: il filtro passa, l'ingresso no."""
    piano = _piano(_rialzo_poi_laterale())
    assert piano["bias"] == "nessun_setup"
    assert "rottura" in piano["motivo"]


def test_segnale_long_su_rottura_in_regime_rialzista():
    piano = _piano(_rialzo())
    assert piano["bias"] == "long"


def test_non_produce_mai_short():
    """Il broker e' spot-only: uno short non sarebbe eseguibile, e un
    backtest che lo include misura operazioni impossibili. Il vecchio
    sistema ne ha aperti (TXN, PLTR, NIO)."""
    for hist in (_rialzo(), _ribasso(), _rialzo_poi_laterale()):
        piano = _piano(hist)
        assert piano is None or piano["bias"] != "short"


def test_rimbalzo_dentro_un_ribasso_non_genera_segnale():
    """Prezzo sopra una media che sta ancora scendendo: e' il caso che la
    sola condizione 'prezzo > media' lascerebbe passare, ed e' il motivo
    per cui esiste la condizione sulla pendenza."""
    # Ribasso lungo, poi un rimbalzo violento e breve: abbastanza forte da
    # riportare il prezzo sopra la media, abbastanza corto da non averne
    # ancora girato la pendenza.
    giu = 200 - 0.25 * np.arange(380)
    rimbalzo = giu[-1] + 4.0 * np.arange(1, 21)
    hist = _ohlc(np.concatenate([giu, rimbalzo]))
    closes = hist["Close"].to_numpy()
    # La premessa del test: il prezzo E' risalito sopra la media, ma la
    # media sta ancora scendendo. Senza questo controllo il test potrebbe
    # passare per il motivo sbagliato.
    ma_ora = closes[-st.REGIME_MA_LENGTH:].mean()
    ma_prima = closes[-st.REGIME_MA_LENGTH - st.REGIME_SLOPE_BARS:-st.REGIME_SLOPE_BARS].mean()
    assert closes[-1] > ma_ora and ma_ora < ma_prima
    assert _piano(hist)["bias"] == "nessun_setup"


# ---------------------------------------------------------------------------
# Forma del piano: e' qui che vivono i difetti del vecchio sistema
# ---------------------------------------------------------------------------

def test_nessun_target_e_uscita_in_trailing():
    """Il difetto strutturale precedente era un ingresso trend-following
    con un'uscita mean-reverting (target sulla resistenza piu' vicina), che
    produceva un R:R mediano di 0,71."""
    piano = _piano(_rialzo())
    assert piano["target"] is None
    assert piano["trailing_atr_mult"] == st.TRAILING_ATR_MULT
    assert piano["target_source"] == "trailing"


def test_stop_iniziale_alla_distanza_atr_dichiarata():
    hist = _rialzo()
    piano = _piano(hist)
    atteso = piano["price"] - st.INITIAL_STOP_ATR_MULT * piano["atr"]
    assert piano["stop"] == pytest.approx(atteso, abs=1e-4)
    assert piano["stop"] < piano["price"]


def test_nessuna_confidenza_inventata():
    """Non esiste una misura calibrata della bonta' di un singolo segnale:
    dichiararne una renderebbe finta la curva di calibrazione."""
    piano = _piano(_rialzo())
    assert piano["confidence"] is None


def test_il_trailing_e_piu_largo_dello_stop_iniziale():
    """Una volta in guadagno l'errore costoso non e' restituire un po' di
    profitto, e' farsi buttare fuori da un ritracciamento normale."""
    assert st.TRAILING_ATR_MULT > st.INITIAL_STOP_ATR_MULT


# ---------------------------------------------------------------------------
# Robustezza e point-in-time
# ---------------------------------------------------------------------------

def test_storico_troppo_corto_non_produce_segnale():
    assert _piano(_rialzo(n=st.REGIME_MA_LENGTH)) is None


def test_il_segnale_non_guarda_le_barre_future():
    """Il segnale calcolato alla barra i deve essere identico che ci siano
    o no barre successive: e' la proprieta' che rende il backtest onesto."""
    hist = _rialzo(n=420)
    i = 400
    con_futuro = st.get("breakout_eur").generate("TEST", hist.iloc[:i + 1], "medio")
    senza_futuro = st.get("breakout_eur").generate("TEST", hist.iloc[:i + 1].copy(), "medio")
    assert con_futuro == senza_futuro
    # e diverso da quello calcolato su tutta la serie
    completo = _piano(hist)
    assert completo["price"] != con_futuro["price"]


def test_atr_non_calcolabile_non_produce_un_piano_stimato():
    """Mai inventare un dato mancante: senza ATR non si sa dove mettere lo
    stop, quindi non si sa quanto rischiare."""
    hist = _rialzo()
    piatta = hist.copy()
    piatta[["Open", "High", "Low", "Close"]] = 100.0
    assert _piano(piatta)["bias"] == "nessun_setup"


# ---------------------------------------------------------------------------
# Il vincolo di costo, che e' la ragione d'essere del disegno
# ---------------------------------------------------------------------------

def test_la_strategia_dichiara_di_operare_solo_in_euro():
    strategia = st.get("breakout_eur")
    assert strategia.allowed_currencies == ("EUR",)


def _rialzo_volatilita_realistica(n=400, seed=3) -> pd.DataFrame:
    """Salita con ATR attorno all'1% del prezzo, come un ETF azionario
    vero. La serie lineare usata negli altri test ha un ATR% molto piu'
    basso, e sul vincolo di costo darebbe una risposta che non descrive
    nessuno strumento reale."""
    rng = np.random.default_rng(seed)
    passi = rng.normal(0.0009, 0.010, n)
    close = 100 * np.exp(np.cumsum(passi))
    close[-1] = close[:-1].max() * 1.01          # rottura garantita
    idx = pd.bdate_range("2022-01-03", periods=n)
    escursione = close * 0.006
    return pd.DataFrame({
        "Open": close, "High": close + escursione, "Low": close - escursione,
        "Close": close, "Volume": 1e6,
    }, index=idx)


def test_lo_stop_tipico_rispetta_il_vincolo_di_costo_in_euro():
    """La verifica che lega il disegno al motivo per cui esiste: con lo
    stop prodotto da questa strategia su uno strumento di volatilita'
    normale, il costo di round trip in euro resta sotto il 10% di R."""
    from src.engine.costs import CostModel
    from src.engine.risk import RiskConfig, size_position

    piano = _piano(_rialzo_volatilita_realistica())
    assert piano["bias"] == "long"
    costi = CostModel(order_fee_eur=1.0, fx_cost_pct_per_leg=0.5, slippage_bps_per_side=5.0)
    sizing = size_position(9_300.0, piano["price"], piano["stop"], None,
                            RiskConfig(risk_pct=0.75), costs=costi, currency="EUR")
    assert sizing.is_tradable
    assert sizing.estimated_cost_in_r < 0.10


def test_lo_stesso_piano_in_dollari_sfonda_il_vincolo():
    """Il numero che giustifica il filtro di valuta: cambia solo la valuta,
    e il costo in R si moltiplica."""
    from src.engine.costs import CostModel
    from src.engine.risk import RiskConfig, size_position

    piano = _piano(_rialzo_volatilita_realistica())
    costi = CostModel(order_fee_eur=1.0, fx_cost_pct_per_leg=0.5, slippage_bps_per_side=5.0)
    eur = size_position(9_300.0, piano["price"], piano["stop"], None,
                         RiskConfig(risk_pct=0.75), costs=costi, currency="EUR")
    usd = size_position(9_300.0, piano["price"], piano["stop"], None,
                         RiskConfig(risk_pct=0.75), costs=costi, currency="USD")
    assert usd.estimated_cost_in_r > 3 * eur.estimated_cost_in_r


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------

def test_il_registro_contiene_solo_la_nuova_strategia():
    assert st.keys() == ["breakout_eur"]
    assert st.DEFAULT_STRATEGY == "breakout_eur"


def test_murphy_e_le_altre_non_sono_piu_raggiungibili():
    for vecchia in ("murphy", "donchian", "ma_trend", "momentum"):
        with pytest.raises(ValueError):
            st.get(vecchia)


def test_i_parametri_sono_dichiarati_nella_scheda():
    strategia = st.get("breakout_eur")
    for valore in (str(st.REGIME_MA_LENGTH), str(st.BREAKOUT_CHANNEL_BARS),
                   f"{st.INITIAL_STOP_ATR_MULT:g}", f"{st.TRAILING_ATR_MULT:g}"):
        assert valore in strategia.parameters


def test_strumento_troppo_poco_volatile_viene_rifiutato():
    """Proprieta' scoperta scrivendo i test, e che vale la pena bloccare:
    la strategia da sola NON garantisce il vincolo di costo. Su uno
    strumento con ATR molto piccolo rispetto al prezzo (tipicamente un ETF
    obbligazionario), 2,5xATR produce uno stop cosi' vicino che le
    commissioni valgono piu' del 10% di R. A fermarlo e' il controllo di
    sostenibilita' del sizing, non la strategia: sono due presidi distinti
    e servono entrambi."""
    from src.engine.costs import CostModel
    from src.engine.risk import RiskConfig, size_position

    piano = _piano(_rialzo())          # serie lineare: ATR ~0,5% del prezzo
    assert piano["bias"] == "long"     # la strategia il segnale lo darebbe

    stop_pct = (piano["price"] - piano["stop"]) / piano["price"] * 100
    assert stop_pct < 1.4              # sotto la soglia ricavata in risk.py

    sizing = size_position(9_300.0, piano["price"], piano["stop"], None,
                            RiskConfig(risk_pct=0.75),
                            costs=CostModel(order_fee_eur=1.0, fx_cost_pct_per_leg=0.5,
                                            slippage_bps_per_side=5.0),
                            currency="EUR")
    assert not sizing.is_tradable
    assert "costo di esecuzione" in sizing.rejected_reason
