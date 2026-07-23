"""
Layer "Note Critiche" (Analisi Fondamentale v2.0 §5, corretto in v2.1) —
19 note rule-based e SELETTIVE: ognuna scatta solo se il suo trigger
machine-detectable è soddisfatto sui dati yfinance disponibili, non su
ogni metrica (§1 Key Finding 4: "va reso selettivo"). Ogni nota porta un
codice (NC-01..NC-19), un testo in italiano pronto per la UI, e una
regola di aggiustamento/soppressione applicata da src/fundamental_score.py
prima di finalizzare gli assi Quality/Valuation.

CORREZIONI v2.1 (Prompt_Cowork_Analisi_Fondamentale_v2.1.md):
- FIX3: ogni soglia numerica è ora una costante nominata e commentata (mai
  un numero magico), e ogni check accetta un parametro opzionale `debug`
  (lista) su cui appende un dizionario diagnostico con il valore di ogni
  condizione del trigger e se il trigger è scattato — utile in sviluppo
  per capire perché una nota non si attiva su un titolo, senza introdurre
  eccezioni per ticker specifici (regola generale, mai un caso particolare).
- FIX5: ogni nota dichiara ora esplicitamente, in NC_META, quale categoria
  Quality impatta (o nessuna) e quale TIPO di aggiustamento applica:
  "penalty" (riduce davvero un sub-score), "suppression" (sopprime/ignora
  una metrica o un criterio, es. Piotroski/Altman), "reclass"
  (riclassifica, es. NC-19 sul lifecycle) o "note_only" (informativa, non
  altera alcun punteggio). Solo le note di tipo "penalty" possono impedire
  a una categoria di comparire fra i Punti di forza in
  src/fundamental_score.py (vincolo di esclusione reciproca).
- FIX8: aggiunta NC-19 (Dickinson distorto da portafoglio marketable
  securities) — la logica di rilevamento vive in src/lifecycle.py (deve
  intervenire PRIMA della classificazione archetipo), qui la nota si
  limita a leggere il flag già calcolato e a renderlo visibile a testo.

Ogni funzione `_nc_xx(ctx, debug=None)` riceve lo stesso dizionario di
contesto `ctx` (costruito da src/fundamental_score.py) e ritorna `None` se
il trigger non scatta, altrimenti un dict {"code", "text", "rule"}. Chiavi
attese in `ctx` (tutte opzionali, assenti = trigger non valutabile -> nessuna
nota, mai una nota su dati mancanti travestita da falso positivo):
    sector, archetype, altman (dict z/zone/variant), roic, roa, roe,
    leverage_ta_equity, net_debt, interest_coverage, total_equity,
    total_assets, goodwill, rd_to_revenue, lease_liabilities,
    sbc_to_revenue, diluted_shares_growing, buyback_active,
    margin_current, margin_median_8y, ni_yoy_pct, revenue_yoy_pct,
    current_ratio, deferred_revenue, total_assets_yoy_pct,
    net_income, ebit, currency, last_statement_date, today,
    operating_income_trend_slope, fcf_trend_slope, n_years_trend,
    ppe_net, ppe_gross, retained_earnings_to_ta,
    stale_fields (dict metrica -> mesi di ritardo, FIX4 v2.1),
    dickinson_overridden_by_securities (bool, FIX8 v2.1/NC-19).
"""
from __future__ import annotations

import datetime as dt

_HIGH_INFLATION_CURRENCIES = {
    "ARS", "TRY", "EGP", "NGN", "VES", "ZWL", "LBP", "SDG", "IRR",
}

# ---------------------------------------------------------------------------
# FIX3 v2.1 — soglie nominate (mai più numeri magici sparsi nei check):
# ogni costante è una regola generale, non tarata su un singolo titolo.
# ---------------------------------------------------------------------------
NC01_INTEREST_COVERAGE_MIN = 8.0
# Allentata da "retained earnings negativi" a "bassi rispetto al totale
# attivo" (v2.1 FIX3): i buyback prolungati erodono i retained earnings
# progressivamente, il segnale di distorsione va colto ben prima che
# diventino negativi.
NC01_RETAINED_EARNINGS_TO_TA_MAX_PCT = 10.0

NC02_EQUITY_TO_TA_MIN_PCT = 0.05

NC03_ROE_MIN_PCT = 20.0
NC03_ROA_MAX_PCT = 6.0
NC03_LEVERAGE_MIN = 3.0

NC04_GOODWILL_TO_TA_MIN = 0.30

NC05_RD_TO_REVENUE_MIN_PCT = 10.0

NC06_LEASE_TO_TA_MIN = 0.05

NC07_SBC_TO_REVENUE_MIN_PCT = 5.0

NC08_CYCLE_DEVIATION_MULT_HIGH = 1.5
NC08_CYCLE_DEVIATION_MULT_LOW = 0.5

NC09_NI_YOY_ABS_MIN_PCT = 50.0
NC09_COHERENCE_MAX_DIFF_PCT = 20.0

NC10_CURRENT_RATIO_MAX = 1.0

NC12_TOTAL_ASSETS_YOY_ABS_MIN_PCT = 40.0
NC12_REVENUE_YOY_ABS_MIN_PCT = 50.0

NC15_STALE_MONTHS = 15

NC16_MIN_YEARS_TREND = 3

NC18_NET_TO_GROSS_PPE_MAX = 0.30

# Entità della penalità reale applicata al sub-score "earnings_quality"
# quando NC-07 o NC-16 sono attive (FIX5 v2.1: "la penalità va effettivamente
# applicata al sub-score della categoria impattata prima del composito").
# Valore scelto da me — non un backtest — documentato qui per trasparenza,
# non nascosto nel codice di fundamental_score.py.
EARNINGS_QUALITY_PENALTY_POINTS = 12.0


def _log(debug, code, fired, **conditions):
    if debug is not None:
        debug.append({"code": code, "fired": fired, "conditions": conditions})


def _nc01_altman_buyback(ctx: dict, debug=None) -> dict | None:
    altman = ctx.get("altman") or {}
    zone = altman.get("zone")
    net_debt = ctx.get("net_debt")
    coverage = ctx.get("interest_coverage")
    ret_to_ta = ctx.get("retained_earnings_to_ta")
    evaluable = zone is not None and net_debt is not None and coverage is not None and ret_to_ta is not None
    fired = False
    if evaluable:
        fired = (
            zone in ("grey", "distress")
            and net_debt < 0
            and coverage > NC01_INTEREST_COVERAGE_MIN
            and ret_to_ta < NC01_RETAINED_EARNINGS_TO_TA_MAX_PCT
        )
    _log(debug, "NC-01", fired, zone=zone, net_debt=net_debt, coverage=coverage, ret_to_ta=ret_to_ta)
    if not fired:
        return None
    return {
        "code": "NC-01",
        "text": (
            "L'Altman Z-Score risulta in zona di allerta ma è distorto dai buyback che hanno "
            "eroso i retained earnings e il book equity. Con cassa netta positiva e interest "
            "coverage elevato, il segnale di distress NON è affidabile."
        ),
        "rule": "suppress_distress_penalty",
    }


def _nc02_negative_book_equity(ctx: dict, debug=None) -> dict | None:
    equity = ctx.get("total_equity")
    ta = ctx.get("total_assets")
    fired = False
    if equity is not None:
        fired = equity <= 0 or (ta and equity / ta < NC02_EQUITY_TO_TA_MIN_PCT)
    _log(debug, "NC-02", fired, equity=equity, ta=ta)
    if not fired:
        return None
    return {
        "code": "NC-02",
        "text": (
            "Il patrimonio netto contabile è negativo o minimo (spesso da buyback o write-off). "
            "P/B, ROE e Debt/Equity sono privi di significato e vanno ignorati."
        ),
        "rule": "suppress_book_equity_metrics",
    }


def _nc03_roe_leverage(ctx: dict, debug=None) -> dict | None:
    roe, roa, leverage = ctx.get("roe"), ctx.get("roa"), ctx.get("leverage_ta_equity")
    fired = roe is not None and roa is not None and leverage is not None and (
        roe > NC03_ROE_MIN_PCT and roa < NC03_ROA_MAX_PCT and leverage > NC03_LEVERAGE_MIN
    )
    _log(debug, "NC-03", fired, roe=roe, roa=roa, leverage=leverage)
    if not fired:
        return None
    return {
        "code": "NC-03",
        "text": (
            "Il ROE elevato deriva dalla leva finanziaria, non dalla performance operativa "
            "(scomposizione DuPont). Valutare ROIC e ROA come indicatori più puliti."
        ),
        "rule": "reduce_roe_weight",
    }


def _nc04_roic_goodwill(ctx: dict, debug=None) -> dict | None:
    goodwill, ta = ctx.get("goodwill"), ctx.get("total_assets")
    fired = goodwill is not None and bool(ta) and (goodwill / ta > NC04_GOODWILL_TO_TA_MIN)
    _log(debug, "NC-04", fired, goodwill=goodwill, ta=ta)
    if not fired:
        return None
    return {
        "code": "NC-04",
        "text": (
            "L'invested capital include goodwill rilevante da acquisizioni; il ROIC può "
            "sottostimare la redditività operativa del business core. Considerare il ROIC su "
            "capitale tangibile."
        ),
        "rule": "show_roic_ex_goodwill",
    }


def _nc05_rd_not_capitalized(ctx: dict, debug=None) -> dict | None:
    sector, archetype, rd = ctx.get("sector"), ctx.get("archetype"), ctx.get("rd_to_revenue")
    is_tech_pharma = sector in ("Technology", "Healthcare") or archetype in ("hyper_growth", "growth")
    fired = rd is not None and is_tech_pharma and rd > NC05_RD_TO_REVENUE_MIN_PCT
    _log(debug, "NC-05", fired, rd=rd, is_tech_pharma=is_tech_pharma)
    if not fired:
        return None
    return {
        "code": "NC-05",
        "text": (
            "L'R&D è spesato invece che capitalizzato (aggiustamento Damodaran): ROIC e margini "
            "operativi sono sottostimati e il capitale investito reale è più alto."
        ),
        "rule": "show_roic_rd_adjusted",
    }


def _nc06_operating_leases(ctx: dict, debug=None) -> dict | None:
    sector = ctx.get("sector")
    lease, ta = ctx.get("lease_liabilities"), ctx.get("total_assets")
    lease_material = lease is not None and bool(ta) and (lease / ta > NC06_LEASE_TO_TA_MIN)
    sector_flagged = sector in ("Consumer Cyclical", "Industrials")
    fired = lease_material or (sector_flagged and lease is not None and lease > 0)
    _log(debug, "NC-06", fired, lease=lease, ta=ta, sector_flagged=sector_flagged)
    if not fired:
        return None
    return {
        "code": "NC-06",
        "text": (
            "I leasing operativi (IFRS 16/ASC 842) influenzano EBITDA, Net Debt/EBITDA e "
            "interest coverage; la comparabilità cross-company è limitata."
        ),
        "rule": "note_only",
    }


def _nc07_sbc(ctx: dict, debug=None) -> dict | None:
    sbc_to_rev = ctx.get("sbc_to_revenue")
    diluted_growing = ctx.get("diluted_shares_growing")
    buyback_active = ctx.get("buyback_active")
    evaluable = sbc_to_rev is not None or diluted_growing is not None
    fired = False
    if evaluable:
        fired = (sbc_to_rev is not None and sbc_to_rev > NC07_SBC_TO_REVENUE_MIN_PCT) or bool(
            diluted_growing and buyback_active
        )
    _log(debug, "NC-07", fired, sbc_to_rev=sbc_to_rev, diluted_growing=diluted_growing, buyback_active=buyback_active)
    if not fired:
        return None
    return {
        "code": "NC-07",
        "text": (
            "La SBC gonfia FCF e FCF conversion (add-back non-cash) e diluisce gli azionisti. "
            "Se il conteggio azioni cresce nonostante i buyback, la diluizione maschera il costo "
            "reale. Penalità applicata al sub-score qualità utili."
        ),
        "rule": "penalize_fcf_conversion_sbc",
    }


def _nc08_cyclicality(ctx: dict, debug=None) -> dict | None:
    archetype = ctx.get("archetype")
    current, median = ctx.get("margin_current"), ctx.get("margin_median_8y")
    fired = (
        archetype == "cyclical" and current is not None and bool(median)
        and (current > NC08_CYCLE_DEVIATION_MULT_HIGH * median or current < NC08_CYCLE_DEVIATION_MULT_LOW * median)
    )
    _log(debug, "NC-08", fired, archetype=archetype, current=current, median=median)
    if not fired:
        return None
    return {
        "code": "NC-08",
        "text": (
            "L'azienda è ciclica e valutata vicino al picco/minimo del ciclo: EV/EBITDA appare "
            "basso al picco (utili gonfiati) e P/E appare assurdo al minimo. Usare utili/EBITDA "
            "mid-cycle normalizzati."
        ),
        "rule": "normalize_mid_cycle",
    }


def _nc09_one_off(ctx: dict, debug=None) -> dict | None:
    ni_yoy, rev_yoy = ctx.get("ni_yoy_pct"), ctx.get("revenue_yoy_pct")
    coherent_with_revenue = rev_yoy is not None and abs(ni_yoy - rev_yoy) < NC09_COHERENCE_MAX_DIFF_PCT if ni_yoy is not None else False
    fired = ni_yoy is not None and abs(ni_yoy) > NC09_NI_YOY_ABS_MIN_PCT and not coherent_with_revenue
    _log(debug, "NC-09", fired, ni_yoy=ni_yoy, rev_yoy=rev_yoy, coherent_with_revenue=coherent_with_revenue)
    if not fired:
        return None
    return {
        "code": "NC-09",
        "text": (
            "L'utile netto è distorto da voci non ricorrenti (cessioni, contenziosi, impairment, "
            "one-timer fiscali). ROA, EPS e i criteri Piotroski basati su variazioni YoY possono "
            "essere fuorvianti."
        ),
        "rule": "suspend_piotroski_yoy_criteria",
    }


def _nc10_negative_working_capital(ctx: dict, debug=None) -> dict | None:
    current_ratio = ctx.get("current_ratio")
    archetype, sector = ctx.get("archetype"), ctx.get("sector")
    deferred_rev = ctx.get("deferred_revenue")
    subscription_like = archetype in ("hyper_growth", "growth") or sector == "Consumer Cyclical"
    fired = (
        current_ratio is not None and deferred_rev is not None
        and current_ratio < NC10_CURRENT_RATIO_MAX and subscription_like and deferred_rev > 0
    )
    _log(debug, "NC-10", fired, current_ratio=current_ratio, subscription_like=subscription_like, deferred_rev=deferred_rev)
    if not fired:
        return None
    return {
        "code": "NC-10",
        "text": (
            "Il current ratio basso/negativo è un PUNTO DI FORZA (working capital negativo, "
            "deferred revenue): i clienti finanziano l'azienda. Il criterio Piotroski sul "
            "current ratio qui è fuorviante."
        ),
        "rule": "neutralize_piotroski_current_ratio",
    }


def _nc11_net_cash(ctx: dict, debug=None) -> dict | None:
    net_debt = ctx.get("net_debt")
    fired = net_debt is not None and net_debt < 0
    _log(debug, "NC-11", fired, net_debt=net_debt)
    if not fired:
        return None
    return {
        "code": "NC-11",
        "text": (
            "L'azienda ha cassa netta: Net Debt/EBITDA è negativo e le metriche di leva sono "
            "non informative. L'interest coverage può essere indefinito o dominato dagli "
            "interessi attivi."
        ),
        "rule": "leverage_score_max",
    }


def _nc12_ma_activity(ctx: dict, debug=None) -> dict | None:
    ta_yoy, rev_yoy = ctx.get("total_assets_yoy_pct"), ctx.get("revenue_yoy_pct")
    fired = (ta_yoy is not None and abs(ta_yoy) > NC12_TOTAL_ASSETS_YOY_ABS_MIN_PCT) or (
        rev_yoy is not None and abs(rev_yoy) > NC12_REVENUE_YOY_ABS_MIN_PCT
    )
    _log(debug, "NC-12", fired, ta_yoy=ta_yoy, rev_yoy=rev_yoy)
    if not fired:
        return None
    return {
        "code": "NC-12",
        "text": (
            "Operazioni straordinarie recenti (M&A, spin-off, dismissioni) rompono la "
            "comparabilità YoY e i calcoli CAGR."
        ),
        "rule": "suspend_cagr_and_yoy_criteria",
    }


def _nc13_loss_making(ctx: dict, debug=None) -> dict | None:
    ni, ebit = ctx.get("net_income"), ctx.get("ebit")
    fired = ni is not None and ebit is not None and ni < 0 and ebit < 0
    _log(debug, "NC-13", fired, ni=ni, ebit=ebit)
    if not fired:
        return None
    return {
        "code": "NC-13",
        "text": (
            "Azienda in perdita/pre-profit: P/E, PEG e ROE sono indefiniti. Valutare con "
            "EV/Sales, Rule of 40, traiettoria gross margin e cash runway."
        ),
        "rule": "switch_to_growth_metrics",
    }


def _nc14_reit_utility(ctx: dict, debug=None) -> dict | None:
    sector = ctx.get("sector")
    fired = sector in ("Real Estate", "Utilities")
    _log(debug, "NC-14", fired, sector=sector)
    if not fired:
        return None
    return {
        "code": "NC-14",
        "text": (
            "Settore a leva strutturalmente elevata: le soglie generiche di leva non si "
            "applicano. Per i REIT usare FFO/AFFO e payout ratio; per le utility la regulated "
            "asset base e la sensibilità ai tassi."
        ),
        "rule": "dedicated_thresholds_reit_utility",
    }


def _nc15_stale_data(ctx: dict, debug=None) -> dict | None:
    last_date, today = ctx.get("last_statement_date"), ctx.get("today")
    stale_fields = ctx.get("stale_fields") or {}
    months = None
    overall_stale = False
    if last_date is not None:
        today = today or dt.date.today()
        d = last_date.date() if hasattr(last_date, "date") else last_date
        months = (today.year - d.year) * 12 + (today.month - d.month)
        overall_stale = months > NC15_STALE_MONTHS
    # FIX4 v2.1: scatta anche se una singola metrica core deriva da un
    # esercizio più vecchio dell'ultimo disponibile per le altre metriche
    # della stessa categoria (campo assente negli anni recenti), non solo
    # quando l'intero bilancio è vecchio.
    per_metric_stale = bool(stale_fields)
    fired = overall_stale or per_metric_stale
    _log(debug, "NC-15", fired, months=months, overall_stale=overall_stale, stale_fields=list(stale_fields.keys()))
    if not fired:
        return None
    if overall_stale:
        d = last_date.date() if hasattr(last_date, "date") else last_date
        text = (
            f"Attenzione: alcuni dati (es. interest coverage) derivano da bilanci non "
            f"aggiornati (ultimo bilancio disponibile: {d.isoformat()}, oltre {NC15_STALE_MONTHS} mesi "
            f"fa). Il valore mostrato potrebbe non essere corrente."
        )
    else:
        stale_list = ", ".join(sorted(stale_fields.keys()))
        text = (
            f"Attenzione: le seguenti metriche derivano da un esercizio più vecchio di quello "
            f"usato per le altre voci della stessa categoria (campo assente negli anni recenti): "
            f"{stale_list}. Etichettate con l'anno di riferimento e pesate meno nel sub-score."
        )
    return {"code": "NC-15", "text": text, "rule": "reduce_confidence_stale"}


def _nc16_earnings_quality_divergence(ctx: dict, debug=None) -> dict | None:
    oi_slope, fcf_slope, n_years = ctx.get("operating_income_trend_slope"), ctx.get("fcf_trend_slope"), ctx.get("n_years_trend")
    evaluable = oi_slope is not None and fcf_slope is not None and bool(n_years) and n_years >= NC16_MIN_YEARS_TREND
    fired = evaluable and oi_slope > 0 and fcf_slope < 0
    _log(debug, "NC-16", fired, oi_slope=oi_slope, fcf_slope=fcf_slope, n_years=n_years)
    if not fired:
        return None
    return {
        "code": "NC-16",
        "text": (
            "Divergenza earnings quality: l'utile operativo cresce ma il free cash flow cala da "
            "più anni. Possibile deterioramento della qualità degli utili (accruals crescenti, "
            "capex, working capital). Penalità applicata al sub-score qualità utili."
        ),
        "rule": "penalize_earnings_quality_strong",
    }


def _nc17_currency_effects(ctx: dict, debug=None) -> dict | None:
    currency = ctx.get("currency")
    fired = bool(currency) and currency in _HIGH_INFLATION_CURRENCIES
    _log(debug, "NC-17", fired, currency=currency)
    if not fired:
        return None
    return {
        "code": "NC-17",
        "text": (
            "Effetti valutari o iperinflazione possono distorcere crescita e margini nominali. "
            "Interpretare i trend con cautela."
        ),
        "rule": "reduce_confidence_currency",
    }


def _nc18_fully_depreciated(ctx: dict, debug=None) -> dict | None:
    ppe_net, ppe_gross = ctx.get("ppe_net"), ctx.get("ppe_gross")
    fired = ppe_net is not None and bool(ppe_gross) and (ppe_net / ppe_gross < NC18_NET_TO_GROSS_PPE_MAX)
    _log(debug, "NC-18", fired, ppe_net=ppe_net, ppe_gross=ppe_gross)
    if not fired:
        return None
    return {
        "code": "NC-18",
        "text": (
            "Base di asset molto ammortizzata: ROIC e ROA possono risultare gonfiati dal basso "
            "valore contabile netto degli asset. Considerare il costo di sostituzione."
        ),
        "rule": "note_only",
    }


def _nc19_dickinson_securities(ctx: dict, debug=None) -> dict | None:
    """FIX8 v2.1 — il trigger vero e proprio (CFI>0, securities/attivo>20%,
    OCF>0) è calcolato in src/lifecycle.py PRIMA della classificazione
    archetipo (deve poter correggere lo stadio Dickinson usato da
    assign_archetype), qui si legge solo il flag già deciso per evitare
    di duplicare/disallineare la soglia in due punti del codice."""
    fired = bool(ctx.get("dickinson_overridden_by_securities"))
    _log(debug, "NC-19", fired)
    if not fired:
        return None
    return {
        "code": "NC-19",
        "text": (
            "Il cash flow da investimento è positivo per la gestione del portafoglio di "
            "marketable securities, non per dismissioni di asset operativi: la classificazione "
            "Dickinson risulta distorta. L'azienda è operativamente matura."
        ),
        "rule": "reclassify_lifecycle_mature",
    }


_ALL_NOTE_CHECKS = [
    _nc01_altman_buyback, _nc02_negative_book_equity, _nc03_roe_leverage,
    _nc04_roic_goodwill, _nc05_rd_not_capitalized, _nc06_operating_leases,
    _nc07_sbc, _nc08_cyclicality, _nc09_one_off, _nc10_negative_working_capital,
    _nc11_net_cash, _nc12_ma_activity, _nc13_loss_making, _nc14_reit_utility,
    _nc15_stale_data, _nc16_earnings_quality_divergence, _nc17_currency_effects,
    _nc18_fully_depreciated, _nc19_dickinson_securities,
]

# ---------------------------------------------------------------------------
# FIX5 v2.1 — metadati per nota: categoria Quality impattata (o None) e
# TIPO di aggiustamento. Solo "penalty" può bloccare una categoria dai
# Punti di forza (vincolo di esclusione reciproca in fundamental_score.py);
# "suppression"/"reclass"/"note_only" restano visibili SOLO nella sezione
# dedicata Note Critiche, mai duplicate nei Punti di attenzione, per non
# generare la contraddizione "stessa dimensione in forza e attenzione".
# ---------------------------------------------------------------------------
NC_META = {
    "NC-01": {"category": None, "type": "suppression"},  # sospende il cap Altman-distress, non una categoria Quality
    "NC-02": {"category": None, "type": "suppression"},   # sopprime metriche book-equity, non ancora in un sub-score Quality
    "NC-03": {"category": None, "type": "note_only"},     # ROE non è un membro dei sub-score Quality: solo informativa
    "NC-04": {"category": "profitability", "type": "note_only"},   # segnala una possibile SOTTOstima, non una penalità
    "NC-05": {"category": "profitability", "type": "note_only"},   # idem (R&D non capitalizzato sottostima, non sovrastima)
    "NC-06": {"category": "financial_strength", "type": "note_only"},
    "NC-07": {"category": "earnings_quality", "type": "penalty"},
    "NC-08": {"category": "profitability", "type": "note_only"},
    "NC-09": {"category": None, "type": "suppression"},   # sospende criteri Piotroski YoY, già applicato lì
    "NC-10": {"category": None, "type": "suppression"},   # neutralizza un criterio Piotroski, già applicato lì
    "NC-11": {"category": "financial_strength", "type": "suppression"},  # già forza il sub-score leva a 100
    "NC-12": {"category": None, "type": "suppression"},   # sospende criteri variazionali Piotroski
    "NC-13": {"category": None, "type": "suppression"},   # P/E naturalmente soppresso a monte per NI<=0
    "NC-14": {"category": "financial_strength", "type": "note_only"},
    "NC-15": {"category": None, "type": "penalty"},        # penalizza la CONFIDENZA, non un sub-score Quality/Valuation
    "NC-16": {"category": "earnings_quality", "type": "penalty"},
    "NC-17": {"category": None, "type": "penalty"},        # penalizza la CONFIDENZA
    "NC-18": {"category": "profitability", "type": "note_only"},
    "NC-19": {"category": None, "type": "reclass"},
}


def detect_critical_notes(ctx: dict, debug: list | None = None) -> list[dict]:
    """Valuta le 19 note critiche sul contesto fornito e ritorna solo
    quelle il cui trigger è scattato (§5: "SOLO se il trigger scatta") —
    lista vuota se nessuna condizione diagnosticabile è presente, mai una
    nota di riempimento. Se `debug` è una lista, viene popolata (FIX3
    v2.1) con un dizionario diagnostico per OGNI nota (anche quelle non
    scattate), per verificare in sviluppo quali condizioni hanno impedito
    l'attivazione — mai per introdurre eccezioni per titolo."""
    notes = []
    for check in _ALL_NOTE_CHECKS:
        try:
            note = check(ctx, debug=debug)
        except Exception:
            note = None
        if note is not None:
            notes.append(note)
    return notes


def rules_active(notes: list[dict]) -> set[str]:
    """Insieme delle regole di aggiustamento attive, da applicare al
    calcolo dei punteggi in src/fundamental_score.py."""
    return {n["rule"] for n in notes}


def penalty_notes_by_category(notes: list[dict]) -> dict[str, list[dict]]:
    """FIX5 v2.1 — raggruppa le note ATTIVE di tipo 'penalty' per
    categoria Quality impattata: usato da src/fundamental_score.py sia per
    applicare davvero la penalità al sub-score, sia per impedire a quella
    categoria di comparire fra i Punti di forza anche se il punteggio
    resta alto (vincolo di esclusione reciproca, FIX5 punto 3)."""
    out: dict[str, list[dict]] = {}
    for note in notes:
        meta = NC_META.get(note["code"], {})
        if meta.get("type") != "penalty":
            continue
        cat = meta.get("category")
        if cat is None:
            continue
        out.setdefault(cat, []).append(note)
    return out
