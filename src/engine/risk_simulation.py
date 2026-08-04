"""
Rischio per trade: rendimento E drawdown — src/engine/risk_simulation.py

Serve a scegliere quanto rischiare per trade guardando **entrambi i lati**.
Il rendimento atteso è banale da calcolare a mente:

    rendimento_annuo ≈ trade_per_anno × expectancy_R × rischio%

ed è lineare nel rischio: raddoppi il rischio, raddoppi il rendimento
atteso. Questo è il lato che si guarda volentieri, ed è anche il motivo
per cui la gente alza il rischio.

Il drawdown non è altrettanto gentile. Raddoppia anch'esso in media, ma
la sua **coda** cresce peggio: le serie di perdite consecutive sono
inevitabili in un sistema con win rate basso, e con un rischio doppio la
stessa serie sfortunata produce un buco doppio su un capitale che nel
frattempo si è ridotto. È l'asimmetria per cui una perdita del 50%
richiede un +100% per tornare in pari.

**Perché bootstrap e non una formula.** Le formule chiuse assumono
rendimenti indipendenti e normali. La distribuzione degli R di un
trend-following non è né l'una né l'altra cosa: è fortemente asimmetrica,
con molte piccole perdite e pochi guadagni enormi, e ha una coda sinistra
più lunga del −1R pianificato per via dei gap. Ricampionare gli R-multipli
**realmente prodotti dal backtest** conserva quella forma; una gaussiana
la distruggerebbe, e proprio nella parte che conta.

**Il limite da tenere presente.** Il bootstrap ricampiona in modo
indipendente, quindi rompe l'eventuale autocorrelazione tra trade: se nel
sistema reale le perdite tendono a raggrupparsi (tipico, perché i mercati
laterali producono falsi segnali a raffica su più strumenti insieme), i
drawdown veri saranno **peggiori** di quelli simulati qui. I numeri di
questo modulo vanno letti come un limite inferiore alla sofferenza, non
come una previsione.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

DEFAULT_RISK_GRID = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0)
DEFAULT_PATHS = 2000
DEFAULT_YEARS = 5

# Soglie di drawdown su cui riportare la probabilità. La prima è quella
# che la specifica indica come limite di abbandono/deleveraging, la
# seconda è il territorio in cui un conto retail viene di norma chiuso
# dal suo proprietario molto prima che dalla matematica.
DRAWDOWN_THRESHOLDS = (0.20, 0.35, 0.50)


@dataclass
class RiskScenario:
    risk_pct: float
    median_annual_return_pct: float
    p5_annual_return_pct: float
    p95_annual_return_pct: float
    median_max_drawdown_pct: float
    p95_max_drawdown_pct: float
    prob_drawdown_over: dict[float, float] = field(default_factory=dict)
    median_worst_losing_streak: float = 0.0
    prob_negative_after_period: float = 0.0

    @property
    def return_to_pain(self) -> float | None:
        """Rendimento annuo mediano diviso drawdown mediano.

        È il rapporto che NON migliora alzando il rischio: entrambi i
        termini crescono insieme, quindi resta piatto. Vederlo scritto
        chiarisce che alzare il rischio non rende il sistema migliore —
        lo rende solo più grande, in entrambe le direzioni."""
        if not self.median_max_drawdown_pct:
            return None
        return self.median_annual_return_pct / self.median_max_drawdown_pct


@dataclass
class RiskSimulationReport:
    scenarios: list[RiskScenario] = field(default_factory=list)
    n_trades_sampled: int = 0
    trades_per_year: float = 0.0
    expectancy_r: float | None = None
    years: int = DEFAULT_YEARS
    paths: int = DEFAULT_PATHS
    notes: list[str] = field(default_factory=list)


def _max_drawdown_fraction(equity: np.ndarray) -> float:
    peaks = np.maximum.accumulate(equity)
    return float(np.max((peaks - equity) / peaks)) if equity.size else 0.0


def _longest_losing_streak(returns: np.ndarray) -> int:
    longest = current = 0
    for r in returns:
        if r < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def simulate(r_multiples, trades_per_year: float, risk_grid=DEFAULT_RISK_GRID,
             years: int = DEFAULT_YEARS, paths: int = DEFAULT_PATHS,
             seed: int = 42) -> RiskSimulationReport:
    """Ricampiona gli R-multipli osservati e compone l'equity.

    Ogni trade muove l'equity di `r × rischio_frazione`: è la definizione
    del sizing a frazione fissa, applicata in modo composto perché il
    rischio si calcola sull'equity **corrente**, non su quella iniziale.
    Il composto è ciò che rende il drawdown peggiore di quanto una somma
    lineare suggerirebbe."""
    r = np.asarray([x for x in r_multiples if x is not None and np.isfinite(x)], dtype=float)
    report = RiskSimulationReport(n_trades_sampled=r.size, trades_per_year=trades_per_year,
                                   years=years, paths=paths)
    if r.size < 10:
        report.notes.append(
            f"Solo {r.size} trade disponibili per il ricampionamento: la simulazione non è "
            "significativa. Servono almeno alcune decine di trade perché la forma della "
            "distribuzione sia rappresentata."
        )
        return report
    if trades_per_year <= 0:
        report.notes.append("Frequenza di trade non determinabile: simulazione non eseguibile.")
        return report

    report.expectancy_r = float(r.mean())
    n_trades_path = max(1, int(round(trades_per_year * years)))
    rng = np.random.default_rng(seed)
    draws = rng.choice(r, size=(paths, n_trades_path), replace=True)

    for risk_pct in risk_grid:
        f = risk_pct / 100.0
        per_trade = draws * f
        # Un trade non può far perdere più del 100% del capitale: si tronca
        # a −99% invece di produrre equity negative, che non esistono.
        per_trade = np.maximum(per_trade, -0.99)
        equity = np.cumprod(1.0 + per_trade, axis=1)

        finals = equity[:, -1]
        annual = (np.power(np.maximum(finals, 1e-9), 1.0 / years) - 1.0) * 100

        drawdowns = np.array([_max_drawdown_fraction(path) for path in equity])
        streaks = np.array([_longest_losing_streak(row) for row in per_trade])

        scenario = RiskScenario(
            risk_pct=risk_pct,
            median_annual_return_pct=float(np.median(annual)),
            p5_annual_return_pct=float(np.percentile(annual, 5)),
            p95_annual_return_pct=float(np.percentile(annual, 95)),
            median_max_drawdown_pct=float(np.median(drawdowns) * 100),
            p95_max_drawdown_pct=float(np.percentile(drawdowns, 95) * 100),
            prob_drawdown_over={t: float((drawdowns >= t).mean() * 100)
                                 for t in DRAWDOWN_THRESHOLDS},
            median_worst_losing_streak=float(np.median(streaks)),
            prob_negative_after_period=float((finals < 1.0).mean() * 100),
        )
        report.scenarios.append(scenario)

    report.notes.append(
        "Il ricampionamento è indipendente: rompe l'eventuale raggruppamento delle perdite. "
        "Nella realtà i mercati laterali producono falsi segnali a raffica su più strumenti "
        "insieme, quindi i drawdown veri tendono a essere PEGGIORI di questi."
    )
    return report


def trades_per_year_from(closed_trades, span_days: int | None) -> float:
    """Frequenza annua osservata, dedotta dal backtest invece che assunta."""
    if not closed_trades or not span_days or span_days <= 0:
        return 0.0
    return len(closed_trades) * 365.25 / span_days


def build_recommendation(report: RiskSimulationReport, tolerated_drawdown_pct: float) -> str:
    """Il rischio più alto la cui coda di drawdown resta dentro la
    tolleranza dichiarata.

    Si usa il 95° percentile e non la mediana di proposito: il drawdown
    che conta non è quello tipico ma quello che ti fa smettere. Un sistema
    abbandonato durante il suo drawdown peggiore ha reso, per chi lo ha
    abbandonato, esattamente quel drawdown."""
    if not report.scenarios:
        return "Simulazione non disponibile."

    accettabili = [s for s in report.scenarios
                   if s.p95_max_drawdown_pct <= tolerated_drawdown_pct]
    if not accettabili:
        minimo = report.scenarios[0]
        return (
            f"Nemmeno il rischio più basso simulato ({minimo.risk_pct:g}%) resta entro il "
            f"{tolerated_drawdown_pct:g}% di drawdown nel 5% dei casi peggiori: il suo 95° "
            f"percentile è {minimo.p95_max_drawdown_pct:.0f}%. O alzi la soglia che sei disposto "
            "a subire, o il sistema non è compatibile con la tua tolleranza."
        )

    scelto = max(accettabili, key=lambda s: s.risk_pct)
    return (
        f"Con una tolleranza dichiarata del {tolerated_drawdown_pct:g}%, il rischio più alto "
        f"sostenibile è **{scelto.risk_pct:g}% per trade**: rendimento annuo mediano "
        f"{scelto.median_annual_return_pct:+.1f}%, drawdown mediano "
        f"{scelto.median_max_drawdown_pct:.0f}% e {scelto.p95_max_drawdown_pct:.0f}% nel 5% dei "
        f"casi peggiori. Nota che il rapporto rendimento/dolore resta praticamente invariato a "
        "ogni livello di rischio: alzarlo non rende il sistema migliore, lo rende più grande in "
        "entrambe le direzioni."
    )
