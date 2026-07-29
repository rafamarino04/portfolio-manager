"""Backtest: il segnale dell'Analisi Tecnica ha un edge reale?

Costruito secondo BACKTEST AND FORWARD.pdf (Stage 0 architettura + Stage 1
backtest in-sample). Testa esattamente il piano operativo che l'app mostra
nella pagina Analisi Tecnica (`trade_plan`), sull'Universo Trading, con un
motore event-driven bar-by-bar (src/engine/).

Il compito di questa pagina non è produrre una bella curva di equity, ma
dire la verità su se il segnale abbia un edge che sopravvive ai costi ed è
statisticamente sostenuto. Per questo l'interfaccia ha guardrail
anti-autoinganno cablati dentro, non opzionali: lordo sempre accanto al
netto, in-sample accanto all'out-of-sample, nessun win rate senza il suo
intervallo di confidenza e il numero di trade, metriche oscurate sotto il
campione minimo, i due benchmark obbligatori accanto a ogni risultato, e un
verdetto in linguaggio piano che dice se l'edge è stabilito, marginale o
non provato.
"""
import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import trading_universe as tu
from src import watchlist as wl
from src.engine import diagnostics as diag
from src.engine import metrics as mt
from src.engine import runner
from src.engine import strategies
from src.engine.core import BacktestConfig
from src.engine.costs import (DEFAULT_FX_COST_PCT_PER_LEG, DEFAULT_SLIPPAGE_BPS_PER_SIDE,
                               TR_BEST_PRICE_FEE_EUR, TR_DIRECT_PRICE_FEE_EUR, CostModel)
from src.engine.risk import DEFAULT_RISK_PCT, MAX_BASE_RISK_PCT, RiskConfig
from src.theme import ACCENT, BLUE, GREEN, RED, TEXT_MUTED, apply_theme, badge, disclaimer

apply_theme()

st.title("Backtest")
st.caption(
    "Il piano operativo dell'Analisi Tecnica ha un edge reale? Questo motore lo esegue "
    "bar per bar sullo storico, con le stesse regole che avresti subito dal vivo: segnale sul "
    "close, esecuzione all'apertura successiva, stop colpito per primo quando il dato non "
    "permette di sapere l'ordine, gap pagati al prezzo reale e tutti i costi applicati. "
    "Serve a smentire il segnale, non a confermarlo."
)

VERDICT_BADGE = {
    mt.VERDICT_ESTABLISHED: "ok",
    mt.VERDICT_MARGINAL: "warn",
    mt.VERDICT_UNPROVEN: "warn",
    mt.VERDICT_NEGATIVE: "bad",
}
VERDICT_TITLE = {
    mt.VERDICT_ESTABLISHED: "Edge statisticamente sostenuto",
    mt.VERDICT_MARGINAL: "Edge marginale",
    mt.VERDICT_UNPROVEN: "Edge non provato",
    mt.VERDICT_NEGATIVE: "Nessun edge",
}


def _fmt(value, suffix="", decimals=2, dash="n/d"):
    if value is None:
        return dash
    return f"{value:,.{decimals}f}{suffix}"


def _render_verdict(segment):
    v = segment.verdict
    kind = VERDICT_BADGE.get(v.get("verdict"), "info")
    st.markdown(
        f"### {badge(VERDICT_TITLE.get(v.get('verdict'), 'Verdetto'), kind)}",
        unsafe_allow_html=True,
    )
    st.info(v.get("text", ""))


def _render_sample_gate(m: mt.PerformanceMetrics) -> bool:
    """Ritorna True se le metriche vanno mostrate a piena leggibilità.

    Sotto il campione minimo la pagina non nasconde i numeri (sarebbe
    paternalistico) ma li marca esplicitamente come non interpretabili,
    che è il punto: un win rate su 20 trade non è un'informazione, è
    rumore travestito da precisione."""
    if m.n_trades == 0:
        st.warning("Nessun trade generato in questo segmento: il segnale non si è mai attivato.")
        return False
    if not m.sample_is_indicative:
        st.error(f"Campione insufficiente. {m.sample_note} I numeri qui sotto NON vanno interpretati.")
        return False
    if not m.sample_is_reliable:
        st.warning(f"Campione limitato. {m.sample_note}")
        return True
    st.success(m.sample_note)
    return True


def _render_metrics(segment):
    m = segment.metrics
    reliable = _render_sample_gate(m)
    dim = "" if reliable else " *(campione insufficiente)*"

    # Expectancy in R in evidenza: è la metrica che la leva non può
    # mascherare, a differenza del P&L in euro.
    e1, e2, e3 = st.columns(3)
    e1.metric("Expectancy per trade (R)", _fmt(m.expectancy_r, "R"),
              help="Multiplo di rischio medio per trade, netto di costi. Sotto +0,2R i costi "
                   "si mangiano l'edge.")
    e2.metric("Expectancy per trade (EUR)", _fmt(m.expectancy_eur, " EUR"))
    e3.metric("Trade", f"{m.n_trades}")

    # Lordo vs netto sempre affiancati.
    st.markdown(f"**Rendimento lordo vs netto**{dim}")
    g1, g2, g3 = st.columns(3)
    g1.metric("Rendimento netto", _fmt(m.total_return_pct, "%"))
    g2.metric("Rendimento lordo", _fmt(m.gross_total_return_pct, "%"))
    g3.metric("Costi totali", _fmt(m.total_costs_eur, " EUR"))
    if m.total_return_pct is not None and m.gross_total_return_pct is not None:
        drag = m.gross_total_return_pct - m.total_return_pct
        st.caption(f"I costi hanno sottratto {drag:,.2f} punti percentuali di rendimento.")

    # Win rate SEMPRE con intervallo di Wilson e numero di trade.
    st.markdown(f"**Statistiche di trade**{dim}")
    w1, w2, w3, w4 = st.columns(4)
    if m.win_rate is not None and m.win_rate_ci:
        lo, hi = m.win_rate_ci
        w1.metric("Win rate", f"{m.win_rate * 100:.1f}%")
        w1.caption(f"Intervallo di Wilson 95%: {lo * 100:.1f}% – {hi * 100:.1f}% su {m.n_trades} trade")
    else:
        w1.metric("Win rate", "n/d")
    w2.metric("Profit factor", _fmt(m.profit_factor))
    w3.metric("Vincita media", _fmt(m.avg_win_r, "R"))
    w4.metric("Perdita media", _fmt(m.avg_loss_r, "R"))

    st.caption(
        "Un win rate basso non è un difetto: il trend-following guadagna da pochi grandi "
        "vincitori, quindi contano expectancy e rapporto vincita/perdita, non la percentuale "
        "di trade vinti."
    )

    st.markdown(f"**Rischio e rendimento corretto per il rischio**{dim}")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Max drawdown", _fmt(m.max_drawdown_pct, "%"))
    r2.metric("Sharpe", _fmt(m.sharpe))
    r3.metric("Sortino", _fmt(m.sortino))
    r4.metric("Calmar", _fmt(m.calmar))
    if m.sortino is not None and m.sharpe is not None and m.sortino > m.sharpe:
        st.caption(
            "Sortino sopra lo Sharpe: rendimenti asimmetrici verso l'alto, la firma tipica di un "
            "sistema che taglia le perdite e lascia correre i guadagni."
        )

    h1, h2, h3 = st.columns(3)
    h1.metric("Durata media (barre)", _fmt(m.avg_holding_days, "", 1))
    h2.metric("MAE media", _fmt(m.avg_mae_r, "R"))
    h3.metric("MFE media", _fmt(m.avg_mfe_r, "R"))
    if m.n_gapped_exits:
        st.caption(
            f"{m.n_gapped_exits} uscite su {m.n_trades} sono avvenute in gap oltre il livello "
            "previsto: perdite peggiori del −1R pianificato, la coda che la leva amplificherebbe."
        )

    for warn in m.warnings:
        st.warning(warn)


def _render_benchmarks(segment):
    """I due benchmark obbligatori, accanto al risultato e non in fondo."""
    m = segment.metrics
    st.markdown("**Benchmark obbligatori**")
    b1, b2 = st.columns(2)

    bh = segment.buy_and_hold
    with b1:
        st.metric("Buy-and-hold (stessi strumenti)",
                  _fmt(bh.total_return_pct if bh else None, "%"))
        if segment.beats_buy_and_hold is True:
            st.markdown(badge("Il timing ha aggiunto valore", "ok"), unsafe_allow_html=True)
        elif segment.beats_buy_and_hold is False:
            st.markdown(badge("Non batte il buy-and-hold", "bad"), unsafe_allow_html=True)
            st.caption("Restare semplicemente investito avrebbe reso di più: il timing ha distrutto valore.")

    rnd = segment.random_entry
    with b2:
        st.metric("Entrata casuale (mediana Monte Carlo)",
                  _fmt(rnd.median_return_pct if rnd else None, "%"))
        if segment.beats_random is True:
            pct = segment.random_percentile
            st.markdown(badge("Batte l'entrata casuale", "ok"), unsafe_allow_html=True)
            if pct is not None:
                st.caption(f"La strategia cade nel {pct:.0f}° percentile delle entrate casuali.")
        elif segment.beats_random is False:
            st.markdown(badge("Non batte l'entrata casuale", "bad"), unsafe_allow_html=True)
            st.caption(
                "Con le stesse uscite e lo stesso sizing, entrate a caso avrebbero fatto meglio "
                "almeno la metà delle volte: l'edge non viene dal segnale."
            )
    st.caption(
        f"Il benchmark casuale usa {rnd.runs if rnd else 0} simulazioni con la stessa frequenza di "
        "trade e identiche regole di stop, target e sizing: l'unica variabile che cambia è da dove "
        "arriva il segnale."
    )


def _equity_figure(segment) -> go.Figure:
    fig = go.Figure()
    curve = segment.backtest.ledger.equity_curve
    if curve:
        dates = [c[0] for c in curve]
        fig.add_trace(go.Scatter(x=dates, y=[c[1] for c in curve], name="Strategia (netta)",
                                  line=dict(color=ACCENT, width=2)))
        fig.add_trace(go.Scatter(x=dates, y=[c[2] for c in curve], name="Strategia (lorda)",
                                  line=dict(color=TEXT_MUTED, width=1, dash="dot")))
    bh = segment.buy_and_hold
    if bh and bh.equity_curve:
        fig.add_trace(go.Scatter(x=[c[0] for c in bh.equity_curve], y=[c[1] for c in bh.equity_curve],
                                  name="Buy-and-hold", line=dict(color=BLUE, width=1.5)))
    fig.update_layout(height=380, margin=dict(t=30, b=30),
                      yaxis_title="Equity (EUR)", legend=dict(orientation="h", y=1.12))
    return fig


def _render_segment(segment, key_prefix: str):
    _render_verdict(segment)
    st.plotly_chart(_equity_figure(segment), use_container_width=True, key=f"{key_prefix}_equity")
    _render_benchmarks(segment)
    st.divider()
    _render_metrics(segment)

    trades = segment.backtest.ledger.closed_trades
    if trades:
        with st.expander(f"Registro dei {len(trades)} trade"):
            rows = [{
                "Simbolo": t.symbol, "Direzione": t.direction,
                "Segnale": t.signal_date, "Ingresso": t.entry_date,
                "Prezzo ingresso": round(t.entry_price, 2),
                "Uscita": t.exit_date, "Prezzo uscita": round(t.exit_price, 2),
                "Motivo": t.exit_reason,
                "R netto": round(t.net_r, 2), "P&L netto (EUR)": round(t.net_pnl_eur, 2),
                "Costi (EUR)": round(t.costs_eur, 2),
                "MAE (R)": round(t.mae_r, 2), "MFE (R)": round(t.mfe_r, 2),
                "Barre": t.bars_held,
            } for t in trades]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    rejected = segment.backtest.rejection_reasons
    if rejected:
        with st.expander(f"{segment.backtest.n_orders_rejected} ordini non eseguiti"):
            st.caption(
                "Ordini generati dal segnale ma non aperti. Vanno guardati: se la maggior parte dei "
                "segnali non diventa un trade, il backtest sta misurando qualcosa di diverso da ciò "
                "che credi di star testando."
            )
            for reason, count in sorted(rejected.items(), key=lambda kv: -kv[1]):
                st.markdown(f"- {reason}: **{count}**")


# ---------------------------------------------------------------------------
# Configurazione
# ---------------------------------------------------------------------------

# Ambito: quale lista testare. Tenerle separate permette di confrontare
# universi diversi — per esempio una lista concentrata su un solo settore
# contro una diversificata tra classi di attivo — senza che l'una
# sovrascriva l'altra. Su un universo molto correlato il trend-following
# non è una strategia diversificata ma una scommessa sola presa N volte,
# ed è una differenza che si vede solo mettendo le due liste a confronto.
SCOPE_UNIVERSE = "Universo Trading"
SCOPE_FAVORITES = "Preferiti"
SCOPE_BOTH = "Entrambe le liste"


def _favorite_tickers() -> list[str]:
    watch = wl.load_watchlist()
    if watch.empty:
        return []
    return sorted(t for t in watch["ticker"].astype(str).str.strip().str.upper().unique()
                  if t and t.lower() != "nan")


universe_tickers = tu.tickers(tu.load_universe())
favorite_tickers = _favorite_tickers()

if not universe_tickers and not favorite_tickers:
    st.info(
        "Universo Trading e Preferiti sono entrambi vuoti. Il backtest gira su una di queste due "
        "liste: popolane almeno una dalla pagina Analisi Tecnica e torna qui."
    )
    st.stop()

scope = st.radio(
    "Lista da testare", [SCOPE_UNIVERSE, SCOPE_FAVORITES, SCOPE_BOTH],
    horizontal=True, key="bt_scope",
    help="Le due liste restano separate: puoi confrontare universi diversi senza che l'uno "
         "sovrascriva l'altro.",
)
if scope == SCOPE_UNIVERSE:
    available_tickers = universe_tickers
elif scope == SCOPE_FAVORITES:
    available_tickers = favorite_tickers
else:
    available_tickers = sorted(set(universe_tickers) | set(favorite_tickers))

if not available_tickers:
    st.warning(f"La lista «{scope}» è vuota: scegline un'altra o popolala dalla pagina Analisi Tecnica.")
    st.stop()

st.markdown("### Configurazione")
st.caption(
    "Ogni parametro qui è dichiarato e modificabile: un backtest di cui non si conoscono i costi "
    "e il rischio per trade non è verificabile."
)

# Selettore di strategia: confrontare regole diverse nello STESSO apparato
# (stessi costi, stesso sizing, stesse regole di esecuzione, stessi
# benchmark) è l'unico modo per sapere se il problema sia un algoritmo
# specifico o l'intero approccio.
strategy_key = st.selectbox(
    "Strategia di segnale", strategies.keys(), key="bt_strategy",
    format_func=lambda k: strategies.get(k).label,
    help="L'unica variabile che cambia tra le strategie è da dove viene il segnale: "
         "costi, dimensionamento, regole di esecuzione e benchmark restano identici.",
)
_strategy = strategies.get(strategy_key)
st.info(f"**{_strategy.label}** — {_strategy.description}")
st.caption(f"Parametri: {_strategy.parameters}. Nessuna soglia è stata scelta osservando i "
           "risultati: sono i valori convenzionali della letteratura.")

c1, c2, c3 = st.columns(3)
with c1:
    symbols = st.multiselect(f"Strumenti ({scope})", available_tickers,
                              default=available_tickers, key=f"bt_symbols_{scope}")
    horizon = st.selectbox("Orizzonte del segnale", ["medio", "breve"], key="bt_horizon",
                            help="Rilevante solo per la strategia Murphy: le altre hanno "
                                 "parametri propri e non dipendono dall'orizzonte. Solo barre "
                                 "daily — il lungo termine userebbe barre settimanali.")
with c2:
    initial_equity = st.number_input("Capitale iniziale (EUR)", min_value=1000.0, value=10_000.0,
                                      step=1000.0, key="bt_equity")
    risk_pct = st.slider("Rischio per trade (% equity)", 0.25, MAX_BASE_RISK_PCT,
                          DEFAULT_RISK_PCT, 0.05, key="bt_risk",
                          help="Frazione fissa dell'equity rischiata per trade, definita dalla "
                               "distanza dallo stop. I professionisti stanno tra 0,5% e 2%.")
with c3:
    fee_model = st.selectbox("Commissione Trade Republic", ["Best Price (1 EUR)", "Direct Price (2 EUR)"],
                              key="bt_fee")
    fx_cost = st.number_input("Costo FX per gamba su strumenti non EUR (%)", min_value=0.0,
                               max_value=2.0, value=DEFAULT_FX_COST_PCT_PER_LEG, step=0.05,
                               key="bt_fx",
                               help="Dopo il cambio di infrastruttura di Trade Republic (luglio 2026) "
                                    "il costo FX è incorporato nello spread e non pubblicato. 0,5% "
                                    "per gamba è una stima prudenziale dichiarata, non un dato ufficiale.")
    slippage_bps = st.number_input("Spread + slippage per lato (punti base)", min_value=0.0,
                                    max_value=100.0, value=DEFAULT_SLIPPAGE_BPS_PER_SIDE, step=1.0,
                                    key="bt_slip")

with st.expander("Impostazioni avanzate"):
    a1, a2 = st.columns(2)
    period = a1.selectbox("Storico da scaricare", ["10y", "5y", "max"], key="bt_period",
                           help="Più regimi di mercato coperti, più il risultato è informativo. "
                                "Uno Sharpe alto su un solo mercato rialzista non dice quasi nulla.")
    mc_runs = a2.slider("Simulazioni del benchmark casuale", 50, 500, 200, 50, key="bt_mc")
    run_oos = st.checkbox(
        "Calcola anche l'out-of-sample (Stage 2)", value=False, key="bt_oos",
        help="Lo Stage 1 della specifica prevede di guardare SOLO l'in-sample. "
             "L'out-of-sample andrebbe guardato una volta sola, dopo aver congelato i parametri: "
             "ogni sbirciata aggiuntiva lo consuma e lo trasforma di fatto in in-sample.",
    )
    long_only = st.checkbox(
        "Solo posizioni long", value=False, key="bt_long_only",
        help="Trade Republic è spot-only: gli short non sono realmente eseguibili. Tenerli nel "
             "backtest produce un risultato non replicabile con il tuo conto. Lasciato "
             "disattivato per non cambiare in silenzio i confronti con le esecuzioni precedenti.",
    )
    skip_bad_rr = st.checkbox(
        "Scarta i piani con rischio/rendimento sfavorevole", value=True, key="bt_skip_rr",
        help="Il piano operativo calcola già un rapporto rischio/rendimento e segnala quelli "
             "sotto la propria soglia minima. Tenendo la casella spuntata il backtest non li "
             "esegue, cioè misura quello che faresti davvero. Toglierla serve solo a misurare "
             "quanto pesavano: non è il comportamento normale.",
    )
    st.caption(
        "Leva da confidenza: **disattivata**. La specifica la sblocca solo dopo che la "
        "calibrazione empirica (Stage 4) ha mostrato che i segnali ad alta confidenza vincono "
        "davvero quanto promettono. Fino ad allora tutto gira a 1,0×."
    )

cost_model = CostModel(
    order_fee_eur=TR_BEST_PRICE_FEE_EUR if fee_model.startswith("Best") else TR_DIRECT_PRICE_FEE_EUR,
    fx_cost_pct_per_leg=fx_cost,
    slippage_bps_per_side=slippage_bps,
)
config = BacktestConfig(
    horizon=horizon, initial_equity_eur=initial_equity,
    risk=RiskConfig(risk_pct=risk_pct, leverage_enabled=False), costs=cost_model,
    skip_unfavorable_rr=skip_bad_rr, strategy=strategy_key, long_only=long_only,
)

# Conteggio delle configurazioni provate in sessione: più sono, più il
# risultato migliore è gonfiato dal caso (problema del multiple testing).
st.session_state.setdefault("_bt_runs", 0)

# Stima della durata, dichiarata PRIMA di partire. Il costo dominante è il
# ricalcolo del segnale barra per barra: è inevitabile se si vuole un
# backtest point-in-time, ma un'attesa di minuti senza preavviso è
# indistinguibile da un blocco.
_bars_per_year = 252
_years = {"5y": 5, "10y": 10, "max": 15}.get(period, 10)
_operative_bars = max(0, _years * _bars_per_year - _strategy.warmup_bars(horizon))
_segments = 2 if run_oos else 1
_est_seconds = len(symbols) * _operative_bars * 0.009 * (2 / 3 if not run_oos else 1)
if symbols:
    st.caption(
        f"Durata stimata: circa **{_est_seconds / 60:.0f} minuti** "
        f"({len(symbols)} strumenti × ~{_operative_bars:,} barre operative, segnale ricalcolato "
        f"barra per barra). Non chiudere la pagina: l'attesa è normale, non un blocco."
    )

if st.button("Esegui backtest", type="primary", key="bt_run"):
    if not symbols:
        st.error("Seleziona almeno uno strumento.")
    else:
        st.session_state["_bt_runs"] += 1
        phase_box = st.empty()
        progress = st.progress(0.0, text="Preparazione...")
        started = dt.datetime.now()

        def _cb(frac, current_date):
            elapsed = (dt.datetime.now() - started).total_seconds()
            eta = (elapsed / frac - elapsed) if frac > 0.02 else None
            suffix = f" · ~{eta / 60:.0f} min rimanenti" if eta and eta > 30 else ""
            progress.progress(min(1.0, frac),
                              text=f"Simulazione bar per bar... {current_date}{suffix}")

        def _phase(nome, frazione):
            # Ogni fase si annuncia: senza, dopo il bar loop la pagina
            # resterebbe muta durante il benchmark, che è esattamente il
            # momento in cui sembra bloccata.
            if frazione is None:
                phase_box.info(f"In corso: {nome}...")
            else:
                phase_box.info(f"In corso: {nome} — {frazione * 100:.0f}%")

        try:
            report = runner.run_full_backtest(
                symbols, config=config, period=period, monte_carlo_runs=mc_runs,
                run_out_of_sample=run_oos,
                configurations_tried=st.session_state["_bt_runs"],
                progress_callback=_cb, phase_callback=_phase,
            )
            st.session_state["_bt_report"] = report
            st.session_state["_bt_frozen_at"] = dt.datetime.now().isoformat(timespec="seconds")
            st.session_state.pop("_diag_sq", None)   # la diagnostica si riferisce al run precedente
            phase_box.success(
                f"Completato in {(dt.datetime.now() - started).total_seconds() / 60:.1f} minuti.")
        except ValueError as exc:
            phase_box.empty()
            st.error(str(exc))
        progress.empty()

report = st.session_state.get("_bt_report")
if not report:
    st.info("Configura i parametri e premi *Esegui backtest*. La simulazione bar per bar su più "
            "anni e più strumenti richiede qualche minuto.")
    st.stop()

st.divider()
st.markdown("### Risultati")
st.caption(
    f"Strategia: **{strategies.get(report.strategy).label}** · lista: **{scope}** · "
    f"strumenti: {', '.join(report.symbols)} · orizzonte {report.horizon} · storico "
    f"{report.history_start} → {report.history_end} · costi applicati: {report.cost_description}"
)

# Guardrail: log della data di congelamento e del numero di configurazioni provate.
freeze_info = st.session_state.get("_bt_frozen_at", "n/d")
st.caption(
    f"Ultima esecuzione: {freeze_info} · configurazioni provate in questa sessione: "
    f"**{report.configurations_tried}**."
)
if report.configurations_tried > 3:
    st.warning(
        f"Hai eseguito {report.configurations_tried} configurazioni diverse in questa sessione. "
        "Ogni tentativo in più gonfia per caso il risultato migliore: se stai cambiando i "
        "parametri finché il risultato non migliora, non stai più misurando un edge, lo stai "
        "costruendo sui dati. Congela i parametri e dichiara la data."
    )

for note in report.diagnostics:
    st.warning(note)

if report.in_sample is None:
    st.error("Nessun risultato calcolabile.")
    st.stop()

if report.out_of_sample is not None:
    tab_is, tab_oos, tab_cmp = st.tabs(["In-sample", "Out-of-sample", "Confronto"])
    with tab_is:
        _render_segment(report.in_sample, "is")
    with tab_oos:
        st.caption(f"Periodo out-of-sample: dal {report.split_date} in poi. Parametri congelati prima "
                   "di guardarlo — se li cambi ora, questo segmento smette di essere out-of-sample.")
        _render_segment(report.out_of_sample, "oos")
    with tab_cmp:
        st.markdown("#### In-sample vs Out-of-sample")
        st.caption(
            "Il decadimento fuori campione è la norma: i rendimenti calano tipicamente di un quarto, "
            "lo Sharpe di circa un terzo. Aspettati che l'out-of-sample sia un terzo/metà più debole; "
            "un out-of-sample MIGLIORE è sospetto di contaminazione, non un trionfo."
        )
        rows = []
        for seg in (report.in_sample, report.out_of_sample):
            m = seg.metrics
            rows.append({
                "Segmento": m.label, "Trade": m.n_trades,
                "Expectancy (R)": _fmt(m.expectancy_r),
                "Rendimento netto": _fmt(m.total_return_pct, "%"),
                "Win rate": _fmt(m.win_rate * 100 if m.win_rate is not None else None, "%", 1),
                "Profit factor": _fmt(m.profit_factor),
                "Sharpe": _fmt(m.sharpe), "Max DD": _fmt(m.max_drawdown_pct, "%"),
                "Verdetto": VERDICT_TITLE.get(seg.verdict.get("verdict"), "n/d"),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        is_m, oos_m = report.in_sample.metrics, report.out_of_sample.metrics
        if is_m.expectancy_r and oos_m.expectancy_r is not None and is_m.expectancy_r > 0:
            retention = oos_m.expectancy_r / is_m.expectancy_r * 100
            st.metric("Expectancy fuori campione trattenuta", f"{retention:.0f}%")
            if retention < 50:
                st.warning(
                    "Sotto il 50% di ritenzione: la soglia della specifica per proseguire allo stadio "
                    "successivo è un out-of-sample non peggiore di circa metà dell'in-sample."
                )
else:
    st.caption(
        "Solo in-sample, come previsto dallo Stage 1 della specifica. L'out-of-sample si attiva "
        "dalle impostazioni avanzate — ma va guardato una volta sola, dopo aver congelato i parametri."
    )
    _render_segment(report.in_sample, "is")

st.divider()

# ---------------------------------------------------------------------------
# Diagnostica: dove si perde valore
# ---------------------------------------------------------------------------

st.markdown("### Diagnostica: dove si perde valore")
st.caption(
    "Un risultato negativo, da solo, non dice se il problema è il segnale o la struttura che gli "
    "sta attorno: sono due diagnosi opposte e portano a due lavori diversi. Questa sezione le "
    "separa, misurando i tre punti in cui il valore può andarsene."
)

seg = report.in_sample
trades = seg.backtest.ledger.closed_trades

if not trades:
    st.info("Nessun trade chiuso: non c'è nulla da diagnosticare.")
else:
    cost_d = diag.cost_drag(trades)
    exit_d = diag.exit_quality(trades)
    plan_d = diag.plan_quality(trades)

    st.info(diag.overall_diagnosis(cost_d, exit_d, plan_d, seg.beats_random))

    d1, d2, d3 = st.tabs(["Costi", "Uscite", "Geometria dei piani"])

    with d1:
        st.caption(
            "Il costo in euro non dice nulla da solo: 20 euro su un trade che rischia 500 sono "
            "irrilevanti, sugli stessi 50 di rischio sono letali. Va letto in R. E dipende dalla "
            "distanza dello stop, non dalla dimensione del trade: il controvalore vale "
            "rischio/stop%, quindi i costi percentuali crescono quando lo stop si stringe mentre "
            "il rischio in euro resta fisso."
        )
        c1, c2, c3 = st.columns(3)
        c1.metric("Costo medio per trade", _fmt(cost_d.mean_cost_r, "R"))
        c2.metric("Costo mediano", _fmt(cost_d.median_cost_r, "R"))
        c3.metric("Costi su P&L lordo", _fmt(cost_d.cost_share_of_gross_pct, "%", 0))
        if cost_d.mean_cost_r is not None and cost_d.mean_cost_r >= diag.COST_ALARM_R:
            st.error(cost_d.verdict)
        else:
            st.success(cost_d.verdict)
        if not cost_d.by_symbol.empty:
            st.dataframe(cost_d.by_symbol.rename(columns={
                "symbol": "Simbolo", "trade": "Trade", "costo_medio_r": "Costo medio (R)",
                "costi_eur": "Costi (EUR)", "pnl_netto_eur": "P&L netto (EUR)"}),
                use_container_width=True, hide_index=True, key="diag_cost_symbol")

    with d2:
        st.caption(
            "Confronto tra quanto un trade ha toccato a proprio favore (MFE) e quanto ha portato a "
            "casa. È il test dell'ipotesi 'i target sono troppo bassi': se i vincenti arrivano a "
            "2-3R prima di chiudere a 0,8R, il segnale la direzione la trova e sono le uscite a "
            "buttarla via."
        )
        e1, e2, e3, e4 = st.columns(4)
        e1.metric("MFE media", _fmt(exit_d.mean_mfe_r, "R"))
        e2.metric("R medio dei vincenti", _fmt(exit_d.mean_realized_r_winners, "R"))
        e3.metric("Lasciato sul tavolo", _fmt(exit_d.mean_gap_r, "R"))
        e4.metric("Vincita/perdita media", _fmt(exit_d.win_loss_size_ratio))
        if exit_d.mean_gap_r is not None and exit_d.mean_gap_r >= diag.MFE_GAP_ALARM_R:
            st.error(exit_d.verdict)
        else:
            st.warning(exit_d.verdict)
        g1, g2 = st.columns(2)
        g1.metric("Miglior trade", _fmt(exit_d.best_trade_r, "R"))
        g2.metric("Peggior trade", _fmt(exit_d.worst_trade_r, "R"))
        if not exit_d.exit_reasons.empty:
            st.dataframe(exit_d.exit_reasons.rename(columns={"motivo": "Motivo di uscita",
                                                              "trade": "Trade"}),
                          use_container_width=True, hide_index=True, key="diag_exit_reasons")

    with d3:
        st.caption(
            "Che piani il motore ha effettivamente eseguito. Il sistema calcola già un rapporto "
            "rischio/rendimento e segnala quelli sfavorevoli: se la quota di trade sfavorevoli è "
            "alta, il backtest sta misurando setup che tu non prenderesti guardandoli a schermo."
        )
        p1, p2, p3 = st.columns(3)
        p1.metric("R:R mediano pianificato", _fmt(plan_d.median_planned_rr))
        p2.metric("Trade già segnalati sfavorevoli", _fmt(plan_d.share_unfavorable_pct, "%", 0))
        p3.metric("Stop dal ripiego ad ATR", _fmt(plan_d.share_stop_from_atr_pct, "%", 0))
        if plan_d.share_unfavorable_pct is not None and plan_d.share_unfavorable_pct >= 30:
            st.error(plan_d.verdict)
        else:
            st.info(plan_d.verdict)
        if not plan_d.rr_distribution.empty:
            st.dataframe(plan_d.rr_distribution, use_container_width=True, hide_index=True,
                          key="diag_rr_dist")

    st.markdown("#### Il segnale, isolato da uscite e costi")
    st.caption(
        "Rendimento medio nelle barre successive a un segnale, confrontato con quello di una barra "
        "qualunque. Non ci sono stop, target, costi né sizing: se dopo un segnale long il prezzo "
        "non sale più di quanto salga in un giorno a caso, il segnale non contiene informazione e "
        "nessuna correzione a valle può salvarlo. Il calcolo ricalcola il segnale barra per barra: "
        "richiede qualche minuto."
    )
    sq_col1, sq_col2 = st.columns([1, 2])
    fwd_bars = sq_col1.slider("Orizzonte (barre)", 5, 60, 20, 5, key="diag_fwd_bars")
    if sq_col2.button("Calcola qualità del segnale", key="diag_signal_quality"):
        if not report.histories:
            st.warning("Storici non disponibili: riesegui il backtest per abilitare questo test.")
        else:
            prog = st.progress(0.0, text="Analisi in corso...")
            with st.spinner("Ricalcolo il segnale barra per barra..."):
                st.session_state["_diag_sq"] = diag.signal_quality(
                    report.histories, horizon=report.horizon, forward_bars=fwd_bars,
                    progress_callback=lambda f, s: prog.progress(min(1.0, f), text=f"Analizzo {s}..."),
                )
            prog.empty()

    sq = st.session_state.get("_diag_sq")
    if sq:
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Dopo un segnale", _fmt(sq.mean_signal_return_pct, "%"))
        q2.metric("Barra qualunque", _fmt(sq.mean_baseline_return_pct, "%"))
        q3.metric("Differenza", _fmt(sq.edge_pct, "%"))
        q4.metric("Segnali analizzati", f"{sq.n_signals}")
        if sq.edge_pct is not None and sq.edge_pct > 0:
            st.success(sq.verdict)
        else:
            st.error(sq.verdict)
        st.caption(
            "La statistica t è indicativa: le osservazioni si sovrappongono nel tempo e non sono "
            "indipendenti, quindi va letta come ordine di grandezza e non come test formale."
        )

disclaimer(
    "Un backtest non è una previsione: è la misura di come un insieme di regole si sarebbe "
    "comportato su dati passati, con tutte le assunzioni dichiarate qui sopra. I risultati fuori "
    "campione e in paper trading sono tipicamente un terzo/metà più deboli dell'in-sample, e "
    "questo decadimento è la norma. I dati provengono da yfinance, che è di qualità retail: "
    "attenzione a rettifiche per split/dividendi e barre mancanti. Le barre daily costringono ad "
    "assumere cosa sia successo dentro la giornata, da cui la regola conservativa dello stop "
    "colpito per primo. Il costo FX di Trade Republic non è pubblicato dopo luglio 2026 ed è qui "
    "una stima prudenziale, non un dato ufficiale. Nulla di tutto questo è consulenza finanziaria "
    "personalizzata."
)
