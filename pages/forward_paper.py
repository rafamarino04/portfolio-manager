"""Forward Paper Trading: il segnale regge in tempo reale?

Stage 3 + impianto dello Stage 4 di BACKTEST AND FORWARD.pdf. Il backtest
dice come il segnale si sarebbe comportato sul passato; il forward lo
verifica su dati che si srotolano in tempo reale, dove non esistono senno
di poi né selezione a posteriori. È la validazione più onesta che si possa
fare senza rischiare denaro — e anche la più lenta, perché un sistema
daily accumula trade con lentezza.

Il motore è lo stesso del backtest (src/engine/), non una riscrittura: è
l'unico modo perché una differenza tra i due risultati significhi
qualcosa.
"""
import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import paper_store
from src import persistence
from src import trading_universe as tu
from src import watchlist as wl
from src.engine import calibration as cal
from src.engine import metrics as mt
from src.engine import paper
from src.theme import ACCENT, BLUE, TEXT_MUTED, apply_theme, badge, disclaimer

apply_theme()

st.title("Forward Paper Trading")
st.caption(
    "Il piano operativo dell'Analisi Tecnica messo alla prova in tempo reale, con capitale "
    "virtuale. Gira da solo ogni giorno feriale a mercato aperto tramite GitHub Actions, quindi "
    "avanza anche quando questa pagina è chiusa. Nessun senno di poi: i trade si aprono e si "
    "chiudono man mano che i dati arrivano."
)

persistence.render_pending_outcome()

state = paper_store.load_state()
config = paper_store.load_config()
closed = state.closed_trades
n_closed = len(closed)


def _symbols() -> list[str]:
    symbols = set(tu.tickers(tu.load_universe()))
    watch = wl.load_watchlist()
    if not watch.empty:
        symbols.update(watch["ticker"].astype(str).str.strip().str.upper().tolist())
    return sorted(s for s in symbols if s and s.lower() != "nan")


symbols = _symbols()

# ---------------------------------------------------------------------------
# Stato del motore
# ---------------------------------------------------------------------------

st.markdown("### Stato")
s1, s2, s3, s4 = st.columns(4)
s1.metric("Trade chiusi", f"{n_closed}")
s2.metric("Posizioni aperte", f"{len(state.open_positions)}")
s3.metric("Equity virtuale", f"{state.equity_eur:,.2f} EUR" if state.started_at else "n/d")
s4.metric("Titoli monitorati", f"{len(symbols)}")

if not symbols:
    st.warning(
        "Universo Trading e Preferiti sono entrambi vuoti: il paper trader non ha nulla su cui "
        "operare. Popola le liste dalla pagina Analisi Tecnica — il job schedulato inizierà a "
        "lavorare dalla prima esecuzione utile."
    )

if state.started_at:
    st.caption(
        f"Avviato il {state.started_at} · ultima esecuzione {state.last_run_at or 'n/d'} · "
        f"parametri congelati il {config.frozen_at or 'non ancora'} · "
        f"rischio {config.risk_pct:g}% per trade · leva "
        f"{'attiva' if config.leverage_enabled else 'disattivata (1,0×)'}"
    )
else:
    st.info(
        "Il paper trading non è ancora partito. Parte da solo alla prima esecuzione del job "
        "schedulato (giorni feriali, 15:00 UTC, a mercato aperto), oppure puoi avviarlo ora "
        "col pulsante qui sotto."
    )

st.caption(
    "**Esecuzione al prezzo corrente.** A differenza del backtest, che riempie all'apertura della "
    "seduta successiva, qui il fill avviene al prezzo del momento in cui il segnale scatta — la "
    "scelta che corrisponde a come opereresti davvero. Il rovescio è che una differenza di "
    "expectancy tra backtest e paper non è attribuibile al solo attrito del mercato: cambia anche "
    "la regola di esecuzione. Per non perdere del tutto l'attribuzione, ogni trade registra anche "
    "l'apertura della seduta (il prezzo a cui il backtest sarebbe entrato) e la differenza è "
    "riportata più sotto come costo del ritardo di esecuzione."
)

if st.button("Aggiorna ora", key="paper_step", disabled=not symbols):
    with st.spinner("Calcolo segnali e aggiorno le posizioni..."):
        if not config.frozen_at:
            config.frozen_at = dt.datetime.now().isoformat(timespec="seconds")
        new_state, events = paper.step(symbols, state, config)
        outcome = persistence.save_and_sync(
            lambda: paper_store.save_state(new_state, config),
            paper_store.CLOSED_TRADES_PATH,
            f"Paper trading - {dt.date.today().isoformat()}")
    persistence.remember_outcome(
        outcome,
        f"Aggiornamento completato: {len(events)} eventi." if events else "Nessun evento: nulla è cambiato.")
    st.session_state["_paper_events"] = [(e.kind, e.symbol, e.message) for e in events]
    st.rerun()

events = st.session_state.pop("_paper_events", None)
if events:
    with st.expander(f"Eventi dell'ultimo aggiornamento ({len(events)})", expanded=True):
        for kind, symbol, message in events:
            st.markdown(f"- **{symbol}** [{kind}] {message}")

st.caption(
    "Il pulsante aggiorna una sola volta. L'avanzamento regolare è affidato al job schedulato: "
    "aggiornare a mano più volte al giorno non accelera l'accumulo di trade, che dipende da quanti "
    "segnali il mercato produce."
)

st.divider()

# ---------------------------------------------------------------------------
# Posizioni aperte
# ---------------------------------------------------------------------------

st.markdown("### Posizioni aperte")
if state.open_positions.empty:
    st.info("Nessuna posizione virtuale aperta.")
else:
    open_view = state.open_positions[[
        "symbol", "direction", "entry_date", "entry_price", "stop", "target",
        "initial_risk_eur", "confidence", "mae_r", "mfe_r", "bars_held",
    ]].rename(columns={
        "symbol": "Simbolo", "direction": "Direzione", "entry_date": "Ingresso",
        "entry_price": "Prezzo", "stop": "Stop", "target": "Target",
        "initial_risk_eur": "Rischio (EUR)", "confidence": "Confidenza",
        "mae_r": "MAE (R)", "mfe_r": "MFE (R)", "bars_held": "Barre",
    })
    st.dataframe(open_view, use_container_width=True, hide_index=True, key="paper_open")

st.divider()

# ---------------------------------------------------------------------------
# Risultati
# ---------------------------------------------------------------------------

st.markdown("### Risultati del forward")

if n_closed == 0:
    st.info(
        "Nessun trade chiuso finora. Un sistema daily accumula lentamente: servono settimane o "
        "mesi per un campione utile, ed è normale. La specifica indica 50-100 trade chiusi prima "
        "di confrontare l'expectancy del paper con quella del backtest."
    )
else:
    net_r = pd.to_numeric(closed["net_r"], errors="coerce").dropna()
    net_pnl = pd.to_numeric(closed["net_pnl_eur"], errors="coerce").dropna()
    wins = int((net_pnl > 0).sum())
    ci_low, ci_high = mt.wilson_interval(wins, len(net_pnl))

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Expectancy (R)", f"{net_r.mean():.2f}R" if not net_r.empty else "n/d")
    r2.metric("P&L netto", f"{net_pnl.sum():,.2f} EUR")
    r3.metric("Win rate", f"{wins / len(net_pnl) * 100:.1f}%")
    r3.caption(f"Wilson 95%: {ci_low * 100:.1f}% – {ci_high * 100:.1f}% su {len(net_pnl)} trade")
    r4.metric("Costi totali", f"{pd.to_numeric(closed['costs_eur'], errors='coerce').sum():,.2f} EUR")

    if n_closed < 50:
        st.error(
            f"Solo {n_closed} trade chiusi: sotto i 50 i risultati sono dominati da pochi outlier "
            "e non vanno interpretati. I numeri qui sopra servono a vedere che il motore gira, non "
            "a trarre conclusioni."
        )
    elif n_closed < 100:
        st.warning(
            f"{n_closed} trade chiusi: indicativi ma sotto la soglia di affidabilità di 100 "
            "(idealmente 200+)."
        )
    else:
        st.success(f"{n_closed} trade chiusi: campione sufficiente per una lettura affidabile.")

    # --- Costo del ritardo di esecuzione ---
    delay = pd.to_numeric(closed.get("execution_delay_r"), errors="coerce").dropna()
    if not delay.empty:
        st.markdown("#### Costo del ritardo di esecuzione")
        st.caption(
            "Differenza, in multipli di rischio, tra entrare al prezzo corrente (come fa il paper) "
            "ed entrare all'apertura della seduta (come fa il backtest). Un valore negativo "
            "significa che aspettare l'apertura sarebbe stato meglio. È l'unica parte della "
            "differenza tra backtest e paper che si può isolare con certezza."
        )
        d1, d2 = st.columns(2)
        d1.metric("Impatto medio", f"{delay.mean():+.3f}R per trade")
        d2.metric("Impatto cumulato", f"{delay.sum():+.2f}R")

    # --- Curva di equity del paper ---
    if "exit_date" in closed.columns:
        curve = closed.copy()
        curve["exit_date"] = pd.to_datetime(curve["exit_date"], errors="coerce")
        curve = curve.dropna(subset=["exit_date"]).sort_values("exit_date")
        curve["equity"] = config.initial_equity_eur + pd.to_numeric(
            curve["net_pnl_eur"], errors="coerce").fillna(0).cumsum()
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=curve["exit_date"], y=curve["equity"],
                                  name="Paper (netto)", line=dict(color=ACCENT, width=2)))
        fig.add_hline(y=config.initial_equity_eur, line=dict(color=TEXT_MUTED, dash="dot"))
        fig.update_layout(height=340, margin=dict(t=30, b=30), yaxis_title="Equity (EUR)",
                          legend=dict(orientation="h", y=1.12))
        st.plotly_chart(fig, use_container_width=True, key="paper_equity")

    with st.expander(f"Registro dei {n_closed} trade chiusi"):
        cols = [c for c in ["symbol", "direction", "signal_date", "entry_date", "entry_price",
                            "reference_open_price", "exit_date", "exit_price", "exit_reason",
                            "confidence", "net_r", "net_pnl_eur", "costs_eur",
                            "execution_delay_r", "mae_r", "mfe_r", "bars_held"]
                if c in closed.columns]
        st.dataframe(closed[cols], use_container_width=True, hide_index=True, key="paper_closed")

st.divider()

# ---------------------------------------------------------------------------
# Confronto con il backtest
# ---------------------------------------------------------------------------

st.markdown("### Backtest vs Forward")
report = st.session_state.get("_bt_report")
if not report or not report.in_sample:
    st.info(
        "Esegui un backtest dalla pagina Backtest per vedere qui il confronto affiancato. "
        "Il confronto è il motivo per cui il forward esiste: da solo, un risultato paper non dice "
        "se il segnale sta reggendo o se il backtest era illusorio."
    )
else:
    rows = []
    for seg in (report.in_sample, report.out_of_sample):
        if seg is None:
            continue
        m = seg.metrics
        rows.append({
            "Segmento": m.label, "Trade": m.n_trades,
            "Expectancy (R)": f"{m.expectancy_r:.2f}" if m.expectancy_r is not None else "n/d",
            "Win rate": f"{m.win_rate * 100:.1f}%" if m.win_rate is not None else "n/d",
        })
    if n_closed:
        paper_r = pd.to_numeric(closed["net_r"], errors="coerce").dropna()
        paper_pnl = pd.to_numeric(closed["net_pnl_eur"], errors="coerce").dropna()
        paper_wins = int((paper_pnl > 0).sum())
        rows.append({
            "Segmento": "Forward (paper)", "Trade": n_closed,
            "Expectancy (R)": f"{paper_r.mean():.2f}" if not paper_r.empty else "n/d",
            "Win rate": f"{paper_wins / len(paper_pnl) * 100:.1f}%" if len(paper_pnl) else "n/d",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, key="paper_vs_bt")
    st.caption(
        "Aspettati che il forward sia più debole: il decadimento fuori campione è la norma, con "
        "cali tipici di un terzo o metà. Un forward migliore dell'in-sample non è un trionfo ma un "
        "motivo di sospetto — di norma segnala un campione ancora piccolo."
    )

st.divider()

# ---------------------------------------------------------------------------
# Calibrazione della confidenza (Stage 4)
# ---------------------------------------------------------------------------

st.markdown("### Calibrazione della confidenza")
st.caption(
    "Il punteggio di confidenza significa quello che dice? Se i segnali etichettati '70' vincono "
    "davvero circa il 70% delle volte è calibrato, altrimenti è decorazione. È il cancello "
    "empirico che la specifica pone prima di anche solo considerare una leva scalata sulla "
    "confidenza: la leva amplifica l'errore di stima, quindi scalarla su un punteggio non "
    "calibrato metterebbe più capitale proprio dove il modello si illude di più."
)

calib = cal.build_calibration(closed)

if calib.leverage_gate_passed:
    st.success(f"Cancello superato. {calib.gate_reason}")
else:
    st.warning(f"Cancello non superato — la leva resta a 1,0×. {calib.gate_reason}")

for note in calib.notes:
    st.caption(note)

points = cal.reliability_points(calib)
if not points.empty and points["Trade"].sum() > 0:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines", name="Calibrazione perfetta",
                              line=dict(color=TEXT_MUTED, dash="dot")))
    valid = points.dropna(subset=["Win rate realizzato"])
    if not valid.empty:
        fig.add_trace(go.Scatter(
            x=valid["Confidenza predetta"], y=valid["Win rate realizzato"],
            mode="markers+text", text=valid["Banda"], textposition="top center",
            name="Bande osservate", marker=dict(color=ACCENT, size=12),
            error_y=dict(type="data", symmetric=False,
                          array=(valid["CI 95% alto"] - valid["Win rate realizzato"]),
                          arrayminus=(valid["Win rate realizzato"] - valid["CI 95% basso"]),
                          color=BLUE),
        ))
    fig.update_layout(height=380, margin=dict(t=30, b=30),
                      xaxis=dict(title="Confidenza predetta", range=[0, 1]),
                      yaxis=dict(title="Win rate realizzato", range=[0, 1]),
                      legend=dict(orientation="h", y=1.12))
    st.plotly_chart(fig, use_container_width=True, key="paper_calibration")

    display = points.copy()
    for col in ("Confidenza predetta", "Win rate realizzato", "CI 95% basso", "CI 95% alto"):
        display[col] = display[col].apply(lambda v: f"{v * 100:.1f}%" if pd.notna(v) else "n/d")
    display["R medio"] = display["R medio"].apply(lambda v: f"{v:+.2f}R" if pd.notna(v) else "n/d")
    st.dataframe(display, use_container_width=True, hide_index=True, key="paper_calib_table")
    st.caption(
        f"Una banda è interpretabile da {cal.MIN_TRADES_PER_BUCKET} trade in su. Sotto quella "
        "soglia l'intervallo di Wilson è così largo che quasi tutto risulterebbe 'calibrato': è "
        "il punto in cui un diagramma di affidabilità inganna più facilmente."
    )
    if calib.mean_absolute_error is not None:
        st.metric("Errore medio di calibrazione", f"{calib.mean_absolute_error * 100:.1f} punti")
else:
    st.info("Nessun trade con confidenza registrata: il diagramma comparirà appena il forward chiude i primi trade.")

disclaimer(
    "Il paper trading usa capitale virtuale e prezzi Yahoo Finance con delay tipico di 15-20 "
    "minuti: il prezzo di ingresso registrato non è quello che avresti ottenuto al millisecondo. "
    "Il motore è identico a quello del backtest tranne che per la regola di esecuzione (prezzo "
    "corrente invece che apertura successiva), scelta dichiarata. La leva è disattivata e lo "
    "resterà finché la calibrazione non supera il proprio cancello. Un forward positivo su pochi "
    "trade non dimostra nulla: il campione è il vincolo stringente, e lo resterà a lungo. Nulla "
    "di tutto questo è consulenza finanziaria personalizzata."
)
