"""
Sezione Fattori: non il grafico del singolo titolo, ma una valutazione
di un titolo sui 5 fattori accademici con premio storico documentato —
Value, Momentum, Quality, Low Volatility, Size. È il ponte tra Analisi
Tecnica (timing) e Fundamental Score (qualità/valore di medio termine):
selezione con fondamentali+fattori, timing con la tecnica.

A differenza di una prima versione basata su percentili contro un
universo di confronto (portafoglio + preferiti + peer di settore), qui
ogni fattore è un punteggio ASSOLUTO 0-100: la metrica grezza viene
mappata su una scala fissa con tre ancore (0=scarso, 50=nella media,
100=eccellente), scelte da me su basi economiche/statistiche
ragionevoli — non calibrate con un backtest, e non relative a nessun
gruppo di titoli. Il vantaggio è che il numero è stabile nel tempo e
confrontabile da solo (non cambia se aggiungi o togli un titolo dal
portafoglio o dai preferiti); lo svantaggio è che le ancore sono scelte
soggettive, dichiarate esplicitamente qui e nel disclaimer della pagina.

Distinzione da non confondere in UI (nota finale): il Momentum-fattore
qui è di MEDIO termine (total return 12-1 mesi sullo stesso titolo, per
capire se il suo trend recente è stato forte o debole in assoluto) —
diverso dagli oscillatori di momentum di src/technical.py (rate-of-change
di BREVE termine, per *quando* entrare/uscire sul singolo titolo).
"""
from __future__ import annotations

from math import log10

from src import data_provider as dp
from src import financials as finmod
from src import fundamental_score as fscore

FACTORS = ["value", "momentum", "quality", "low_vol", "size"]

FACTOR_LABELS_IT = {
    "value": "Value", "momentum": "Momentum", "quality": "Quality",
    "low_vol": "Low Volatility", "size": "Size",
}

DEFAULT_WEIGHTS = {f: 1 / 5 for f in FACTORS}

# Profili di peso opzionali: equal-weight di default, o un tilt esplicito
# verso un fattore — sempre dichiarato, mai nascosto.
TILT_PROFILES = {
    "Equal-weight": dict(DEFAULT_WEIGHTS),
    "Value tilt": {"value": 0.40, "momentum": 0.15, "quality": 0.20, "low_vol": 0.125, "size": 0.125},
    "Momentum tilt": {"value": 0.15, "momentum": 0.40, "quality": 0.20, "low_vol": 0.125, "size": 0.125},
    "Quality tilt": {"value": 0.15, "momentum": 0.15, "quality": 0.40, "low_vol": 0.15, "size": 0.15},
}

SCORE_BANDS = [
    (80, 100, "Eccellente"),
    (60, 79, "Solido"),
    (40, 59, "Nella media"),
    (20, 39, "Debole"),
    (0, 19, "Scarso"),
]


def score_band_label(score: float | None) -> str:
    if score is None:
        return "n/d"
    for lo, hi, label in SCORE_BANDS:
        if lo <= score <= hi:
            return label
    return "n/d"


# ---------------------------------------------------------------------------
# Ancore assolute per metrica: (valore_grezzo, punteggio) — interpolazione
# lineare a tratti tra le ancore, valore clippato oltre gli estremi. Ogni
# lista è scelta in modo che 50 corrisponda grosso modo a un titolo "medio"
# e gli estremi a casi chiaramente forti/deboli, su basi economiche
# ragionevoli (non un backtest):
#
# - Value (earnings/FCF/EV-EBIT yield, book-to-price): 50 ~ multiplo in
#   linea con la media storica di lungo periodo del mercato azionario
#   USA (P/E ~15, P/B ~3); 100 ~ titolo a sconto marcato; 0 ~ molto caro.
# - Momentum: 50 = prezzo piatto negli 11 mesi rilevanti; +40% ~ trend
#   annuo forte; -30% ~ trend annuo debole.
# - Quality: ROIC 50 ~ 10% (attorno a un costo del capitale tipico),
#   100 ~ 25% (creazione di valore marcata); gross-profit/assets e
#   accruals hanno ancore da Novy-Marx/Sloan.
# - Low Volatility: 50 ~ volatilità/beta di mercato (circa 30%/1.0).
# - Size: scala logaritmica sulla capitalizzazione (il premio storico
#   delle small cap prevede punteggio più alto per capitalizzazione più
#   piccola), 50 ~ 10 Mld $ (mid cap).
# ---------------------------------------------------------------------------
ANCHORS = {
    "earnings_yield": [(2, 0), (6.5, 50), (12, 100)],
    "fcf_yield": [(0, 0), (4, 50), (9, 100)],
    "ev_ebit_yield": [(2, 0), (6.5, 50), (12, 100)],
    "book_to_price": [(10, 0), (33, 50), (100, 100)],
    "momentum_12_1": [(-30, 0), (0, 50), (40, 100)],
    "momentum_vol_adj": [(-1.5, 0), (0, 50), (2.0, 100)],
    "roic": [(0, 0), (10, 50), (25, 100)],
    "gross_profits_to_assets": [(10, 0), (20, 50), (40, 100)],
    "accruals_ratio": [(15, 0), (3, 50), (-10, 100)],
    "volatility_12m": [(55, 0), (30, 50), (12, 100)],
    "beta": [(2.0, 0), (1.0, 50), (0.4, 100)],
}

# Market cap: scala logaritmica, ancore in miliardi di $ (gestita a parte
# in _score_market_cap perché richiede log10 prima dell'interpolazione).
SIZE_ANCHORS_LOG10 = [(log10(0.5e9), 100), (log10(10e9), 50), (log10(200e9), 0)]

FACTOR_CACHE_PATH = "data/factor_cache.json"  # non più usato (nessuna cache di peer/universo)


def _piecewise_score(value: float | None, anchors: list[tuple[float, float]]) -> float | None:
    """Interpolazione lineare a tratti tra ancore (x, punteggio). Le
    ancore possono essere in ordine di punteggio crescente o decrescente
    (a seconda che un valore grezzo più alto sia meglio o peggio) — qui
    si ordina per x e si interpola qualunque sia la direzione."""
    if value is None:
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


def _score_market_cap(market_cap: float | None) -> float | None:
    if market_cap is None or market_cap <= 0:
        return None
    return _piecewise_score(log10(market_cap), SIZE_ANCHORS_LOG10)


# ---------------------------------------------------------------------------
# Metriche grezze per titolo (definizioni operative da yfinance)
# ---------------------------------------------------------------------------

def compute_factor_metrics(symbol: str, info: dict | None = None, hist: dict | None = None,
                            price_hist=None) -> dict:
    """Le metriche grezze dei 5 fattori per un singolo titolo. Riusa
    `fundamental_score.compute_core_metrics` per Quality (ROIC,
    gross-profits-to-assets, accruals) ed EV/EBIT yield — stessa fonte
    del Fundamental Score, cosi' i due moduli restano coerenti tra loro."""
    info = info if info is not None else dp.get_info(symbol)
    hist = hist if hist is not None else finmod.get_financial_history(symbol, freq="annual")

    metrics = {
        "earnings_yield": None, "fcf_yield": None, "ev_ebit_yield": None, "book_to_price": None,
        "momentum_12_1": None, "momentum_vol_adj": None,
        "roic": None, "gross_profits_to_assets": None, "accruals_ratio": None,
        "volatility_12m": None, "beta": None, "market_cap": None,
    }

    market_cap = info.get("market_cap")
    metrics["market_cap"] = market_cap

    # --- Value: earnings yield (E/P), FCF yield, EV/EBIT yield, book-to-price ---
    pe = info.get("pe_ratio")
    if pe and pe > 0:
        metrics["earnings_yield"] = 1 / pe * 100
    fcf = info.get("free_cashflow")
    if fcf and market_cap:
        metrics["fcf_yield"] = fcf / market_cap * 100
    pb = info.get("price_to_book")
    if pb and pb > 0:
        metrics["book_to_price"] = 1 / pb * 100

    core = fscore.compute_core_metrics(symbol, info=info, hist=hist)
    metrics["ev_ebit_yield"] = core.get("ev_ebit_yield")

    # --- Quality: link diretto al Fundamental Score ---
    metrics["roic"] = core.get("roic")
    metrics["gross_profits_to_assets"] = core.get("gross_profits_to_assets")
    metrics["accruals_ratio"] = core.get("accruals_ratio")

    # --- Momentum (12-1 mesi, salta l'ultimo mese) + Low Vol (volatilità 12m) ---
    if price_hist is None:
        price_hist = dp.get_history(symbol, period="14mo", interval="1d")
    if price_hist is not None and not price_hist.empty and len(price_hist) > 30:
        close = price_hist["Close"].dropna()
        price_12m_ago = close.iloc[-252] if len(close) > 252 else close.iloc[0]
        idx_1m_ago = max(0, len(close) - 22)
        price_1m_ago = close.iloc[idx_1m_ago]
        if price_12m_ago and price_12m_ago > 0:
            metrics["momentum_12_1"] = (price_1m_ago / price_12m_ago - 1) * 100

        returns = close.pct_change().dropna()
        if len(returns) >= 30:
            vol = float(returns.tail(252).std() * (252 ** 0.5) * 100)
            metrics["volatility_12m"] = vol
            if metrics["momentum_12_1"] is not None and vol:
                metrics["momentum_vol_adj"] = metrics["momentum_12_1"] / vol

    metrics["beta"] = info.get("beta")
    return metrics


# ---------------------------------------------------------------------------
# Punteggio assoluto 0-100 per fattore + composite
# ---------------------------------------------------------------------------

def compute_factor_scores(metrics: dict) -> dict:
    """Punteggio assoluto 0-100 (ancore fisse, vedi ANCHORS) per ciascuno
    dei 5 fattori, per un singolo titolo — non dipende da nessun
    universo di confronto."""
    value_scores = [
        s for s in (
            _piecewise_score(metrics.get(k), ANCHORS[k])
            for k in ("earnings_yield", "fcf_yield", "ev_ebit_yield", "book_to_price")
        ) if s is not None
    ]
    momentum_scores = [
        s for s in (
            _piecewise_score(metrics.get("momentum_12_1"), ANCHORS["momentum_12_1"]),
            _piecewise_score(metrics.get("momentum_vol_adj"), ANCHORS["momentum_vol_adj"]),
        ) if s is not None
    ]
    quality_scores = [
        s for s in (
            _piecewise_score(metrics.get("roic"), ANCHORS["roic"]),
            _piecewise_score(metrics.get("gross_profits_to_assets"), ANCHORS["gross_profits_to_assets"]),
            _piecewise_score(metrics.get("accruals_ratio"), ANCHORS["accruals_ratio"]),
        ) if s is not None
    ]
    lowvol_scores = [
        s for s in (
            _piecewise_score(metrics.get("volatility_12m"), ANCHORS["volatility_12m"]),
            _piecewise_score(metrics.get("beta"), ANCHORS["beta"]),
        ) if s is not None
    ]
    size_score = _score_market_cap(metrics.get("market_cap"))

    return {
        "value": sum(value_scores) / len(value_scores) if value_scores else None,
        "momentum": sum(momentum_scores) / len(momentum_scores) if momentum_scores else None,
        "quality": sum(quality_scores) / len(quality_scores) if quality_scores else None,
        "low_vol": sum(lowvol_scores) / len(lowvol_scores) if lowvol_scores else None,
        "size": size_score,
    }


def compute_composite(scores: dict, weight_profile: str = "Equal-weight") -> float | None:
    """Composite factor score: media pesata dei punteggi assoluti
    disponibili, coi pesi ridistribuiti sui fattori disponibili se uno
    manca (stessa logica di ridistribuzione del Fundamental Score)."""
    weights = TILT_PROFILES.get(weight_profile, DEFAULT_WEIGHTS)
    available = {f: scores.get(f) for f in FACTORS if scores.get(f) is not None}
    if not available:
        return None
    total_w = sum(weights[f] for f in available)
    if total_w <= 0:
        return None
    return sum(available[f] * weights[f] for f in available) / total_w


# ---------------------------------------------------------------------------
# Orchestrazione end-to-end per un insieme di titoli (portafoglio + preferiti)
# ---------------------------------------------------------------------------

def build_factor_report(target_tickers: list[str], weight_profile: str = "Equal-weight") -> dict:
    """Calcola metriche/punteggi assoluti/composite per ciascun ticker in
    `target_tickers`. Nessun universo di confronto: ogni titolo è
    valutato sulla propria scala assoluta, quindi il risultato per un
    titolo non cambia se aggiungi o togli altri titoli."""
    metrics_by_ticker: dict[str, dict] = {}
    scores_by_ticker: dict[str, dict] = {}
    composites: dict[str, float | None] = {}

    for t in target_tickers:
        try:
            info = dp.get_info(t)
            hist = finmod.get_financial_history(t, freq="annual")
            m = compute_factor_metrics(t, info=info, hist=hist)
        except Exception:
            continue
        metrics_by_ticker[t] = m
        s = compute_factor_scores(m)
        scores_by_ticker[t] = s
        composites[t] = compute_composite(s, weight_profile)

    ranking = sorted(
        ({"ticker": t, "composite": composites.get(t), **scores_by_ticker.get(t, {})} for t in target_tickers if t in scores_by_ticker),
        key=lambda r: (r["composite"] is None, -(r["composite"] or 0)),
    )

    return {
        "weight_profile": weight_profile,
        "metrics": metrics_by_ticker,
        "scores": scores_by_ticker,
        "composites": composites,
        "ranking": ranking,
    }


def radar_data(symbol: str, scores: dict) -> dict:
    """Dati pronti per un radar a 5 assi (Value/Momentum/Quality/Low-Vol/
    Size) per un singolo titolo — il rendering vero e proprio (Plotly) è
    nella pagina, questo modulo resta senza dipendenze di grafica."""
    s = scores.get(symbol, {})
    return {
        "symbol": symbol,
        "axes": [FACTOR_LABELS_IT[f] for f in FACTORS],
        "values": [s.get(f) if s.get(f) is not None else 0 for f in FACTORS],
        "raw": s,
    }
