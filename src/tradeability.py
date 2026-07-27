"""
Technical Tradeability Score — src/tradeability.py

Ricostruito secondo Prompt_Cowork_Technical_Tradeability_Score.md. Non è
un segnale di acquisto: valuta quanto uno strumento è STRUTTURALMENTE
adatto a un sistema di trading trend-following basato su analisi
tecnica (src/technical.py) — serve a decidere cosa mettere nell'universo
di trading e cosa testare per primo in backtest/forward test.

Sei criteri, ciascuno un sub-score assoluto 0-100 su una scala fissa
(ancore dichiarate qui sotto, nessun confronto contro un gruppo di
titoli), combinati in una media pesata:

  1. Liquidità (20%)            — controvalore scambiato (ADV in EUR)
  2. Volatilità ATR% (15%)      — curva a campana, sweet spot centrale
  3. Trendiness (30%)           — media di Efficiency Ratio, ADX, Hurst
  4. Frequenza dei gap (15%)    — gap overnight rispetto all'ATR
  5. Sensibilità earnings (10%) — violenza dei movimenti su pubblicazione utili
  6. Autocorrelazione (10%)     — persistenza vs mean-reversion sull'orizzonte
     dei rendimenti                di posizionamento (k giorni)

Principi (dalla spec, vincolanti):
  - Ogni soglia è una costante configurabile e commentata qui sotto —
    nessun valore magico sepolto nel codice.
  - Lo score si calcola su una finestra rolling (default 252 barre
    daily ≈ 1 anno di borsa) e va ricalcolato periodicamente.
  - Nessun hardcoding di ticker: la classe di strumento (azione/ETF/
    indice/FX/crypto/future) si rileva da yfinance (`quoteType`), mai da
    un elenco scritto a mano di simboli.
  - Trasparenza radicale: ogni override (FX/crypto sulla liquidità) o
    esclusione va sempre mostrato, mai silenzioso.
  - Nessun dato mancante viene stimato "a occhio": se una metrica non è
    calcolabile il sub-score è None ("n/d") e la confidenza si riduce di
    conseguenza — mai un valore neutro che gonfia il totale.
  - Robustezza: un errore su uno strumento non deve interrompere il
    calcolo sugli altri (vedi build_tradeability_report).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from src import data_provider as dp
from src import technical as tech

# ---------------------------------------------------------------------------
# Finestre e parametri per criterio (tutti configurabili, tutti commentati)
# ---------------------------------------------------------------------------

ROLLING_WINDOW_DAYS = 252   # spec: ~1 anno di borsa, finestra su cui si aggregano i sub-score
HISTORY_PERIOD = "2y"       # buffer oltre la finestra rolling per il warm-up degli indicatori
                             # (ATR/ADX di Wilder, Hurst fino a lag 64, ~8 trimestri di earnings)
MIN_BARS_REQUIRED = 280     # sotto questa soglia lo score non è calcolabile (mai forzato a zero)

ADV_LOOKBACK_DAYS = 20      # Criterio 1: media del controvalore scambiato sugli ultimi N giorni
ATR_PERIOD = 14             # Criteri 2/3b/4: ATR di Wilder (src/technical.py::atr, stessa formula)
ADX_PERIOD = 14             # Criterio 3b: ADX di Wilder
ER_LOOKBACK = 20            # Criterio 3a: Kaufman Efficiency Ratio, finestra n
HURST_LAGS = (2, 4, 8, 16, 32, 64)   # Criterio 3c: lag tau per la regressione di Hurst
GAP_LOOKBACK_DAYS = 60      # Criterio 4: finestra di conteggio dei gap
GAP_ATR_MULTIPLE = 1.0      # Criterio 4: soglia GapRatio oltre la quale un gap è "significativo"
EARNINGS_LOOKBACK_YEARS = 2         # Criterio 5: coerente con HISTORY_PERIOD, ~8 trimestri
AUTOCORR_K_DAYS = 5         # Criterio 6: orizzonte di posizionamento = settimanale (5 giorni di borsa)
AUTOCORR_MAX_LAG = 4        # Criterio 6: lag calcolati per trasparenza (mostrati tutti in raw)
AUTOCORR_LAGS_AVERAGED = (1, 2)     # Criterio 6: lag effettivamente mediati nel sub-score — scelta
                             # editoriale: i lag 1-2 pesano la persistenza vicina all'orizzonte di
                             # posizionamento, i lag 3-4 sono troppo rumorosi con ~250/k osservazioni
                             # per anno e vengono mostrati solo a titolo informativo

WEIGHTS = {
    "liquidity": 0.20,
    "volatility": 0.15,
    "trendiness": 0.30,
    "gap_frequency": 0.15,
    "earnings": 0.10,
    "autocorrelation": 0.10,
}

CRITERION_LABELS_IT = {
    "liquidity": "Liquidità",
    "volatility": "Volatilità (ATR%)",
    "trendiness": "Trendiness",
    "gap_frequency": "Frequenza dei gap",
    "earnings": "Sensibilità earnings",
    "autocorrelation": "Autocorrelazione",
}

# Regola di esclusione hard (spec): un buon punteggio sugli altri criteri
# non compensa illiquidità o assenza di trend — lo strumento è marcato
# "inadatto al trading tecnico" indipendentemente dal totale pesato.
HARD_EXCLUSION_LIQUIDITY_MIN = 20
HARD_EXCLUSION_TRENDINESS_MIN = 25

SCORE_BANDS = [
    (80, 100, "Eccellente"),
    (65, 79, "Buono"),
    (50, 64, "Discreto"),
    (35, 49, "Debole"),
    (0, 34, "Inadatto"),
]

# ---------------------------------------------------------------------------
# Classe di strumento (mai hardcoding di ticker: sempre da quoteType yfinance)
# ---------------------------------------------------------------------------

ASSET_CLASS_LABELS = {
    "EQUITY": "Azione",
    "ETF": "ETF",
    "INDEX": "Indice",
    "MUTUALFUND": "Fondo/SICAV",
    "CURRENCY": "FX",
    "CRYPTOCURRENCY": "Crypto",
    "FUTURE": "Future/Commodity",
}

NO_EARNINGS_ASSET_CLASSES = {"ETF", "INDEX", "CURRENCY", "CRYPTOCURRENCY", "FUTURE", "MUTUALFUND"}

# Assunzione indicativa e dichiarata (da verificare/correggere con Capo se
# l'offerta reale diverge): Trade Republic copre tipicamente azioni, ETF e
# fondi; FX, future e crypto non sono trattati con le stesse modalità o non
# sono disponibili. Non è un dato ufficiale integrato via API — è una mappa
# manuale, mostrata sempre esplicitamente in UI, mai usata silenziosamente.
BROKER_TRADABLE_ASSET_CLASSES = {"EQUITY", "ETF", "MUTUALFUND"}


def _classify_asset(quote_type: str | None) -> tuple[str, str]:
    """Classe raw (quoteType yfinance) + etichetta italiana. Se yfinance
    non fornisce un quoteType riconosciuto, il default è EQUITY (il caso
    più comune) — dichiarato qui, mai un'esclusione silenziosa."""
    asset_class = quote_type if quote_type in ASSET_CLASS_LABELS else "EQUITY"
    return asset_class, ASSET_CLASS_LABELS.get(asset_class, asset_class.title())


# ---------------------------------------------------------------------------
# Override di liquidità per FX/crypto (spec, Criterio 1): il campo Volume
# di yfinance è spesso inaffidabile o zero per queste classi. Sub-score
# fisso, sempre segnalato come override — mai calcolato in silenzio da un
# ADV che sarebbe comunque inattendibile.
# ---------------------------------------------------------------------------
FX_LIQUIDITY_OVERRIDE = 90
CRYPTO_MAJOR_LIQUIDITY_OVERRIDE = 85       # BTC, ETH (esempi espliciti della spec)
CRYPTO_OTHER_LIQUIDITY_OVERRIDE = 60       # altcoin: liquidità storicamente più incerta —
                                            # stima editoriale prudenziale, non backtestata
CRYPTO_MAJORS = {"BTC", "ETH"}

LIQUIDITY_ANCHORS_EUR = [(1e6, 0), (10e6, 40), (100e6, 70), (1000e6, 100)]


def _crypto_base_symbol(symbol: str) -> str:
    """'BTC-USD' -> 'BTC'. Usato solo per distinguere BTC/ETH (override
    liquidità più alto) dalle altre crypto — non è un elenco di ticker
    scritto a mano su cui si basa l'intero score, solo un dettaglio
    dell'override di UN criterio su sei."""
    return symbol.split("-")[0].upper()


def _score_liquidity(symbol: str, hist: pd.DataFrame, currency: str | None, asset_class: str) -> dict:
    if asset_class == "CURRENCY":
        return {
            "score": float(FX_LIQUIDITY_OVERRIDE), "adv_eur": None,
            "override_note": f"Liquidità FX: il volume di yfinance non è affidabile per le coppie "
                              f"valutarie, sub-score fisso {FX_LIQUIDITY_OVERRIDE} (assunzione "
                              f"editoriale dichiarata, non backtestata).",
        }
    if asset_class == "CRYPTOCURRENCY":
        base = _crypto_base_symbol(symbol)
        is_major = base in CRYPTO_MAJORS
        override = CRYPTO_MAJOR_LIQUIDITY_OVERRIDE if is_major else CRYPTO_OTHER_LIQUIDITY_OVERRIDE
        return {
            "score": float(override), "adv_eur": None,
            "override_note": f"Liquidità crypto: il volume di yfinance è spesso inaffidabile, "
                              f"sub-score fisso {override} per {'BTC/ETH' if is_major else 'altcoin'} "
                              f"(assunzione editoriale dichiarata, non backtestata).",
        }

    volume = hist.get("Volume")
    if volume is None or float(volume.tail(ADV_LOOKBACK_DAYS).fillna(0).sum()) <= 0:
        return {"score": None, "adv_eur": None, "override_note": None}

    dollar_volume = (volume * hist["Close"]).tail(ADV_LOOKBACK_DAYS)
    adv = float(dollar_volume.mean())

    conv_note = None
    if currency is None:
        fx_rate = None
        conv_note = "Valuta dello strumento non disponibile da yfinance: ADV mostrato senza conversione in EUR."
    elif currency.upper() == "EUR":
        fx_rate = 1.0
    else:
        fx_rate = dp.get_fx_rate(currency, "EUR")
        if fx_rate is None:
            conv_note = f"Tasso di cambio {currency}->EUR non disponibile: ADV mostrato senza conversione."

    adv_eur = adv / fx_rate if fx_rate else adv
    score = _piecewise_score(adv_eur, LIQUIDITY_ANCHORS_EUR)
    return {"score": score, "adv_eur": adv_eur, "override_note": conv_note}


# ---------------------------------------------------------------------------
# Criterio 2 — Volatilità adeguata / ATR%
# ---------------------------------------------------------------------------

# Curva a campana standard: premia il centro (sweet spot 2,5%), penalizza
# entrambi gli estremi. Ancore dalla spec.
STANDARD_ATR_ANCHORS = [(0.8, 10), (1.5, 70), (2.5, 100), (4.0, 70), (6.0, 30), (10.0, 10)]

# Crypto: sweet spot più alto (ATR% tipico 3-6%), curva spostata a destra,
# nessuna penalizzazione forte fino a ~8% (spec, adattamento per classe).
CRYPTO_ATR_ANCHORS = [(1.0, 20), (2.0, 55), (4.0, 90), (5.0, 100), (6.0, 95), (8.0, 80), (12.0, 50), (20.0, 10)]


def _score_volatility(close: pd.Series, atr_series: pd.Series, asset_class: str) -> dict:
    atr_pct_series = (atr_series / close.replace(0, np.nan)) * 100
    window = atr_pct_series.tail(ROLLING_WINDOW_DAYS).dropna()
    if window.empty:
        return {"score": None, "atr_pct": None, "curve": None}

    # Media sulla finestra rolling (non solo l'ultimo valore): coerente col
    # principio generale "finestra rolling" e con la stabilità richiesta dai
    # criteri di validazione (lo score non deve oscillare da un giorno
    # all'altro sul singolo valore di chiusura).
    atr_pct_val = float(window.mean())
    is_crypto = asset_class == "CRYPTOCURRENCY"
    anchors = CRYPTO_ATR_ANCHORS if is_crypto else STANDARD_ATR_ANCHORS
    score = _piecewise_score(atr_pct_val, anchors)
    return {"score": score, "atr_pct": atr_pct_val, "curve": "crypto" if is_crypto else "standard"}


# ---------------------------------------------------------------------------
# Criterio 3 — Trendiness (media di ER, ADX medio, Hurst)
# ---------------------------------------------------------------------------

ER_ANCHORS = [(0.0, 0), (0.20, 20), (0.30, 50), (0.50, 80), (0.70, 100)]
ADX_ANCHORS = [(15, 10), (20, 40), (25, 65), (35, 90), (45, 100)]
HURST_ANCHORS = [(0.40, 10), (0.45, 10), (0.50, 40), (0.55, 70), (0.60, 100)]


def _efficiency_ratio_series(close: pd.Series, n: int = ER_LOOKBACK) -> pd.Series:
    """Kaufman Efficiency Ratio (3a): |Close_t - Close_{t-n}| / somma
    delle variazioni assolute giorno-per-giorno sulla stessa finestra.
    1 = movimento in linea retta, 0 = zigzag senza direzione netta."""
    net_change = (close - close.shift(n)).abs()
    total_path = close.diff().abs().rolling(n).sum()
    er = net_change / total_path.replace(0, np.nan)
    return er.clip(0, 1)


def _wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    """EMA di Wilder: stessa formula di src/technical.py::rsi/atr
    (alpha = 1/period), riusata qui per +DM/-DM/DX -> ADX (Criterio 3b)."""
    return series.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _adx_series(hist: pd.DataFrame, period: int = ADX_PERIOD) -> pd.Series:
    """ADX di Wilder (3b), riusando l'ATR di src/technical.py::atr come
    denominatore di +DI/-DI per restare coerenti con l'unico ATR usato
    anche nei Criteri 2 e 4."""
    high, low = hist["High"], hist["Low"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    atr_series = tech.atr(hist, period=period)
    plus_di = 100 * _wilder_smooth(plus_dm, period) / atr_series.replace(0, np.nan)
    minus_di = 100 * _wilder_smooth(minus_dm, period) / atr_series.replace(0, np.nan)
    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    return _wilder_smooth(dx.fillna(0.0), period)


def _hurst_exponent(close: pd.Series, lags: tuple[int, ...] = HURST_LAGS,
                     window: int = ROLLING_WINDOW_DAYS) -> float | None:
    """Esponente di Hurst (3c) via il metodo della varianza degli
    incrementi a lag crescenti: H = pendenza della regressione di
    log(std(Δτ)) su log(τ), dove Δτ = log(Close_t) - log(Close_{t-τ})
    (equivalente al rendimento log cumulato su τ giorni). H > 0,5 =
    persistente/trending, H = 0,5 = random walk, H < 0,5 = mean-reverting."""
    series = close.tail(window + max(lags)).dropna()
    if len(series) < max(lags) * 2:
        return None
    log_price = np.log(series)

    valid_lags, log_stds = [], []
    for lag in lags:
        diffs = log_price.diff(lag).dropna()
        if len(diffs) < 10:
            continue
        std = float(diffs.std())
        if std > 0:
            valid_lags.append(lag)
            log_stds.append(math.log(std))
    if len(valid_lags) < 3:
        return None

    x = np.log(valid_lags)
    slope, _ = np.polyfit(x, log_stds, 1)
    return float(slope)


def _score_trendiness(hist: pd.DataFrame, close: pd.Series) -> dict:
    er_series = _efficiency_ratio_series(close, ER_LOOKBACK).tail(ROLLING_WINDOW_DAYS).dropna()
    er_val = float(er_series.mean()) if not er_series.empty else None
    er_score = _piecewise_score(er_val, ER_ANCHORS) if er_val is not None else None

    adx_series = _adx_series(hist, ADX_PERIOD).tail(ROLLING_WINDOW_DAYS).dropna()
    adx_val = float(adx_series.mean()) if not adx_series.empty else None
    adx_score = _piecewise_score(adx_val, ADX_ANCHORS) if adx_val is not None else None

    hurst_val = _hurst_exponent(close)
    hurst_score = _piecewise_score(hurst_val, HURST_ANCHORS) if hurst_val is not None else None

    components = [s for s in (er_score, adx_score, hurst_score) if s is not None]
    score = float(np.mean(components)) if components else None
    return {
        "score": score,
        "er": er_val, "er_score": er_score,
        "adx": adx_val, "adx_score": adx_score,
        "hurst": hurst_val, "hurst_score": hurst_score,
        "n_submetrics_missing": sum(1 for s in (er_score, adx_score, hurst_score) if s is None),
    }


# ---------------------------------------------------------------------------
# Criterio 4 — Frequenza dei gap
# ---------------------------------------------------------------------------

GAP_ANCHORS = [(0, 100), (5, 70), (15, 40), (30, 10)]


def _gap_frequency(hist: pd.DataFrame, atr_series: pd.Series, lookback_days: int = GAP_LOOKBACK_DAYS) -> dict:
    open_ = hist["Open"]
    prev_close = hist["Close"].shift(1)
    gap = (open_ - prev_close).abs()
    gap_ratio = gap / atr_series.replace(0, np.nan)
    recent = gap_ratio.tail(lookback_days).dropna()
    if recent.empty:
        return {"gap_frequency_pct": None, "weekend_gap_frequency_pct": None, "n_gaps": None, "n_bars": 0}

    n_gaps = int((recent > GAP_ATR_MULTIPLE).sum())
    freq_pct = 100 * n_gaps / len(recent)

    # Rischio weekend (spec, Criterio 4, adattamento crypto 24/7): i gap del
    # lunedì/inizio settimana contati separatamente, per non premiare a 100
    # automaticamente uno strumento che gappa poco nei giorni feriali ma
    # gappa spesso durante il weekend.
    mondays = recent[recent.index.weekday == 0] if hasattr(recent.index, "weekday") else recent.iloc[0:0]
    weekend_freq_pct = (100 * (mondays > GAP_ATR_MULTIPLE).sum() / len(mondays)) if len(mondays) else None

    return {
        "gap_frequency_pct": freq_pct, "weekend_gap_frequency_pct": weekend_freq_pct,
        "n_gaps": n_gaps, "n_bars": len(recent),
    }


def _score_gap_frequency(hist: pd.DataFrame, atr_series: pd.Series, asset_class: str) -> dict:
    g = _gap_frequency(hist, atr_series)
    freq = g.get("gap_frequency_pct")
    if freq is None:
        return {"score": None, **g}

    score = _piecewise_score(freq, GAP_ANCHORS)
    weekend_freq = g.get("weekend_gap_frequency_pct")
    if asset_class == "CRYPTOCURRENCY" and weekend_freq is not None and weekend_freq > 0:
        # Scelta editoriale dichiarata: lo score non può salire fino a 100
        # se il lunedì gappa spesso, anche quando la frequenza giornaliera
        # complessiva è bassa — coerente col principio "non premiare crypto
        # a 100 automaticamente" della spec.
        score = min(score, 100 - weekend_freq)
    return {"score": score, **g}


# ---------------------------------------------------------------------------
# Criterio 5 — Sensibilità agli earnings
# ---------------------------------------------------------------------------

EARNINGS_MOVE_ANCHORS = [(2, 80), (5, 50), (8, 30), (12, 10)]


def _to_naive_index(idx: pd.Index) -> pd.Index:
    try:
        return idx.tz_localize(None)
    except TypeError:
        return idx


def _score_earnings(symbol: str, asset_class: str, hist: pd.DataFrame) -> dict:
    if asset_class in NO_EARNINGS_ASSET_CLASSES:
        return {
            "score": 100.0, "avg_move_pct": None, "next_earnings_date": None, "n_events": 0,
            "note": "Nessuna sensibilità earnings: classe strutturalmente esente (ETF/indice/FX/"
                    "crypto/future non pubblicano utili trimestrali).",
        }

    edf = dp.get_earnings_dates(symbol, limit=16)
    if edf is None or edf.empty:
        return {
            "score": None, "avg_move_pct": None, "next_earnings_date": None, "n_events": 0,
            "note": "Date earnings non disponibili da yfinance per questo titolo.",
        }

    edf = edf.copy()
    edf.index = _to_naive_index(edf.index)
    now = pd.Timestamp.now().normalize()
    past = edf[edf.index <= now]
    future = edf[edf.index > now]
    next_date = future.index.min().date().isoformat() if not future.empty else None

    close = hist["Close"].dropna()
    close_idx_naive = _to_naive_index(close.index)
    close_naive = close.copy()
    close_naive.index = close_idx_naive

    cutoff = now - pd.Timedelta(days=365 * EARNINGS_LOOKBACK_YEARS)
    moves = []
    for ts in past.index:
        if ts < cutoff:
            continue
        pos = close_idx_naive.searchsorted(ts)
        if pos <= 0 or pos >= len(close_naive):
            continue
        c_after = float(close_naive.iloc[pos])
        c_before = float(close_naive.iloc[pos - 1])
        if c_before:
            moves.append(abs(c_after - c_before) / c_before * 100)

    if not moves:
        return {
            "score": None, "avg_move_pct": None, "next_earnings_date": next_date, "n_events": 0,
            "note": "Nessuna data earnings passata nella finestra considerata "
                    f"(ultimi {EARNINGS_LOOKBACK_YEARS} anni).",
        }

    avg_move = float(np.mean(moves))
    score = _piecewise_score(avg_move, EARNINGS_MOVE_ANCHORS)
    return {
        "score": score, "avg_move_pct": avg_move, "next_earnings_date": next_date,
        "n_events": len(moves), "note": None,
    }


# ---------------------------------------------------------------------------
# Criterio 6 — Autocorrelazione dei rendimenti (sull'orizzonte di posizionamento)
# ---------------------------------------------------------------------------

AUTOCORR_ANCHORS = [(-0.15, 10), (-0.05, 35), (0.0, 50), (0.10, 80), (0.20, 100)]


def _autocorrelation(close: pd.Series, k: int = AUTOCORR_K_DAYS, max_lag: int = AUTOCORR_MAX_LAG,
                      window: int = ROLLING_WINDOW_DAYS) -> dict:
    """Rendimenti log aggregati a k giorni (NON sovrapposti, per non
    inflazionare artificialmente l'autocorrelazione), poi AC(lag) per
    lag 1..max_lag. Calcolata sull'orizzonte di posizionamento (k) e non
    sui rendimenti daily grezzi: sui daily molti strumenti mostrano una
    leggera autocorrelazione negativa (short-term reversal) che
    scomparirebbe/invertirebbe proprio all'orizzonte k-giorni (spec)."""
    series = close.tail(window + k * (max_lag + 2)).dropna()
    log_ret = np.log(series / series.shift(1)).dropna()
    if len(log_ret) < k * (max_lag + 5):
        return {"ac_by_lag": {}, "ac_used_avg": None, "k_days": k, "n_periods": 0}

    n_periods = len(log_ret) // k
    trimmed = log_ret.iloc[-(n_periods * k):]
    periodic = pd.Series(trimmed.values).groupby(np.arange(len(trimmed)) // k).sum()

    ac_by_lag = {}
    for lag in range(1, max_lag + 1):
        if len(periodic) > lag + 5:
            val = periodic.autocorr(lag=lag)
            if val is not None and not pd.isna(val):
                ac_by_lag[lag] = float(val)

    used = [ac_by_lag[l] for l in AUTOCORR_LAGS_AVERAGED if l in ac_by_lag]
    ac_avg = float(np.mean(used)) if used else None
    return {"ac_by_lag": ac_by_lag, "ac_used_avg": ac_avg, "k_days": k, "n_periods": len(periodic)}


def _score_autocorrelation(close: pd.Series) -> dict:
    ac = _autocorrelation(close)
    val = ac.get("ac_used_avg")
    score = _piecewise_score(val, AUTOCORR_ANCHORS) if val is not None else None
    return {"score": score, **ac}


# ---------------------------------------------------------------------------
# Utility di interpolazione (stesso pattern di src/factors.py::_piecewise_score,
# duplicato qui per tenere il modulo autonomo, come per gli altri motori di
# scoring assoluto del progetto)
# ---------------------------------------------------------------------------

def _piecewise_score(value: float | None, anchors: list[tuple[float, float]]) -> float | None:
    """Interpolazione lineare a tratti tra ancore (valore_grezzo, punteggio),
    clamp oltre gli estremi. Funziona anche per curve a campana (Criterio 2)
    perché interpola solo tra ancore consecutive in x, senza richiedere che
    la sequenza di y sia monotona."""
    if value is None or pd.isna(value):
        return None
    pts = sorted(anchors, key=lambda p: p[0])
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    if value <= xs[0]:
        return float(ys[0])
    if value >= xs[-1]:
        return float(ys[-1])
    for i in range(len(xs) - 1):
        if xs[i] <= value <= xs[i + 1]:
            frac = (value - xs[i]) / (xs[i + 1] - xs[i]) if xs[i + 1] != xs[i] else 0.0
            return float(ys[i] + frac * (ys[i + 1] - ys[i]))
    return float(ys[-1])


def _last(series: pd.Series | None):
    if series is None:
        return None
    s = series.dropna()
    return float(s.iloc[-1]) if not s.empty else None


def _band_label(score: float | None) -> str:
    if score is None:
        return "n/d"
    for lo, hi, label in SCORE_BANDS:
        if lo <= score <= hi:
            return label
    return "n/d"


# ---------------------------------------------------------------------------
# Orchestrazione per singolo titolo
# ---------------------------------------------------------------------------

def compute_tradeability(symbol: str) -> dict:
    """Technical Tradeability Score completo per un titolo: i sei
    sub-score, i valori grezzi (per verifica), il totale pesato, la
    banda di lettura, la regola di esclusione hard, un indicatore di
    confidenza e tutti gli override/flag da mostrare sempre in UI."""
    hist = dp.get_history(symbol, period=HISTORY_PERIOD, interval="1d")
    if hist is None or hist.empty or len(hist) < MIN_BARS_REQUIRED:
        n = len(hist) if hist is not None else 0
        return {
            "symbol": symbol, "computable": False,
            "reason": f"Serie storica insufficiente ({n} barre, minimo richiesto {MIN_BARS_REQUIRED}).",
        }

    try:
        info_raw = dp.get_ticker(symbol).info or {}
    except Exception:
        info_raw = {}
    currency = info_raw.get("currency")
    quote_type = str(info_raw.get("quoteType")).upper() if info_raw.get("quoteType") else None
    asset_class, asset_class_label = _classify_asset(quote_type)

    close = hist["Close"]
    atr_series = tech.atr(hist, period=ATR_PERIOD)

    liq = _score_liquidity(symbol, hist, currency, asset_class)
    vol = _score_volatility(close, atr_series, asset_class)
    trend = _score_trendiness(hist, close)
    gap = _score_gap_frequency(hist, atr_series, asset_class)
    earn = _score_earnings(symbol, asset_class, hist)
    ac = _score_autocorrelation(close)

    sub_scores = {
        "liquidity": liq["score"], "volatility": vol["score"], "trendiness": trend["score"],
        "gap_frequency": gap["score"], "earnings": earn["score"], "autocorrelation": ac["score"],
    }
    raw = {"liquidity": liq, "volatility": vol, "trendiness": trend, "gap_frequency": gap,
           "earnings": earn, "autocorrelation": ac}

    n_missing = sum(1 for v in sub_scores.values() if v is None)
    confidence = round(1 - n_missing / len(sub_scores), 2)

    total_w = sum(WEIGHTS[k] for k, v in sub_scores.items() if v is not None)
    tts = (sum(sub_scores[k] * WEIGHTS[k] for k in sub_scores if sub_scores[k] is not None) / total_w
           if total_w > 0 else None)

    hard_excluded = False
    exclusion_reasons = []
    if sub_scores["liquidity"] is not None and sub_scores["liquidity"] < HARD_EXCLUSION_LIQUIDITY_MIN:
        hard_excluded = True
        exclusion_reasons.append(f"Liquidità {sub_scores['liquidity']:.0f} < {HARD_EXCLUSION_LIQUIDITY_MIN}")
    if sub_scores["trendiness"] is not None and sub_scores["trendiness"] < HARD_EXCLUSION_TRENDINESS_MIN:
        hard_excluded = True
        exclusion_reasons.append(f"Trendiness {sub_scores['trendiness']:.0f} < {HARD_EXCLUSION_TRENDINESS_MIN}")

    notes = []
    if liq.get("override_note"):
        notes.append(liq["override_note"])
    if earn.get("note"):
        notes.append(earn["note"])

    return {
        "symbol": symbol, "computable": True,
        "asset_class": asset_class, "asset_class_label": asset_class_label,
        "currency": currency, "price": _last(close),
        "sub_scores": sub_scores, "raw": raw,
        "tts": round(tts, 1) if tts is not None else None,
        "band": _band_label(tts) if not hard_excluded else "Inadatto (esclusione hard)",
        "confidence": confidence,
        "hard_excluded": hard_excluded, "exclusion_reasons": exclusion_reasons,
        "notes": notes,
        "tradable_on_broker": asset_class in BROKER_TRADABLE_ASSET_CLASSES,
        "next_earnings_date": earn.get("next_earnings_date"),
        "n_bars": len(hist),
    }


# ---------------------------------------------------------------------------
# Orchestrazione per l'universo (portafoglio + preferiti — stesso pattern di
# src/factors.py::build_factor_report, nessun ticker hardcoded)
# ---------------------------------------------------------------------------

def build_tradeability_report(target_tickers: list[str]) -> dict:
    """Calcola il Technical Tradeability Score per ciascun ticker in
    `target_tickers`. Un errore imprevisto su un titolo non deve
    interrompere il calcolo sugli altri (spec, "Robustezza")."""
    results: dict[str, dict] = {}
    for t in target_tickers:
        try:
            results[t] = compute_tradeability(t)
        except Exception as exc:  # difensivo: non deve mai far crashare l'intero report
            results[t] = {"symbol": t, "computable": False,
                           "reason": f"Errore imprevisto nel calcolo: {exc}"}

    computable = [r for r in results.values() if r.get("computable") and r.get("tts") is not None]
    ranking = sorted(computable, key=lambda r: -r["tts"])
    not_computable = [r for r in results.values() if not r.get("computable")]

    return {"results": results, "ranking": ranking, "not_computable": not_computable}
