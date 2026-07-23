"""
Motore di Analisi Fondamentale v2.0 — Quality/Valuation assoluti,
calibrati per settore (specifica fornita dall'utente, 23 luglio 2026,
"Absolute Sector-Calibrated Scoring with Quality-Valuation Matrix and
Critical Notes Layer"). Sostituisce integralmente il motore v1
(percentile/peer-relative, src/sector_universe.py + src/fundamental_cache.py
per il peer group): NESSUN peer group costruito a runtime — ogni
metrica si confronta con tabelle di soglie pre-calcolate per settore/
archetipo (src/sector_thresholds.py), e il risultato si separa in due
ASSI ORTOGONALI — Quality (0-100) e Valuation (0-100) — presentati in
una matrice 2x2 interpretativa (§6), non fusi in un unico numero
(il blended number resta un dettaglio secondario, mai il segnale
primario, §6/§11 raccomandazione 6).

Non è un modello di fair value: resta uno strumento di screening, ora
ancorato a soglie assolute invece che a un confronto relativo — un
punteggio alto è "oggettivamente buono", non "il migliore di un gruppo
scarso" (bug-fix §8/§9.2). Le banche/assicurazioni restano escluse
(EBITDA/ROIC/EV non significativi per il loro modello di business).
"""
from __future__ import annotations

import datetime as dt

from src import beneish as ben
from src import critical_notes as cn
from src import data_provider as dp
from src import financials as finmod
from src import lifecycle as lc
from src import sector_thresholds as sth
from src import sector_universe as su

# ---------------------------------------------------------------------------
# §3.1 — Categorie dell'asse Quality (Capital Allocation ripartita fra
# Profitability e Financial Strength; Relative Valuation esce dall'asse
# Quality ed entra nell'asse Valuation)
# ---------------------------------------------------------------------------
CATEGORIES = ["profitability", "earnings_quality", "financial_strength", "growth_quality"]

CATEGORY_LABELS_IT = {
    "profitability": "Redditività e creazione di valore",
    "earnings_quality": "Qualità degli utili e cash flow",
    "financial_strength": "Solidità finanziaria",
    "growth_quality": "Qualità della crescita",
}

# §7 "Aggiustamenti per market cap": peso Piotroski cap-adjusted, invariato da v1.
PIOTROSKI_WEIGHT_BY_CAP = {"mega_large": 5.0, "mid": 10.0, "small_micro": 13.0, "unknown": 8.0}

# §8 — Vocabolario label italiano su bande ASSOLUTE (6 bande, non più 5:
# bug-fix esplicito rispetto a v1, che usava un vocabolario a 5 bande
# tarato per un contesto percentile).
SCORE_BANDS = [
    (85, 100, "Eccellente"),
    (70, 84, "Buono"),
    (55, 69, "Discreto"),
    (40, 54, "Sufficiente"),
    (20, 39, "Debole"),
    (0, 19, "Scarso"),
]

DATA_COMPLETENESS_THRESHOLD = 0.60

# FIX4 v2.1 — peso di una metrica "stale" (derivata da un esercizio più
# vecchio di quello delle altre voci della sua categoria) nella media di
# categoria: strategia "(b) peso dimezzato" fra le due previste dalla
# specifica v2.1 (l'altra, esclusione+ridistribuzione, è il caso limite
# peso=0 di una media pesata generale — qui si usa sempre la stessa media
# pesata, con questo peso invece di escludere il membro del tutto, per non
# perdere l'informazione quando è l'unico dato disponibile in categoria).
STALE_MEMBER_WEIGHT = 0.5

# FIX4 v2.1 — oltre quanti mesi di ritardo rispetto alla metrica più
# recente della stessa categoria una singola voce viene etichettata
# "stale" (regola generale, non per titolo: un anno di bilancio).
STALE_FIELD_LAG_MONTHS = 12

# §5, NC-05: settori/archetipi dove l'R&D non capitalizzato è materiale.
_ALTMAN_MANUFACTURING_LIKE_SECTORS = {"Industrials", "Basic Materials", "Energy", "Consumer Cyclical"}

MATRIX_QUALITY_THRESHOLD = 60
MATRIX_VALUATION_THRESHOLD = 60

MATRIX_QUADRANTS = {
    ("high", "cheap"): {
        "key": "wonderful", "label": "Wonderful company at a fair price",
        "action": "Candidato forte: approfondire la tesi e la sostenibilità del moat.",
    },
    ("high", "expensive"): {
        "key": "quality_at_price", "label": "Quality-at-a-price — buon business ma caro",
        "action": "Watchlist: attendere un pullback o accumulare gradualmente.",
    },
    ("low", "cheap"): {
        "key": "value_trap", "label": "Potenziale VALUE TRAP",
        "action": "Cautela: distinguere tra trappola strutturale e occasione contrarian — serve una tesi specifica su catalizzatore/turnaround.",
    },
    ("low", "expensive"): {
        "key": "avoid", "label": "Evitare",
        "action": "Nessun interesse, salvo una scommessa speculativa esplicita su turnaround/momentum.",
    },
}


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
        if isinstance(d, float) and d != d:
            return None
        return n / d
    except Exception:
        return None


def _global_anchor(value, anchors):
    return sth.interp(value, anchors) if value is not None else None


# Ancore assolute GLOBALI aggiuntive (non sector-specific), mia scelta
# esplicita dove la specifica non fornisce un numero preciso.
_SHAREHOLDER_YIELD_ANCHORS = [(0, 10), (2, 47), (5, 77), (8, 92)]
_REVENUE_CAGR_ANCHORS = [(0, 10), (5, 47), (15, 77), (30, 92)]
_EPS_CAGR_ANCHORS = [(0, 10), (5, 47), (15, 77), (30, 92)]
_GROWTH_VOLATILITY_ANCHORS = [(5, 92), (15, 77), (30, 47), (60, 10)]  # più bassa = meglio
_EARNINGS_YIELD_SPREAD_ANCHORS = [(0, 10), (3, 47), (6, 77), (10, 92)]
_PEG_ANCHORS = [(0.5, 92), (1.0, 70), (1.5, 50), (3.0, 10)]  # più basso = economico


# ---------------------------------------------------------------------------
# §2 — Metriche core (grezze) per un titolo: estende compute_core_metrics
# v1 con le voci richieste dal motore v2 (Dickinson, Beneish, Note
# Critiche, assi Quality/Valuation assoluti).
# ---------------------------------------------------------------------------

def compute_core_metrics(symbol: str, info: dict | None = None, hist: dict | None = None) -> dict:
    info = info if info is not None else dp.get_info(symbol)
    hist = hist if hist is not None else finmod.get_financial_history(symbol, freq="annual")

    metrics: dict = {}

    ebit_s = hist.get("operating_income")
    debt_s, equity_s, cash_s = hist.get("total_debt"), hist.get("total_equity"), hist.get("cash")
    tax_s, pretax_s = hist.get("tax_provision"), hist.get("pretax_income")
    ta_s = hist.get("total_assets")

    # FIX4 v2.1 — data dell'esercizio da cui deriva ciascuna metrica
    # "puntuale" (non la data di download): serve a rilevare se una
    # singola metrica arriva da un anno più vecchio delle altre della
    # stessa categoria (campo assente negli anni recenti), non solo se
    # l'intero bilancio è vecchio (quello lo copre già last_statement_date).
    metric_dates: dict = {}

    def _index_date(series):
        if series is None or len(series) == 0:
            return None
        idx = series.index[-1]
        return idx.date() if hasattr(idx, "date") else idx

    # --- ROIC (media pluriennale NOPAT/Invested Capital) ---
    metrics["roic"] = None
    if ebit_s is not None and debt_s is not None and equity_s is not None and len(ebit_s) > 0:
        n = min(5, len(ebit_s))
        ebit_avg = float(ebit_s.iloc[-n:].mean())
        d_avg = float(debt_s.iloc[-min(n, len(debt_s)):].mean())
        e_avg = float(equity_s.iloc[-min(n, len(equity_s)):].mean())
        c_avg = float(cash_s.iloc[-min(n, len(cash_s)):].mean()) if cash_s is not None and len(cash_s) else 0.0

        tax_rate = 0.25
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

    # --- Gross-profits-to-assets (Novy-Marx) ---
    metrics["gross_profits_to_assets"] = None
    gp_s = hist.get("gross_profit")
    if gp_s is not None and ta_s is not None:
        gp_a, ta_a = gp_s.align(ta_s, join="inner")
        if not gp_a.empty and ta_a.iloc[-1]:
            metrics["gross_profits_to_assets"] = float(gp_a.iloc[-1] / ta_a.iloc[-1] * 100)
            metric_dates["gross_profits_to_assets"] = _index_date(gp_a)

    # --- Margine operativo after-tax (§3.2) — livello corrente + mediana storica (NC-08) ---
    margins = finmod.compute_margins(hist)
    op_margin_s = margins.get("operating_margin")
    metrics["operating_margin_current"] = finmod._last(op_margin_s)
    metrics["operating_margin_median_8y"] = float(op_margin_s.median()) if op_margin_s is not None and len(op_margin_s) >= 3 else None
    metric_dates["operating_margin_current"] = _index_date(op_margin_s)

    # --- FCF conversion ---
    fcf_s, ni_s = hist.get("free_cash_flow"), hist.get("net_income")
    metrics["fcf_conversion"] = None
    if fcf_s is not None and ni_s is not None:
        f_a, n_a = fcf_s.align(ni_s, join="inner")
        if not f_a.empty and n_a.iloc[-1]:
            metrics["fcf_conversion"] = float(f_a.iloc[-1] / n_a.iloc[-1] * 100)
            metric_dates["fcf_conversion"] = _index_date(f_a)

    # --- Accruals ratio (Sloan, formula cash-flow v2.0: (NI-CFO-CFI)/Attivo medio) ---
    cfo_s, cfi_s = hist.get("operating_cash_flow"), hist.get("cfi")
    metrics["accruals_ratio"] = None
    if ni_s is not None and cfo_s is not None and cfi_s is not None and ta_s is not None and len(ta_s) >= 2:
        n_a, c_a = ni_s.align(cfo_s, join="inner")
        if not n_a.empty:
            _, ci_a = n_a.align(cfi_s, join="inner")
            if not ci_a.empty:
                avg_ta = float(ta_s.iloc[-2:].mean())
                if avg_ta:
                    ni_last = float(n_a.iloc[-1])
                    cfo_last = float(c_a.loc[n_a.index[-1]]) if n_a.index[-1] in c_a.index else None
                    cfi_last = float(ci_a.loc[n_a.index[-1]]) if n_a.index[-1] in ci_a.index else None
                    if cfo_last is not None and cfi_last is not None:
                        metrics["accruals_ratio"] = (ni_last - cfo_last - cfi_last) / avg_ta * 100

    # --- Net Debt/EBITDA, interest coverage ---
    ratios = finmod.compute_ratios(hist)
    metrics["net_debt_to_ebitda"] = finmod._last(ratios.get("net_debt_to_ebitda"))
    metrics["interest_coverage"] = finmod._last(ratios.get("interest_coverage"))
    metrics["net_debt"] = finmod._last(ratios.get("net_debt"))
    metric_dates["net_debt_to_ebitda"] = _index_date(ratios.get("net_debt_to_ebitda"))
    metric_dates["interest_coverage"] = _index_date(ratios.get("interest_coverage"))

    # --- EV/EBIT earnings yield (Greenblatt) ---
    ebit_latest = finmod._last(ebit_s) if ebit_s is not None else None
    ev = info.get("enterprise_value")
    metrics["ebit"] = ebit_latest
    metrics["ev_ebit_yield"] = float(ebit_latest / ev * 100) if ebit_latest is not None and ev else None

    # --- Shareholder yield ---
    div_s, buy_s, iss_s = hist.get("dividends_paid"), hist.get("buyback"), hist.get("stock_issuance")
    market_cap = info.get("market_cap")
    metrics["shareholder_yield"] = None
    div_latest = abs(finmod._last(div_s) or 0.0)
    buy_latest = abs(finmod._last(buy_s) or 0.0)
    iss_latest = finmod._last(iss_s) or 0.0
    net_buyback = max(buy_latest - iss_latest, 0.0)
    if market_cap:
        metrics["shareholder_yield"] = float((div_latest + net_buyback) / market_cap * 100)
    metrics["buyback_active"] = buy_latest > 0

    # --- Crescita (§3, riusata anche da lifecycle.py per l'archetipo) ---
    rev_s, eps_s = hist.get("revenue"), hist.get("eps")
    metrics["revenue_cagr"] = finmod.growth_rate(rev_s)
    metrics["eps_cagr"] = finmod.growth_rate(eps_s)
    metrics["growth_volatility"] = None
    if rev_s is not None and len(rev_s) >= 3:
        yoy = rev_s.pct_change().dropna() * 100
        if len(yoy) >= 2:
            metrics["growth_volatility"] = float(yoy.std())
    rev_yoy = finmod.latest_and_yoy(rev_s)
    metrics["revenue_yoy_pct"] = rev_yoy.get("yoy_pct")
    ni_yoy = finmod.latest_and_yoy(ni_s)
    metrics["ni_yoy_pct"] = ni_yoy.get("yoy_pct")
    metrics["net_income"] = ni_yoy.get("latest")
    ta_yoy = finmod.latest_and_yoy(ta_s)
    metrics["total_assets_yoy_pct"] = ta_yoy.get("yoy_pct")
    metrics["total_assets"] = ta_yoy.get("latest")

    # --- ROE / ROA / leva (per NC-02, NC-03) ---
    equity_latest = finmod._last(equity_s)
    metrics["total_equity"] = equity_latest
    metrics["roe"] = (metrics["net_income"] / equity_latest * 100) if metrics["net_income"] is not None and equity_latest else None
    metrics["roa"] = (metrics["net_income"] / metrics["total_assets"] * 100) if metrics["net_income"] is not None and metrics["total_assets"] else None
    metrics["leverage_ta_equity"] = _safe_div(metrics["total_assets"], equity_latest) if equity_latest else None
    retained = finmod._last(hist.get("retained_earnings"))
    metrics["retained_earnings_to_ta"] = _safe_div(retained, metrics["total_assets"])
    metrics["retained_earnings_to_ta"] = metrics["retained_earnings_to_ta"] * 100 if metrics["retained_earnings_to_ta"] is not None else None

    # --- Goodwill, R&D, lease, SBC, deferred revenue, current ratio, PP&E (Note Critiche) ---
    goodwill = finmod._last(hist.get("goodwill"))
    metrics["goodwill"] = goodwill
    metrics["goodwill_to_ta"] = _safe_div(goodwill, metrics["total_assets"])

    rd = finmod._last(hist.get("research_development"))
    rev_latest = finmod._last(rev_s)
    metrics["rd_to_revenue"] = _safe_div(abs(rd), rev_latest) * 100 if rd is not None and rev_latest else None

    lease = finmod._last(hist.get("lease_liabilities"))
    metrics["lease_liabilities"] = lease

    sbc = finmod._last(hist.get("stock_based_compensation"))
    metrics["sbc_to_revenue"] = _safe_div(abs(sbc), rev_latest) * 100 if sbc is not None and rev_latest else None

    diluted_s = hist.get("diluted_shares")
    metrics["diluted_shares_growing"] = None
    if diluted_s is not None and len(diluted_s) >= 2:
        metrics["diluted_shares_growing"] = bool(diluted_s.iloc[-1] > diluted_s.iloc[-2])

    metrics["deferred_revenue"] = finmod._last(hist.get("deferred_revenue"))
    metrics["current_ratio"] = finmod._last(ratios.get("current_ratio"))

    ppe_net, ppe_gross = finmod._last(hist.get("ppe_net")), finmod._last(hist.get("ppe_gross"))
    metrics["ppe_net"], metrics["ppe_gross"] = ppe_net, ppe_gross

    # --- Data ultimo bilancio (NC-15) ---
    metrics["last_statement_date"] = rev_s.index[-1] if rev_s is not None and len(rev_s) else None

    # FIX4 v2.1 — rileva le metriche "stale": una metrica il cui ultimo
    # dato disponibile è più vecchio di STALE_FIELD_LAG_MONTHS rispetto
    # all'esercizio più recente usato per le altre metriche (qui: i ricavi,
    # quasi sempre la voce più aggiornata disponibile). Regola GENERALE,
    # non legata a un titolo: capita tipicamente quando un campo di
    # bilancio è assente negli anni più recenti e valorizzato solo in anni
    # passati (es. una riga di dettaglio che Yahoo Finance ha smesso di
    # riportare separatamente).
    reference_date = _index_date(rev_s) if rev_s is not None else None
    stale_fields: dict = {}
    if reference_date is not None:
        for key, as_of in metric_dates.items():
            if as_of is None or metrics.get(key) is None:
                continue
            months_behind = (reference_date.year - as_of.year) * 12 + (reference_date.month - as_of.month)
            if months_behind > STALE_FIELD_LAG_MONTHS:
                stale_fields[key] = {"months_behind": months_behind, "year": as_of.year}
    metrics["stale_fields"] = stale_fields

    # --- Trend earnings quality (NC-16): pendenza OI vs FCF su fino a 5 anni ---
    metrics["operating_income_trend_slope"] = None
    metrics["fcf_trend_slope"] = None
    metrics["n_years_trend"] = None
    if ebit_s is not None and fcf_s is not None and len(ebit_s) >= 3:
        oi_a, f_a2 = ebit_s.align(fcf_s, join="inner")
        if len(oi_a) >= 3:
            n = len(oi_a)
            x = list(range(n))
            oi_slope = _linreg_slope(x, oi_a.tolist())
            fcf_slope = _linreg_slope(x, f_a2.tolist())
            metrics["operating_income_trend_slope"] = oi_slope
            metrics["fcf_trend_slope"] = fcf_slope
            metrics["n_years_trend"] = n

    return metrics


def _linreg_slope(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    if n < 2:
        return None
    mean_x, mean_y = sum(x) / n, sum(y) / n
    num = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    den = sum((xi - mean_x) ** 2 for xi in x)
    if den == 0:
        return None
    return num / den


# ---------------------------------------------------------------------------
# §3.3 — Piotroski F-Score, con guard rules dalle Note Critiche
# ---------------------------------------------------------------------------

def compute_piotroski(hist: dict, active_rules: set[str] | None = None) -> dict:
    active_rules = active_rules or set()
    result = {"score": None, "criteria": {}, "n_criteria_available": 0, "insufficient_data": True, "suspended_variational": False}

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

    suspend_variational = "suspend_cagr_and_yoy_criteria" in active_rules or "suspend_piotroski_yoy_criteria" in active_rules
    if not suspend_variational:
        if ni_t is not None and ta_t and ni_prev is not None and ta_prev:
            crit["roa_in_crescita"] = (ni_t / ta_t) > (ni_prev / ta_prev)
        if cfo_t is not None and ni_t is not None:
            crit["cfo_supera_utile"] = cfo_t > ni_t
        if ltd_t is not None and ta_t and ltd_prev is not None and ta_prev:
            crit["leva_ltd_in_calo"] = (ltd_t / ta_t) < (ltd_prev / ta_prev)
        if "neutralize_piotroski_current_ratio" not in active_rules:
            if ca_t is not None and cl_t and ca_prev is not None and cl_prev:
                crit["current_ratio_in_crescita"] = (ca_t / cl_t) > (ca_prev / cl_prev)
        if shares_t is not None and shares_prev is not None:
            crit["nessuna_diluizione"] = shares_t <= shares_prev
        if gp_t is not None and rev_t and gp_prev is not None and rev_prev:
            crit["margine_lordo_in_crescita"] = (gp_t / rev_t) > (gp_prev / rev_prev)
        if rev_t is not None and ta_t and rev_prev is not None and ta_prev:
            crit["turnover_in_crescita"] = (rev_t / ta_t) > (rev_prev / ta_prev)
    else:
        result["suspended_variational"] = True

    result["criteria"] = crit
    result["n_criteria_available"] = len(crit)
    if not crit:
        return result

    result["insufficient_data"] = len(crit) < 6
    if not result["insufficient_data"]:
        result["score"] = sum(1 for v in crit.values() if v)
    return result


# ---------------------------------------------------------------------------
# §3.5 — Altman Z / Z'' (distress), soggetto a NC-01
# ---------------------------------------------------------------------------

def compute_altman(info: dict, hist: dict, sector: str | None) -> dict:
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
# §3 — Asse QUALITY: sub-score assoluti per categoria + composito
# ---------------------------------------------------------------------------

def compute_quality_subscores(metrics: dict, bucket: str | None, active_rules: set[str] | None = None,
                               stale_fields: dict | None = None) -> tuple[dict, dict]:
    active_rules = active_rules or set()
    stale_fields = stale_fields or {}

    # FIX4 v2.1: una metrica il cui valore deriva da un esercizio più
    # vecchio di quello usato dalle altre voci della stessa categoria non
    # deve contribuire con peso pieno alla media di categoria — strategia
    # "peso dimezzato" (l'altra strategia prevista dalla spec, esclusione +
    # redistribuzione, è matematicamente equivalente a un peso di 0 per il
    # membro stale in una media pesata: qui usiamo un'unica media pesata
    # generale, con peso 1.0 o STALE_MEMBER_WEIGHT a seconda del caso).
    def _weighted_mean(members_with_keys: list[tuple[float | None, str]]) -> tuple[float | None, int]:
        weighted_sum, weight_total, n_available = 0.0, 0.0, 0
        for value, key in members_with_keys:
            if value is None:
                continue
            n_available += 1
            w = STALE_MEMBER_WEIGHT if key in stale_fields else 1.0
            weighted_sum += value * w
            weight_total += w
        if weight_total <= 0:
            return None, n_available
        return weighted_sum / weight_total, n_available

    roic_s = sth.roic_score(bucket, metrics.get("roic"))
    gpa_s = sth.gross_profits_to_assets_score(metrics.get("gross_profits_to_assets"))
    margin_s = sth.operating_margin_score(bucket, metrics.get("operating_margin_current"))
    shy_s = _global_anchor(metrics.get("shareholder_yield"), _SHAREHOLDER_YIELD_ANCHORS)
    profitability_score, n_profitability = _weighted_mean([
        (roic_s, "roic"), (gpa_s, "gross_profits_to_assets"),
        (margin_s, "operating_margin_current"), (shy_s, "shareholder_yield"),
    ])

    fcf_conv_s = sth.fcf_conversion_score(metrics.get("fcf_conversion"))
    accruals_s = sth.accruals_score(metrics.get("accruals_ratio"))
    earnings_quality_score, n_earnings_quality = _weighted_mean([
        (fcf_conv_s, "fcf_conversion"), (accruals_s, "accruals_ratio"),
    ])
    # FIX5 v2.1 — NC-07/NC-16: penalità REALMENTE applicata (non solo
    # segnalata a testo) al sub-score qualità utili, prima del composito.
    if earnings_quality_score is not None and (
        "penalize_fcf_conversion_sbc" in active_rules or "penalize_earnings_quality_strong" in active_rules
    ):
        n_penalties = sum(r in active_rules for r in ("penalize_fcf_conversion_sbc", "penalize_earnings_quality_strong"))
        earnings_quality_score = max(0.0, earnings_quality_score - cn.EARNINGS_QUALITY_PENALTY_POINTS * n_penalties)

    # Cassa netta (NC-11): punteggio massimo indipendentemente
    # dall'EBITDA, anche se Net Debt/EBITDA non è calcolabile.
    net_debt = metrics.get("net_debt")
    nd_ebitda_raw = metrics.get("net_debt_to_ebitda")
    if nd_ebitda_raw is None and net_debt is not None and net_debt < 0:
        nd_ebitda_s = 100.0
    else:
        nd_ebitda_s = sth.net_debt_ebitda_score(nd_ebitda_raw)
    coverage_s = sth.interest_coverage_score(metrics.get("interest_coverage"))
    financial_strength_score, n_financial_strength = _weighted_mean([
        (nd_ebitda_s, "net_debt_to_ebitda"), (coverage_s, "interest_coverage"),
    ])

    rev_cagr_s = _global_anchor(metrics.get("revenue_cagr"), _REVENUE_CAGR_ANCHORS)
    eps_cagr_s = _global_anchor(metrics.get("eps_cagr"), _EPS_CAGR_ANCHORS)
    growth_vol_s = _global_anchor(metrics.get("growth_volatility"), _GROWTH_VOLATILITY_ANCHORS)
    growth_score, n_growth = _weighted_mean([
        (rev_cagr_s, "revenue_cagr"), (eps_cagr_s, "eps_cagr"), (growth_vol_s, "growth_volatility"),
    ])

    subscores = {
        "profitability": profitability_score,
        "earnings_quality": earnings_quality_score,
        "financial_strength": financial_strength_score,
        "growth_quality": growth_score,
    }
    coverage = {
        "profitability": n_profitability / 4,
        "earnings_quality": n_earnings_quality / 2,
        "financial_strength": n_financial_strength / 2,
        "growth_quality": n_growth / 3,
    }
    return subscores, coverage


def compute_quality_composite(subscores: dict, archetype_weights: dict, cap_bucket: str,
                               piotroski: dict, altman: dict, active_rules: set[str]) -> dict:
    piotroski_weight = PIOTROSKI_WEIGHT_BY_CAP.get(cap_bucket, 8.0)
    scale = (100 - piotroski_weight) / 100
    category_weights = {cat: archetype_weights.get(cat, 0) * scale for cat in CATEGORIES}

    available_cats = [c for c in CATEGORIES if subscores.get(c) is not None]
    total_available_weight = sum(category_weights[c] for c in available_cats)
    missing_weight = sum(category_weights[c] for c in CATEGORIES if c not in available_cats)

    final_weights = {}
    if total_available_weight > 0:
        for c in available_cats:
            final_weights[c] = category_weights[c] + missing_weight * (category_weights[c] / total_available_weight)

    weighted_sum = sum(subscores[c] * final_weights.get(c, 0) for c in available_cats)
    category_component = weighted_sum / 100

    piotroski_component = None
    if piotroski.get("score") is not None:
        piotroski_component = (piotroski["score"] / 9 * 100) * piotroski_weight / 100

    covered_weight = total_available_weight + (piotroski_weight if piotroski_component is not None else 0.0)
    completeness = covered_weight / 100.0

    if completeness < DATA_COMPLETENESS_THRESHOLD:
        return {
            "score": None, "insufficient_data": True, "completeness": completeness,
            "reason": f"copertura dati {completeness*100:.0f}%, sotto la soglia minima del {DATA_COMPLETENESS_THRESHOLD*100:.0f}%",
            "category_weights_used": final_weights, "piotroski_weight_used": piotroski_weight if piotroski_component is not None else None,
        }

    composite = max(0.0, min(100.0, category_component + (piotroski_component or 0.0)))

    capped = False
    if altman.get("zone") == "distress" and composite > 40 and "suppress_distress_penalty" not in active_rules:
        composite = 40.0
        capped = True

    return {
        "score": composite, "band": score_band_label(composite),
        "insufficient_data": False, "completeness": completeness,
        "altman_capped": capped, "category_weights_used": final_weights,
        "piotroski_weight_used": piotroski_weight if piotroski_component is not None else None,
    }


# ---------------------------------------------------------------------------
# §4 — Asse VALUATION: 4 componenti, senza percentili peer
# ---------------------------------------------------------------------------

def compute_valuation_axis(info: dict, hist: dict, metrics: dict, bucket: str | None,
                            wacc: float | None, risk_free_pct: float | None,
                            pe_band: dict | None, archetype: str | None) -> dict:
    components = {}

    net_income = metrics.get("net_income")
    ebitda = finmod._last(hist.get("ebitda"))
    fcf = finmod._last(hist.get("free_cash_flow"))
    market_cap = info.get("market_cap")
    ev = info.get("enterprise_value")
    pe = info.get("pe_ratio") if net_income is not None and net_income > 0 else None

    # --- 1. Multipli assoluti calibrati per settore (§4.1.1) ---
    ev_ebitda_mult = _safe_div(ev, ebitda) if ebitda and ebitda > 0 else None
    ev_sales_mult = _safe_div(ev, finmod._last(hist.get("revenue")))
    multiple_scores = [
        s for s in (
            sth.ev_ebitda_valuation_score(bucket, ev_ebitda_mult),
            sth.ev_sales_valuation_score(bucket, ev_sales_mult),
            sth.pe_valuation_score(bucket, pe),
        ) if s is not None
    ]
    components["sector_multiples"] = sum(multiple_scores) / len(multiple_scores) if multiple_scores else None

    # --- 2. Storia multi-anno propria (§4.1.2, finestra 8 anni, fallback 5) ---
    components["own_history"] = None
    if pe_band is not None and pe is not None:
        components["own_history"] = 100 - pe_band["percentile"]  # percentile alto = caro -> score basso

    # --- 3. Earnings yield vs risk-free (§4.1.3) ---
    components["earnings_yield_vs_rf"] = None
    ev_ebit_yield = metrics.get("ev_ebit_yield")
    if ev_ebit_yield is not None and risk_free_pct is not None:
        spread = ev_ebit_yield - risk_free_pct
        components["earnings_yield_vs_rf"] = _global_anchor(spread, _EARNINGS_YIELD_SPREAD_ANCHORS)

    # --- 4. Growth-adjusted: PEG dove definito, o Rule of 40 per hyper-growth (§4.1.4, §4.4) ---
    components["growth_adjusted"] = None
    revenue_growth_pct = info.get("revenue_growth")
    if pe is not None and revenue_growth_pct and revenue_growth_pct > 0:
        peg = pe / (revenue_growth_pct * 100)
        components["growth_adjusted"] = _global_anchor(peg, _PEG_ANCHORS)
    elif archetype == "hyper_growth":
        rev_yoy = metrics.get("revenue_yoy_pct")
        margin_for_r40 = None
        if ebitda is not None and finmod._last(hist.get("revenue")):
            margin_for_r40 = ebitda / finmod._last(hist.get("revenue")) * 100
        elif fcf is not None and finmod._last(hist.get("revenue")):
            margin_for_r40 = fcf / finmod._last(hist.get("revenue")) * 100
        if rev_yoy is not None and margin_for_r40 is not None:
            rule_of_40 = rev_yoy + margin_for_r40
            components["growth_adjusted"] = 85.0 if rule_of_40 >= 40 else max(10.0, 85.0 * rule_of_40 / 40)

    available = [v for v in components.values() if v is not None]
    score = sum(available) / len(available) if available else None
    completeness = len(available) / 4

    if completeness < DATA_COMPLETENESS_THRESHOLD:
        return {
            "score": None, "insufficient_data": True, "completeness": completeness,
            "components": components,
            "reason": f"copertura dati {completeness*100:.0f}%, sotto la soglia minima del {DATA_COMPLETENESS_THRESHOLD*100:.0f}%",
        }

    return {
        "score": score, "band": score_band_label(score), "insufficient_data": False,
        "completeness": completeness, "components": components,
    }


def classify_matrix(quality_score: float | None, valuation_score: float | None) -> dict | None:
    if quality_score is None or valuation_score is None:
        return None
    q = "high" if quality_score >= MATRIX_QUALITY_THRESHOLD else "low"
    v = "cheap" if valuation_score >= MATRIX_VALUATION_THRESHOLD else "expensive"
    return dict(MATRIX_QUADRANTS[(q, v)])


# ---------------------------------------------------------------------------
# §7 — Modello di Confidenza/Incertezza
# ---------------------------------------------------------------------------

def compute_confidence(quality: dict, valuation: dict, lifecycle_profile: dict, overall_stale: bool,
                        stale_fields: dict | None = None) -> dict:
    q_completeness = quality.get("completeness") or 0.0
    v_completeness = valuation.get("completeness") or 0.0
    data_completeness = (q_completeness + v_completeness) / 2 * 100

    # FIX4 v2.1 — la componente staleness ora è GRADUATA invece che binaria
    # 20/100: il bilancio intero vecchio (>15 mesi, `overall_stale`) resta
    # la penalità più forte, ma anche un numero crescente di singole
    # metriche stale la riduce proporzionalmente (mai sotto un pavimento
    # di 20). `overall_stale` e `stale_fields` sono condizioni distinte:
    # la prima riguarda l'intero bilancio, la seconda singole metriche.
    stale_fields = stale_fields or {}
    staleness = 100.0
    if overall_stale:
        staleness = 20.0
    elif stale_fields:
        staleness = max(20.0, 100.0 - 15.0 * len(stale_fields))

    dickinson_stable = lifecycle_profile.get("dickinson_stable")
    dickinson_latest = lifecycle_profile.get("dickinson_latest")
    if dickinson_latest is None:
        business_model_fit = 30.0
    elif dickinson_stable:
        business_model_fit = 100.0
    else:
        business_model_fit = 50.0

    reasons_text = " ".join(lifecycle_profile.get("archetype_reasons", []))
    archetype_clarity = 50.0 if "default" in reasons_text else 90.0

    weighted = (
        data_completeness * 0.40 + staleness * 0.25
        + business_model_fit * 0.20 + archetype_clarity * 0.15
    )
    level = "Alta" if weighted >= 75 else ("Media" if weighted >= 50 else "Bassa")

    explanation = []
    if data_completeness < 70:
        explanation.append(f"copertura dati parziale ({data_completeness:.0f}%)")
    if overall_stale:
        explanation.append("bilancio più vecchio di 15 mesi")
    elif stale_fields:
        explanation.append(f"{len(stale_fields)} metrica/e derivata/e da un esercizio più vecchio delle altre della stessa categoria")
    if business_model_fit < 100:
        explanation.append("segnale di ciclo di vita (Dickinson) instabile o non disponibile sugli anni recenti")
    if archetype_clarity < 90:
        explanation.append("archetipo assegnato per default, non da un trigger specifico")

    # FIX v2.1-2 — vincolo di coerenza: il badge non può dichiararsi "Alta"
    # se è presente almeno un fattore di riduzione elencato subito sotto
    # (altrimenti il livello e la spiegazione si contraddicono a video).
    # Non è un ricalcolo diverso del punteggio: il punteggio numerico
    # resta quello sopra, solo l'ETICHETTA testuale viene declassata.
    downgraded_for_consistency = False
    if explanation and level == "Alta":
        level = "Media"
        downgraded_for_consistency = True

    return {
        "score": weighted, "level": level,
        "downgraded_for_consistency": downgraded_for_consistency,
        "components": {
            "data_completeness": data_completeness, "data_staleness": staleness,
            "business_model_fit": business_model_fit, "archetype_clarity": archetype_clarity,
        },
        "explanation": explanation,
    }


# ---------------------------------------------------------------------------
# Testo di sintesi
# ---------------------------------------------------------------------------

def build_thesis_text(result: dict) -> str:
    quality, valuation, matrix = result["quality"], result["valuation"], result.get("matrix")
    q_score, v_score = quality.get("score"), valuation.get("score")
    parts = []
    if q_score is not None:
        parts.append(f"Quality {score_band_label(q_score)} ({q_score:.0f}/100)")
    else:
        parts.append("Quality non mostrato (dati insufficienti)")
    if v_score is not None:
        parts.append(f"Valuation {score_band_label(v_score)} ({v_score:.0f}/100)")
    else:
        parts.append("Valuation non mostrato (dati insufficienti)")
    parts.append(f"archetipo {lc.ARCHETYPE_LABELS_IT[result['archetype']]}")
    if matrix:
        parts.append(f"— {matrix['label']}")
    if quality.get("altman_capped"):
        parts.append("(punteggio Quality limitato a 40 per zona di distress Altman)")
    return " ".join(parts) + "."


def build_bull_bear(result: dict) -> tuple[list[str], list[str]]:
    """Punti di forza / Punti di attenzione (v2.1, FIX5+FIX6).

    FIX6 — due fonti, non più solo le Note Critiche: (a) Note Critiche
    ATTIVE di tipo "penalty" (cn.NC_META: le uniche che riducono davvero un
    punteggio); (b) categorie Quality, asse Quality e asse Valuation in
    banda Debole/Scarso (<40) — prima un asse debole senza un trigger
    diagnostico specifico non compariva mai, anche se era il fattore più
    rilevante per la decisione. I Punti di forza sono simmetrici (>=70).

    FIX5 — vincolo di esclusione reciproca: una categoria colpita da una
    nota critica ATTIVA di tipo "penalty" non può comparire fra i Punti di
    forza anche se il suo punteggio resta alto. Le note di tipo diverso da
    "penalty" (suppression/reclass/note_only) non vengono duplicate qui:
    restano visibili solo nella sezione dedicata Note Critiche, per non
    mostrarle con un segno "negativo" che non hanno davvero (es. NC-04/
    NC-05 segnalano una possibile SOTTOstima, non un difetto).

    Entrambi gli elenchi sono ordinati per rilevanza decrescente (peso
    della categoria nel composito Quality x distanza dalla soglia; gli
    elementi senza un "peso" esplicito — Piotroski/Altman/Beneish/note —
    usano una rilevanza di default fissa, documentata inline)."""
    active_rules = result.get("active_rules", set())
    critical_notes = result.get("critical_notes", [])
    penalized_categories = set(cn.penalty_notes_by_category(critical_notes).keys())

    bull_items: list[tuple[float, str]] = []
    bear_items: list[tuple[float, str]] = []

    quality = result["quality"]
    subs = quality.get("subscores", {})
    weights_used = quality.get("category_weights_used", {})
    for cat, sub in subs.items():
        if sub is None:
            continue
        label = CATEGORY_LABELS_IT[cat]
        weight = weights_used.get(cat) or 10.0
        if sub >= 70 and cat not in penalized_categories:
            bull_items.append((weight * (sub - 70), f"{label}: {score_band_label(sub)} in assoluto (punteggio {sub:.0f})"))
        elif sub < 40:
            bear_items.append((weight * (40 - sub), f"{label}: {score_band_label(sub)} in assoluto (punteggio {sub:.0f})"))

    # FIX6 — assi complessivi Quality/Valuation, non solo le singole categorie
    q_score = quality.get("score")
    if q_score is not None:
        if q_score >= 70:
            bull_items.append((100 * (q_score - 70), f"Quality complessivo: {score_band_label(q_score)} in assoluto (punteggio {q_score:.0f})"))
        elif q_score < 40:
            bear_items.append((100 * (40 - q_score), f"Quality complessivo: {score_band_label(q_score)} in assoluto (punteggio {q_score:.0f}) — asse rilevante per la decisione"))

    v_score = result["valuation"].get("score")
    if v_score is not None:
        if v_score >= 70:
            bull_items.append((100 * (v_score - 70), f"Valuation complessiva: {score_band_label(v_score)}, economica in assoluto (punteggio {v_score:.0f})"))
        elif v_score < 40:
            bear_items.append((100 * (40 - v_score), f"Valuation complessiva: {score_band_label(v_score)}, cara in assoluto (punteggio {v_score:.0f}) — asse rilevante per la decisione"))

    piotroski = result["piotroski"]
    if piotroski.get("score") is not None:
        if piotroski["score"] >= 7:
            bull_items.append((50.0, f"Piotroski F-Score {piotroski['score']}/9: solido su profittabilità, leva ed efficienza operativa"))
        elif piotroski["score"] <= 3:
            bear_items.append((50.0, f"Piotroski F-Score {piotroski['score']}/9: segnali deboli su più fronti contabili"))

    altman = result["altman"]
    if altman.get("zone") == "safe":
        bull_items.append((40.0, f"Altman {altman['variant']}: zona sicura ({altman['z']:.2f})"))
    elif altman.get("zone") == "distress" and "suppress_distress_penalty" not in active_rules:
        bear_items.append((60.0, f"Altman {altman['variant']}: zona di distress ({altman['z']:.2f})"))

    beneish = result.get("beneish", {})
    if beneish.get("zone") == "possibile_manipolatore":
        bear_items.append((60.0, f"Beneish M-Score ({beneish['version']}) in zona di possibile manipolazione contabile: {beneish['m_score']:.2f}"))

    for note in critical_notes:
        if cn.NC_META.get(note["code"], {}).get("type") == "penalty":
            bear_items.append((45.0, f"[{note['code']}] {note['text']}"))

    bull_items.sort(key=lambda x: x[0], reverse=True)
    bear_items.sort(key=lambda x: x[0], reverse=True)
    return [text for _, text in bull_items], [text for _, text in bear_items]


# ---------------------------------------------------------------------------
# Orchestrazione end-to-end
# ---------------------------------------------------------------------------

def build_fundamental_score(symbol: str, wacc: float | None = None, risk_free_pct: float | None = None) -> dict:
    """Punto di ingresso principale v2.0: nessun peer group a runtime —
    tutte le soglie sono lookup statiche per settore/archetipo."""
    info = dp.get_info(symbol)
    hist = finmod.get_financial_history(symbol, freq="annual")
    sector = info.get("sector")

    if su.is_excluded_sector(sector):
        return {
            "symbol": symbol, "excluded": True, "sector": sector,
            "reason": "Settore finanziario (banche/assicurazioni): EBITDA, ROIC, EV e Piotroski/Altman non sono metriche significative per questo modello di business.",
        }

    bucket = sth.bucket_for_sector(sector)
    cap_bucket = su.market_cap_bucket(info.get("market_cap"))
    metrics = compute_core_metrics(symbol, info=info, hist=hist)

    lifecycle_profile = lc.build_lifecycle_profile(hist, metrics.get("roic"), wacc)
    archetype = lifecycle_profile["archetype"]

    # --- Contesto per le Note Critiche (§5) ---
    ctx = {
        "sector": sector, "archetype": archetype,
        "roic": metrics.get("roic"), "roa": metrics.get("roa"), "roe": metrics.get("roe"),
        "leverage_ta_equity": metrics.get("leverage_ta_equity"),
        "net_debt": metrics.get("net_debt"), "interest_coverage": metrics.get("interest_coverage"),
        "total_equity": metrics.get("total_equity"), "total_assets": metrics.get("total_assets"),
        "goodwill": metrics.get("goodwill"), "rd_to_revenue": metrics.get("rd_to_revenue"),
        "lease_liabilities": metrics.get("lease_liabilities"), "sbc_to_revenue": metrics.get("sbc_to_revenue"),
        "diluted_shares_growing": metrics.get("diluted_shares_growing"), "buyback_active": metrics.get("buyback_active"),
        "margin_current": metrics.get("operating_margin_current"), "margin_median_8y": metrics.get("operating_margin_median_8y"),
        "ni_yoy_pct": metrics.get("ni_yoy_pct"), "revenue_yoy_pct": metrics.get("revenue_yoy_pct"),
        "current_ratio": metrics.get("current_ratio"), "deferred_revenue": metrics.get("deferred_revenue"),
        "total_assets_yoy_pct": metrics.get("total_assets_yoy_pct"),
        "net_income": metrics.get("net_income"), "ebit": metrics.get("ebit"),
        "currency": info.get("currency"), "last_statement_date": metrics.get("last_statement_date"),
        "today": dt.date.today(),
        "operating_income_trend_slope": metrics.get("operating_income_trend_slope"),
        "fcf_trend_slope": metrics.get("fcf_trend_slope"), "n_years_trend": metrics.get("n_years_trend"),
        "ppe_net": metrics.get("ppe_net"), "ppe_gross": metrics.get("ppe_gross"),
        "retained_earnings_to_ta": metrics.get("retained_earnings_to_ta"),
        "stale_fields": metrics.get("stale_fields") or {},
        "dickinson_overridden_by_securities": lifecycle_profile.get("dickinson_overridden_by_securities"),
        "altman": None,  # popolato sotto (serve prima calcolare Altman)
    }

    altman = compute_altman(info, hist, sector)
    ctx["altman"] = altman
    critical_notes = cn.detect_critical_notes(ctx)
    active_rules = cn.rules_active(critical_notes)

    piotroski = compute_piotroski(hist, active_rules)
    beneish = ben.compute_m_score(hist)

    subscores, coverage = compute_quality_subscores(metrics, bucket, active_rules, metrics.get("stale_fields"))
    quality_composite = compute_quality_composite(
        subscores, lifecycle_profile["quality_weights"], cap_bucket, piotroski, altman, active_rules,
    )
    quality = dict(quality_composite)
    quality["subscores"] = subscores
    quality["coverage"] = coverage

    pe_band = finmod.historical_multiple_band(symbol)
    valuation = compute_valuation_axis(info, hist, metrics, bucket, wacc, risk_free_pct, pe_band, archetype)

    matrix = classify_matrix(quality.get("score"), valuation.get("score"))
    blended = None
    if quality.get("score") is not None and valuation.get("score") is not None:
        blended = (quality["score"] + valuation["score"]) / 2

    stale_note = next((n for n in critical_notes if n["code"] == "NC-15"), None)
    overall_stale = False
    last_stmt = metrics.get("last_statement_date")
    if last_stmt is not None:
        d = last_stmt.date() if hasattr(last_stmt, "date") else last_stmt
        months = (dt.date.today().year - d.year) * 12 + (dt.date.today().month - d.month)
        overall_stale = months > cn.NC15_STALE_MONTHS
    confidence = compute_confidence(quality, valuation, lifecycle_profile, overall_stale, metrics.get("stale_fields"))

    result = {
        "symbol": symbol, "excluded": False, "sector": sector, "bucket": bucket,
        "bucket_label": sth.BUCKET_LABELS_IT.get(bucket, "n/d"),
        "cap_bucket": cap_bucket,
        "archetype": archetype, "archetype_label": lifecycle_profile["archetype_label"],
        "archetype_reasons": lifecycle_profile["archetype_reasons"],
        "dickinson_latest": lifecycle_profile["dickinson_latest"],
        "dickinson_latest_label": lc.DICKINSON_STAGE_LABELS_IT.get(lifecycle_profile["dickinson_latest"], "n/d"),
        "dickinson_stable": lifecycle_profile["dickinson_stable"],
        "metrics": metrics,
        "quality": quality, "valuation": valuation, "matrix": matrix, "blended": blended,
        "confidence": confidence,
        "piotroski": piotroski, "altman": altman, "beneish": beneish,
        "critical_notes": critical_notes, "active_rules": active_rules,
        "pe_band": pe_band,
        "needs_reit_override": su.needs_unimplemented_override(sector),
    }
    return result
