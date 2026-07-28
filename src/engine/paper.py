"""
Forward paper trading — src/engine/paper.py

Stage 3 di BACKTEST AND FORWARD.pdf. È la validazione più vicina al reale
che esista senza rischiare denaro: i dati arrivano barra per barra in
tempo reale, quindi non c'è senno di poi né selezione a posteriori. Il
suo limite è la lentezza — un sistema daily accumula trade con
lentezza — ma due anni di forward valgono più di un backtest ventennale
proprio perché il record non può essere stato contaminato.

**Riuso, non riscrittura.** Questo modulo non reimplementa nulla: importa
`signals`, `risk`, `costs` ed `execution` dal motore di backtest. È
l'intero motivo per cui il motore è event-driven: se il forward avesse un
codice suo, una differenza di risultato tra backtest e paper non sarebbe
attribuibile — non sapresti se è attrito reale del mercato o una
divergenza di implementazione.

**Momento di esecuzione (scelta dichiarata).** Il fill avviene al
**prezzo corrente** nel momento in cui il segnale scatta, non
all'apertura della seduta successiva come nel backtest. È una scelta
esplicita: corrisponde a come si opera davvero guardando un segnale a
mercato aperto. Ha però una conseguenza che va tenuta presente leggendo i
risultati — una differenza di expectancy tra backtest e paper non è più
attribuibile con certezza al solo attrito del mercato, perché anche la
regola di esecuzione è diversa.

Per non perdere del tutto l'attribuzione, ogni fill registra **anche
l'apertura della seduta in corso** (`reference_open_price`), che è
esattamente il prezzo a cui il backtest sarebbe entrato. La differenza tra
i due misura il costo (o il guadagno) del ritardo di esecuzione, ed è
riportata in pagina. Non è un secondo registro parallelo: è una colonna
diagnostica sullo stesso trade.

**Il segnale usa solo barre COMPLETE.** Durante la seduta yfinance
restituisce anche la barra parziale del giorno in corso, il cui "close"
non è un close ma il prezzo dell'istante. Calcolare il segnale su quella
barra darebbe un valore che cambia di minuto in minuto e che non
corrisponde a nulla di ciò che il backtest ha testato. Il troncamento
alle sole barre chiuse è quindi una condizione di correttezza, non
un'ottimizzazione.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field

import pandas as pd

from src import data_provider as dp
from src.engine import execution as ex
from src.engine import signals as sig
from src.engine.costs import CostModel
from src.engine.risk import RiskConfig, size_position

OPEN_POSITIONS_COLUMNS = [
    "symbol", "direction", "signal_date", "entry_date", "entry_price",
    "reference_open_price", "stop", "target", "size", "risk_per_unit",
    "initial_risk_eur", "entry_cost_eur", "confidence", "leverage", "currency",
    "mae_r", "mfe_r", "bars_held", "last_processed_date",
]

CLOSED_TRADES_COLUMNS = [
    "symbol", "direction", "signal_date", "entry_date", "entry_price",
    "reference_open_price", "exit_date", "exit_price", "exit_reason",
    "size", "risk_per_unit", "initial_risk_eur", "confidence", "leverage",
    "gross_pnl_eur", "costs_eur", "net_pnl_eur", "gross_r", "net_r",
    "mae_r", "mfe_r", "bars_held", "gapped_exit", "execution_delay_r",
]


@dataclass
class PaperConfig:
    """Parametri congelati del forward. La specifica è esplicita: vanno
    fissati PRIMA di iniziare e la data di congelamento va registrata,
    perché ritoccarli mentre il forward gira lo trasformerebbe in un
    ennesimo backtest ottimizzato."""
    horizon: str = "medio"
    initial_equity_eur: float = 10_000.0
    risk_pct: float = 0.75
    # Stage 3: si opera SEMPRE a 1.0x. La leva si sblocca solo dopo che la
    # calibrazione (Stage 4) ha dimostrato che la confidenza vale quello
    # che promette.
    leverage_enabled: bool = False
    order_fee_eur: float = 1.0
    fx_cost_pct_per_leg: float = 0.5
    slippage_bps_per_side: float = 5.0
    # Stessa regola del backtest: non si opera sui piani che il sistema
    # stesso segnala come sfavorevoli. Backtest e forward DEVONO applicare
    # gli stessi filtri, altrimenti il confronto tra i due — che è l'intero
    # scopo del forward — misura due strategie diverse.
    skip_unfavorable_rr: bool = True
    frozen_at: str = ""

    def risk_config(self) -> RiskConfig:
        return RiskConfig(risk_pct=self.risk_pct, leverage_enabled=self.leverage_enabled)

    def cost_model(self) -> CostModel:
        return CostModel(order_fee_eur=self.order_fee_eur,
                          fx_cost_pct_per_leg=self.fx_cost_pct_per_leg,
                          slippage_bps_per_side=self.slippage_bps_per_side)


@dataclass
class PaperState:
    open_positions: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(columns=OPEN_POSITIONS_COLUMNS))
    closed_trades: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(columns=CLOSED_TRADES_COLUMNS))
    equity_eur: float = 0.0
    started_at: str = ""
    last_run_at: str = ""

    def has_position(self, symbol: str) -> bool:
        if self.open_positions.empty:
            return False
        return symbol.upper() in self.open_positions["symbol"].astype(str).str.upper().values

    def open_risk_eur(self) -> float:
        if self.open_positions.empty:
            return 0.0
        return float(pd.to_numeric(self.open_positions["initial_risk_eur"], errors="coerce").fillna(0).sum())

    def open_gross_exposure_eur(self) -> float:
        if self.open_positions.empty:
            return 0.0
        size = pd.to_numeric(self.open_positions["size"], errors="coerce").fillna(0)
        price = pd.to_numeric(self.open_positions["entry_price"], errors="coerce").fillna(0)
        return float((size * price).abs().sum())


@dataclass
class StepEvent:
    kind: str          # "apertura" | "chiusura" | "scarto"
    symbol: str
    message: str


def _completed_bars(hist: pd.DataFrame, today: dt.date) -> pd.DataFrame:
    """Elimina la barra del giorno in corso.

    A mercato aperto yfinance include la seduta corrente, il cui "Close" è
    solo il prezzo dell'istante. Usarla per il segnale produrrebbe un
    valore che cambia durante la giornata e che non corrisponde a nulla di
    ciò che il backtest ha testato."""
    if hist is None or hist.empty:
        return hist
    dates = [ts.date() if hasattr(ts, "date") else ts for ts in hist.index]
    mask = [d < today for d in dates]
    return hist.loc[mask]


def _bars_after(hist: pd.DataFrame, after: dt.date | None, today: dt.date) -> list[tuple[dt.date, dict]]:
    """Barre complete successive a `after`, in ordine cronologico."""
    out = []
    for ts, row in hist.iterrows():
        d = ts.date() if hasattr(ts, "date") else ts
        if d >= today:
            continue
        if after is not None and d <= after:
            continue
        out.append((d, {"open": float(row["Open"]), "high": float(row["High"]),
                        "low": float(row["Low"]), "close": float(row["Close"])}))
    return out


def _as_date(value) -> dt.date | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    try:
        return pd.to_datetime(value).date()
    except Exception:
        return None


def step(symbols: list[str], state: PaperState, config: PaperConfig,
          today: dt.date | None = None, now_iso: str | None = None,
          price_fn=None, history_fn=None, currency_fn=None) -> tuple[PaperState, list[StepEvent]]:
    """Avanza il paper trading di un passo (una esecuzione del job).

    Ordine delle operazioni, deliberato:
      1. Aggiorna le posizioni aperte sulle barre COMPLETE non ancora
         processate, con le stesse regole del backtest (stop-first, gap).
      2. Controlla il prezzo corrente per un tocco intraday di stop/target.
      3. Valuta i segnali sulle barre complete e apre al prezzo corrente.

    Le uscite vengono prima delle entrate perché una posizione chiusa oggi
    libera il capitale e i cap di rischio per un'eventuale nuova entrata
    sullo stesso simbolo, esattamente come accadrebbe operando.

    Le funzioni `price_fn`/`history_fn`/`currency_fn` sono iniettabili per
    poter testare il motore senza rete."""
    today = today or dt.date.today()
    now_iso = now_iso or dt.datetime.now().isoformat(timespec="seconds")
    price_fn = price_fn or dp.get_current_price
    history_fn = history_fn or (lambda s: dp.get_history(s, period="2y", interval="1d"))
    currency_fn = currency_fn or (lambda s: (dp.get_ticker(s).info or {}).get("currency"))

    risk_cfg = config.risk_config()
    costs = config.cost_model()
    events: list[StepEvent] = []

    if not state.started_at:
        state.started_at = now_iso
        state.equity_eur = config.initial_equity_eur

    histories: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        try:
            hist = history_fn(symbol)
        except Exception:
            hist = None
        if hist is not None and not hist.empty:
            histories[symbol] = _completed_bars(hist, today)

    # --- 1./2. Aggiornamento e uscite -------------------------------------
    state = _process_open_positions(state, histories, config, costs, today, price_fn, events)

    # --- 3. Nuovi segnali --------------------------------------------------
    for symbol in symbols:
        hist = histories.get(symbol)
        if hist is None or hist.empty:
            continue
        if state.has_position(symbol):
            continue
        if len(hist) < sig.warmup_bars(config.horizon):
            continue

        plan = sig.generate_signal(symbol, hist, horizon=config.horizon)
        if not plan or plan.get("bias") not in ("long", "short"):
            continue
        if plan.get("stop") is None or plan.get("target") is None:
            continue
        if config.skip_unfavorable_rr and plan.get("rr_unfavorable"):
            events.append(StepEvent(
                "scarto", symbol,
                f"Rapporto rischio/rendimento sfavorevole ({plan.get('risk_reward')}): "
                "il sistema stesso scarta questo piano."))
            continue

        price = price_fn(symbol)
        if not price or price <= 0:
            events.append(StepEvent("scarto", symbol, "Prezzo corrente non disponibile: nessuna apertura."))
            continue

        stop = float(plan["stop"])
        target = float(plan["target"])
        direction = plan["bias"]

        # Se il prezzo corrente ha già superato lo stop pianificato il trade
        # non ha rischio definito: non si apre, esattamente come nel backtest.
        if ((direction == "long" and price <= stop) or (direction == "short" and price >= stop)):
            events.append(StepEvent(
                "scarto", symbol,
                f"Prezzo corrente {price:.2f} già oltre lo stop pianificato {stop:.2f}: nessuna apertura."))
            continue

        sizing = size_position(state.equity_eur, price, stop, plan.get("confidence"), risk_cfg,
                                state.open_gross_exposure_eur(), state.open_risk_eur())
        if not sizing.is_tradable:
            events.append(StepEvent("scarto", symbol, f"Nessuna apertura: {sizing.rejected_reason}."))
            continue

        currency = currency_fn(symbol)
        entry_cost = costs.entry_cost_eur(sizing.notional_eur, currency)
        signal_date = _as_date(hist.index[-1])

        # Apertura della seduta in corso: è il prezzo a cui il backtest
        # sarebbe entrato. Serve a misurare il costo del ritardo di
        # esecuzione, non a costruire un secondo registro.
        reference_open = _todays_open(symbol, today, history_fn)

        row = {
            "symbol": symbol, "direction": direction, "signal_date": signal_date,
            "entry_date": today, "entry_price": price, "reference_open_price": reference_open,
            "stop": stop, "target": target, "size": sizing.size,
            "risk_per_unit": sizing.risk_per_unit, "initial_risk_eur": sizing.initial_risk_eur,
            "entry_cost_eur": entry_cost, "confidence": plan.get("confidence"),
            "leverage": sizing.leverage, "currency": currency,
            "mae_r": 0.0, "mfe_r": 0.0, "bars_held": 0,
            # L'ultima barra processata è quella del SEGNALE, non quella di
            # oggi: la seduta in cui si è entrati va riesaminata alla
            # prossima esecuzione, quando sarà completa. Segnandola già
            # come processata, uno stop toccato dopo l'ingresso — nel resto
            # della stessa giornata — non verrebbe mai rilevato.
            "last_processed_date": signal_date,
        }
        state.open_positions = _append_row(state.open_positions, row, OPEN_POSITIONS_COLUMNS)
        state.equity_eur -= entry_cost
        events.append(StepEvent(
            "apertura", symbol,
            f"{direction.upper()} aperto a {price:.2f} (stop {stop:.2f}, target {target:.2f}, "
            f"rischio {sizing.initial_risk_eur:.2f} EUR)."))

    state.last_run_at = now_iso
    return state, events


def _todays_open(symbol: str, today: dt.date, history_fn) -> float | None:
    """Apertura della seduta odierna, se disponibile.

    Va letta dallo storico NON troncato: è l'unica informazione della
    barra in corso che è già definitiva (l'apertura non cambia più durante
    la giornata), a differenza del close."""
    try:
        hist = history_fn(symbol)
    except Exception:
        return None
    if hist is None or hist.empty:
        return None
    for ts, row in hist.iloc[::-1].iterrows():
        d = ts.date() if hasattr(ts, "date") else ts
        if d == today:
            return float(row["Open"])
        if d < today:
            break
    return None


def _process_open_positions(state: PaperState, histories: dict[str, pd.DataFrame],
                             config: PaperConfig, costs: CostModel, today: dt.date,
                             price_fn, events: list[StepEvent]) -> PaperState:
    if state.open_positions.empty:
        return state

    still_open = []
    for _, pos in state.open_positions.iterrows():
        symbol = str(pos["symbol"])
        direction = str(pos["direction"])
        stop = float(pos["stop"])
        target = float(pos["target"])
        entry_price = float(pos["entry_price"])
        risk_per_unit = float(pos["risk_per_unit"])
        size = float(pos["size"])
        mae_r = float(pos.get("mae_r") or 0.0)
        mfe_r = float(pos.get("mfe_r") or 0.0)
        bars_held = int(pos.get("bars_held") or 0)
        last_done = _as_date(pos.get("last_processed_date"))
        entry_date = _as_date(pos.get("entry_date"))

        hist = histories.get(symbol)
        exit_event = None
        exit_date = None

        # 1. Barre complete non ancora processate, con le regole del backtest.
        if hist is not None and not hist.empty:
            for bar_date, bar in _bars_after(hist, last_done, today):
                bars_held += 1
                mae_r, mfe_r = ex.update_excursions(direction, entry_price, risk_per_unit,
                                                     bar["high"], bar["low"], mae_r, mfe_r)
                if bar_date == entry_date:
                    # Barra della seduta in cui si è entrati, ora completa.
                    # Non si applica la logica di gap sull'apertura: quando
                    # quella barra si è aperta la posizione non esisteva
                    # ancora, si è entrati a metà giornata.
                    #
                    # Il massimo e il minimo della barra però coprono tutta
                    # la seduta, comprese le ore PRIMA dell'ingresso: con
                    # dati daily non c'è modo di sapere se lo stop è stato
                    # sfiorato prima o dopo che siamo entrati. Si applica
                    # comunque la regola conservativa (uscita sullo stop),
                    # coerentemente con lo stop-first del resto del motore:
                    # meglio registrare una perdita che forse non c'è stata
                    # che ignorarne una che c'è stata davvero.
                    hit_stop = (bar["low"] <= stop) if direction == "long" else (bar["high"] >= stop)
                    hit_target = (bar["high"] >= target) if direction == "long" else (bar["low"] <= target)
                    if hit_stop:
                        exit_event = ex.ExitEvent(price=stop, reason="stop")
                    elif hit_target:
                        exit_event = ex.ExitEvent(price=target, reason="target")
                else:
                    exit_event = ex.resolve_exit(direction, stop, target,
                                                  bar["open"], bar["high"], bar["low"])
                last_done = bar_date
                if exit_event is not None:
                    exit_date = bar_date
                    break

        # 2. Tocco intraday sul prezzo corrente, se non già uscito.
        if exit_event is None:
            current = price_fn(symbol)
            if current and current > 0:
                mae_r, mfe_r = ex.update_excursions(direction, entry_price, risk_per_unit,
                                                     current, current, mae_r, mfe_r)
                if direction == "long":
                    if current <= stop:
                        exit_event = ex.ExitEvent(price=current, reason="stop_intraday")
                    elif current >= target:
                        exit_event = ex.ExitEvent(price=current, reason="target_intraday")
                else:
                    if current >= stop:
                        exit_event = ex.ExitEvent(price=current, reason="stop_intraday")
                    elif current <= target:
                        exit_event = ex.ExitEvent(price=current, reason="target_intraday")
                if exit_event is not None:
                    exit_date = today

        if exit_event is None:
            updated = pos.copy()
            updated["mae_r"] = mae_r
            updated["mfe_r"] = mfe_r
            updated["bars_held"] = bars_held
            updated["last_processed_date"] = last_done if last_done else pos.get("last_processed_date")
            still_open.append(updated)
            continue

        # Chiusura
        exit_price = exit_event.price
        delta = ((exit_price - entry_price) if direction == "long" else (entry_price - exit_price))
        gross_pnl = delta * size
        entry_cost = float(pos.get("entry_cost_eur") or 0.0)
        exit_cost = costs.exit_cost_eur(abs(size * exit_price), pos.get("currency"))
        total_costs = entry_cost + exit_cost
        net_pnl = gross_pnl - total_costs
        initial_risk = float(pos.get("initial_risk_eur") or 0.0)

        # Costo del ritardo di esecuzione: quanto è valso, in R, entrare al
        # prezzo corrente invece che all'apertura come nel backtest.
        reference_open = pos.get("reference_open_price")
        delay_r = None
        try:
            if reference_open is not None and not pd.isna(reference_open) and risk_per_unit > 0:
                ref = float(reference_open)
                diff = (ref - entry_price) if direction == "long" else (entry_price - ref)
                delay_r = diff / risk_per_unit
        except (TypeError, ValueError):
            delay_r = None

        closed = {
            "symbol": symbol, "direction": direction,
            "signal_date": _as_date(pos.get("signal_date")), "entry_date": entry_date,
            "entry_price": entry_price, "reference_open_price": reference_open,
            "exit_date": exit_date, "exit_price": exit_price, "exit_reason": exit_event.reason,
            "size": size, "risk_per_unit": risk_per_unit, "initial_risk_eur": initial_risk,
            "confidence": pos.get("confidence"), "leverage": pos.get("leverage"),
            "gross_pnl_eur": gross_pnl, "costs_eur": total_costs, "net_pnl_eur": net_pnl,
            "gross_r": (gross_pnl / initial_risk) if initial_risk else 0.0,
            "net_r": (net_pnl / initial_risk) if initial_risk else 0.0,
            "mae_r": mae_r, "mfe_r": mfe_r, "bars_held": bars_held,
            "gapped_exit": bool(exit_event.gapped), "execution_delay_r": delay_r,
        }
        state.closed_trades = _append_row(state.closed_trades, closed, CLOSED_TRADES_COLUMNS)
        state.equity_eur += gross_pnl - exit_cost
        events.append(StepEvent(
            "chiusura", symbol,
            f"Chiuso a {exit_price:.2f} ({exit_event.reason}): {closed['net_r']:+.2f}R, "
            f"{net_pnl:+.2f} EUR."))

    state.open_positions = (pd.DataFrame(still_open, columns=OPEN_POSITIONS_COLUMNS)
                            if still_open
                            else pd.DataFrame(columns=OPEN_POSITIONS_COLUMNS))
    return state


def _append_row(df: pd.DataFrame, row: dict, columns: list[str]) -> pd.DataFrame:
    """Append senza pd.concat su colonne tutte-NA (che emette FutureWarning
    quando i campi opzionali sono vuoti, es. un trade senza confidenza)."""
    base = df.copy() if not df.empty else pd.DataFrame(columns=columns)
    base = base.reindex(columns=columns).astype(object)
    base.loc[len(base)] = {c: row.get(c) for c in columns}
    return base


# ---------------------------------------------------------------------------
# Serializzazione dello stato (CSV, per poterlo committare nel repository)
# ---------------------------------------------------------------------------

def state_to_frames(state: PaperState) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    meta = {
        "equity_eur": state.equity_eur,
        "started_at": state.started_at,
        "last_run_at": state.last_run_at,
    }
    return (state.open_positions.reindex(columns=OPEN_POSITIONS_COLUMNS),
            state.closed_trades.reindex(columns=CLOSED_TRADES_COLUMNS),
            meta)


def state_from_frames(open_df: pd.DataFrame | None, closed_df: pd.DataFrame | None,
                       meta: dict | None) -> PaperState:
    meta = meta or {}
    open_df = (open_df if open_df is not None and not open_df.empty
               else pd.DataFrame(columns=OPEN_POSITIONS_COLUMNS))
    closed_df = (closed_df if closed_df is not None and not closed_df.empty
                 else pd.DataFrame(columns=CLOSED_TRADES_COLUMNS))
    return PaperState(
        open_positions=open_df.reindex(columns=OPEN_POSITIONS_COLUMNS),
        closed_trades=closed_df.reindex(columns=CLOSED_TRADES_COLUMNS),
        equity_eur=float(meta.get("equity_eur") or 0.0),
        started_at=str(meta.get("started_at") or ""),
        last_run_at=str(meta.get("last_run_at") or ""),
    )


def config_to_dict(config: PaperConfig) -> dict:
    return asdict(config)


def config_from_dict(data: dict | None) -> PaperConfig:
    data = data or {}
    known = {f for f in PaperConfig.__dataclass_fields__}
    return PaperConfig(**{k: v for k, v in data.items() if k in known})
