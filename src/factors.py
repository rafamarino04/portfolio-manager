"""
Sezione Fattori (§12 di Specifica_Analisi_Tecnica_Murphy.md): non il
grafico del singolo titolo, ma la classificazione di un titolo rispetto
a un UNIVERSO (portafoglio + preferiti + peer di settore) sui 5 fattori
accademici con premio storico documentato. È il ponte tra Analisi
Tecnica (timing) e Fundamental Score (qualità/valore di medio termine):
selezione con fondamentali+fattori, timing con la tecnica.

Value, Momentum, Quality, Low Volatility, Size — definizioni operative
da yfinance (§12), percentile cross-sezionale winsorizzato al 5°/95°
(stesso metodo del Fundamental Score, vedi src/fundamental_score.py),
composite = media dei percentili (pesi uguali di default, profili
"tilt" opzionali).

Distinzione da non confondere in UI (§12, nota finale): il
Momentum-fattore qui è cross-sezionale e di MEDIO termine (total return
12-1 mesi tra titoli diversi, per selezionare *quali* titoli) — diverso
dagli oscillatori di momentum di src/technical.py (rate-of-change di
BREVE termine sul singolo titolo, per *quando* entrare/uscire).
"""
from __future__ import annotations

from src import data_provider as dp
from src import financials as finmod
from src import fundamental_cache as fc
from src import fundamental_score as fscore
from src import sector_universe as su

FACTORS = ["value", "momentum", "quality", "low_vol", "size"]

FACTOR_LABELS_IT = {
    "value": "Value", "momentum": "Momentum", "quality": "Quality",
    "low_vol": "Low Volatility", "size": "Size",
}

DEFAULT_WEIGHTS = {f: 1 / 5 for f in FACTORS}

# Profili di peso opzionali (§12 step 3): equal-weight di default, o un
# tilt esplicito verso un fattore — sempre dichiarato, mai nascosto.
TILT_PROFILES = {
    "Equal-weight": dict(DEFAULT_WEIGHTS),
    "Value tilt": {"value": 0.40, "momentum": 0.15, "quality": 0.20, "low_vol": 0.125, "size": 0.125},
    "Momentum tilt": {"value": 0.15, "momentum": 0.40, "quality": 0.20, "low_vol": 0.125, "size": 0.125},
    "Quality tilt": {"value": 0.15, "momentum": 0.15, "quality": 0.40, "low_vol": 0.15, "size": 0.15},
}

FACTOR_CACHE_PATH = "data/factor_cache.json"


# ---------------------------------------------------------------------------
# Metriche grezze per titolo (§12, tabella "Definizione operativa")
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
# Percentile cross-sezionale entro l'universo (§12 step 2) e composite (step 3)
# ---------------------------------------------------------------------------

def compute_factor_percentiles(universe_metrics: dict[str, dict]) -> dict[str, dict]:
    """Percentile 0-100 (winsorizzato al 5°/95°, higher=better) per
    ciascuno dei 5 fattori, per ogni ticker dell'universo fornito."""
    peer_lists: dict[str, list] = {}
    for m in universe_metrics.values():
        for k, v in m.items():
            peer_lists.setdefault(k, []).append(v)

    out = {}
    for ticker, m in universe_metrics.items():
        value_pcts = [
            p for p in (
                fscore.percentile_rank(m.get(k), peer_lists.get(k, []), True)
                for k in ("earnings_yield", "fcf_yield", "ev_ebit_yield", "book_to_price")
            ) if p is not None
        ]
        mom_pcts = [
            p for p in (
                fscore.percentile_rank(m.get("momentum_12_1"), peer_lists.get("momentum_12_1", []), True),
                fscore.percentile_rank(m.get("momentum_vol_adj"), peer_lists.get("momentum_vol_adj", []), True),
            ) if p is not None
        ]
        qual_pcts = [
            p for p in (
                fscore.percentile_rank(m.get("roic"), peer_lists.get("roic", []), True),
                fscore.percentile_rank(m.get("gross_profits_to_assets"), peer_lists.get("gross_profits_to_assets", []), True),
                fscore.percentile_rank(m.get("accruals_ratio"), peer_lists.get("accruals_ratio", []), False),
            ) if p is not None
        ]
        lowvol_pcts = [
            p for p in (
                fscore.percentile_rank(m.get("volatility_12m"), peer_lists.get("volatility_12m", []), False),
                fscore.percentile_rank(m.get("beta"), peer_lists.get("beta", []), False),
            ) if p is not None
        ]
        # Size: storicamente piccolo = premio -> percentile alto per market cap PIU' basso
        size_pct = fscore.percentile_rank(m.get("market_cap"), peer_lists.get("market_cap", []), False)

        out[ticker] = {
            "value": sum(value_pcts) / len(value_pcts) if value_pcts else None,
            "momentum": sum(mom_pcts) / len(mom_pcts) if mom_pcts else None,
            "quality": sum(qual_pcts) / len(qual_pcts) if qual_pcts else None,
            "low_vol": sum(lowvol_pcts) / len(lowvol_pcts) if lowvol_pcts else None,
            "size": size_pct,
        }
    return out


def compute_composite(percentiles: dict, weight_profile: str = "Equal-weight") -> float | None:
    """Composite factor score (§12 step 3): media pesata dei percentili
    disponibili, coi pesi ridistribuiti sui fattori disponibili se uno
    manca (stessa logica di ridistribuzione del Fundamental Score)."""
    weights = TILT_PROFILES.get(weight_profile, DEFAULT_WEIGHTS)
    available = {f: percentiles.get(f) for f in FACTORS if percentiles.get(f) is not None}
    if not available:
        return None
    total_w = sum(weights[f] for f in available)
    if total_w <= 0:
        return None
    return sum(available[f] * weights[f] for f in available) / total_w


# ---------------------------------------------------------------------------
# Universo (§12 step 1) e orchestrazione end-to-end
# ---------------------------------------------------------------------------

def build_universe(portfolio_tickers: list[str], watchlist_tickers: list[str],
                    sectors: list[str] | None = None, include_sector_peers: bool = True) -> list[str]:
    """Titoli in portafoglio + preferiti + peer di settore (riusa la
    stessa lista curata del Fundamental Score, src/sector_universe.py) —
    l'universo di confronto per i percentili cross-sezionali."""
    tickers = {t.strip().upper() for t in portfolio_tickers} | {t.strip().upper() for t in watchlist_tickers}
    if include_sector_peers and sectors:
        for sector in sectors:
            tickers |= set(su.peers_for_sector(sector))
    return sorted(tickers)


def build_factor_report(target_tickers: list[str], universe_tickers: list[str],
                         weight_profile: str = "Equal-weight",
                         use_cache: bool = True, sync_cache: bool = False) -> dict:
    """Calcola metriche/percentili/composite per `target_tickers` (i
    titoli da mostrare, es. portafoglio+preferiti) usando `universe_tickers`
    (target inclusi) come base di confronto cross-sezionale. Cache locale
    condivisa con lo stesso meccanismo del Fundamental Score
    (src/fundamental_cache.py), file separato per non mischiare schemi."""
    all_tickers = sorted(set(universe_tickers) | set(target_tickers))

    def _fetch(ticker: str) -> dict:
        info = dp.get_info(ticker)
        hist = finmod.get_financial_history(ticker, freq="annual")
        return compute_factor_metrics(ticker, info=info, hist=hist)

    universe_metrics: dict[str, dict] = {}
    if use_cache:
        cache = fc.load_cache(FACTOR_CACHE_PATH)
        universe_metrics, cache, changed = fc.get_peer_group_data(all_tickers, _fetch, cache)
        if changed:
            fc.persist_and_sync(cache, path=FACTOR_CACHE_PATH, sync_to_github=sync_cache)
    else:
        for t in all_tickers:
            try:
                universe_metrics[t] = _fetch(t)
            except Exception:
                continue

    percentiles = compute_factor_percentiles(universe_metrics)
    composites = {t: compute_composite(percentiles.get(t, {}), weight_profile) for t in percentiles}

    ranking = sorted(
        ({"ticker": t, "composite": composites.get(t), **percentiles.get(t, {})} for t in target_tickers if t in percentiles),
        key=lambda r: (r["composite"] is None, -(r["composite"] or 0)),
    )

    return {
        "universe_size": len(universe_metrics),
        "weight_profile": weight_profile,
        "metrics": universe_metrics,
        "percentiles": percentiles,
        "composites": composites,
        "ranking": ranking,
    }


def radar_data(symbol: str, percentiles: dict) -> dict:
    """Dati pronti per un radar a 5 assi (Value/Momentum/Quality/Low-Vol/
    Size) per un singolo titolo — il rendering vero e proprio (Plotly) è
    nella pagina, questo modulo resta senza dipendenze di grafica."""
    p = percentiles.get(symbol, {})
    return {
        "symbol": symbol,
        "axes": [FACTOR_LABELS_IT[f] for f in FACTORS],
        "values": [p.get(f) if p.get(f) is not None else 0 for f in FACTORS],
        "raw": p,
    }
