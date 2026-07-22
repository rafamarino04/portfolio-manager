"""
Motore di Fundamental Score (0-100), costruito seguendo strettamente
Specifica_Fundamental_Score_yfinance.md (fornita dall'utente). I commenti
richiamano i paragrafi (§n) della specifica per ogni blocco, cosi' e'
verificabile riga per riga cosa implementa cosa.

Non e' un modello di fair value: e' uno strumento di screening — qualita'
(redditivita', solidita', qualita' degli utili) + convenienza relativa
(percentile di valutazione contro il peer group di settore), pensato per
un orizzonte di medio termine (§0, §10).
"""
from __future__ import annotations

from src import data_provider as dp
from src import financials as finmod
from src import fundamental_cache as fc
from src import sector_universe as su

# ---------------------------------------------------------------------------
# §3 / §7 — le 6 categorie, i profili di peso settoriali e le metriche membro
# ---------------------------------------------------------------------------
CATEGORIES = [
    "profitability", "earnings_quality", "financial_strength",
    "growth_quality", "capital_allocation", "valuation",
]

CATEGORY_LABELS_IT = {
    "profitability": "Redditività e creazione di valore",
    "earnings_quality": "Qualità degli utili e cash flow",
    "financial_strength": "Solidità finanziaria",
    "growth_quality": "Qualità della crescita",
    "capital_allocation": "Capital allocation",
    "valuation": "Valutazione relativa",
}

# §7, tabella pesi per categoria/profilo (ogni colonna somma 100)
SECTOR_WEIGHTS = {
    "Growth/Tech":         {"profitability": 28, "earnings_quality": 20, "financial_strength": 12, "growth_quality": 22, "capital_allocation": 6,  "valuation": 12},
    "Value/Industrial":    {"profitability": 22, "earnings_quality": 20, "financial_strength": 22, "growth_quality": 12, "capital_allocation": 12, "valuation": 12},
    "Utilities/Defensive": {"profitability": 18, "earnings_quality": 15, "financial_strength": 25, "growth_quality": 8,  "capital_allocation": 20, "valuation": 14},
    "Consumer":            {"profitability": 24, "earnings_quality": 18, "financial_strength": 16, "growth_quality": 14, "capital_allocation": 14, "valuation": 14},
    "Healthcare":          {"profitability": 26, "earnings_quality": 18, "financial_strength": 14, "growth_quality": 20, "capital_allocation": 8,  "valuation": 14},
    "Energy/Materials":    {"profitability": 18, "earnings_quality": 22, "financial_strength": 24, "growth_quality": 8,  "capital_allocation": 14, "valuation": 14},
}

# §7 "Aggiustamenti per market cap": peso Piotroski cap-adjusted (aggiunto
# a parte rispetto alle 6 categorie, §6 step 7-8)
PIOTROSKI_WEIGHT_BY_CAP = {"mega_large": 5.0, "mid": 10.0, "small_micro": 13.0, "unknown": 8.0}

# Metriche membro di ciascuna categoria: (chiave, higher_is_better).
# La specifica non specifica sotto-pesi più fini tra le metriche di una
# stessa categoria ("media pesata dei percentili delle metriche membro",
# §6 step 6): qui si usa una media equal-weight tra i membri disponibili,
# scelta esplicita mia in assenza di indicazioni più precise.
CATEGORY_METRICS = {
    "profitability": [("roic", True), ("gross_profits_to_assets", True)],
    "earnings_quality": [("fcf_conversion", True), ("accruals_ratio", False)],
    "financial_strength": [("net_debt_to_ebitda", False), ("interest_coverage", True)],
    "growth_quality": [("revenue_cagr", True), ("eps_cagr", True), ("growth_volatility", False)],
    "capital_allocation": [("shareholder_yield", True)],
    "valuation": [("ev_ebit_yield", True)],
}

SCORE_BANDS = [
    (80, 100, "Eccellente"),
    (60, 79, "Solido"),
    (40, 59, "Nella media"),
    (20, 39, "Debole"),
    (0, 19, "Scarso"),
]

# §6 step 10: soglia minima di completezza dati per mostrare uno score
DATA_COMPLETENESS_THRESHOLD = 0.60

# §5: settori più vicini al campione manifatturiero originale di Altman
# (intensità di capitale fisico, magazzino, ciclo industriale) usano la
# variante Z; gli altri non-financial (servizi, tech, sanità, consumer
# staples...) usano Z'' come indicato dalla specifica per i non-manifatturieri.
_ALTMAN_MANUFACTURING_LIKE_SECTORS = {"Industrials", "Basic Materials", "Energy", "Consumer Cyclical"}


def score_band_label(score: float | None) -> str:
    if score is None:
        return "n/d"
    for lo, hi, label in SCORE_BANDS:
        if lo <= score <= hi:
            return label
    return "n/d"


def _safe_div(n, d):
    if n is None or d in (None, 0):
        return None
    try:
        if isinstance(d, float) and d != d:  # NaN
            return None
        return n / d
    except Exception:
        return None


# ---------------------------------------------------------------------------
# §2 — le 8 metriche core + le 3 di crescita usate dalla categoria Growth Quality
# ---------------------------------------------------------------------------

def compute_core_metrics(symbol: str, info: dict | None = None, hist: dict | None = None) -> dict:
    """Calcola le metriche grezze (core §2 + crescita §3) per un titolo,
    dai bilanci storici e da `Ticker.info`. Ogni valore può restare None
    se i dati sottostanti non sono disponibili per quel titolo."""
    info = info if info is not None else dp.get_info(symbol)
    hist = hist if hist is not None else finmod.get_financial_history(symbol, freq="annual")

    all_keys = [k for members in CATEGORY_METRICS.values() for k, _ in members]
    metrics: dict = {k: None for k in all_keys}

    # --- ROIC (§2.1): medie 3-5 anni di EBIT (proxy: Utile operativo) e
    # Invested Capital, per smorzare il rumore ciclico, poi NOPAT / IC.
    ebit_s = hist.get("operating_income")
    debt_s, equity_s, cash_s = hist.get("total_debt"), hist.get("total_equity"), hist.get("cash")
    tax_s, pretax_s = hist.get("tax_provision"), hist.get("pretax_income")
    if ebit_s is not None and debt_s is not None and equity_s is not None and len(ebit_s) > 0:
        n = min(5, len(ebit_s))
        ebit_avg = float(ebit_s.iloc[-n:].mean())
        d_avg = float(debt_s.iloc[-min(n, len(debt_s)):].mean())
        e_avg = float(equity_s.iloc[-min(n, len(equity_s)):].mean())
        c_avg = float(cash_s.iloc[-min(n, len(cash_s)):].mean()) if cash_s is not None and len(cash_s) else 0.0

        tax_rate = 0.25  # fallback esplicito di specifica se anomalo/mancante
        if tax_s is not None and pretax_s is not None:
            t_aligned, p_aligned = tax_s.align(pretax_s, join="inner")
            if not t_aligned.empty:
                rates = (t_aligned / p_aligned).replace([float("inf"), float("-inf")], None).dropna()
                rates = rates[(rates >= 0) & (rates <= 0.6)]
                if not rates.empty:
                    tax_rate = float(rates.mean())

        nopat_avg = ebit_avg * (1 - tax_rate)
        invested_capital = d_avg + e_avg - c_avg
        if invested_capital and invested_capital > 0:
            metrics["roic"] = nopat_avg / invested_capital * 100

    # --- Gross-profits-to-assets (Novy-Marx), ultimo periodo disponibile
    gp_s, ta_s = hist.get("gross_profit"), hist.get("total_assets")
    if gp_s is not None and ta_s is not None:
        gp_a, ta_a = gp_s.align(ta_s, join="inner")
        if not gp_a.empty and ta_a.iloc[-1]:
            metrics["gross_profits_to_assets"] = float(gp_a.iloc[-1] / ta_a.iloc[-1] * 100)

    # --- FCF conversion = FCF / Utile netto
    fcf_s, ni_s = hist.get("free_cash_flow"), hist.get("net_income")
    if fcf_s is not None and ni_s is not None:
        f_a, n_a = fcf_s.align(ni_s, join="inner")
        if not f_a.empty and n_a.iloc[-1]:
            metrics["fcf_conversion"] = float(f_a.iloc[-1] / n_a.iloc[-1] * 100)

    # --- Accruals ratio (Sloan) = (NI - CFO) / Total Assets, ultimo periodo
    cfo_s = hist.get("operating_cash_flow")
    if ni_s is not None and cfo_s is not None and ta_s is not None:
        n_a, c_a = ni_s.align(cfo_s, join="inner")
        if not n_a.empty:
            _, t_a = n_a.align(ta_s, join="inner")
            if not t_a.empty and t_a.iloc[-1]:
                metrics["accruals_ratio"] = float((n_a.iloc[-1] - c_a.iloc[-1]) / t_a.iloc[-1] * 100)

    # --- Net Debt/EBITDA e Interest coverage: riusa i ratio di financials.py
    ratios = finmod.compute_ratios(hist)
    metrics["net_debt_to_ebitda"] = finmod._last(ratios.get("net_debt_to_ebitda"))
    metrics["interest_coverage"] = finmod._last(ratios.get("interest_coverage"))

    # --- EV/EBIT earnings yield
    ebit_latest = finmod._last(ebit_s) if ebit_s is not None else None
    ev = info.get("enterprise_value")
    if ebit_latest is not None and ev:
        metrics["ev_ebit_yield"] = float(ebit_latest / ev * 100)

    # --- Shareholder yield = (dividendi + buyback netti) / market cap
    div_s, buy_s, iss_s = hist.get("dividends_paid"), hist.get("buyback"), hist.get("stock_issuance")
    market_cap = info.get("market_cap")
    if market_cap:
        div_latest = abs(finmod._last(div_s) or 0.0)
        buy_latest = abs(finmod._last(buy_s) or 0.0)
        iss_latest = finmod._last(iss_s) or 0.0
        net_buyback = max(buy_latest - iss_latest, 0.0)
        metrics["shareholder_yield"] = float((div_latest + net_buyback) / market_cap * 100)

    # --- Growth Quality (§3): CAGR ricavi/EPS 3-5y + volatilità crescita
    rev_s, eps_s = hist.get("revenue"), hist.get("eps")
    metrics["revenue_cagr"] = finmod.growth_rate(rev_s)
    metrics["eps_cagr"] = finmod.growth_rate(eps_s)
    if rev_s is not None and len(rev_s) >= 3:
        yoy = rev_s.pct_change().dropna() * 100
        if len(yoy) >= 2:
            metrics["growth_volatility"] = float(yoy.std())

    return metrics


# ---------------------------------------------------------------------------
# §4 — Piotroski F-Score (badge separato)
# ---------------------------------------------------------------------------

def compute_piotroski(hist: dict) -> dict:
    """F-Score 0-9 sui 9 criteri binari di §4, confrontando l'ultimo
    periodo annuale disponibile (t) con il precedente (t-1)."""
    result = {"score": None, "criteria": {}, "n_criteria_available": 0, "insufficient_data": True}

    def _two(series):
        if series is None or len(series) < 2:
            return None, None
        return float(series.iloc[-2]), float(series.iloc[-1])

    ni_prev, ni_t = _two(hist.get("net_income"))
    ta_prev, ta_t = _two(hist.get("total_assets"))
    cfo_prev, cfo_t = _two(hist.get("operating_cash_flow"))
    ltd_prev, ltd_t = _two(hist.get("long_term_debt"))
    ca_prev, ca_t = _two(hist.get("current_assets"))
    cl_prev, cl_t = _two(hist.get("current_liabilities"))
    shares_prev, shares_t = _two(hist.get("diluted_shares"))
    gp_prev, gp_t = _two(hist.get("gross_profit"))
    rev_prev, rev_t = _two(hist.get("revenue"))

    crit = {}
    if ni_t is not None and ta_t:
        crit["roa_positivo"] = (ni_t / ta_t) > 0
    if cfo_t is not None:
        crit["cfo_positivo"] = cfo_t > 0
    if ni_t is not None and ta_t and ni_prev is not None and ta_prev:
        crit["roa_in_crescita"] = (ni_t / ta_t) > (ni_prev / ta_prev)
    if cfo_t is not None and ni_t is not None:
        crit["cfo_supera_utile"] = cfo_t > ni_t
    if ltd_t is not None and ta_t and ltd_prev is not None and ta_prev:
        crit["leva_ltd_in_calo"] = (ltd_t / ta_t) < (ltd_prev / ta_prev)
    if ca_t is not None and cl_t and ca_prev is not None and cl_prev:
        crit["current_ratio_in_crescita"] = (ca_t / cl_t) > (ca_prev / cl_prev)
    if shares_t is not None and shares_prev is not None:
        crit["nessuna_diluizione"] = shares_t <= shares_prev
    if gp_t is not None and rev_t and gp_prev is not None and rev_prev:
        crit["margine_lordo_in_crescita"] = (gp_t / rev_t) > (gp_prev / rev_prev)
    if rev_t is not None and ta_t and rev_prev is not None and ta_prev:
        crit["turnover_in_crescita"] = (rev_t / ta_t) > (rev_prev / ta_prev)

    result["criteria"] = crit
    result["n_criteria_available"] = len(crit)
    if not crit:
        return result

    # Soglia di robustezza aggiunta da me (non esplicitata dalla specifica
    # per il singolo badge): sotto i 6/9 criteri calcolabili il punteggio
    # sarebbe costruito su troppi pochi criteri per essere indicativo,
    # coerentemente con lo spirito della soglia di completezza del 60%
    # usata altrove nella specifica (§6 step 10).
    result["insufficient_data"] = len(crit) < 6
    if not result["insufficient_data"]:
        result["score"] = sum(1 for v in crit.values() if v)
    return result


# ---------------------------------------------------------------------------
# §5 — Altman Z / Z'' (override di distress)
# ---------------------------------------------------------------------------

def compute_altman(info: dict, hist: dict, sector: str | None) -> dict:
    """Z (manifatturiero) o Z'' (non-manifatturiero) a seconda del
    settore, come indicato in §5. yfinance non espone 'Total Liabilities'
    come voce diretta: la si ricava dall'identità di bilancio
    Total Assets - Total Equity."""
    result = {"z": None, "variant": None, "zone": None, "insufficient_data": True}

    variant = "Z" if sector in _ALTMAN_MANUFACTURING_LIKE_SECTORS else "Z''"

    ta = finmod._last(hist.get("total_assets"))
    ca = finmod._last(hist.get("current_assets"))
    cl = finmod._last(hist.get("current_liabilities"))
    re_ = finmod._last(hist.get("retained_earnings"))
    ebit = finmod._last(hist.get("operating_income"))
    rev = finmod._last(hist.get("revenue"))
    equity_book = finmod._last(hist.get("total_equity"))
    market_cap = info.get("market_cap")

    if not ta:
        return result

    total_liabilities = (ta - equity_book) if equity_book is not None else None

    x1 = _safe_div((ca - cl) if (ca is not None and cl is not None) else None, ta)
    x2 = _safe_div(re_, ta)
    x3 = _safe_div(ebit, ta)

    if variant == "Z":
        x4 = _safe_div(market_cap, total_liabilities)
        x5 = _safe_div(rev, ta)
        parts = [x1, x2, x3, x4, x5]
        if any(p is None for p in parts):
            return result
        z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
        zone = "safe" if z > 2.99 else ("grey" if z >= 1.81 else "distress")
    else:
        x4 = _safe_div(equity_book, total_liabilities)
        parts = [x1, x2, x3, x4]
        if any(p is None for p in parts):
            return result
        z = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
        zone = "safe" if z > 2.6 else ("grey" if z >= 1.1 else "distress")

    result.update({"z": float(z), "variant": variant, "zone": zone, "insufficient_data": False})
    return result


# ---------------------------------------------------------------------------
# §6 steps 4-6 — winsorizzazione + percentile-rank sector-relative
# ---------------------------------------------------------------------------

def _winsorize(values: list[float], low_pct: float = 5, high_pct: float = 95) -> list[float]:
    if len(values) < 5:
        return values
    s = sorted(values)
    n = len(s)

    def _pct(p):
        idx = (p / 100) * (n - 1)
        lo, hi = int(idx), min(int(idx) + 1, n - 1)
        frac = idx - lo
        return s[lo] + (s[hi] - s[lo]) * frac

    lo_val, hi_val = _pct(low_pct), _pct(high_pct)
    return [min(max(v, lo_val), hi_val) for v in values]


def percentile_rank(value: float | None, peer_values: list[float | None], higher_is_better: bool = True) -> float | None:
    """Percentile 0-100 di `value` nel peer group (winsorizzato al
    5°/95°), orientato cosi' che un valore piu' alto sia sempre 'meglio'
    (§6 step 5: multipli e metriche di leva vanno invertiti)."""
    if value is None:
        return None
    clean = [v for v in peer_values if v is not None]
    if len(clean) < 3:
        return None
    winsorized = _winsorize(clean)
    v = min(max(value, min(winsorized)), max(winsorized))
    rank = sum(1 for p in winsorized if p <= v) / len(winsorized) * 100
    return rank if higher_is_better else 100 - rank


def compute_metric_percentiles(target_metrics: dict, peer_metrics_by_ticker: dict[str, dict]) -> dict:
    """Percentile sector-relative (0-100) di ciascuna metrica core,
    orientato higher=better — usato sia per i sub-score di categoria sia
    per il metric grid della pagina (mostrare il percentile per singola
    metrica, non solo il numero aggregato, è più utile per capire *perché*
    uno score è quello che è)."""
    peer_lists: dict[str, list] = {}
    for m in peer_metrics_by_ticker.values():
        for key, val in m.items():
            peer_lists.setdefault(key, []).append(val)

    higher_better_map = {k: hb for members in CATEGORY_METRICS.values() for k, hb in members}
    return {
        key: percentile_rank(target_metrics.get(key), peer_lists.get(key, []), hb)
        for key, hb in higher_better_map.items()
    }


def compute_category_subscores(target_metrics: dict, peer_metrics_by_ticker: dict[str, dict]) -> tuple[dict, dict]:
    """Sub-score (0-100) per ciascuna delle 6 categorie (§3, §6 step 6):
    media dei percentili sector-relative delle metriche disponibili nella
    categoria. Ritorna anche la copertura (quota di metriche disponibili
    per categoria) per il calcolo di completezza dati complessivo."""
    metric_percentiles = compute_metric_percentiles(target_metrics, peer_metrics_by_ticker)

    subscores, coverage = {}, {}
    for cat, members in CATEGORY_METRICS.items():
        percentiles = [metric_percentiles[key] for key, _ in members if metric_percentiles.get(key) is not None]
        if percentiles:
            subscores[cat] = sum(percentiles) / len(percentiles)
            coverage[cat] = len(percentiles) / len(members)
        else:
            subscores[cat] = None
            coverage[cat] = 0.0
    return subscores, coverage


# ---------------------------------------------------------------------------
# §6 steps 7-11 — composito: pesi sector/cap-adjusted + Piotroski + Altman
# ---------------------------------------------------------------------------

def compute_composite_score(
    subscores: dict,
    weight_profile: str | None,
    cap_bucket: str,
    piotroski: dict,
    altman: dict,
) -> dict:
    base_weights = SECTOR_WEIGHTS.get(weight_profile) if weight_profile else None
    if base_weights is None:
        return {"score": None, "insufficient_data": True, "reason": "profilo di peso settoriale non disponibile per questo titolo"}

    piotroski_weight = PIOTROSKI_WEIGHT_BY_CAP.get(cap_bucket, 8.0)
    # Le 6 categorie si riscalano per lasciare spazio al Piotroski, che si
    # aggiunge "a parte" (§6 step 7-8) invece di essere sepolto in una
    # categoria.
    scale = (100 - piotroski_weight) / 100
    category_weights = {cat: w * scale for cat, w in base_weights.items()}

    available_cats = [c for c in CATEGORIES if subscores.get(c) is not None]
    total_available_weight = sum(category_weights[c] for c in available_cats)
    missing_weight = sum(category_weights[c] for c in CATEGORIES if c not in available_cats)

    # Ridistribuzione del peso delle categorie mancanti sulle disponibili,
    # in proporzione al loro peso originale (§6 step 10).
    final_weights = {}
    if total_available_weight > 0:
        for c in available_cats:
            final_weights[c] = category_weights[c] + missing_weight * (category_weights[c] / total_available_weight)

    weighted_sum = sum(subscores[c] * final_weights.get(c, 0) for c in available_cats)
    category_component = weighted_sum / 100

    piotroski_component = None
    if piotroski.get("score") is not None:
        piotroski_component = (piotroski["score"] / 9 * 100) * piotroski_weight / 100

    # Completezza dati complessiva (§6 step 10): quota del peso totale
    # (categorie + Piotroski) effettivamente coperta da dati reali.
    covered_weight = total_available_weight + (piotroski_weight if piotroski_component is not None else 0.0)
    completeness = covered_weight / 100.0

    if completeness < DATA_COMPLETENESS_THRESHOLD:
        return {
            "score": None, "insufficient_data": True, "completeness": completeness,
            "reason": f"copertura dati {completeness*100:.0f}%, sotto la soglia minima del {DATA_COMPLETENESS_THRESHOLD*100:.0f}% (§6 step 10)",
        }

    composite = max(0.0, min(100.0, category_component + (piotroski_component or 0.0)))

    capped = False
    if altman.get("zone") == "distress" and composite > 40:
        composite = 40.0
        capped = True

    return {
        "score": composite,
        "band": score_band_label(composite),
        "insufficient_data": False,
        "completeness": completeness,
        "altman_capped": capped,
        "category_weights_used": final_weights,
        "piotroski_weight_used": piotroski_weight if piotroski_component is not None else None,
    }


# ---------------------------------------------------------------------------
# §9 — flag automatici testuali
# ---------------------------------------------------------------------------

def generate_flags(hist: dict, altman: dict, pe_band: dict | None = None, roic: float | None = None, wacc: float | None = None) -> list[str]:
    flags: list[str] = []

    fcf_s, ni_s = hist.get("free_cash_flow"), hist.get("net_income")
    if fcf_s is not None and ni_s is not None:
        f_a, n_a = fcf_s.align(ni_s, join="inner")
        if len(f_a) >= 3:
            denom = n_a.replace(0, None)
            conv = (f_a / denom * 100).dropna()
            if len(conv) >= 3 and conv.iloc[-1] < conv.iloc[-2] < conv.iloc[-3]:
                flags.append("FCF conversion in calo da almeno 3 periodi consecutivi")

    buy_s, shares_s = hist.get("buyback"), hist.get("diluted_shares")
    if buy_s is not None and shares_s is not None and len(shares_s) >= 2:
        last_buyback = finmod._last(buy_s)
        if last_buyback is not None and abs(last_buyback) > 0 and shares_s.iloc[-1] > shares_s.iloc[-2]:
            flags.append("Buyback dichiarati ma numero di azioni in aumento (possibile diluizione da SBC)")

    if pe_band and pe_band.get("percentile") is not None and pe_band["percentile"] >= 90:
        flags.append(f"P/E al {pe_band['percentile']:.0f}° percentile del proprio storico a {pe_band['years']} anni")

    if roic is not None and wacc is not None and roic < wacc:
        flags.append("ROIC sotto il costo del capitale stimato (WACC)")

    if altman.get("zone") == "distress":
        flags.append("Zona di distress secondo Altman Z — punteggio limitato a 40")

    return flags


CAP_LABELS_IT = {
    "mega_large": "mega/large cap (≥ 10 Mld $)", "mid": "mid cap (2-10 Mld $)",
    "small_micro": "small/micro cap (< 2 Mld $)", "unknown": "capitalizzazione non nota",
}


def build_thesis_text(result: dict, info: dict) -> str:
    """Tesi in una riga (formato piano, senza markdown) — usata sia dalla
    pagina sia dall'export Excel, cosi' i due restano sempre coerenti."""
    composite = result["composite"]
    band = composite.get("band", "n/d")
    score = composite.get("score")
    cap_label = CAP_LABELS_IT.get(result.get("cap_bucket"), "n/d")
    profile = result.get("weight_profile") or "n/d"
    sector = info.get("sector") or "n/d"

    subs = {k: v for k, v in result["subscores"].items() if v is not None}
    parts = []
    if score is not None:
        parts.append(f"Punteggio {band} ({score:.0f}/100)")
    else:
        parts.append("Punteggio non mostrato (copertura dati insufficiente)")
    parts.append(f"nel settore {sector} (profilo {profile}, {cap_label}, {result.get('n_peers', 0)} peer di confronto)")

    if len(subs) >= 2:
        best = max(subs, key=subs.get)
        worst = min(subs, key=subs.get)
        if best != worst:
            parts.append(
                f"— punto di forza relativo: {CATEGORY_LABELS_IT[best]} ({subs[best]:.0f}); "
                f"punto debole relativo: {CATEGORY_LABELS_IT[worst]} ({subs[worst]:.0f})"
            )

    if composite.get("altman_capped"):
        parts.append("— punteggio limitato a 40 per zona di distress secondo Altman Z (override di sicurezza)")

    return " ".join(parts) + "."


def build_bull_bear(result: dict) -> tuple[list[str], list[str]]:
    """Punti di forza/attenzione testuali — usati sia dalla pagina sia
    dall'export Excel."""
    bulls, bears = [], []
    subs = result["subscores"]
    for cat, sub in subs.items():
        if sub is None:
            continue
        label = CATEGORY_LABELS_IT[cat]
        if sub >= 70:
            bulls.append(f"{label}: tra i migliori del peer group di settore (percentile {sub:.0f})")
        elif sub <= 30:
            bears.append(f"{label}: tra i più deboli del peer group di settore (percentile {sub:.0f})")

    piotroski = result["piotroski"]
    if piotroski.get("score") is not None:
        if piotroski["score"] >= 7:
            bulls.append(f"Piotroski F-Score {piotroski['score']}/9: solido su profittabilità, leva ed efficienza operativa")
        elif piotroski["score"] <= 3:
            bears.append(f"Piotroski F-Score {piotroski['score']}/9: segnali deboli su più fronti contabili")

    altman = result["altman"]
    if altman.get("zone") == "safe":
        bulls.append(f"Altman {altman['variant']}: zona sicura ({altman['z']:.2f})")

    bears.extend(result.get("flags", []))
    return bulls, bears


# ---------------------------------------------------------------------------
# Orchestrazione end-to-end
# ---------------------------------------------------------------------------

def build_fundamental_score(symbol: str, use_cache: bool = True, sync_cache: bool = False, wacc: float | None = None) -> dict:
    """Punto di ingresso principale: calcola l'intero Fundamental Score
    per `symbol`, incluso il confronto sector-relative con il peer group
    curato per settore (src.sector_universe), via cache locale
    (src.fundamental_cache) per non richiamare yfinance su 15-25 peer ad
    ogni singola analisi."""
    info = dp.get_info(symbol)
    hist = finmod.get_financial_history(symbol, freq="annual")
    sector = info.get("sector")

    if su.is_excluded_sector(sector):
        return {
            "symbol": symbol, "excluded": True, "sector": sector,
            "reason": "Settore finanziario (banche/assicurazioni): EBITDA, ROIC, EV e Piotroski/Altman non sono metriche significative per questo modello di business (§0.5).",
        }

    weight_profile = su.weight_profile_for_sector(sector)
    cap_bucket = su.market_cap_bucket(info.get("market_cap"))
    peers = [p for p in su.peers_for_sector(sector) if p.upper() != symbol.upper()]

    target_metrics = compute_core_metrics(symbol, info=info, hist=hist)

    def _fetch_peer(ticker: str) -> dict:
        p_info = dp.get_info(ticker)
        p_hist = finmod.get_financial_history(ticker, freq="annual")
        return compute_core_metrics(ticker, info=p_info, hist=p_hist)

    peer_metrics: dict = {}
    if use_cache:
        cache = fc.load_cache()
        peer_metrics, cache, changed = fc.get_peer_group_data(peers, _fetch_peer, cache)
        if changed:
            fc.persist_and_sync(cache, sync_to_github=sync_cache)
    else:
        for p in peers:
            try:
                peer_metrics[p] = _fetch_peer(p)
            except Exception:
                continue

    metric_percentiles = compute_metric_percentiles(target_metrics, peer_metrics)
    subscores, coverage = compute_category_subscores(target_metrics, peer_metrics)
    piotroski = compute_piotroski(hist)
    altman = compute_altman(info, hist, sector)
    composite = compute_composite_score(subscores, weight_profile, cap_bucket, piotroski, altman)
    pe_band = finmod.historical_multiple_band(symbol)
    flags = generate_flags(hist, altman, pe_band=pe_band, roic=target_metrics.get("roic"), wacc=wacc)

    return {
        "symbol": symbol, "excluded": False, "sector": sector,
        "weight_profile": weight_profile, "cap_bucket": cap_bucket,
        "n_peers": len(peer_metrics), "peer_metrics": peer_metrics,
        "metrics": target_metrics, "metric_percentiles": metric_percentiles,
        "subscores": subscores, "coverage": coverage,
        "piotroski": piotroski, "altman": altman, "composite": composite,
        "pe_band": pe_band, "flags": flags,
        "needs_reit_override": su.needs_unimplemented_override(sector),
    }
