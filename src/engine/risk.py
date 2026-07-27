"""
Dimensionamento della posizione e leva — src/engine/risk.py

Il dimensionamento domina i risultati: circa il 91% della variabilità
della performance di un portafoglio è attribuibile alla decisione di
allocazione/sizing piuttosto che alla selezione dei titoli (Brinson,
Singer & Beebower, ripreso da Van Tharp). La leva, invece, è il punto in
cui i conti retail saltano.

**Sizing a frazione fissa del rischio.** Si rischia una percentuale
costante dell'equity corrente su ogni trade, dove il rischio è definito
dalla distanza dallo stop:

    size = (equity × risk%) / (entry − stop)

Il risultato è che ogni perdita piena vale sempre la stessa frazione
dell'equity, qualunque sia lo strumento e qualunque sia la sua
volatilità: quando la volatilità sale (stop più lontano in punti di
prezzo) la size si riduce automaticamente, e viceversa. È il sizing
standard del trend-following sistematico.

**R-multipli.** R è il rischio iniziale del trade (entry − stop, per la
size). Ogni esito si esprime come multiplo di R: un trade che guadagna il
doppio del rischio è +2R, uno stoppato al livello iniziale è −1R. Gli
R-multipli rendono i trade confrontabili tra strumenti, size e valute,
e — cosa decisiva qui — permettono di separare la qualità del segnale
dall'effetto della leva: la distribuzione degli R dice se il segnale ha
un edge, il P&L in euro dice cosa hanno fatto leva e sizing a quell'edge.

**Confidenza → leva: la parte pericolosa.** Far pesare di più i segnali
ad alta confidenza è difendibile con moderazione, ma pericoloso se fatto
ingenuamente, per tre ragioni: (1) la leva amplifica simmetricamente
guadagni e perdite, e i drawdown compongono (una perdita del 50% richiede
un +100% per recuperare); (2) la confidenza è una *stima*, e l'errore di
stima è esattamente ciò che la leva magnifica; (3) i segnali ad alta
confidenza, quando falliscono, tendono a farlo in eventi di coda (gap,
cambi di regime) dove gli stop slittano e la perdita realizzata supera il
−1R pianificato. Concentrare la leva sui segnali "migliori" la concentra
quindi proprio dove vive la coda sinistra.

Per questo la leva qui nasce **disattivata** (`leverage_enabled=False`,
tutto a 1.0×) e va sbloccata solo dopo che la calibrazione empirica ha
mostrato che i segnali "85 di confidenza" vincono davvero circa l'85%
delle volte (Stage 4 della specifica). Nota infine che Trade Republic è
spot-only: qui la "leva" è un costrutto di modello che nel reale mappa
sulla *concentrazione* di capitale, la quale amplifica i drawdown
esattamente allo stesso modo.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Rischio base per trade, in percentuale dell'equity. I professionisti
# rischiano tipicamente tra lo 0,5% e il 2%; per un default difensivo
# retail si sta tra 0,5% e 1%, con l'1% come tetto del caso base.
DEFAULT_RISK_PCT = 0.75
MAX_BASE_RISK_PCT = 1.0

# Mappa confidenza (0-100) → moltiplicatore di leva. Sotto 50 non si opera.
CONFIDENCE_LEVERAGE_BANDS = [
    (0, 49, 0.0),      # nessun trade
    (50, 69, 1.0),     # solo rischio base
    (70, 84, 1.25),
    (85, 100, 1.5),    # tetto rigido
]

# Tetti rigidi: non superarli mai, nemmeno alla massima confidenza.
HARD_MAX_LEVERAGE = 1.5
HARD_MAX_RISK_PCT_PER_TRADE = 1.5
# Esposizione lorda aggregata su tutte le posizioni aperte, in multipli
# dell'equity, e somma dei rischi aperti (i −1R) in percentuale di equity.
HARD_MAX_GROSS_EXPOSURE = 1.5
HARD_MAX_AGGREGATE_OPEN_RISK_PCT = 5.0


def leverage_for_confidence(confidence: float | None, enabled: bool = False) -> float:
    """Moltiplicatore di leva per un punteggio di confidenza 0-100.

    Con `enabled=False` (default) ritorna sempre 1.0 per i segnali
    operabili: è lo stato previsto dalla specifica finché la calibrazione
    non è stata verificata. La banda "nessun trade" sotto 50 resta attiva
    anche a leva disabilitata, perché non è una scelta di leva ma un
    filtro di qualità del segnale."""
    if confidence is None:
        return 1.0
    for lo, hi, mult in CONFIDENCE_LEVERAGE_BANDS:
        if lo <= confidence <= hi:
            if mult == 0.0:
                return 0.0
            return min(mult, HARD_MAX_LEVERAGE) if enabled else 1.0
    return 1.0


@dataclass
class RiskConfig:
    risk_pct: float = DEFAULT_RISK_PCT
    leverage_enabled: bool = False
    max_gross_exposure: float = HARD_MAX_GROSS_EXPOSURE
    max_aggregate_open_risk_pct: float = HARD_MAX_AGGREGATE_OPEN_RISK_PCT
    # Un solo trade aperto per strumento: evita di accumulare esposizione
    # sullo stesso rischio senza dichiararlo.
    one_position_per_symbol: bool = True

    def __post_init__(self):
        if self.risk_pct > MAX_BASE_RISK_PCT:
            # Non si silenzia una configurazione pericolosa: la si taglia
            # e lo si dichiara nel risultato (vedi `warnings` in sizing).
            self.risk_pct = MAX_BASE_RISK_PCT


@dataclass
class SizingResult:
    size: float
    risk_per_unit: float
    initial_risk_eur: float          # questo è 1R in euro
    leverage: float
    notional_eur: float
    rejected_reason: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def is_tradable(self) -> bool:
        return self.rejected_reason is None and self.size > 0


def size_position(equity_eur: float, entry: float, stop: float, confidence: float | None,
                   config: RiskConfig, open_gross_exposure_eur: float = 0.0,
                   open_risk_eur: float = 0.0) -> SizingResult:
    """Size a frazione fissa del rischio, con leva da confidenza e tutti i
    cap rigidi applicati in cascata.

    I cap aggregati (esposizione lorda e rischio aperto totale) sono
    controllati *prima* di aprire: un sistema che rispetta l'1% per trade
    ma tiene dieci posizioni aperte contemporaneamente sta rischiando il
    10%, non l'1%."""
    warnings: list[str] = []

    risk_per_unit = abs(entry - stop)
    if risk_per_unit <= 0:
        return SizingResult(0.0, 0.0, 0.0, 0.0, 0.0,
                            rejected_reason="stop coincidente col prezzo di ingresso")
    if equity_eur <= 0:
        return SizingResult(0.0, risk_per_unit, 0.0, 0.0, 0.0,
                            rejected_reason="equity esaurita")

    leverage = leverage_for_confidence(confidence, enabled=config.leverage_enabled)
    if leverage <= 0:
        return SizingResult(0.0, risk_per_unit, 0.0, 0.0, 0.0,
                            rejected_reason=f"confidenza {confidence:.0f} sotto la soglia operativa (50)")

    effective_risk_pct = config.risk_pct * leverage
    if effective_risk_pct > HARD_MAX_RISK_PCT_PER_TRADE:
        warnings.append(
            f"Rischio per trade richiesto {effective_risk_pct:.2f}% oltre il tetto rigido "
            f"{HARD_MAX_RISK_PCT_PER_TRADE:g}%: tagliato al tetto."
        )
        effective_risk_pct = HARD_MAX_RISK_PCT_PER_TRADE

    risk_budget_eur = equity_eur * effective_risk_pct / 100.0

    # Cap sul rischio aggregato aperto: si riduce il budget del trade a
    # quanto resta disponibile, invece di rifiutarlo del tutto.
    max_total_risk_eur = equity_eur * config.max_aggregate_open_risk_pct / 100.0
    residual_risk_eur = max_total_risk_eur - open_risk_eur
    if residual_risk_eur <= 0:
        return SizingResult(0.0, risk_per_unit, 0.0, leverage, 0.0,
                            rejected_reason="rischio aggregato aperto già al tetto")
    if risk_budget_eur > residual_risk_eur:
        warnings.append("Budget di rischio ridotto per rispettare il cap sul rischio aggregato aperto.")
        risk_budget_eur = residual_risk_eur

    size = risk_budget_eur / risk_per_unit
    notional = size * entry

    # Cap sull'esposizione lorda aggregata.
    max_gross_eur = equity_eur * config.max_gross_exposure
    residual_gross_eur = max_gross_eur - open_gross_exposure_eur
    if residual_gross_eur <= 0:
        return SizingResult(0.0, risk_per_unit, 0.0, leverage, 0.0,
                            rejected_reason="esposizione lorda aggregata già al tetto")
    if notional > residual_gross_eur:
        warnings.append("Size ridotta per rispettare il cap sull'esposizione lorda aggregata.")
        size = residual_gross_eur / entry
        notional = size * entry

    if size <= 0:
        return SizingResult(0.0, risk_per_unit, 0.0, leverage, 0.0,
                            rejected_reason="size risultante nulla")

    return SizingResult(
        size=size,
        risk_per_unit=risk_per_unit,
        initial_risk_eur=size * risk_per_unit,
        leverage=leverage,
        notional_eur=notional,
        warnings=warnings,
    )
