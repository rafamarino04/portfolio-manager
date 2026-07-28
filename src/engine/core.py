"""
Bar loop event-driven — src/engine/core.py

Il cuore del motore. Processa le barre in ordine cronologico stretto,
come se arrivassero dal vivo, e per ogni bar esegue **sempre nello stesso
ordine**:

  1. Esegue gli ordini accodati dal bar precedente, all'**open** di questo
     bar (regola del next-bar-open).
  2. Aggiorna le posizioni aperte: MAE/MFE, e verifica se questo bar ha
     toccato stop o target (con la regola stop-first e la gestione dei gap).
  3. Valuta il segnale sul **close** di questo bar, usando solo dati fino
     a qui.
  4. Se il segnale è operabile, accoda un ordine per l'open del bar
     successivo.
  5. Valorizza l'equity a fine giornata (mark-to-market).

L'ordine dei passi non è arbitrario. Il passo 1 precede il 2 perché un
ordine accodato ieri si esegue in apertura, prima che il prezzo si muova
dentro la giornata. Il passo 3 segue il 2 perché il segnale nasce sul
close, che è l'ultimo dato del bar. E il passo 4 non può mai eseguire
nello stesso bar del 3: è precisamente lì che si annida il look-ahead
bias che fabbrica profitti inesistenti.

Perché event-driven e non vettoriale: un backtest vettoriale calcola i
segnali su tutto l'array di prezzi in una passata — è veloce, ma non
modella naturalmente stop/target, path-dependence ed esecuzione, e invita
il look-ahead bias. Il vantaggio decisivo dell'event-driven qui è il
**riuso del codice**: la stessa logica di segnale ed esecuzione guiderà
sia questo backtest sia il forward paper trader, ed è l'unico modo perché
un confronto tra i due sia attribuibile all'attrito reale del mercato
invece che a differenze di implementazione.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from src.engine import execution as ex
from src.engine import signals as sig
from src.engine.costs import CostModel
from src.engine.ledger import Ledger, OpenPosition
from src.engine.risk import RiskConfig, size_position

DEFAULT_INITIAL_EQUITY_EUR = 10_000.0


@dataclass
class PendingOrder:
    """Ordine generato sul close del bar `signal_date`, da eseguire
    all'open del bar successivo."""
    symbol: str
    direction: str
    stop: float
    target: float
    confidence: float | None
    signal_date: date
    signal_price: float     # il close su cui è nato il segnale, per diagnostica
    # Diagnostica: rapporto rischio/rendimento pianificato, se il sistema lo
    # riteneva sfavorevole, e da dove venivano stop e target. Nessuno di
    # questi campi condiziona l'esecuzione — servono solo a capire, dopo,
    # quali piani il motore ha effettivamente tradato.
    planned_rr: float | None = None
    rr_unfavorable: bool | None = None
    stop_source: str | None = None
    target_source: str | None = None


@dataclass
class BacktestConfig:
    horizon: str = "medio"
    initial_equity_eur: float = DEFAULT_INITIAL_EQUITY_EUR
    risk: RiskConfig = field(default_factory=RiskConfig)
    costs: CostModel = field(default_factory=CostModel)
    # Chiusura forzata delle posizioni ancora aperte all'ultimo bar: senza
    # di essa i trade aperti resterebbero fuori dalle statistiche e il
    # risultato sarebbe sistematicamente più bello del reale (le posizioni
    # in perdita tendono a restare aperte più a lungo).
    close_open_positions_at_end: bool = True
    # Non eseguire i piani che `trade_plan` segnala già come sfavorevoli
    # (rapporto rischio/rendimento sotto PLAN_MIN_ACCEPTABLE_RR).
    #
    # Prima il motore ignorava quel flag ed eseguiva comunque: il backtest
    # misurava così setup che il sistema stesso dichiara da scartare e che
    # nessuno prenderebbe guardandoli a schermo. Non è una taratura — la
    # soglia è quella già dichiarata in src/technical.py, non un valore
    # scelto osservando i risultati.
    skip_unfavorable_rr: bool = True


@dataclass
class BacktestResult:
    ledger: Ledger
    config: BacktestConfig
    symbols: list[str]
    start_date: date | None
    end_date: date | None
    n_signals_evaluated: int = 0
    n_signals_actionable: int = 0
    n_orders_rejected: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)


def _to_date(ts) -> date:
    return ts.date() if hasattr(ts, "date") else ts


def run_backtest(histories: dict[str, pd.DataFrame], config: BacktestConfig | None = None,
                  currencies: dict[str, str | None] | None = None,
                  start: date | None = None, end: date | None = None,
                  progress_callback=None) -> BacktestResult:
    """Esegue il backtest event-driven su più strumenti con equity condivisa.

    `histories`: {simbolo: DataFrame OHLCV con indice temporale ordinato}.
    `start`/`end` delimitano il periodo **operativo**: le barre precedenti
    a `start` restano disponibili come storico per il calcolo degli
    indicatori (warm-up), ma non generano trade. È così che si ottiene uno
    split in-sample/out-of-sample onesto: il segmento OOS vede lo stesso
    warm-up che avrebbe avuto dal vivo, senza però che il periodo di
    training produca trade nel conteggio.
    """
    config = config or BacktestConfig()
    currencies = currencies or {}

    histories = {s: h for s, h in histories.items() if h is not None and not h.empty}
    if not histories:
        return BacktestResult(ledger=Ledger(config.initial_equity_eur), config=config,
                               symbols=[], start_date=None, end_date=None,
                               diagnostics=["Nessuno storico disponibile per i simboli richiesti."])

    # Calendario unificato: l'unione ordinata di tutte le date disponibili.
    all_dates = sorted({_to_date(ts) for h in histories.values() for ts in h.index})
    if start:
        operative_dates = [d for d in all_dates if d >= start]
    else:
        operative_dates = list(all_dates)
    if end:
        operative_dates = [d for d in operative_dates if d <= end]
    if not operative_dates:
        return BacktestResult(ledger=Ledger(config.initial_equity_eur), config=config,
                               symbols=list(histories), start_date=None, end_date=None,
                               diagnostics=["Nessuna barra nel periodo operativo richiesto."])

    # Indicizzazione per data, per accesso O(1) dentro il loop.
    by_symbol: dict[str, dict[date, dict]] = {}
    ordered_dates: dict[str, list[date]] = {}
    for symbol, hist in histories.items():
        rows: dict[date, dict] = {}
        for ts, row in hist.iterrows():
            rows[_to_date(ts)] = {
                "open": float(row["Open"]), "high": float(row["High"]),
                "low": float(row["Low"]), "close": float(row["Close"]),
            }
        by_symbol[symbol] = rows
        ordered_dates[symbol] = sorted(rows.keys())

    ledger = Ledger(initial_equity_eur=config.initial_equity_eur)
    result = BacktestResult(ledger=ledger, config=config, symbols=sorted(histories),
                             start_date=operative_dates[0], end_date=operative_dates[-1])

    pending: dict[str, PendingOrder] = {}
    warmup = sig.warmup_bars(config.horizon)
    total = len(operative_dates)

    for i, current_date in enumerate(operative_dates):
        if progress_callback and (i % 10 == 0 or i == total - 1):
            progress_callback((i + 1) / total, current_date)

        # --- 1. Esecuzione degli ordini accodati ieri, all'open di oggi ---
        for symbol, order in list(pending.items()):
            bar = by_symbol[symbol].get(current_date)
            if bar is None:
                # Lo strumento non ha quotato oggi (festivo locale): l'ordine
                # non si esegue e decade, invece di essere trascinato a un
                # prezzo di un giorno diverso da quello previsto.
                del pending[symbol]
                result.n_orders_rejected += 1
                result.rejection_reasons["nessuna barra alla data di esecuzione"] = \
                    result.rejection_reasons.get("nessuna barra alla data di esecuzione", 0) + 1
                continue
            del pending[symbol]

            entry_price = ex.fill_price_next_open(bar["open"])
            if config.risk.one_position_per_symbol and ledger.has_position(symbol):
                result.n_orders_rejected += 1
                result.rejection_reasons["posizione già aperta sullo strumento"] = \
                    result.rejection_reasons.get("posizione già aperta sullo strumento", 0) + 1
                continue

            # Lo stop è quello pianificato ieri, ma l'ingresso reale è
            # l'open di oggi: R si ricalcola sull'ingresso effettivo, non
            # su quello ipotizzato. Se il gap in apertura ha già superato
            # lo stop, il trade non si apre affatto.
            invalid = ((order.direction == "long" and entry_price <= order.stop)
                       or (order.direction == "short" and entry_price >= order.stop))
            if invalid:
                result.n_orders_rejected += 1
                result.rejection_reasons["apertura oltre lo stop pianificato"] = \
                    result.rejection_reasons.get("apertura oltre lo stop pianificato", 0) + 1
                continue

            sizing = size_position(
                equity_eur=ledger.equity_eur, entry=entry_price, stop=order.stop,
                confidence=order.confidence, config=config.risk,
                open_gross_exposure_eur=ledger.open_gross_exposure_eur(),
                open_risk_eur=ledger.open_risk_eur(),
            )
            if not sizing.is_tradable:
                result.n_orders_rejected += 1
                reason = sizing.rejected_reason or "size non valida"
                result.rejection_reasons[reason] = result.rejection_reasons.get(reason, 0) + 1
                continue

            entry_cost = config.costs.entry_cost_eur(sizing.notional_eur, currencies.get(symbol))
            ledger.open_position(OpenPosition(
                symbol=symbol, direction=order.direction, entry_date=current_date,
                entry_price=entry_price, stop=order.stop, target=order.target,
                size=sizing.size, risk_per_unit=sizing.risk_per_unit,
                initial_risk_eur=sizing.initial_risk_eur, entry_cost_eur=entry_cost,
                confidence=order.confidence, leverage=sizing.leverage,
                currency=currencies.get(symbol), signal_date=order.signal_date,
                planned_rr=order.planned_rr, rr_unfavorable=order.rr_unfavorable,
                stop_source=order.stop_source, target_source=order.target_source,
            ))

        # --- 2. Aggiornamento e uscite sulle posizioni aperte ---
        for symbol in list(ledger.open_positions.keys()):
            bar = by_symbol[symbol].get(current_date)
            if bar is None:
                continue
            pos = ledger.open_positions[symbol]
            if current_date == pos.entry_date:
                # Il bar di ingresso non può anche stopparti sullo stesso
                # open a cui sei entrato: le escursioni partono da qui.
                pos.mae_r, pos.mfe_r = ex.update_excursions(
                    pos.direction, pos.entry_price, pos.risk_per_unit,
                    bar["high"], bar["low"], pos.mae_r, pos.mfe_r)
                exit_event = _intrabar_exit_on_entry_bar(pos, bar)
            else:
                pos.bars_held += 1
                pos.mae_r, pos.mfe_r = ex.update_excursions(
                    pos.direction, pos.entry_price, pos.risk_per_unit,
                    bar["high"], bar["low"], pos.mae_r, pos.mfe_r)
                exit_event = ex.resolve_exit(pos.direction, pos.stop, pos.target,
                                              bar["open"], bar["high"], bar["low"])
            if exit_event is not None:
                exit_notional = abs(pos.size * exit_event.price)
                exit_cost = config.costs.exit_cost_eur(exit_notional, pos.currency)
                ledger.close_position(symbol, current_date, exit_event.price,
                                       exit_event.reason, exit_cost, gapped=exit_event.gapped)

        # --- 3./4. Segnale sul close di oggi, ordine per l'open di domani ---
        for symbol, hist in histories.items():
            if current_date not in by_symbol[symbol]:
                continue
            if ledger.has_position(symbol) or symbol in pending:
                continue

            idx = _index_upto(ordered_dates[symbol], current_date)
            if idx < warmup:
                continue

            hist_to_date = hist.iloc[:idx + 1]
            plan = sig.generate_signal(symbol, hist_to_date, horizon=config.horizon)
            result.n_signals_evaluated += 1
            if not plan or plan.get("bias") not in ("long", "short"):
                continue
            if plan.get("stop") is None or plan.get("target") is None:
                continue

            if config.skip_unfavorable_rr and plan.get("rr_unfavorable"):
                result.n_orders_rejected += 1
                reason = "rapporto rischio/rendimento sfavorevole (scartato dal sistema)"
                result.rejection_reasons[reason] = result.rejection_reasons.get(reason, 0) + 1
                continue

            result.n_signals_actionable += 1
            pending[symbol] = PendingOrder(
                symbol=symbol, direction=plan["bias"], stop=float(plan["stop"]),
                target=float(plan["target"]), confidence=plan.get("confidence"),
                signal_date=current_date, signal_price=float(plan["entry"]),
                planned_rr=plan.get("risk_reward"), rr_unfavorable=plan.get("rr_unfavorable"),
                stop_source=plan.get("stop_source"), target_source=plan.get("target_source"),
            )

        # --- 5. Mark-to-market di fine giornata ---
        closes = {s: by_symbol[s][current_date]["close"]
                  for s in ledger.open_positions if current_date in by_symbol[s]}
        ledger.mark_to_market(current_date, closes)

    # --- Chiusura forzata delle posizioni residue ---
    if config.close_open_positions_at_end and ledger.open_positions:
        last_date = operative_dates[-1]
        for symbol in list(ledger.open_positions.keys()):
            pos = ledger.open_positions[symbol]
            bar = by_symbol[symbol].get(last_date)
            price = bar["close"] if bar else pos.entry_price
            exit_cost = config.costs.exit_cost_eur(abs(pos.size * price), pos.currency)
            ledger.close_position(symbol, last_date, price, "chiusura_forzata", exit_cost)
        result.diagnostics.append(
            "Le posizioni ancora aperte all'ultimo bar sono state chiuse al close: escluderle "
            "avrebbe reso i risultati sistematicamente migliori del reale."
        )

    return result


def _intrabar_exit_on_entry_bar(pos: OpenPosition, bar: dict) -> "ex.ExitEvent | None":
    """Uscita nello stesso bar dell'ingresso.

    Va trattata a parte perché l'ingresso è avvenuto all'**open**: non ha
    senso applicare qui la logica di gap sull'apertura (si è entrati
    proprio a quel prezzo). Resta però valida la regola conservativa: se
    il resto del bar contiene sia lo stop sia il target, vince lo stop."""
    if pos.direction == "long":
        hit_stop = bar["low"] <= pos.stop
        hit_target = bar["high"] >= pos.target
    else:
        hit_stop = bar["high"] >= pos.stop
        hit_target = bar["low"] <= pos.target
    if hit_stop:
        return ex.ExitEvent(price=pos.stop, reason="stop")
    if hit_target:
        return ex.ExitEvent(price=pos.target, reason="target")
    return None


def _index_upto(dates: list[date], target: date) -> int:
    """Posizione di `target` nella lista ordinata di date dello strumento."""
    lo, hi = 0, len(dates) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if dates[mid] == target:
            return mid
        if dates[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return lo - 1
