"""
Benchmark obbligatori — src/engine/benchmarks.py

Nessun backtest va letto da solo. Due confronti sono obbligatori e
rispondono a due domande diverse, entrambe capaci di demolire un
risultato che sembrava buono.

**1. Buy-and-hold degli stessi strumenti, sullo stesso periodo.** È il
test onesto di se il *timing* abbia aggiunto qualcosa rispetto al
semplice stare investiti. Molte strategie ottimizzate perdono contro il
buy-and-hold fuori campione: se il mercato è salito e tu hai guadagnato
meno restando dentro e fuori, il tuo segnale ha distrutto valore.

**2. Entrata casuale, con la stessa frequenza di trade e identiche regole
di stop/target/sizing.** È il test di se l'edge venga dal *segnale* o
soltanto dalle uscite e dal money management. Nell'esperimento di Tom
Basso riportato da Van Tharp — entrate a testa o croce su 10 mercati, con
stop a 3 volte una media dell'ATR e rischio all'1% — il sistema "ha fatto
soldi il 100% delle volte", con una reliability del 38%, "che è circa la
media per un sistema trend-following". La lezione è netta: buone uscite e
un sizing corretto rendono profittevoli persino entrate casuali. Un
segnale si guadagna il posto solo se batte l'entrata casuale a parità di
tutto il resto.

Il benchmark casuale si esegue come Monte Carlo (molte ripetizioni) e si
riporta **in quale percentile** cade la strategia reale: un singolo run
casuale non direbbe nulla, perché la varianza tra run è ampia.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from src.engine.costs import CostModel
from src.engine.ledger import Ledger, OpenPosition
from src.engine.risk import RiskConfig, size_position
from src.engine import execution as ex

DEFAULT_MONTE_CARLO_RUNS = 200


@dataclass
class BuyAndHoldResult:
    total_return_pct: float | None
    final_equity_eur: float
    equity_curve: list[tuple[date, float]]
    per_symbol_return_pct: dict[str, float]


def buy_and_hold(histories: dict[str, pd.DataFrame], initial_equity_eur: float,
                  start: date | None = None, end: date | None = None,
                  costs: CostModel | None = None,
                  currencies: dict[str, str | None] | None = None) -> BuyAndHoldResult:
    """Buy-and-hold equipesato sugli stessi strumenti, netto dei costi di
    ingresso e uscita (una sola andata e ritorno per strumento).

    Applicare i costi anche qui è necessario per un confronto equo: la
    strategia attiva ne paga molti, il buy-and-hold pochissimi, ed è
    proprio questa asimmetria uno dei motivi per cui il buy-and-hold è
    difficile da battere."""
    costs = costs or CostModel()
    currencies = currencies or {}

    frames = {}
    for symbol, hist in histories.items():
        if hist is None or hist.empty:
            continue
        h = hist.copy()
        h.index = [ts.date() if hasattr(ts, "date") else ts for ts in h.index]
        if start:
            h = h[[d >= start for d in h.index]]
        if end:
            h = h[[d <= end for d in h.index]]
        if not h.empty:
            frames[symbol] = h
    if not frames:
        return BuyAndHoldResult(None, initial_equity_eur, [], {})

    allocation = initial_equity_eur / len(frames)
    holdings: dict[str, float] = {}
    per_symbol_return: dict[str, float] = {}
    cash_after_entry = 0.0

    for symbol, h in frames.items():
        entry_price = float(h["Close"].iloc[0])
        entry_cost = costs.entry_cost_eur(allocation, currencies.get(symbol))
        invested = max(0.0, allocation - entry_cost)
        holdings[symbol] = invested / entry_price if entry_price > 0 else 0.0
        cash_after_entry += 0.0
        exit_price = float(h["Close"].iloc[-1])
        per_symbol_return[symbol] = (exit_price / entry_price - 1) * 100 if entry_price else 0.0

    all_dates = sorted({d for h in frames.values() for d in h.index})
    curve: list[tuple[date, float]] = []
    last_price: dict[str, float] = {}
    for d in all_dates:
        value = 0.0
        for symbol, h in frames.items():
            if d in h.index:
                last_price[symbol] = float(h.loc[d, "Close"])
            price = last_price.get(symbol)
            if price is not None:
                value += holdings[symbol] * price
        curve.append((d, value))

    # Costo di uscita, pagato una sola volta a fine periodo.
    final_value = curve[-1][1] if curve else initial_equity_eur
    exit_costs = sum(costs.exit_cost_eur(holdings[s] * last_price.get(s, 0.0), currencies.get(s))
                     for s in frames)
    final_value -= exit_costs
    if curve:
        curve[-1] = (curve[-1][0], final_value)

    total_return = (final_value / initial_equity_eur - 1) * 100 if initial_equity_eur else None
    return BuyAndHoldResult(total_return, final_value, curve, per_symbol_return)


@dataclass
class RandomEntryResult:
    runs: int
    returns_pct: list[float]
    expectancy_r: list[float]
    median_return_pct: float | None
    p95_return_pct: float | None
    strategy_percentile: float | None = None

    def beats(self, strategy_return_pct: float | None) -> bool | None:
        """La strategia batte il benchmark casuale solo se sta sopra la
        **mediana** dei run casuali. Non è un criterio severo — è il
        minimo: stare sotto la mediana significa che una monetina, con le
        stesse uscite e lo stesso sizing, avrebbe fatto meglio la metà
        delle volte."""
        if strategy_return_pct is None or self.median_return_pct is None:
            return None
        return strategy_return_pct > self.median_return_pct


def random_entry_monte_carlo(histories: dict[str, pd.DataFrame], n_trades_target: int,
                              initial_equity_eur: float, atr_by_symbol: dict[str, pd.Series],
                              risk: RiskConfig | None = None, costs: CostModel | None = None,
                              currencies: dict[str, str | None] | None = None,
                              start: date | None = None, end: date | None = None,
                              runs: int = DEFAULT_MONTE_CARLO_RUNS, seed: int = 42,
                              stop_atr_mult: float = 2.0,
                              target_atr_mult: float = 4.0,
                              progress_callback=None) -> RandomEntryResult:
    """Monte Carlo di entrate casuali con la stessa frequenza della
    strategia e identiche regole di uscita e sizing.

    Le entrate sono date pescate a caso (direzione long/short a testa o
    croce), stop e target a multipli di ATR — l'impianto dell'esperimento
    di Basso. Tutto il resto (fill al next-bar-open, stop-first, gap,
    costi, sizing a frazione fissa) è identico alla strategia reale,
    perché il confronto abbia senso: l'unica variabile che cambia è
    **da dove viene il segnale**."""
    risk = risk or RiskConfig()
    costs = costs or CostModel()
    currencies = currencies or {}
    rng = np.random.default_rng(seed)

    # --- Precalcolo, una volta sola ------------------------------------
    # Il ciclo interno gira runs x n_trades volte (facilmente centinaia di
    # migliaia): qualunque lavoro ripetuto lì dentro domina il tempo totale.
    # In particolare l'ATR va indicizzato per posizione una volta sola —
    # ricostruire un dizionario sull'intera serie ad ogni trade simulato
    # costava ~2 ms a chiamata e rendeva il benchmark più lento dell'intero
    # backtest che doveva validare.
    data: dict[str, dict] = {}
    for symbol, hist in histories.items():
        if hist is None or hist.empty:
            continue
        dates = np.array([ts.date() if hasattr(ts, "date") else ts for ts in hist.index],
                          dtype=object)
        mask = np.ones(len(dates), dtype=bool)
        if start:
            mask &= np.array([d >= start for d in dates], dtype=bool)
        if end:
            mask &= np.array([d <= end for d in dates], dtype=bool)
        if mask.sum() <= 5:
            continue

        atr_series = atr_by_symbol.get(symbol)
        if atr_series is None:
            continue
        atr_values = pd.to_numeric(pd.Series(atr_series).reindex(hist.index),
                                    errors="coerce").to_numpy(dtype=float)

        data[symbol] = {
            "dates": dates[mask],
            "open": hist["Open"].to_numpy(dtype=float)[mask],
            "high": hist["High"].to_numpy(dtype=float)[mask],
            "low": hist["Low"].to_numpy(dtype=float)[mask],
            "close": hist["Close"].to_numpy(dtype=float)[mask],
            "atr": atr_values[mask],
            "currency": currencies.get(symbol),
        }

    if not data or n_trades_target <= 0:
        return RandomEntryResult(0, [], [], None, None)

    symbols = list(data)
    returns_pct: list[float] = []
    expectancies: list[float] = []

    for run_idx in range(runs):
        ledger = Ledger(initial_equity_eur=initial_equity_eur)
        for _ in range(n_trades_target):
            symbol = symbols[rng.integers(0, len(symbols))]
            d = data[symbol]
            n_bars = len(d["close"])
            if n_bars < 3:
                continue

            # L'ingresso non può cadere sull'ultimo bar: serve almeno un
            # bar successivo su cui eseguire il fill al next-open.
            i = int(rng.integers(0, n_bars - 2))
            atr_val = d["atr"][i]
            if not np.isfinite(atr_val) or atr_val <= 0:
                continue

            entry_price = d["open"][i + 1]
            direction = "long" if rng.random() < 0.5 else "short"
            if direction == "long":
                stop = entry_price - stop_atr_mult * atr_val
                target = entry_price + target_atr_mult * atr_val
            else:
                stop = entry_price + stop_atr_mult * atr_val
                target = entry_price - target_atr_mult * atr_val

            sizing = size_position(ledger.equity_eur, entry_price, stop, None, risk,
                                    ledger.open_gross_exposure_eur(), ledger.open_risk_eur())
            if not sizing.is_tradable:
                continue

            entry_cost = costs.entry_cost_eur(sizing.notional_eur, d["currency"])
            ledger.open_position(OpenPosition(
                symbol=symbol, direction=direction, entry_date=d["dates"][i + 1],
                entry_price=entry_price, stop=stop, target=target, size=sizing.size,
                risk_per_unit=sizing.risk_per_unit, initial_risk_eur=sizing.initial_risk_eur,
                entry_cost_eur=entry_cost, confidence=None, leverage=sizing.leverage,
                currency=d["currency"], signal_date=d["dates"][i],
            ))

            # Percorre i bar successivi con le stesse regole di uscita del
            # motore reale (stop-first, gap): stessa funzione, solo su array
            # invece che su righe di DataFrame.
            opens, highs, lows = d["open"], d["high"], d["low"]
            exit_done = False
            for j in range(i + 2, n_bars):
                event = ex.resolve_exit(direction, stop, target,
                                         opens[j], highs[j], lows[j])
                if event is not None:
                    notional = abs(sizing.size * event.price)
                    ledger.close_position(symbol, d["dates"][j], event.price, event.reason,
                                           costs.exit_cost_eur(notional, d["currency"]),
                                           gapped=event.gapped)
                    exit_done = True
                    break
            if not exit_done:
                price = float(d["close"][-1])
                ledger.close_position(symbol, d["dates"][-1], price, "chiusura_forzata",
                                       costs.exit_cost_eur(abs(sizing.size * price), d["currency"]))

        final_equity = ledger.equity_eur
        returns_pct.append((final_equity / initial_equity_eur - 1) * 100)
        if ledger.closed_trades:
            expectancies.append(float(np.mean([t.net_r for t in ledger.closed_trades])))

        if progress_callback:
            progress_callback((run_idx + 1) / runs)

    if not returns_pct:
        return RandomEntryResult(0, [], [], None, None)

    return RandomEntryResult(
        runs=runs, returns_pct=returns_pct, expectancy_r=expectancies,
        median_return_pct=float(np.median(returns_pct)),
        p95_return_pct=float(np.percentile(returns_pct, 95)),
    )


def percentile_of(value: float | None, distribution: list[float]) -> float | None:
    """In quale percentile della distribuzione casuale cade la strategia.

    È il numero che rende il confronto leggibile: "sopra il 50%" è appena
    sufficiente, "sopra il 95%" significa che il segnale fa qualcosa che
    il caso non riproduce facilmente."""
    if value is None or not distribution:
        return None
    arr = np.asarray(distribution, dtype=float)
    return float((arr < value).mean() * 100)
