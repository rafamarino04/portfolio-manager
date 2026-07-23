"""
Layer "Note Critiche" (Analisi Fondamentale v2.0, §5) — 18 note
rule-based e SELETTIVE: ognuna scatta solo se il suo trigger
machine-detectable è soddisfatto sui dati yfinance disponibili, non su
ogni metrica (§1 Key Finding 4: "va reso selettivo"). Ogni nota porta un
codice (NC-01..NC-18), un testo in italiano pronto per la UI, e una
regola di aggiustamento/soppressione applicata da src/fundamental_score.py
prima di finalizzare gli assi Quality/Valuation.

Ogni funzione `_nc_xx(ctx)` riceve lo stesso dizionario di contesto
`ctx` (costruito da src/fundamental_score.py) e ritorna `None` se il
trigger non scatta, altrimenti un dict {"code", "text", "rule"}.
Chiavi attese in `ctx` (tutte opzionali, assenti = trigger non valutabile
-> nessuna nota, mai una nota su dati mancanti travestita da falso
positivo):
    sector, archetype, altman (dict z/zone/variant), roic, roa, roe,
    leverage_ta_equity, net_debt, interest_coverage, total_equity,
    total_assets, goodwill, rd_to_revenue, lease_liabilities,
    sbc_to_revenue, diluted_shares_growing, buyback_active,
    margin_current, margin_median_8y, ni_yoy_pct, revenue_yoy_pct,
    current_ratio, deferred_revenue, total_assets_yoy_pct,
    net_income, ebit, currency, last_statement_date, today,
    operating_income_trend_slope, fcf_trend_slope, n_years_trend,
    ppe_net, ppe_gross, retained_earnings_to_ta,
"""
from __future__ import annotations

import datetime as dt

_HIGH_INFLATION_CURRENCIES = {
    "ARS", "TRY", "EGP", "NGN", "VES", "ZWL", "LBP", "SDG", "IRR",
}


def _nc01_altman_buyback(ctx: dict) -> dict | None:
    altman = ctx.get("altman") or {}
    zone = altman.get("zone")
    net_debt = ctx.get("net_debt")
    coverage = ctx.get("interest_coverage")
    ret_to_ta = ctx.get("retained_earnings_to_ta")
    if zone not in ("grey", "distress") or net_debt is None or coverage is None or ret_to_ta is None:
        return None
    if net_debt < 0 and coverage > 8 and ret_to_ta < 10:
        return {
            "code": "NC-01",
            "text": (
                "L'Altman Z-Score risulta in zona di allerta ma è distorto dai buyback che hanno "
                "eroso i retained earnings e il book equity. Con cassa netta positiva e interest "
                "coverage elevato, il segnale di distress NON è affidabile."
            ),
            "rule": "suppress_distress_penalty",
        }
    return None


def _nc02_negative_book_equity(ctx: dict) -> dict | None:
    equity = ctx.get("total_equity")
    ta = ctx.get("total_assets")
    if equity is None:
        return None
    if equity <= 0 or (ta and equity / ta < 0.05):
        return {
            "code": "NC-02",
            "text": (
                "Il patrimonio netto contabile è negativo o minimo (spesso da buyback o write-off). "
                "P/B, ROE e Debt/Equity sono privi di significato e vanno ignorati."
            ),
            "rule": "suppress_book_equity_metrics",
        }
    return None


def _nc03_roe_leverage(ctx: dict) -> dict | None:
    roe, roa, leverage = ctx.get("roe"), ctx.get("roa"), ctx.get("leverage_ta_equity")
    if roe is None or roa is None or leverage is None:
        return None
    if roe > 20 and roa < 6 and leverage > 3:
        return {
            "code": "NC-03",
            "text": (
                "Il ROE elevato deriva dalla leva finanziaria, non dalla performance operativa "
                "(scomposizione DuPont). Valutare ROIC e ROA come indicatori più puliti."
            ),
            "rule": "reduce_roe_weight",
        }
    return None


def _nc04_roic_goodwill(ctx: dict) -> dict | None:
    goodwill, ta = ctx.get("goodwill"), ctx.get("total_assets")
    if goodwill is None or not ta:
        return None
    if goodwill / ta > 0.30:
        return {
            "code": "NC-04",
            "text": (
                "L'invested capital include goodwill rilevante da acquisizioni; il ROIC può "
                "sottostimare la redditività operativa del business core. Considerare il ROIC su "
                "capitale tangibile."
            ),
            "rule": "show_roic_ex_goodwill",
        }
    return None


def _nc05_rd_not_capitalized(ctx: dict) -> dict | None:
    sector, archetype, rd = ctx.get("sector"), ctx.get("archetype"), ctx.get("rd_to_revenue")
    if rd is None:
        return None
    is_tech_pharma = sector in ("Technology", "Healthcare") or archetype in ("hyper_growth", "growth")
    if is_tech_pharma and rd > 10:
        return {
            "code": "NC-05",
            "text": (
                "L'R&D è spesato invece che capitalizzato (aggiustamento Damodaran): ROIC e margini "
                "operativi sono sottostimati e il capitale investito reale è più alto."
            ),
            "rule": "show_roic_rd_adjusted",
        }
    return None


def _nc06_operating_leases(ctx: dict) -> dict | None:
    sector = ctx.get("sector")
    lease, ta = ctx.get("lease_liabilities"), ctx.get("total_assets")
    lease_material = lease is not None and ta and lease / ta > 0.05
    sector_flagged = sector in ("Consumer Cyclical", "Industrials")
    if lease_material or (sector_flagged and lease is not None and lease > 0):
        return {
            "code": "NC-06",
            "text": (
                "I leasing operativi (IFRS 16/ASC 842) influenzano EBITDA, Net Debt/EBITDA e "
                "interest coverage; la comparabilità cross-company è limitata."
            ),
            "rule": "note_only",
        }
    return None


def _nc07_sbc(ctx: dict) -> dict | None:
    sbc_to_rev = ctx.get("sbc_to_revenue")
    diluted_growing = ctx.get("diluted_shares_growing")
    buyback_active = ctx.get("buyback_active")
    if sbc_to_rev is None and diluted_growing is None:
        return None
    if (sbc_to_rev is not None and sbc_to_rev > 5) or (diluted_growing and buyback_active):
        return {
            "code": "NC-07",
            "text": (
                "La SBC gonfia FCF e FCF conversion (add-back non-cash) e diluisce gli azionisti. "
                "Se il conteggio azioni cresce nonostante i buyback, la diluizione maschera il costo "
                "reale."
            ),
            "rule": "penalize_fcf_conversion_sbc",
        }
    return None


def _nc08_cyclicality(ctx: dict) -> dict | None:
    archetype = ctx.get("archetype")
    current, median = ctx.get("margin_current"), ctx.get("margin_median_8y")
    if archetype != "cyclical" or current is None or not median:
        return None
    if current > 1.5 * median or current < 0.5 * median:
        return {
            "code": "NC-08",
            "text": (
                "L'azienda è ciclica e valutata vicino al picco/minimo del ciclo: EV/EBITDA appare "
                "basso al picco (utili gonfiati) e P/E appare assurdo al minimo. Usare utili/EBITDA "
                "mid-cycle normalizzati."
            ),
            "rule": "normalize_mid_cycle",
        }
    return None


def _nc09_one_off(ctx: dict) -> dict | None:
    ni_yoy, rev_yoy = ctx.get("ni_yoy_pct"), ctx.get("revenue_yoy_pct")
    if ni_yoy is None:
        return None
    coherent_with_revenue = rev_yoy is not None and abs(ni_yoy - rev_yoy) < 20
    if abs(ni_yoy) > 50 and not coherent_with_revenue:
        return {
            "code": "NC-09",
            "text": (
                "L'utile netto è distorto da voci non ricorrenti (cessioni, contenziosi, impairment, "
                "one-timer fiscali). ROA, EPS e i criteri Piotroski basati su variazioni YoY possono "
                "essere fuorvianti."
            ),
            "rule": "suspend_piotroski_yoy_criteria",
        }
    return None


def _nc10_negative_working_capital(ctx: dict) -> dict | None:
    current_ratio = ctx.get("current_ratio")
    archetype, sector = ctx.get("archetype"), ctx.get("sector")
    deferred_rev = ctx.get("deferred_revenue")
    if current_ratio is None or deferred_rev is None:
        return None
    subscription_like = archetype in ("hyper_growth", "growth") or sector == "Consumer Cyclical"
    if current_ratio < 1 and subscription_like and deferred_rev > 0:
        return {
            "code": "NC-10",
            "text": (
                "Il current ratio basso/negativo è un PUNTO DI FORZA (working capital negativo, "
                "deferred revenue): i clienti finanziano l'azienda. Il criterio Piotroski sul "
                "current ratio qui è fuorviante."
            ),
            "rule": "neutralize_piotroski_current_ratio",
        }
    return None


def _nc11_net_cash(ctx: dict) -> dict | None:
    net_debt = ctx.get("net_debt")
    if net_debt is None:
        return None
    if net_debt < 0:
        return {
            "code": "NC-11",
            "text": (
                "L'azienda ha cassa netta: Net Debt/EBITDA è negativo e le metriche di leva sono "
                "non informative. L'interest coverage può essere indefinito o dominato dagli "
                "interessi attivi."
            ),
            "rule": "leverage_score_max",
        }
    return None


def _nc12_ma_activity(ctx: dict) -> dict | None:
    ta_yoy, rev_yoy = ctx.get("total_assets_yoy_pct"), ctx.get("revenue_yoy_pct")
    if ta_yoy is None and rev_yoy is None:
        return None
    if (ta_yoy is not None and abs(ta_yoy) > 40) or (rev_yoy is not None and abs(rev_yoy) > 50):
        return {
            "code": "NC-12",
            "text": (
                "Operazioni straordinarie recenti (M&A, spin-off, dismissioni) rompono la "
                "comparabilità YoY e i calcoli CAGR."
            ),
            "rule": "suspend_cagr_and_yoy_criteria",
        }
    return None


def _nc13_loss_making(ctx: dict) -> dict | None:
    ni, ebit = ctx.get("net_income"), ctx.get("ebit")
    if ni is None or ebit is None:
        return None
    if ni < 0 and ebit < 0:
        return {
            "code": "NC-13",
            "text": (
                "Azienda in perdita/pre-profit: P/E, PEG e ROE sono indefiniti. Valutare con "
                "EV/Sales, Rule of 40, traiettoria gross margin e cash runway."
            ),
            "rule": "switch_to_growth_metrics",
        }
    return None


def _nc14_reit_utility(ctx: dict) -> dict | None:
    sector = ctx.get("sector")
    if sector in ("Real Estate", "Utilities"):
        return {
            "code": "NC-14",
            "text": (
                "Settore a leva strutturalmente elevata: le soglie generiche di leva non si "
                "applicano. Per i REIT usare FFO/AFFO e payout ratio; per le utility la regulated "
                "asset base e la sensibilità ai tassi."
            ),
            "rule": "dedicated_thresholds_reit_utility",
        }
    return None


def _nc15_stale_data(ctx: dict) -> dict | None:
    last_date, today = ctx.get("last_statement_date"), ctx.get("today")
    if last_date is None:
        return None
    today = today or dt.date.today()
    if hasattr(last_date, "date"):
        last_date = last_date.date()
    months = (today.year - last_date.year) * 12 + (today.month - last_date.month)
    if months > 15:
        return {
            "code": "NC-15",
            "text": (
                f"Attenzione: alcuni dati (es. interest coverage) derivano da bilanci non "
                f"aggiornati (ultimo bilancio disponibile: {last_date.isoformat()}, oltre 15 mesi "
                f"fa). Il valore mostrato potrebbe non essere corrente."
            ),
            "rule": "reduce_confidence_stale",
        }
    return None


def _nc16_earnings_quality_divergence(ctx: dict) -> dict | None:
    oi_slope, fcf_slope, n_years = ctx.get("operating_income_trend_slope"), ctx.get("fcf_trend_slope"), ctx.get("n_years_trend")
    if oi_slope is None or fcf_slope is None or not n_years or n_years < 3:
        return None
    if oi_slope > 0 and fcf_slope < 0:
        return {
            "code": "NC-16",
            "text": (
                "Divergenza earnings quality: l'utile operativo cresce ma il free cash flow cala da "
                "più anni. Possibile deterioramento della qualità degli utili (accruals crescenti, "
                "capex, working capital)."
            ),
            "rule": "penalize_earnings_quality_strong",
        }
    return None


def _nc17_currency_effects(ctx: dict) -> dict | None:
    currency = ctx.get("currency")
    if not currency:
        return None
    if currency in _HIGH_INFLATION_CURRENCIES:
        return {
            "code": "NC-17",
            "text": (
                "Effetti valutari o iperinflazione possono distorcere crescita e margini nominali. "
                "Interpretare i trend con cautela."
            ),
            "rule": "reduce_confidence_currency",
        }
    return None


def _nc18_fully_depreciated(ctx: dict) -> dict | None:
    ppe_net, ppe_gross = ctx.get("ppe_net"), ctx.get("ppe_gross")
    if ppe_net is None or not ppe_gross:
        return None
    if ppe_net / ppe_gross < 0.30:
        return {
            "code": "NC-18",
            "text": (
                "Base di asset molto ammortizzata: ROIC e ROA possono risultare gonfiati dal basso "
                "valore contabile netto degli asset. Considerare il costo di sostituzione."
            ),
            "rule": "note_only",
        }
    return None


_ALL_NOTE_CHECKS = [
    _nc01_altman_buyback, _nc02_negative_book_equity, _nc03_roe_leverage,
    _nc04_roic_goodwill, _nc05_rd_not_capitalized, _nc06_operating_leases,
    _nc07_sbc, _nc08_cyclicality, _nc09_one_off, _nc10_negative_working_capital,
    _nc11_net_cash, _nc12_ma_activity, _nc13_loss_making, _nc14_reit_utility,
    _nc15_stale_data, _nc16_earnings_quality_divergence, _nc17_currency_effects,
    _nc18_fully_depreciated,
]


def detect_critical_notes(ctx: dict) -> list[dict]:
    """Valuta le 18 note critiche sul contesto fornito e ritorna solo
    quelle il cui trigger è scattato (§5: "SOLO se il trigger scatta") —
    lista vuota se nessuna condizione diagnosticabile è presente, mai una
    nota di riempimento."""
    notes = []
    for check in _ALL_NOTE_CHECKS:
        try:
            note = check(ctx)
        except Exception:
            note = None
        if note is not None:
            notes.append(note)
    return notes


def rules_active(notes: list[dict]) -> set[str]:
    """Insieme delle regole di aggiustamento attive, da applicare al
    calcolo dei punteggi in src/fundamental_score.py."""
    return {n["rule"] for n in notes}
