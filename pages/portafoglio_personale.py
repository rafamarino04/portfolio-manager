"""Portafoglio Personale: la vista unica su tutto ciò che riguarda le
posizioni reali. Registro Transazioni (fonte di verità), allocazione
attuale, confronto con l'allocazione ideale, rendimento dettagliato per
prodotto/portafoglio e confronto con un benchmark di mercato — prima
divisi in quattro pagine separate, ora una sola vista con sezioni
apribili, perché sono letture dello stesso portafoglio, non argomenti
diversi."""
import datetime as dt
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src import benchmark as bm
from src import github_sync
from src import portfolio as pf
from src import rebalancing as rb
from src import report_config as cfg
from src import transactions as tx
from src.portfolio import CATEGORIES
from src.theme import CATEGORY_COLORS, apply_theme, badge, disclaimer

apply_theme()

st.title("Portafoglio Personale")
st.caption(
    f"Aggiornato al {dt.datetime.now().strftime('%d/%m/%Y %H:%M')} · dati Yahoo Finance, "
    "delay tipico 15-20 minuti · solo a scopo informativo, non consulenza finanziaria."
)

TX_PATH = "data/transactions.csv"
PORTFOLIO_PATH = "data/portfolio.csv"


# ---------------------------------------------------------------------------
# Registro Transazioni — fonte di verità, in cima, a tendina
# ---------------------------------------------------------------------------
with st.expander("Registro Transazioni", expanded=False):
    st.caption(
        "Ogni riga è un movimento reale: acquisto, vendita o dividendo. Le posizioni, il P&L "
        "realizzato e il rendimento (XIRR) si calcolano automaticamente da qui."
    )

    if "tx_editor_df" not in st.session_state:
        st.session_state["tx_editor_df"] = tx.load_transactions(TX_PATH)

    def _persist_transactions(clean: pd.DataFrame):
        clean.to_csv(TX_PATH, index=False)
        st.session_state["tx_editor_df"] = tx.load_transactions(TX_PATH)
        positions = tx.compute_positions(tx.load_transactions(TX_PATH))
        positions.to_csv(PORTFOLIO_PATH, index=False)
        st.success("Movimenti salvati e posizioni ricalcolate.")
        if github_sync.is_configured():
            today = dt.date.today().isoformat()
            ok1, msg1 = github_sync.push_csv(TX_PATH, TX_PATH, f"Aggiorna transazioni - {today}")
            ok2, msg2 = github_sync.push_csv(PORTFOLIO_PATH, PORTFOLIO_PATH, f"Ricalcola posizioni - {today}")
            (st.success if ok1 else st.error)(msg1)
            (st.success if ok2 else st.error)(msg2)
        else:
            st.warning(
                "GitHub non collegato: le modifiche potrebbero perdersi al prossimo riavvio. "
                "Configura GITHUB_TOKEN e GITHUB_REPO nei secrets (vedi README)."
            )

    st.markdown("**Aggiungi movimento**")
    with st.form("quick_add_tx", clear_on_submit=True):
        r1 = st.columns([1, 1.3, 1, 1, 1, 1])
        new_date = r1[0].date_input("Data", value=dt.date.today())
        new_ticker = r1[1].text_input("Ticker / etichetta")
        new_type = r1[2].selectbox("Tipo", tx.TRANSACTION_TYPES)
        new_qty = r1[3].number_input("Quantità", min_value=0.0, step=1.0)
        new_price = r1[4].number_input("Prezzo", min_value=0.0, step=0.01)
        new_amount = r1[5].number_input("Importo (dividendi)", min_value=0.0, step=0.01)
        r2 = st.columns([1, 1, 1, 1, 2])
        new_fees = r2[0].number_input("Commissioni", min_value=0.0, step=0.01)
        new_currency = r2[1].text_input("Valuta", value="EUR")
        new_category = r2[2].selectbox("Categoria (solo primo acquisto)", [""] + CATEGORIES)
        new_manual_price = r2[3].number_input("Prezzo manuale", min_value=0.0, step=0.01)
        new_note = r2[4].text_input("Nota (opzionale)")
        quick_submitted = st.form_submit_button("Aggiungi movimento", type="primary")

    if quick_submitted:
        if not new_ticker.strip() or not new_type:
            st.error("Ticker e tipo sono obbligatori.")
        else:
            current = tx.load_transactions(TX_PATH)
            new_row = pd.DataFrame([{
                "date": new_date, "ticker": new_ticker.strip(), "type": new_type,
                "quantity": new_qty or None, "price": new_price or None,
                "amount": new_amount or None, "fees": new_fees or None,
                "currency": new_currency or None, "category": new_category or None,
                "manual_price": new_manual_price or None, "note": new_note or None,
            }])
            updated = pd.concat([current, new_row], ignore_index=True)
            _persist_transactions(updated)
            st.rerun()

    st.divider()
    st.markdown("**Storico completo — visualizza e modifica**")
    with st.container(border=True):
        edited = st.data_editor(
            st.session_state["tx_editor_df"],
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "date": st.column_config.DateColumn("Data", required=True),
                "ticker": st.column_config.TextColumn("Ticker / Etichetta", required=True),
                "type": st.column_config.SelectboxColumn("Tipo", options=tx.TRANSACTION_TYPES, required=True),
                "quantity": st.column_config.NumberColumn("Quantità", min_value=0.0),
                "price": st.column_config.NumberColumn("Prezzo", min_value=0.0),
                "amount": st.column_config.NumberColumn("Importo (dividendi)", min_value=0.0),
                "fees": st.column_config.NumberColumn("Commissioni", min_value=0.0),
                "currency": st.column_config.TextColumn("Valuta"),
                "category": st.column_config.SelectboxColumn("Categoria", options=CATEGORIES),
                "manual_price": st.column_config.NumberColumn("Prezzo manuale", min_value=0.0),
                "note": st.column_config.TextColumn("Note"),
            },
            key="tx_data_editor",
        )
        if st.button("Salva modifiche allo storico", type="primary", key="save_full_editor"):
            clean = edited.dropna(how="all").copy()
            clean["ticker"] = clean["ticker"].astype(str).str.strip()
            bad = clean[(clean["ticker"] == "") | clean["date"].isna() | clean["type"].isna()]
            if not bad.empty:
                st.error("Ci sono righe senza data, ticker o tipo: completale o eliminale prima di salvare.")
            else:
                _persist_transactions(clean)
                st.rerun()

    current_tx = tx.load_transactions(TX_PATH) if os.path.exists(TX_PATH) else pd.DataFrame(columns=tx.COLUMNS)
    if not current_tx.empty:
        realized = tx.compute_realized_pl(current_tx)
        dividends = tx.compute_dividends(current_tx)
        total_realized = realized["realized_pl"].sum() if not realized.empty else 0.0
        total_dividends = dividends["total_dividends"].sum() if not dividends.empty else 0.0
        st.divider()
        rc1, rc2 = st.columns(2)
        rc1.metric("P&L realizzato (vendite chiuse)", f"{total_realized:,.2f}")
        rc2.metric("Dividendi incassati", f"{total_dividends:,.2f}")


# ---------------------------------------------------------------------------
# Dati base per il resto della pagina
# ---------------------------------------------------------------------------
try:
    raw = pf.load_portfolio(PORTFOLIO_PATH)
except Exception as e:
    st.error(f"Errore nel caricare il portafoglio: {e}")
    st.stop()

with st.spinner("Recupero prezzi live..."):
    enriched = pf.enrich_with_prices(raw)

summary = pf.portfolio_summary(enriched)
settings = cfg.load_settings()

xirr_value = None
if os.path.exists(TX_PATH):
    tx_data = tx.load_transactions(TX_PATH)
    if not tx_data.empty:
        xirr_value = tx.compute_xirr(tx_data, current_total_value=summary.get("total_value") or 0)

st.divider()
k1, k2, k3, k4 = st.columns(4)
k1.metric("Valore totale", f"{summary['total_value']:,.2f}" if summary["total_value"] else "n/d")
k2.metric("Costo totale", f"{summary['total_cost']:,.2f}" if summary["total_cost"] else "n/d")
k3.metric(
    "P&L non realizzato",
    f"{summary['total_pl']:,.2f}" if summary["total_pl"] is not None else "n/d",
    f"{summary['total_pl_pct']:.2f}%" if summary["total_pl_pct"] is not None else None,
)
k4.metric("Rendimento reale (XIRR)", f"{xirr_value:.2f}%" if xirr_value is not None else "n/d")


# ---------------------------------------------------------------------------
# Allocazione: torta + confronto con il portafoglio ideale (a tendina)
# ---------------------------------------------------------------------------
st.divider()
col_pie, col_compare = st.columns([1, 1.2])

with col_pie:
    st.subheader("Allocazione")
    if enriched["market_value"].notna().any():
        has_category = "category" in enriched.columns
        alloc_view = st.segmented_control(
            "Vista allocazione", ["Per categoria", "Per titolo"],
            default="Per categoria", key="alloc_view", label_visibility="collapsed",
        ) or "Per categoria"

        names_col = "ticker" if alloc_view == "Per titolo" else ("category" if has_category else "ticker")
        fig = px.pie(
            enriched, values="market_value", names=names_col,
            hole=0.55, color="category" if has_category else None,
            color_discrete_map=CATEGORY_COLORS if has_category else None,
        )
        if alloc_view == "Per titolo":
            fig.update_traces(hovertemplate="%{label}<br>%{value:,.2f} · %{percent}<extra></extra>")
        fig.update_layout(showlegend=True, margin=dict(t=10, b=10))
        st.plotly_chart(fig, use_container_width=True, key="alloc_pie_chart")
    else:
        st.info("Nessun prezzo disponibile per calcolare l'allocazione.")

with col_compare:
    with st.expander("Confronto con il portafoglio ideale", expanded=False):
        with st.container(border=True):
            st.markdown("**Imposta il portafoglio ideale**")
            st.caption("Deve sommare a 100%.")
            new_target = {}
            tcols = st.columns(3)
            for i, cat in enumerate(CATEGORIES):
                new_target[cat] = tcols[i % 3].number_input(
                    cat, min_value=0, max_value=100,
                    value=int(settings["target_allocation"].get(cat, 0)),
                    step=1, key=f"target_{cat}",
                )
            total_target = sum(new_target.values())
            tolerance = st.slider(
                "Banda di tolleranza (%)", min_value=1, max_value=20,
                value=int(settings["rebalance_tolerance_pct"]),
            )
            if total_target == 100:
                st.success(f"Totale: {total_target}%")
            else:
                st.warning(f"Totale: {total_target}% — deve fare 100% per salvare.")
            if st.button("Salva portafoglio ideale", type="primary", key="save_target"):
                if total_target != 100:
                    st.error("L'allocazione ideale deve sommare a 100%.")
                else:
                    new_settings = dict(settings)
                    new_settings["target_allocation"] = new_target
                    new_settings["rebalance_tolerance_pct"] = tolerance
                    cfg.save_settings(new_settings)
                    if github_sync.is_configured():
                        github_sync.push_csv(
                            "data/settings.json", "data/settings.json",
                            f"Aggiorna allocazione ideale - {dt.date.today().isoformat()}",
                        )
                    st.success("Portafoglio ideale salvato.")
                    st.rerun()

        table = rb.compute_rebalancing(enriched, settings["target_allocation"],
                                        tolerance_pct=settings["rebalance_tolerance_pct"])
        if table.empty:
            st.info("Nessuna categoria con target o posizioni da confrontare.")
        else:
            fig_rb = go.Figure()
            fig_rb.add_bar(name="Ideale", x=table["category"], y=table["target_pct"])
            fig_rb.add_bar(name="Reale", x=table["category"], y=table["actual_pct"])
            fig_rb.update_layout(barmode="group", yaxis_title="% del portafoglio", height=320,
                                  margin=dict(t=10, b=10))
            st.plotly_chart(fig_rb, use_container_width=True)

            for _, row in table.iterrows():
                kind = "ok" if row["action"] == "In linea" else ("warn" if "Vendi" in row["action"] else "bad")
                rcols = st.columns([2, 1, 1, 2])
                rcols[0].markdown(f"**{row['category']}**")
                rcols[1].caption(f"Ideale {row['target_pct']:.1f}% · Reale {row['actual_pct']:.1f}%")
                rcols[2].caption(f"Scarto {row['drift_pct']:+.1f}%")
                action_html = badge(row["action"], kind)
                if row["amount_to_trade"] > 0:
                    action_html += f" &nbsp; ~{row['amount_to_trade']:,.0f}"
                rcols[3].markdown(action_html, unsafe_allow_html=True)
            st.caption(f"Banda di tolleranza: ±{settings['rebalance_tolerance_pct']}%.")


# ---------------------------------------------------------------------------
# Rendimento nel dettaglio: prodotti, portafoglio, benchmark
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Rendimento e benchmark")

benchmark_ticker = settings["benchmark_ticker"]
benchmark_name = settings.get("benchmark_name", benchmark_ticker)
preset_labels = [f"{v} ({k})" for k, v in cfg.BENCHMARK_PRESETS.items()]
preset_keys = list(cfg.BENCHMARK_PRESETS.keys())
current_idx = preset_keys.index(benchmark_ticker) if benchmark_ticker in preset_keys else None

bench_choice = st.selectbox(
    "Benchmark di riferimento",
    options=["(personalizzato)"] + preset_labels,
    index=(current_idx + 1) if current_idx is not None else 0,
    key="benchmark_choice",
)
if bench_choice == "(personalizzato)":
    custom_ticker = st.text_input("Ticker benchmark personalizzato", value=benchmark_ticker, key="benchmark_custom")
    chosen_benchmark_ticker = custom_ticker.strip()
    chosen_benchmark_name = chosen_benchmark_ticker
else:
    chosen_benchmark_ticker = preset_keys[preset_labels.index(bench_choice)]
    chosen_benchmark_name = cfg.BENCHMARK_PRESETS[chosen_benchmark_ticker]

if chosen_benchmark_ticker != benchmark_ticker:
    new_settings = dict(settings)
    new_settings["benchmark_ticker"] = chosen_benchmark_ticker
    new_settings["benchmark_name"] = chosen_benchmark_name
    cfg.save_settings(new_settings)
    if github_sync.is_configured():
        github_sync.push_csv("data/settings.json", "data/settings.json",
                              f"Aggiorna benchmark - {dt.date.today().isoformat()}")
    benchmark_ticker, benchmark_name = chosen_benchmark_ticker, chosen_benchmark_name
    st.rerun()

since_inception = bm.since_inception_comparison(raw, summary, benchmark_ticker)
if since_inception:
    b1, b2, b3 = st.columns(3)
    if xirr_value is not None:
        b1.metric("Rendimento portafoglio (XIRR)", f"{xirr_value:.2f}%")
    else:
        b1.metric("Rendimento portafoglio (approssimato)", f"{since_inception['portfolio_return_pct']:.2f}%")
    b2.metric(f"Rendimento {benchmark_name}", f"{since_inception['benchmark_return_pct']:.2f}%")
    compare_value = xirr_value if xirr_value is not None else since_inception["portfolio_return_pct"]
    diff = compare_value - since_inception["benchmark_return_pct"]
    b3.metric("Differenza", f"{diff:+.2f}%", delta=f"{diff:+.2f}%")
    st.caption(f"Periodo confrontato da {since_inception['start_date'].strftime('%d/%m/%Y')} ad oggi.")
else:
    st.info("Dati insufficienti per calcolare il confronto (serve almeno una data di acquisto valida).")

tracked = bm.tracked_history_vs_benchmark("reports/history.csv", benchmark_ticker)
if tracked is not None:
    fig_t = go.Figure()
    fig_t.add_scatter(x=tracked["date"], y=tracked["Portafoglio"], name="Portafoglio", mode="lines+markers")
    fig_t.add_scatter(x=tracked["date"], y=tracked["Benchmark"], name=benchmark_name, mode="lines+markers")
    fig_t.update_layout(title="Base 100 dal primo snapshot", yaxis_title="Indice (base 100)")
    st.plotly_chart(fig_t, use_container_width=True)
else:
    st.info(
        "Non ci sono ancora abbastanza report settimanali salvati per tracciare l'andamento nel "
        "tempo. Il grafico si arricchisce automaticamente ogni lunedì."
    )

st.markdown("**Rendimento per prodotto**")
display_cols = [
    "ticker", "name", "category", "quantity", "buy_price", "price", "price_source",
    "market_value", "pl_abs", "pl_pct", "day_change_pct", "weight_pct",
]
display_cols = [c for c in display_cols if c in enriched.columns]
st.dataframe(
    enriched[display_cols].style.format({
        "buy_price": "{:.2f}", "price": "{:.2f}", "market_value": "{:,.2f}",
        "pl_abs": "{:,.2f}", "pl_pct": "{:.2f}%", "day_change_pct": "{:.2f}%",
        "weight_pct": "{:.1f}%",
    }, na_rep="n/d"),
    use_container_width=True,
    hide_index=True,
)
if "price_source" in enriched.columns and (enriched["price_source"] != "live").any():
    st.caption(
        "price_source 'manuale' = prezzo inserito a mano (obbligazioni/fondi non coperti da Yahoo "
        "Finance) · 'liquidità' = valore nominale, nessun prezzo di mercato · 'n/d' = dato mancante."
    )

st.markdown("**Cosa ha contribuito di più al risultato**")
attribution = bm.performance_attribution(enriched)
if not attribution.empty:
    fig_attr = px.bar(
        attribution, x="ticker", y="pl_abs", color="pl_abs",
        color_continuous_scale=["#E5484D", "#1F252B", "#2FBF71"],
        labels={"pl_abs": "P&L (valore)", "ticker": "Titolo"},
    )
    fig_attr.update_layout(margin=dict(t=10, b=10))
    st.plotly_chart(fig_attr, use_container_width=True)
else:
    st.info("Nessun dato sufficiente per l'attribuzione della performance.")

disclaimer(
    "Il rendimento XIRR tiene conto di quando sono entrati e usciti i soldi; l'approssimazione "
    "'da quando hai iniziato' si usa solo finché il Registro Transazioni non ha dati sufficienti. "
    "Il confronto con il benchmark è puramente informativo — non è consulenza finanziaria "
    "personalizzata."
)
