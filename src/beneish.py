"""
Beneish M-Score (Beneish 1999, "The Detection of Earnings Manipulation",
Financial Analysts Journal) — Analisi Fondamentale v2.0 §3.4. Un
indicatore forensic "early warning statistico", non una prova di frode:
confronta l'ultimo periodo annuale disponibile (t) col precedente (t-1)
su 8 variabili contabili collegate a pratiche di manipolazione degli
utili documentate in letteratura (crescita anomala dei crediti,
deterioramento del margine lordo, qualità degli asset, crescita ricavi,
tasso di ammortamento, spese SG&A, accruals, leva).

Limite yfinance dichiarato dalla specifica: DEPI e AQI richiedono
dettagli di bilancio (aliquota di ammortamento, titoli/investimenti) non
sempre presenti — se 2 o più delle 8 variabili non sono calcolabili si
passa alla versione a 5 variabili (Beneish 1999, versione ridotta); se
anche questa non è calcolabile, l'M-Score va soppresso con nota di dati
insufficienti, mai stimato a metà.
"""
from __future__ import annotations

from src import financials as finmod

M_SCORE_MANIPULATOR_THRESHOLD = -1.78  # M > questo valore: possibile manipolatore (modello 1999)
M_SCORE_CLEAN_THRESHOLD = -2.22  # M < questo valore: pulito (soglia conservativa 1997)


def _two_periods(series):
    """Ultimi due valori (t-1, t) di una serie storica, o (None, None)
    se non ci sono almeno due periodi validi."""
    if series is None or len(series) < 2:
        return None, None
    return float(series.iloc[-2]), float(series.iloc[-1])


def _safe_ratio(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def _compute_variables(hist: dict) -> dict:
    """Le 8 variabili grezze di Beneish (1999), quando calcolabili dai
    dati disponibili. None dove i dati sottostanti mancano."""
    out = {"DSRI": None, "GMI": None, "AQI": None, "SGI": None,
           "DEPI": None, "SGAI": None, "TATA": None, "LVGI": None}

    rev_prev, rev_t = _two_periods(hist.get("revenue"))
    rec_prev, rec_t = _two_periods(hist.get("receivables"))
    if None not in (rev_prev, rev_t, rec_prev, rec_t) and rev_prev and rev_t:
        dsri_t = _safe_ratio(rec_t, rev_t)
        dsri_prev = _safe_ratio(rec_prev, rev_prev)
        out["DSRI"] = _safe_ratio(dsri_t, dsri_prev)

    gp_prev, gp_t = _two_periods(hist.get("gross_profit"))
    if None not in (gp_prev, gp_t, rev_prev, rev_t) and rev_prev and rev_t and gp_prev is not None:
        gm_t = _safe_ratio(gp_t, rev_t)
        gm_prev = _safe_ratio(gp_prev, rev_prev)
        out["GMI"] = _safe_ratio(gm_prev, gm_t)  # invertito: margine in calo -> GMI > 1 (segnale di rischio)

    ca_prev, ca_t = _two_periods(hist.get("current_assets"))
    ppe_prev, ppe_t = _two_periods(hist.get("ppe_net"))
    sec_prev, sec_t = _two_periods(hist.get("securities"))
    ta_prev, ta_t = _two_periods(hist.get("total_assets"))
    if None not in (ca_t, ppe_t, ta_t) and ta_t:
        sec_t_val = sec_t or 0.0
        aqi_t = 1 - (ca_t + ppe_t + sec_t_val) / ta_t
        if None not in (ca_prev, ppe_prev, ta_prev) and ta_prev:
            sec_prev_val = sec_prev or 0.0
            aqi_prev = 1 - (ca_prev + ppe_prev + sec_prev_val) / ta_prev
            out["AQI"] = _safe_ratio(aqi_t, aqi_prev)

    if rev_prev and rev_t is not None:
        out["SGI"] = _safe_ratio(rev_t, rev_prev)

    da_prev, da_t = _two_periods(hist.get("depreciation_amortization"))
    if None not in (da_prev, da_t, ppe_prev, ppe_t):
        da_prev_abs, da_t_abs = abs(da_prev), abs(da_t)
        rate_t = _safe_ratio(da_t_abs, da_t_abs + ppe_t) if (da_t_abs + ppe_t) else None
        rate_prev = _safe_ratio(da_prev_abs, da_prev_abs + ppe_prev) if (da_prev_abs + ppe_prev) else None
        out["DEPI"] = _safe_ratio(rate_prev, rate_t)

    sga_prev, sga_t = _two_periods(hist.get("sga"))
    if None not in (sga_prev, sga_t, rev_prev, rev_t) and rev_prev and rev_t:
        sgai_t = _safe_ratio(sga_t, rev_t)
        sgai_prev = _safe_ratio(sga_prev, rev_prev)
        out["SGAI"] = _safe_ratio(sgai_t, sgai_prev)

    ni_t = finmod._last(hist.get("net_income"))
    cfo_t = finmod._last(hist.get("operating_cash_flow"))
    if None not in (ni_t, cfo_t, ta_t) and ta_t:
        out["TATA"] = (ni_t - cfo_t) / ta_t

    cl_prev, cl_t = _two_periods(hist.get("current_liabilities"))
    ltd_prev, ltd_t = _two_periods(hist.get("long_term_debt"))
    if None not in (cl_t, ltd_t, ta_t) and ta_t:
        lev_t = (cl_t + ltd_t) / ta_t
        if None not in (cl_prev, ltd_prev, ta_prev) and ta_prev:
            lev_prev = (cl_prev + ltd_prev) / ta_prev
            out["LVGI"] = _safe_ratio(lev_t, lev_prev)

    return out


def _zone(m: float | None) -> str | None:
    if m is None:
        return None
    if m > M_SCORE_MANIPULATOR_THRESHOLD:
        return "possibile_manipolatore"
    if m < M_SCORE_CLEAN_THRESHOLD:
        return "pulito"
    return "gray_zone"


def compute_m_score(hist: dict) -> dict:
    """Orchestrazione: prova la formula a 8 variabili; se 2 o più
    variabili mancano, tenta la versione a 5 (che richiede comunque
    DSRI/GMI/AQI/SGI/DEPI); se anche questa non è calcolabile,
    sopprime l'M-Score con nota di dati insufficienti (mai un valore
    a metà)."""
    variables = _compute_variables(hist)
    n_missing = sum(1 for v in variables.values() if v is None)

    result = {
        "variables": variables, "n_missing": n_missing, "version": None,
        "m_score": None, "zone": None, "insufficient_data": True,
    }

    if n_missing < 2:
        v = variables
        m = (-4.84 + 0.92 * v["DSRI"] + 0.528 * v["GMI"] + 0.404 * v["AQI"]
             + 0.892 * v["SGI"] + 0.115 * v["DEPI"] - 0.172 * v["SGAI"]
             + 4.679 * v["TATA"] - 0.327 * v["LVGI"])
        result.update({"version": "8-variabili", "m_score": float(m), "zone": _zone(m), "insufficient_data": False})
        return result

    five_var_keys = ("DSRI", "GMI", "AQI", "SGI", "DEPI")
    if all(variables[k] is not None for k in five_var_keys):
        v = variables
        m = (-6.065 + 0.823 * v["DSRI"] + 0.906 * v["GMI"] + 0.593 * v["AQI"]
             + 0.717 * v["SGI"] + 0.107 * v["DEPI"])
        result.update({"version": "5-variabili", "m_score": float(m), "zone": _zone(m), "insufficient_data": False})
        return result

    return result
