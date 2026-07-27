"""
Orchestrazione del backtest — src/engine/runner.py

Wrapper sottile sopra il motore: scarica i dati, esegue lo split
in-sample / out-of-sample, lancia il bar loop e i due benchmark
obbligatori, calcola le metriche e costruisce il verdetto.

**Lo split in-sample / out-of-sample.** Si tiene fuori almeno un terzo
della storia come out-of-sample (raccomandazione di Ernie Chan). Il
segmento OOS riceve comunque tutto lo storico precedente come warm-up per
gli indicatori — altrimenti i primi mesi opererebbero con medie non
ancora formate e il confronto sarebbe distorto — ma i trade generati nel
periodo in-sample non entrano nelle sue statistiche.

**La trappola da cui questo modulo non può proteggerti.** Rieseguire il
backtest cambiando parametri finché l'out-of-sample non migliora converte
silenziosamente l'OOS in in-sample e garantisce overfitting. Per questo
il risultato riporta sempre `configurations_tried`: un conteggio delle
esecuzioni fatte in sessione, da leggere come "quante volte ho pescato
dal mazzo prima di trovare questo risultato". Più è alto, più il miglior
risultato è inflazionato dal caso.

**Perché OOS ≥ in-sample è un campanello d'allarme, non un trionfo.** La
letteratura è concorde nel quantificare il decadimento fuori campione:
i rendimenti calano di circa un quarto fuori campione, lo Sharpe di circa
un terzo (mediana ~44%), e su strategie commerciali si è misurato un
crollo mediano del 73% tra backtest e live. Un OOS migliore
dell'in-sample, quindi, di norma segnala una contaminazione tra i due
insiemi piuttosto che una strategia eccezionale.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from src import data_provider as dp
from src import technical as tech
from src.engine import benchmarks as bm
from src.engine import metrics as mt
from src.engine import signals as sig
from src.engine.core import BacktestConfig, BacktestResult, run_backtest

# Frazione di storia riservata all'out-of-sample.
DEFAULT_OOS_FRACTION = 1 / 3

# Storico da scaricare: serve a coprire più regimi di mercato, non solo
# l'ultimo ciclo. Uno Sharpe alto su un unico regime rialzista non dice
# quasi nulla sulla robustezza.
DEFAULT_HISTORY_PERIOD = "10y"


@dataclass
class SegmentResult:
    label: str
    backtest: BacktestResult
    metrics: mt.PerformanceMetrics
    buy_and_hold: bm.BuyAndHoldResult | None = None
    random_entry: bm.RandomEntryResult | None = None
    beats_buy_and_hold: bool | None = None
    beats_random: bool | None = None
    random_percentile: float | None = None
    verdict: dict = field(default_factory=dict)


@dataclass
class FullBacktestReport:
    symbols: list[str]
    horizon: str
    in_sample: SegmentResult | None
    out_of_sample: SegmentResult | None
    split_date: date | None
    history_start: date | None
    history_end: date | None
    cost_description: str = ""
    diagnostics: list[str] = field(default_factory=list)
    configurations_tried: int = 1


def load_histories(symbols: list[str], period: str = DEFAULT_HISTORY_PERIOD
                    ) -> tuple[dict[str, pd.DataFrame], dict[str, str | None], list[str]]:
    """Scarica gli storici daily e le valute (per sapere a chi applicare
    il costo FX). Ritorna anche la lista dei simboli scartati, che va
    mostrata: un universo silenziosamente ridotto cambia i risultati."""
    histories: dict[str, pd.DataFrame] = {}
    currencies: dict[str, str | None] = {}
    skipped: list[str] = []

    for symbol in symbols:
        try:
            hist = dp.get_history(symbol, period=period, interval="1d")
        except Exception:
            hist = None
        if hist is None or hist.empty or len(hist) < 300:
            skipped.append(symbol)
            continue
        histories[symbol] = hist
        try:
            currencies[symbol] = (dp.get_ticker(symbol).info or {}).get("currency")
        except Exception:
            currencies[symbol] = None
    return histories, currencies, skipped


def compute_split_date(histories: dict[str, pd.DataFrame],
                        oos_fraction: float = DEFAULT_OOS_FRACTION) -> date | None:
    """Data che separa in-sample e out-of-sample, calcolata sul calendario
    unificato di tutti gli strumenti."""
    all_dates = sorted({ts.date() if hasattr(ts, "date") else ts
                        for h in histories.values() for ts in h.index})
    if len(all_dates) < 50:
        return None
    idx = int(len(all_dates) * (1 - oos_fraction))
    return all_dates[idx]


def _atr_series_by_symbol(histories: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
    """ATR per il benchmark a entrata casuale: stessa funzione usata dal
    motore tecnico, così stop e target casuali hanno la stessa scala di
    volatilità di quelli reali."""
    return {s: tech.atr(h, period=14) for s, h in histories.items()}


def _run_segment(label: str, histories: dict[str, pd.DataFrame], currencies: dict[str, str | None],
                  config: BacktestConfig, start: date | None, end: date | None,
                  monte_carlo_runs: int, progress_callback=None) -> SegmentResult:
    result = run_backtest(histories, config=config, currencies=currencies,
                           start=start, end=end, progress_callback=progress_callback)
    metrics = mt.compute_metrics(result.ledger.closed_trades, result.ledger.equity_curve,
                                  config.initial_equity_eur, label=label)

    bh = bm.buy_and_hold(histories, config.initial_equity_eur, start=start, end=end,
                          costs=config.costs, currencies=currencies)

    beats_bh = None
    if metrics.total_return_pct is not None and bh.total_return_pct is not None:
        beats_bh = metrics.total_return_pct > bh.total_return_pct

    random_result = None
    beats_random = None
    percentile = None
    if metrics.n_trades > 0:
        random_result = bm.random_entry_monte_carlo(
            histories, n_trades_target=metrics.n_trades,
            initial_equity_eur=config.initial_equity_eur,
            atr_by_symbol=_atr_series_by_symbol(histories),
            risk=config.risk, costs=config.costs, currencies=currencies,
            start=start, end=end, runs=monte_carlo_runs,
        )
        beats_random = random_result.beats(metrics.total_return_pct)
        percentile = bm.percentile_of(metrics.total_return_pct, random_result.returns_pct)

    verdict = mt.build_verdict(metrics, beats_bh, beats_random)
    return SegmentResult(label=label, backtest=result, metrics=metrics, buy_and_hold=bh,
                          random_entry=random_result, beats_buy_and_hold=beats_bh,
                          beats_random=beats_random, random_percentile=percentile,
                          verdict=verdict)


def run_full_backtest(symbols: list[str], config: BacktestConfig | None = None,
                       period: str = DEFAULT_HISTORY_PERIOD,
                       oos_fraction: float = DEFAULT_OOS_FRACTION,
                       monte_carlo_runs: int = bm.DEFAULT_MONTE_CARLO_RUNS,
                       run_out_of_sample: bool = True,
                       configurations_tried: int = 1,
                       progress_callback=None) -> FullBacktestReport:
    """Backtest completo con split in-sample/out-of-sample e benchmark.

    `run_out_of_sample=False` permette di restare deliberatamente sullo
    Stage 1 della specifica (solo in-sample): l'OOS andrebbe guardato una
    volta sola, dopo aver congelato i parametri, e ogni sbirciata
    aggiuntiva lo consuma."""
    config = config or BacktestConfig()
    if config.horizon not in sig.SUPPORTED_HORIZONS:
        raise ValueError(
            f"Orizzonte '{config.horizon}' non supportato dal motore di backtest. "
            f"Supportati: {', '.join(sig.SUPPORTED_HORIZONS)} (il lungo termine usa barre "
            "settimanali e richiederebbe un ricampionamento dedicato)."
        )

    histories, currencies, skipped = load_histories(symbols, period=period)
    diagnostics: list[str] = []
    if skipped:
        diagnostics.append(
            f"Esclusi per storico insufficiente (<300 barre daily): {', '.join(skipped)}."
        )
    if not histories:
        return FullBacktestReport(symbols=symbols, horizon=config.horizon, in_sample=None,
                                   out_of_sample=None, split_date=None, history_start=None,
                                   history_end=None, cost_description=config.costs.describe(),
                                   diagnostics=diagnostics + ["Nessuno storico utilizzabile."],
                                   configurations_tried=configurations_tried)

    all_dates = sorted({ts.date() if hasattr(ts, "date") else ts
                        for h in histories.values() for ts in h.index})
    split = compute_split_date(histories, oos_fraction)

    warmup = sig.warmup_bars(config.horizon)
    lookback = sig.HORIZON_LOOKBACK_BARS[config.horizon]
    first_operative = all_dates[min(len(all_dates) - 1, max(warmup, lookback))]

    in_sample = _run_segment("In-sample", histories, currencies, config,
                              start=first_operative, end=split,
                              monte_carlo_runs=monte_carlo_runs,
                              progress_callback=progress_callback)

    out_of_sample = None
    if run_out_of_sample and split is not None:
        out_of_sample = _run_segment("Out-of-sample", histories, currencies, config,
                                      start=split, end=None,
                                      monte_carlo_runs=monte_carlo_runs,
                                      progress_callback=progress_callback)

    diagnostics.extend(in_sample.backtest.diagnostics)
    if out_of_sample:
        diagnostics.extend(out_of_sample.backtest.diagnostics)
        contamination = _check_contamination(in_sample.metrics, out_of_sample.metrics)
        if contamination:
            diagnostics.append(contamination)

    return FullBacktestReport(
        symbols=sorted(histories), horizon=config.horizon,
        in_sample=in_sample, out_of_sample=out_of_sample, split_date=split,
        history_start=all_dates[0], history_end=all_dates[-1],
        cost_description=config.costs.describe(),
        diagnostics=diagnostics, configurations_tried=configurations_tried,
    )


def _check_contamination(is_metrics: mt.PerformanceMetrics,
                          oos_metrics: mt.PerformanceMetrics) -> str | None:
    """Segnala il caso in cui l'out-of-sample risulti migliore
    dell'in-sample, che va trattato come sospetto di contaminazione e non
    come conferma della bontà della strategia."""
    if is_metrics.expectancy_r is None or oos_metrics.expectancy_r is None:
        return None
    if oos_metrics.n_trades == 0 or is_metrics.n_trades == 0:
        return None
    if oos_metrics.expectancy_r > is_metrics.expectancy_r:
        return (
            f"L'out-of-sample ({oos_metrics.expectancy_r:+.2f}R per trade) risulta MIGLIORE "
            f"dell'in-sample ({is_metrics.expectancy_r:+.2f}R). Il decadimento fuori campione è la "
            "norma, non l'eccezione: un OOS migliore va letto come sospetto di contaminazione tra i "
            "due insiemi (o come effetto di un campione piccolo), non come conferma della strategia."
        )
    return None
