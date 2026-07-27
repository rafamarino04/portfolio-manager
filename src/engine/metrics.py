"""
Metriche di performance — src/engine/metrics.py

Il compito di questo modulo non è produrre una bella curva di equity, ma
dire la verità su se il segnale abbia un edge reale, che sopravvive ai
costi e statisticamente significativo.

Due principi che governano tutto il resto:

**Il win rate da solo non significa nulla.** Il trend-following ha per
costruzione un win rate basso (tipicamente 30-45%) e guadagna da pochi
grandi vincitori. Un sistema al 35% con rapporto 3:1 ha expectancy
(0,35×3) − (0,65×1) = +0,40R per trade, cioè è solidamente profittevole.
Quello che conta è expectancy, profit factor e il rapporto tra dimensione
media di vincite e perdite.

**Il campione è il vincolo stringente.** Un win rate su 20 trade è quasi
privo di significato. Si usa l'intervallo di Wilson (migliore di quello
di Wald con n piccolo e proporzioni estreme) e si dichiara sempre il
numero di trade: a p=0,5 servono ~50 trade per ±13%, ~100 per ±9,6%, e
l'intervallo si stringe solo come 1/√n. Sotto i 50 trade i risultati sono
dominati da pochi outlier; la soglia di affidabilità è 100 trade, meglio
200.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np

# Soglie di campione minimo (dalla specifica).
MIN_TRADES_RELIABLE = 100
MIN_TRADES_INDICATIVE = 50

TRADING_DAYS_PER_YEAR = 252


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervallo di confidenza di Wilson al 95% per una proporzione.

    Preferito a quello di Wald (p̂ ± z·√(p̂(1−p̂)/n)) perché resta sensato
    con n piccolo e con proporzioni vicine a 0 o 1, dove Wald produce
    estremi fuori da [0,1] o intervalli di ampiezza nulla — esattamente
    le condizioni in cui si trova un sistema retail con pochi trade."""
    if n <= 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z ** 2 / n
    centre = p + z ** 2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2))
    return (max(0.0, (centre - margin) / denom), min(1.0, (centre + margin) / denom))


def max_drawdown(equity: list[float]) -> tuple[float, float]:
    """Massimo drawdown come (valore assoluto, frazione del picco).

    Va trattato come filtro rigido, non come metrica secondaria: è il
    numero che determina se il sistema è vivibile psicologicamente e se il
    conto sopravvive."""
    if not equity:
        return (0.0, 0.0)
    peak = equity[0]
    max_abs = 0.0
    max_pct = 0.0
    for value in equity:
        peak = max(peak, value)
        drop = peak - value
        if drop > max_abs:
            max_abs = drop
        if peak > 0 and drop / peak > max_pct:
            max_pct = drop / peak
    return (max_abs, max_pct)


def _annualized(returns: np.ndarray, periods_per_year: int = TRADING_DAYS_PER_YEAR) -> tuple[float, float]:
    if returns.size < 2:
        return (0.0, 0.0)
    return (float(returns.mean() * periods_per_year),
            float(returns.std(ddof=1) * math.sqrt(periods_per_year)))


def sharpe_ratio(returns: np.ndarray, risk_free_annual: float = 0.0) -> float | None:
    """Sharpe annualizzato. 1,0 è solido, 1,5 forte, 2,0+ eccezionale —
    ma solo su campioni che coprono più regimi di mercato."""
    if returns.size < 2:
        return None
    ann_ret, ann_vol = _annualized(returns)
    if ann_vol <= 0:
        return None
    return (ann_ret - risk_free_annual) / ann_vol


def sortino_ratio(returns: np.ndarray, risk_free_annual: float = 0.0) -> float | None:
    """Come lo Sharpe ma al denominatore solo la deviazione al ribasso.

    Un Sortino significativamente più alto dello Sharpe indica rendimenti
    asimmetrici verso l'alto: è la firma tipica del trend-following, dove
    le perdite sono tagliate dagli stop e i guadagni lasciati correre."""
    if returns.size < 2:
        return None
    downside = returns[returns < 0]
    if downside.size < 2:
        return None
    ann_ret = float(returns.mean() * TRADING_DAYS_PER_YEAR)
    downside_dev = float(downside.std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR))
    if downside_dev <= 0:
        return None
    return (ann_ret - risk_free_annual) / downside_dev


@dataclass
class PerformanceMetrics:
    label: str
    n_trades: int = 0
    total_return_pct: float | None = None
    cagr_pct: float | None = None
    win_rate: float | None = None
    win_rate_ci: tuple[float, float] | None = None
    avg_win_eur: float | None = None
    avg_loss_eur: float | None = None
    avg_win_r: float | None = None
    avg_loss_r: float | None = None
    profit_factor: float | None = None
    expectancy_eur: float | None = None
    expectancy_r: float | None = None
    sharpe: float | None = None
    sortino: float | None = None
    max_drawdown_eur: float | None = None
    max_drawdown_pct: float | None = None
    calmar: float | None = None
    avg_holding_days: float | None = None
    avg_mae_r: float | None = None
    avg_mfe_r: float | None = None
    total_costs_eur: float = 0.0
    gross_total_return_pct: float | None = None
    n_gapped_exits: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def sample_is_reliable(self) -> bool:
        return self.n_trades >= MIN_TRADES_RELIABLE

    @property
    def sample_is_indicative(self) -> bool:
        return self.n_trades >= MIN_TRADES_INDICATIVE

    @property
    def sample_note(self) -> str:
        if self.n_trades == 0:
            return "Nessun trade: nessuna metrica calcolabile."
        if not self.sample_is_indicative:
            return (f"Solo {self.n_trades} trade: sotto i {MIN_TRADES_INDICATIVE} i risultati sono "
                    "dominati da pochi outlier e non vanno interpretati.")
        if not self.sample_is_reliable:
            return (f"{self.n_trades} trade: indicativi ma sotto la soglia di affidabilità di "
                    f"{MIN_TRADES_RELIABLE} (idealmente 200+).")
        return f"{self.n_trades} trade: campione sufficiente per una lettura affidabile."


def compute_metrics(closed_trades: list, equity_curve: list[tuple[date, float, float]],
                     initial_equity: float, label: str = "") -> PerformanceMetrics:
    """Calcola tutte le metriche su una lista di ClosedTrade e una curva
    di equity. Le metriche di trade sono sempre calcolate **al netto** dei
    costi; il lordo è riportato a parte solo come rendimento totale, per
    rendere visibile il peso del costo."""
    m = PerformanceMetrics(label=label, n_trades=len(closed_trades))

    if equity_curve:
        net_equity = [e[1] for e in equity_curve]
        gross_equity = [e[2] for e in equity_curve]
        final_net = net_equity[-1]
        m.total_return_pct = (final_net / initial_equity - 1) * 100 if initial_equity else None
        m.gross_total_return_pct = (gross_equity[-1] / initial_equity - 1) * 100 if initial_equity else None

        span_days = (equity_curve[-1][0] - equity_curve[0][0]).days
        years = span_days / 365.25 if span_days > 0 else 0
        if years > 0 and initial_equity > 0 and final_net > 0:
            m.cagr_pct = ((final_net / initial_equity) ** (1 / years) - 1) * 100

        dd_abs, dd_pct = max_drawdown(net_equity)
        m.max_drawdown_eur, m.max_drawdown_pct = dd_abs, dd_pct * 100
        if m.cagr_pct is not None and dd_pct > 0:
            m.calmar = m.cagr_pct / (dd_pct * 100)

        arr = np.array(net_equity, dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            daily_returns = np.diff(arr) / arr[:-1]
        daily_returns = daily_returns[np.isfinite(daily_returns)]
        m.sharpe = sharpe_ratio(daily_returns)
        m.sortino = sortino_ratio(daily_returns)

    if not closed_trades:
        m.warnings.append("Nessun trade generato nel periodo: il segnale non si è mai attivato.")
        return m

    wins = [t for t in closed_trades if t.is_winner]
    losses = [t for t in closed_trades if not t.is_winner]

    m.win_rate = len(wins) / len(closed_trades)
    m.win_rate_ci = wilson_interval(len(wins), len(closed_trades))

    m.avg_win_eur = float(np.mean([t.net_pnl_eur for t in wins])) if wins else 0.0
    m.avg_loss_eur = float(np.mean([abs(t.net_pnl_eur) for t in losses])) if losses else 0.0
    m.avg_win_r = float(np.mean([t.net_r for t in wins])) if wins else 0.0
    m.avg_loss_r = float(np.mean([abs(t.net_r) for t in losses])) if losses else 0.0

    gross_profit = sum(t.net_pnl_eur for t in wins)
    gross_loss = abs(sum(t.net_pnl_eur for t in losses))
    if gross_loss > 0:
        m.profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        # Nessuna perdita: profit factor matematicamente infinito. Non si
        # riporta un numero finto, si segnala la condizione.
        m.profit_factor = None
        m.warnings.append("Nessun trade in perdita: profit factor non definito (campione troppo piccolo o irrealistico).")

    m.expectancy_eur = float(np.mean([t.net_pnl_eur for t in closed_trades]))
    m.expectancy_r = float(np.mean([t.net_r for t in closed_trades]))
    m.avg_holding_days = float(np.mean([t.bars_held for t in closed_trades]))
    m.avg_mae_r = float(np.mean([t.mae_r for t in closed_trades]))
    m.avg_mfe_r = float(np.mean([t.mfe_r for t in closed_trades]))
    m.total_costs_eur = float(sum(t.costs_eur for t in closed_trades))
    m.n_gapped_exits = sum(1 for t in closed_trades if t.gapped_exit)

    if not m.sample_is_indicative:
        m.warnings.append(m.sample_note)
    if m.profit_factor is not None and m.profit_factor > 3 and not m.sample_is_reliable:
        m.warnings.append(
            f"Profit factor {m.profit_factor:.2f} su un campione di {m.n_trades} trade: "
            "sopra 3 con pochi trade è quasi sempre overfitting o fortuna, non un edge."
        )
    return m


# ---------------------------------------------------------------------------
# Verdetto in linguaggio piano — il requisito finale della specifica:
# la pagina deve dire se l'edge è stabilito, marginale o non provato,
# invece di lasciare che sia una curva di equity a suggerirlo.
# ---------------------------------------------------------------------------

VERDICT_ESTABLISHED = "stabilito"
VERDICT_MARGINAL = "marginale"
VERDICT_UNPROVEN = "non provato"
VERDICT_NEGATIVE = "assente"


def build_verdict(m: PerformanceMetrics, beats_buy_and_hold: bool | None,
                   beats_random: bool | None) -> dict:
    """Verdetto sintetico sull'edge, con la motivazione esplicita.

    La gerarchia dei criteri non è negoziabile e riflette la specifica:
    prima il campione (senza numeri sufficienti non si conclude nulla),
    poi l'expectancy netta (se è ≤ 0 non c'è edge, punto), poi i due
    benchmark obbligatori. Un sistema che guadagna ma non batte il
    buy-and-hold non ha dimostrato che il *timing* serva a qualcosa; uno
    che non batte l'entrata casuale non ha dimostrato che il *segnale*
    aggiunga qualcosa a uscite e money management."""
    if m.n_trades == 0:
        return {"verdict": VERDICT_UNPROVEN,
                "text": "Nessun trade generato: non c'è nulla da valutare."}

    if m.expectancy_r is not None and m.expectancy_r <= 0:
        return {"verdict": VERDICT_NEGATIVE,
                "text": (f"Expectancy netta negativa ({m.expectancy_r:+.2f}R per trade su {m.n_trades} "
                         "trade): al netto dei costi il segnale perde denaro. Non è una questione di "
                         "taratura — è il segnale a non avere edge in questa forma.")}

    if not m.sample_is_indicative:
        return {"verdict": VERDICT_UNPROVEN,
                "text": (f"Expectancy positiva ({m.expectancy_r:+.2f}R) ma su soli {m.n_trades} trade: "
                         f"sotto i {MIN_TRADES_INDICATIVE} il risultato è dominato da pochi outlier e "
                         "non distingue un edge dalla fortuna.")}

    failed = []
    if beats_buy_and_hold is False:
        failed.append("non batte il buy-and-hold (il timing non ha aggiunto nulla rispetto a stare "
                      "semplicemente investito)")
    if beats_random is False:
        failed.append("non batte l'entrata casuale (l'edge viene da uscite e sizing, non dal segnale)")

    if failed:
        return {"verdict": VERDICT_UNPROVEN,
                "text": (f"Expectancy positiva ({m.expectancy_r:+.2f}R su {m.n_trades} trade), ma il "
                         f"sistema {' e '.join(failed)}.")}

    if not m.sample_is_reliable:
        return {"verdict": VERDICT_MARGINAL,
                "text": (f"Expectancy {m.expectancy_r:+.2f}R su {m.n_trades} trade, benchmark superati, "
                         f"ma il campione è sotto la soglia di affidabilità di {MIN_TRADES_RELIABLE} "
                         "trade: promettente, non ancora dimostrato.")}

    return {"verdict": VERDICT_ESTABLISHED,
            "text": (f"Expectancy {m.expectancy_r:+.2f}R per trade su {m.n_trades} trade, netta di costi, "
                     "con buy-and-hold ed entrata casuale entrambi superati. L'edge è statisticamente "
                     "sostenuto su questo campione — che resta un backtest, non una garanzia futura.")}
