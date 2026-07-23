"""
Archetipo / lifecycle operativo (Analisi Fondamentale v2.0, §2). Deriva
il profilo di un'azienda dai segni dei tre flussi di cassa (Dickinson,
2011, "Cash Flow Patterns as a Proxy for Firm Life Cycle", The Accounting
Review 86(6):1969-1994) combinati con caratteristiche operative osservabili
(crescita ricavi, margini, capex/ricavi, R&D/ricavi, payout, ROIC) — MAI
dal solo settore GICS/Yahoo, per correggere il bug per cui un'azienda
matura in un settore "Tech" verrebbe penalizzata sul peso crescita solo
per l'etichetta di settore (§2.2, "Bug-fix chiave").

I pesi Quality per archetipo (Profitability/Earnings Quality/Financial
Strength/Growth) sono presi letteralmente dalla tabella §2.2 della
specifica fornita dall'utente.
"""
from __future__ import annotations

from src import financials as finmod

DICKINSON_STAGES = {
    ("-", "-", "+"): "Introduction",
    ("+", "-", "+"): "Growth",
    ("+", "-", "-"): "Mature",
    ("-", "+", "+"): "Decline",
    ("-", "+", "-"): "Decline",
    ("+", "+", "+"): "Shake-out",
    ("+", "+", "-"): "Shake-out",
    ("-", "-", "-"): "Shake-out",
}

DICKINSON_STAGE_LABELS_IT = {
    "Introduction": "Introduzione", "Growth": "Crescita", "Mature": "Maturità",
    "Decline": "Declino", "Shake-out": "Shake-out",
}

ARCHETYPES = [
    "hyper_growth", "growth", "mature_compounder", "mature_cash_cow",
    "cyclical", "turnaround", "capital_intensive",
]

ARCHETYPE_LABELS_IT = {
    "hyper_growth": "Hyper-growth",
    "growth": "Growth",
    "mature_compounder": "Mature compounder",
    "mature_cash_cow": "Mature cash cow",
    "cyclical": "Cyclical",
    "turnaround": "Turnaround",
    "capital_intensive": "Capital-intensive / utility-like",
}

# Pesi Quality (Profitability / Earnings Quality / Financial Strength /
# Growth Quality), su 100 — Capital Allocation è ripartita fra
# Profitability e Financial Strength (§3.1), Relative Valuation esce
# dall'asse Quality (va nell'asse Valuation, §3.1).
ARCHETYPE_QUALITY_WEIGHTS = {
    "hyper_growth":       {"profitability": 25, "earnings_quality": 25, "financial_strength": 20, "growth_quality": 30},
    "growth":             {"profitability": 30, "earnings_quality": 25, "financial_strength": 20, "growth_quality": 25},
    "mature_compounder":  {"profitability": 35, "earnings_quality": 30, "financial_strength": 20, "growth_quality": 15},
    "mature_cash_cow":    {"profitability": 35, "earnings_quality": 30, "financial_strength": 25, "growth_quality": 10},
    "cyclical":           {"profitability": 30, "earnings_quality": 30, "financial_strength": 25, "growth_quality": 15},
    "turnaround":         {"profitability": 25, "earnings_quality": 35, "financial_strength": 30, "growth_quality": 10},
    "capital_intensive":  {"profitability": 25, "earnings_quality": 25, "financial_strength": 35, "growth_quality": 15},
}

DEFAULT_ARCHETYPE = "mature_compounder"


def _sign(x: float | None) -> str | None:
    if x is None:
        return None
    return "+" if x >= 0 else "-"


def dickinson_stage(ocf: float | None, cfi: float | None, cff: float | None) -> str | None:
    """Stadio Dickinson per un singolo periodo, dai segni di OCF/CFI/CFF."""
    key = (_sign(ocf), _sign(cfi), _sign(cff))
    if None in key:
        return None
    return DICKINSON_STAGES.get(key)


def dickinson_history(hist: dict, n_periods: int = 5) -> list[str | None]:
    """Stadio Dickinson per ciascuno degli ultimi `n_periods` anni
    disponibili (§2.1: "calcolare Dickinson su TTM e sugli ultimi 3-5
    anni: se il segnale oscilla, ridurre la confidenza"). yfinance offre
    tipicamente ~4 anni di bilanci gratuiti, quindi in pratica questo è
    spesso un best-effort su meno periodi degli idealmente richiesti."""
    ocf, cfi, cff = hist.get("operating_cash_flow"), hist.get("cfi"), hist.get("cff")
    if ocf is None:
        return []
    stages = []
    n = len(ocf)
    for i in range(max(0, n - n_periods), n):
        try:
            o = float(ocf.iloc[i])
        except Exception:
            continue
        c_i = None
        c_f = None
        if cfi is not None and ocf.index[i] in cfi.index:
            c_i = float(cfi.loc[ocf.index[i]])
        if cff is not None and ocf.index[i] in cff.index:
            c_f = float(cff.loc[ocf.index[i]])
        stages.append(dickinson_stage(o, c_i, c_f))
    return stages


def dickinson_stability(stages: list[str | None]) -> tuple[str | None, bool]:
    """Stadio prevalente (l'ultimo disponibile, coerentemente con "TTM")
    e se il segnale è stabile (nessuna oscillazione tra stadi diversi
    negli anni disponibili) — usato dal modello di confidenza (§7)."""
    valid = [s for s in stages if s is not None]
    if not valid:
        return None, False
    latest = valid[-1]
    stable = len(set(valid)) == 1
    return latest, stable


# ---------------------------------------------------------------------------
# Osservabili operative (§2.2) usate per assegnare l'archetipo
# ---------------------------------------------------------------------------

def compute_observables(hist: dict) -> dict:
    """Le caratteristiche operative osservabili richieste da §2.2:
    crescita ricavi, livello/stabilità margini, capex/ricavi, R&D/ricavi,
    payout/buyback, livello/trend ROIC (via ROIC "puntuale" più recente,
    non una vera serie storica di ROIC — costruirla richiederebbe NOPAT e
    capitale investito per ogni periodo, non solo l'ultimo; qui si usa il
    margine operativo come proxy di stabilità della redditività, più
    diretto da una serie storica reale)."""
    rev = hist.get("revenue")
    margins = finmod.compute_margins(hist)
    op_margin = margins.get("operating_margin")

    revenue_cagr = finmod.growth_rate(rev)
    revenue_latest_yoy = finmod.latest_and_yoy(rev).get("yoy_pct")

    margin_level = finmod._last(op_margin)
    margin_trend = finmod.margin_trend(op_margin)
    margin_volatility = None
    if op_margin is not None and len(op_margin) >= 3:
        margin_volatility = float(op_margin.std())

    revenue_volatility = None
    if rev is not None and len(rev) >= 3:
        yoy = rev.pct_change().dropna() * 100
        if len(yoy) >= 2:
            revenue_volatility = float(yoy.std())

    capex, revenue = hist.get("capex"), rev
    capex_to_revenue = None
    if capex is not None and revenue is not None:
        c, r = capex.align(revenue, join="inner")
        if not c.empty and (r != 0).any():
            capex_to_revenue = float((c.abs() / r).mean() * 100)

    rd, revenue2 = hist.get("research_development"), rev
    rd_to_revenue = None
    if rd is not None and revenue2 is not None:
        rr, rv = rd.align(revenue2, join="inner")
        if not rr.empty and rv.iloc[-1]:
            rd_to_revenue = float(rr.iloc[-1] / rv.iloc[-1] * 100)

    div = finmod._last(hist.get("dividends_paid"))
    buyback = finmod._last(hist.get("buyback"))
    ni = finmod._last(hist.get("net_income"))
    payout_ratio = None
    has_payout = False
    total_return_to_shareholders = abs(div or 0) + abs(buyback or 0)
    if total_return_to_shareholders > 0:
        has_payout = True
        if ni and ni > 0:
            payout_ratio = total_return_to_shareholders / ni * 100

    return {
        "revenue_cagr": revenue_cagr,
        "revenue_latest_yoy": revenue_latest_yoy,
        "margin_level": margin_level,
        "margin_trend": margin_trend,
        "margin_volatility": margin_volatility,
        "revenue_volatility": revenue_volatility,
        "capex_to_revenue": capex_to_revenue,
        "rd_to_revenue": rd_to_revenue,
        "has_payout": has_payout,
        "payout_ratio": payout_ratio,
    }


def assign_archetype(observables: dict, dickinson_latest: str | None, roic: float | None, wacc: float | None) -> dict:
    """Classificatore rule-based (§2.2), applicato in ordine di priorità
    dichiarato (la specifica elenca i trigger per riga ma non un ordine
    esplicito di risoluzione dei conflitti: l'ordine qui sotto è la mia
    scelta esplicita, dal più specifico/diagnostico al più generico,
    con "Mature compounder" come default finale)."""
    growth = observables.get("revenue_cagr")
    if growth is None:
        growth = observables.get("revenue_latest_yoy")
    margin_level = observables.get("margin_level")
    margin_trend = observables.get("margin_trend")
    margin_vol = observables.get("margin_volatility")
    rev_vol = observables.get("revenue_volatility")
    capex_rev = observables.get("capex_to_revenue")
    has_payout = observables.get("has_payout")

    reasons = []

    # 1. Turnaround: Dickinson Decline/Shake-out + margini negativi in recupero
    if dickinson_latest in ("Decline", "Shake-out") and margin_level is not None and margin_level < 0 and margin_trend == "in espansione":
        reasons.append(f"Dickinson {dickinson_latest}, margine operativo negativo ma in miglioramento")
        return {"archetype": "turnaround", "reasons": reasons}

    # 2. Capital-intensive/utility-like: capex/ricavi alto, ROIC basso e stabile
    if capex_rev is not None and capex_rev > 15 and roic is not None and roic < 10:
        reasons.append(f"capex/ricavi {capex_rev:.0f}%, ROIC contenuto ({roic:.1f}%)")
        return {"archetype": "capital_intensive", "reasons": reasons}

    # 3. Hyper-growth: crescita >30%, margini bassi/negativi, Dickinson Intro/Growth
    # (soglia di "margine basso" fissata da me a 12%: la specifica non
    # indica un numero preciso, solo "bassi/negativi"). Controllato PRIMA
    # della ciclicità: una crescita ricavi esplosiva è un segnale più
    # specifico e distintivo di una volatilità di margine, che in
    # un'azienda in rapida scalata è spesso solo l'effetto della leva
    # operativa mentre si avvicina al breakeven, non vera ciclicità.
    if growth is not None and growth > 30 and (margin_level is None or margin_level < 12):
        reasons.append(f"crescita ricavi {growth:.0f}%, margine operativo basso/negativo")
        return {"archetype": "hyper_growth", "reasons": reasons}

    # 4. Cyclical: volatilità margini/ricavi alta
    if (margin_vol is not None and margin_vol > 6) or (rev_vol is not None and rev_vol > 20):
        reasons.append("volatilità di margini e/o ricavi elevata tra i periodi disponibili")
        return {"archetype": "cyclical", "reasons": reasons}

    # 5. Growth: crescita 15-30%, margini in miglioramento
    if growth is not None and 15 <= growth <= 30:
        reasons.append(f"crescita ricavi {growth:.0f}%")
        return {"archetype": "growth", "reasons": reasons}

    # 6. Mature cash cow: crescita <5%, margini alti stabili, alto payout
    if growth is not None and growth < 5 and margin_level is not None and margin_level > 15 and margin_trend == "stabile" and has_payout:
        reasons.append(f"crescita ricavi {growth:.0f}%, margine operativo alto e stabile, payout attivo")
        return {"archetype": "mature_cash_cow", "reasons": reasons}

    # 7. Mature compounder: crescita 5-15%, ROIC>WACC+5pp, buyback/dividendi, Dickinson Mature
    if growth is not None and 5 <= growth <= 15:
        reasons.append(f"crescita ricavi {growth:.0f}% (profilo maturo)")
        return {"archetype": "mature_compounder", "reasons": reasons}
    if roic is not None and wacc is not None and (roic - wacc) > 5 and has_payout:
        reasons.append(f"ROIC supera il WACC di oltre 5pp, payout attivo")
        return {"archetype": "mature_compounder", "reasons": reasons}

    # 8. Default esplicito (§2.2)
    reasons.append("nessun trigger specifico soddisfatto: applicato il default Mature compounder")
    return {"archetype": DEFAULT_ARCHETYPE, "reasons": reasons}


def build_lifecycle_profile(hist: dict, roic: float | None, wacc: float | None) -> dict:
    """Orchestrazione end-to-end: stadio Dickinson (+ stabilità),
    osservabili operative, archetipo assegnato e pesi Quality associati."""
    stages = dickinson_history(hist)
    latest_stage, stable = dickinson_stability(stages)
    observables = compute_observables(hist)
    assignment = assign_archetype(observables, latest_stage, roic, wacc)
    archetype = assignment["archetype"]
    return {
        "dickinson_stages_history": stages,
        "dickinson_latest": latest_stage,
        "dickinson_stable": stable,
        "observables": observables,
        "archetype": archetype,
        "archetype_label": ARCHETYPE_LABELS_IT[archetype],
        "archetype_reasons": assignment["reasons"],
        "quality_weights": ARCHETYPE_QUALITY_WEIGHTS[archetype],
    }
