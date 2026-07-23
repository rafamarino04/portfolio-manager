"""
Tabelle di soglie ASSOLUTE per settore/archetipo — Analisi Fondamentale
v2.0 (§1.2, §3.2, §4.1). Nessun peer group a runtime: ogni metrica si
confronta con una tabella di lookup pre-calcolata per "bucket" di
settore, non con altri titoli che l'utente segue.

Fonte dichiarata delle ancore: dove la specifica fornita dall'utente
riporta un numero esplicito (Damodaran NYU Stern, "Margins and ROIC by
Sector", gennaio 2026, più le convenzioni di rating S&P/Moody's per la
leva), quel numero è usato direttamente — vedi i commenti per bucket.
Dove la specifica non copre un settore Yahoo Finance (Energy, Basic
Materials, Consumer Cyclical, Communication Services), le soglie sono
un'estensione ragionata mia, coerente con l'ordine di grandezza dei
bucket vicini citati nella specifica — NON l'esatto dataset Damodaran
di gennaio 2026, che non è consultabile in modo automatico da qui. Sono
pensate come un punto di partenza dichiarato, da versionare/aggiornare
manualmente (idealmente ogni gennaio, quando Damodaran pubblica
l'aggiornamento), non come un valore definitivo.

Ogni tabella è una lista di 4 coppie (valore_grezzo, punteggio) — punto
"Scarso", "Sufficiente", "Buono", "Eccellente" secondo il vocabolario
§8 — interpolate linearmente a tratti da `_interp` (vedi anche
src/factors.py per lo stesso pattern usato sui fattori assoluti).
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Mappatura settore Yahoo Finance -> bucket di soglie. 8 bucket: i 5
# esplicitamente nominati dalla specifica (§3.2) più 3 di mia estensione
# per coprire tutti i settori non finanziari usati da questa app.
# ---------------------------------------------------------------------------
SECTOR_BUCKETS: dict[str, str] = {
    "Technology": "software_semis",
    "Communication Services": "media_telecom",
    "Healthcare": "pharma_healthcare",
    "Consumer Cyclical": "consumer_cyclical",
    "Consumer Defensive": "consumer_staples",
    "Industrials": "industrial_machinery",
    "Energy": "energy_materials",
    "Basic Materials": "energy_materials",
    "Utilities": "utility_capital_intensive",
    "Real Estate": "utility_capital_intensive",  # override dedicato REIT, vedi NC-14
}

BUCKET_LABELS_IT = {
    "industrial_machinery": "Industriale/Machinery",
    "software_semis": "Software/Semiconductor",
    "consumer_staples": "Consumer staples/Household",
    "pharma_healthcare": "Pharma/Healthcare",
    "utility_capital_intensive": "Utility/capital-intensive",
    "energy_materials": "Energy/Materials (estensione)",
    "consumer_cyclical": "Consumer Cyclical (estensione)",
    "media_telecom": "Media/Telecom (estensione)",
}


def bucket_for_sector(sector: str | None) -> str | None:
    if not sector:
        return None
    return SECTOR_BUCKETS.get(sector)


# ---------------------------------------------------------------------------
# Interpolazione lineare a tratti tra 4 ancore (Scarso/Sufficiente/Buono/
# Eccellente), clamp oltre gli estremi — §10 "Curve di Scoring".
# ---------------------------------------------------------------------------

def interp(value: float | None, anchors: list[tuple[float, float]]) -> float | None:
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


def bell_score(value: float | None, safe_abs: float, warn_abs: float, red_abs: float, peak_score: float = 92) -> float | None:
    """Curva "a campana" (§10): un valore vicino a 0 è sano (accruals
    ratio, Sloan 1996), sia troppo negativo sia troppo positivo peggiora
    il punteggio. `safe_abs`/`warn_abs`/`red_abs` sono soglie di |valore|."""
    if value is None:
        return None
    av = abs(value)
    if av <= safe_abs:
        # dentro la zona sicura: punteggio massimo al centro, degradazione lieve verso il bordo
        return peak_score - (av / safe_abs) * (peak_score - 70)
    if av <= warn_abs:
        frac = (av - safe_abs) / (warn_abs - safe_abs)
        return 70 - frac * (70 - 35)
    if av <= red_abs:
        frac = (av - warn_abs) / (red_abs - warn_abs)
        return 35 - frac * (35 - 10)
    return 5.0


# ---------------------------------------------------------------------------
# ROIC per bucket (§3.2) — spread di valore creato: la soglia già
# incorpora implicitamente il WACC tipico del settore (es. un utility ha
# WACC ~5-6%, un software ~9-10%: le soglie assolute sono più basse per
# l'utility non perché "meno bravo" ma perché il suo costo del capitale
# è strutturalmente più basso).
# ---------------------------------------------------------------------------
ROIC_ANCHORS_PCT: dict[str, list[tuple[float, float]]] = {
    "industrial_machinery":     [(6, 10), (9, 47), (14, 77), (20, 92)],
    "software_semis":           [(12, 10), (20, 47), (30, 77), (45, 92)],
    "consumer_staples":         [(10, 10), (15, 47), (25, 77), (38, 92)],
    "pharma_healthcare":        [(8, 10), (15, 47), (25, 77), (35, 92)],
    "utility_capital_intensive": [(4, 10), (6.5, 47), (9, 77), (12, 92)],
    "energy_materials":         [(5, 10), (8, 47), (12, 77), (18, 92)],
    "consumer_cyclical":        [(7, 10), (11, 47), (18, 77), (28, 92)],
    "media_telecom":            [(8, 10), (13, 47), (22, 77), (35, 92)],
}

# Margine operativo after-tax per bucket (§3.2, es. Software 32.62%,
# Pharma 26.36%, Tobacco 37.34%, Auto & Truck 2.44%, Grocery 1.50%).
OPERATING_MARGIN_ANCHORS_PCT: dict[str, list[tuple[float, float]]] = {
    "industrial_machinery":     [(3, 10), (7, 47), (12, 77), (18, 92)],
    "software_semis":           [(10, 10), (20, 47), (30, 77), (42, 92)],
    "consumer_staples":         [(4, 10), (8, 47), (14, 77), (22, 92)],
    "pharma_healthcare":        [(8, 10), (16, 47), (24, 77), (34, 92)],
    "utility_capital_intensive": [(8, 10), (14, 47), (20, 77), (28, 92)],
    "energy_materials":         [(3, 10), (7, 47), (12, 77), (20, 92)],
    "consumer_cyclical":        [(2, 10), (5, 47), (9, 77), (15, 92)],
    "media_telecom":            [(8, 10), (15, 47), (24, 77), (36, 92)],
}

# --- Metriche GLOBALI (non sector-specific per §3.2/§10): stesse ancore
# per tutti i bucket, in scala percentuale (coerente con come le
# calcola src/fundamental_score.py, es. 25.0 = 25%). ---
GROSS_PROFITS_TO_ASSETS_ANCHORS = [(15, 10), (25, 47), (35, 77), (50, 92)]
FCF_CONVERSION_ANCHORS = [(60, 10), (80, 47), (100, 77), (110, 92)]
NET_DEBT_EBITDA_ANCHORS = [(1.5, 92), (3.25, 77), (4.25, 47), (5.5, 10)]  # più basso = meglio
INTEREST_COVERAGE_ANCHORS = [(1.5, 5), (3, 47), (6, 77), (10, 92)]

# Accruals ratio (Sloan): curva a campana, |ratio| in punti percentuali.
ACCRUALS_SAFE_ABS, ACCRUALS_WARN_ABS, ACCRUALS_RED_ABS = 10.0, 25.0, 40.0

# ---------------------------------------------------------------------------
# Multipli di "fair value" assoluti per bucket (§4.1-4.2) — punteggio
# ALTO = economico (convenzione dichiarata dalla specifica). Stime
# ragionate coerenti con gli ordini di grandezza citati (EV/EBITDA
# "profittevoli" ~5x energy, >20x software/tech) — non l'esatto dataset
# Damodaran, vedi disclaimer del modulo.
# ---------------------------------------------------------------------------
EV_EBITDA_FAIR_ANCHORS: dict[str, list[tuple[float, float]]] = {
    "industrial_machinery":     [(6, 100), (10, 60), (14, 30), (20, 0)],
    "software_semis":           [(10, 100), (18, 60), (26, 30), (38, 0)],
    "consumer_staples":         [(8, 100), (13, 60), (17, 30), (23, 0)],
    "pharma_healthcare":        [(8, 100), (13, 60), (18, 30), (25, 0)],
    "utility_capital_intensive": [(6, 100), (9, 60), (12, 30), (16, 0)],
    "energy_materials":         [(3, 100), (5, 60), (7, 30), (10, 0)],
    "consumer_cyclical":        [(6, 100), (10, 60), (14, 30), (20, 0)],
    "media_telecom":            [(6, 100), (10, 60), (15, 30), (22, 0)],
}

EV_SALES_FAIR_ANCHORS: dict[str, list[tuple[float, float]]] = {
    "industrial_machinery":     [(0.8, 100), (1.5, 60), (2.5, 30), (4, 0)],
    "software_semis":           [(3, 100), (6, 60), (10, 30), (16, 0)],
    "consumer_staples":         [(1, 100), (2, 60), (3, 30), (4.5, 0)],
    "pharma_healthcare":        [(2, 100), (3.5, 60), (5, 30), (7, 0)],
    "utility_capital_intensive": [(1.5, 100), (2.5, 60), (3.5, 30), (5, 0)],
    "energy_materials":         [(0.5, 100), (1, 60), (1.7, 30), (2.5, 0)],
    "consumer_cyclical":        [(0.5, 100), (1, 60), (1.7, 30), (2.7, 0)],
    "media_telecom":            [(1.5, 100), (2.5, 60), (4, 30), (6, 0)],
}

PE_FAIR_ANCHORS: dict[str, list[tuple[float, float]]] = {
    "industrial_machinery":     [(10, 100), (16, 60), (22, 30), (30, 0)],
    "software_semis":           [(15, 100), (25, 60), (35, 30), (50, 0)],
    "consumer_staples":         [(12, 100), (18, 60), (24, 30), (32, 0)],
    "pharma_healthcare":        [(12, 100), (18, 60), (25, 30), (35, 0)],
    "utility_capital_intensive": [(11, 100), (16, 60), (20, 30), (26, 0)],
    "energy_materials":         [(8, 100), (12, 60), (16, 30), (22, 0)],
    "consumer_cyclical":        [(10, 100), (15, 60), (20, 30), (28, 0)],
    "media_telecom":            [(9, 100), (14, 60), (19, 30), (26, 0)],
}

# WACC tipico per bucket (§3.2, "WACC settoriale tipico 7-10%") — usato
# solo come nota di sanity-check testuale: il WACC "vero" mostrato in
# pagina resta quello CAPM company-specific già calcolato da
# src/fundamental.py (beta del titolo, non una media di settore).
WACC_TYPICAL_RANGE_PCT: dict[str, tuple[float, float]] = {
    "industrial_machinery": (7, 9),
    "software_semis": (9, 11),
    "consumer_staples": (6, 8),
    "pharma_healthcare": (7, 9),
    "utility_capital_intensive": (5, 6.5),
    "energy_materials": (8, 10),
    "consumer_cyclical": (7, 9),
    "media_telecom": (7, 9),
}


def roic_score(bucket: str | None, roic_pct: float | None) -> float | None:
    if bucket is None or roic_pct is None:
        return None
    return interp(roic_pct, ROIC_ANCHORS_PCT.get(bucket, ROIC_ANCHORS_PCT["industrial_machinery"]))


def operating_margin_score(bucket: str | None, margin_pct: float | None) -> float | None:
    if bucket is None or margin_pct is None:
        return None
    return interp(margin_pct, OPERATING_MARGIN_ANCHORS_PCT.get(bucket, OPERATING_MARGIN_ANCHORS_PCT["industrial_machinery"]))


def gross_profits_to_assets_score(value_pct: float | None) -> float | None:
    return interp(value_pct, GROSS_PROFITS_TO_ASSETS_ANCHORS)


def fcf_conversion_score(value_pct: float | None) -> float | None:
    return interp(value_pct, FCF_CONVERSION_ANCHORS)


def accruals_score(ratio_pct: float | None) -> float | None:
    return bell_score(ratio_pct, ACCRUALS_SAFE_ABS, ACCRUALS_WARN_ABS, ACCRUALS_RED_ABS)


def net_debt_ebitda_score(x: float | None) -> float | None:
    """Più basso (o negativo = cassa netta) è meglio; la cassa netta
    riceve il punteggio massimo per costruzione (coerente con NC-11)."""
    if x is None:
        return None
    if x < 0:
        return 100.0
    return interp(x, NET_DEBT_EBITDA_ANCHORS)


def interest_coverage_score(x: float | None) -> float | None:
    return interp(x, INTEREST_COVERAGE_ANCHORS)


def ev_ebitda_valuation_score(bucket: str | None, multiple: float | None) -> float | None:
    if bucket is None or multiple is None or multiple <= 0:
        return None
    return interp(multiple, EV_EBITDA_FAIR_ANCHORS.get(bucket, EV_EBITDA_FAIR_ANCHORS["industrial_machinery"]))


def ev_sales_valuation_score(bucket: str | None, multiple: float | None) -> float | None:
    if bucket is None or multiple is None or multiple <= 0:
        return None
    return interp(multiple, EV_SALES_FAIR_ANCHORS.get(bucket, EV_SALES_FAIR_ANCHORS["industrial_machinery"]))


def pe_valuation_score(bucket: str | None, pe: float | None) -> float | None:
    if bucket is None or pe is None or pe <= 0:
        return None
    return interp(pe, PE_FAIR_ANCHORS.get(bucket, PE_FAIR_ANCHORS["industrial_machinery"]))
