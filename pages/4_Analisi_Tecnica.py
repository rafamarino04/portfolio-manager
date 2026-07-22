"""Analisi Tecnica: hub decisionale sui singoli titoli, ricostruito
secondo Specifica_Analisi_Tecnica_Murphy.md. Tre sezioni — Portafoglio,
Preferiti e Cerca — tutte appoggiate sullo stesso motore (src/technical.py):
trend strutturale (Dow) riconciliato con l'allineamento delle medie,
oscillatori letti nel contesto del trend, volume/OBV, pattern grafici e
candlestick filtrati per affidabilità, e un motore di sintesi a due
numeri distinti — Directional Score e Agreement Index — che separa
esplicitamente "neutro per assenza di direzione" da "conflitto tra
segnali", invece di appiattire tutto in un unico punteggio ambiguo."""
import datetime as dt
import os

import pandas as pd
import streamlit as st

from src import alerts
from src import data_provider as dp
from src import github_sync
from src import portfolio as pf
from src import technical as tech
from src import technical_view as tv
from src import watchlist as wl
from src.auth import check_password
from src.portfolio import CASH_CATEGORY
from src.theme import apply_theme, badge, disclaimer

st.set_page_config(page_title="Analisi Tecnica", page_icon="\U0001F4C8", layout="wide")
apply_theme()

if not check_password():
    st.stop()

st.title("\U0001F4C8 Analisi Tecnica")
st.caption(
    "Portafoglio e Preferiti sono già pronti da analizzare, senza doverli ricercare — usa Cerca "
    "per qualsiasi altro titolo. Il motore riconcilia trend strutturale e medie mobili prima di dare "
    "un verdetto, e la sintesi finale mostra due numeri distinti — Directional Score e Agreement "
    "Index — invece di un unico punteggio che confonde 'senza direzione' con 'segnali in conflitto'."
)

PORTFOLIO_PATH = "data/portfolio.csv"
WATCHLIST_PATH = "data/watchlist.csv"

HORIZON_LABEL_TO_KEY = {v["label"]: k for k, v in tech.HORIZONS.items()}


def _verdict_badge_kind(verdict: str) -> str:
    if verdict.startswith("Rialzista"):
        return "ok"
    if verdict.startswith("Ribassista"):
        return "bad"
    if "Conflitto" in verdict:
        return "bad"
    if "Neutro" in verdict:
        return "info"
    return "warn"  # "Direzione debole e contrastata: cautela"


def _push_watchlist():
    if github_sync.is_configured():
        ok, msg = github_sync.push_csv(WATCHLIST_PATH, WATCHLIST_PATH,
                                        f"Aggiorna preferiti - {dt.date.today().isoformat()}")
        (st.success if ok else st.error)(msg)


def render_ticker_analysis(symbol: str, key_prefix: str, entry_price: float | None = None,
                            entry_label: str = "prezzo di riferimento", default_horizon: str = "medio"):
    """Blocco completo per un ticker: intestazione, orizzonte temporale,
    Directional Score + Agreement Index, grafico+oscillatori+volume,
    contesto sul prezzo di ingresso (se fornito), analisi sezionata con
    flag tematici e sintesi finale, piano operativo. Riutilizzato
    identico dalle tre sezioni della pagina."""
    info = dp.get_info(symbol)
    st.subheader(f"{info.get('name', symbol)} ({symbol})")

    horizon_options = list(HORIZON_LABEL_TO_KEY.keys())
    default_idx = list(tech.HORIZONS.keys()).index(default_horizon)
    chosen_label = st.selectbox("Orizzonte temporale del grafico e dell'analisi", horizon_options,
                                 index=default_idx, key=f"{key_prefix}_horizon")
    horizon = HORIZON_LABEL_TO_KEY[chosen_label]

    with st.spinner("Calcolo indicatori..."):
        snap = tech.technical_snapshot(symbol, horizon)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Prezzo", f"{snap['price']:,.2f}" if snap and snap.get("price") else "n/d")
    c2.metric("Settore", info.get("sector") or "n/d")
    c3.metric("Range 52 sett.",
              f"{info.get('week52_low', 0):,.2f} - {info.get('week52_high', 0):,.2f}"
              if info.get("week52_low") else "n/d")
    c4.metric("P/E", f"{info.get('pe_ratio'):.1f}" if info.get("pe_ratio") else "n/d")

    if snap is None:
        st.warning("Dati storici insufficienti per questo ticker/orizzonte. Prova un altro orizzonte.")
        return

    synthesis = snap["synthesis"]
    d1, d2, d3 = st.columns([1, 1, 2])
    d1.metric("Directional Score", f"{synthesis['D']:+.2f}")
    d1.caption("-1 fortemente ribassista … +1 fortemente rialzista")
    d2.metric("Agreement Index", f"{synthesis['A']:.2f}")
    d2.caption("0 = famiglie in conflitto, 1 = pienamente allineate")
    d3.markdown(f"**Verdetto**<br>{badge(synthesis['verdict'], _verdict_badge_kind(synthesis['verdict']))}",
                unsafe_allow_html=True)
    d3.caption(f"{synthesis['n_families']} famiglie di indicatori considerate (Trend, Medie, Momentum, "
               f"Volume, Pattern, Candlestick, Volatilità).")

    if entry_price:
        ctx = tech.entry_context(snap, entry_price)
        if ctx:
            st.markdown(f"##### Rispetto al tuo {entry_label} ({entry_price:,.2f})")
            e1, e2 = st.columns(2)
            e1.metric("Variazione da ingresso", f"{ctx['pl_pct']:+.1f}%")
            kind = "ok" if ctx["pl_pct"] >= 0 else "bad"
            e2.markdown(f"**Stato**<br>{badge('In guadagno' if ctx['pl_pct'] >= 0 else 'In perdita', kind)}",
                        unsafe_allow_html=True)
            for note in ctx["notes"][1:]:
                st.markdown(f"- {note}")

    fig = tv.build_price_chart(snap)
    st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_price_chart")
    osc = tv.build_oscillator_chart(snap)
    st.plotly_chart(osc, use_container_width=True, key=f"{key_prefix}_osc_chart")

    st.markdown("### Livelli e valori numerici")
    rows = tech.numeric_summary(snap)
    if rows:
        st.dataframe(
            pd.DataFrame(rows, columns=["Indicatore", "Valore"]),
            use_container_width=True, hide_index=True, key=f"{key_prefix}_numeric_table",
        )

    st.markdown("### Analisi dettagliata")
    narrative = tech.build_narrative(snap, entry_price=entry_price)
    if narrative:
        for sec in narrative["sections"]:
            with st.container(border=True):
                st.markdown(
                    f"**{sec['icon']} {sec['title']}** "
                    f"{badge(tech.VERDICT_LABELS[sec['verdict']], tech.VERDICT_BADGE_KIND[sec['verdict']])}",
                    unsafe_allow_html=True,
                )
                st.write(sec["text"])

        if snap.get("thematic_flags"):
            st.markdown("#### \U0001F3F7️ Flag tematici")
            st.caption(
                "Segnali che raccontano la stessa storia, raggruppati in un unico tema invece di "
                "disperdersi in più 'neutri' separati."
            )
            for flag in snap["thematic_flags"]:
                st.markdown(f"- {flag}")

        st.markdown("#### \U0001F9ED Sintesi")
        st.info(narrative["synthesis"])
    else:
        st.info("Nessun segnale rilevante al momento.")

    st.markdown("### \U0001F3AF Piano operativo")
    st.caption(
        "Uno schema di ingresso/stop/target costruito solo su livelli tecnici oggettivi (supporti, "
        "resistenze, ATR, obiettivi di figura) — un modello da adattare, non un ordine pronto. Se il "
        "quadro non è direzionale (Directional Score o Agreement Index bassi) l'app si rifiuta di "
        "proporne uno, invece di forzare un piano su un quadro indecidibile."
    )
    plan = tech.trade_plan(snap)
    if not plan or plan["bias"] == "nessun_setup":
        motivo = plan.get("reason") if plan else None
        st.info(
            "Il quadro tecnico attuale non è abbastanza direzionale o concorde per costruire un piano "
            "operativo" + (f" ({motivo})." if motivo else ".") +
            " Aspettare un'impostazione più chiara è spesso la scelta più prudente."
        )
    else:
        bias_kind = "ok" if plan["bias"] == "long" else "bad"
        p1, p2, p3, p4 = st.columns(4)
        p1.markdown(f"**Impostazione**<br>{badge(plan['bias'].upper(), bias_kind)}", unsafe_allow_html=True)
        p2.metric("Ingresso", f"{plan['entry']:,.2f}")
        p3.metric("Stop", f"{plan['stop']:,.2f}", f"{plan['stop'] - plan['entry']:+.2f}")
        p4.metric("Target", f"{plan['target']:,.2f}", f"{plan['target'] - plan['entry']:+.2f}")
        rr = plan.get("risk_reward")
        rr_kind = "bad" if plan.get("rr_unfavorable") else ("ok" if rr and rr >= 2 else "warn")
        st.markdown(
            f"Rapporto rischio/rendimento: {badge(f'{rr:.2f}' if rr else 'n/d', rr_kind)} "
            f"(rischio {plan['risk']:.2f}, rendimento potenziale {plan['reward']:.2f})"
            + (" — sotto 1:1,5, segnalato come sfavorevole." if plan.get("rr_unfavorable") else ""),
            unsafe_allow_html=True,
        )
        st.caption(f"Stop basato su: {plan['stop_basis']}. Target basato su: {plan['target_basis']}.")

    with st.expander("News recenti"):
        news = dp.get_news(symbol, limit=6)
        if news:
            for n in news:
                link = n.get("link")
                title = n.get("title")
                publisher = n.get("publisher") or ""
                st.markdown(f"- [{title}]({link}) · *{publisher}*" if link else f"- {title} · *{publisher}*")
        else:
            st.info("Nessuna news trovata per questo ticker al momento.")


tab_portfolio, tab_favorites, tab_search = st.tabs(
    ["\U0001F4BC Portafoglio", "⭐ Preferiti", "\U0001F50D Cerca"]
)

with tab_portfolio:
    if os.path.exists(PORTFOLIO_PATH):
        positions = pf.load_portfolio(PORTFOLIO_PATH)
        if "category" in positions.columns:
            positions = positions[positions["category"] != CASH_CATEGORY]
    else:
        positions = pd.DataFrame()

    if positions.empty:
        st.info("Nessun titolo in portafoglio. Aggiungili dal Registro Transazioni.")
    else:
        tickers = sorted(positions["ticker"].unique())
        chosen = st.selectbox("Titolo in portafoglio", tickers, key="pf_ticker")
        row = positions[positions["ticker"] == chosen].iloc[0]
        buy_price = float(row["buy_price"]) if pd.notna(row.get("buy_price")) else None
        qty = float(row["quantity"]) if pd.notna(row.get("quantity")) else None
        if qty is not None:
            st.caption(f"Quantità in portafoglio: {qty:g}" +
                       (f" · prezzo medio di carico: {buy_price:,.2f}" if buy_price else ""))
        render_ticker_analysis(chosen, key_prefix="pf", entry_price=buy_price,
                                entry_label="prezzo medio di carico")

with tab_favorites:
    watch_df = wl.load_watchlist(WATCHLIST_PATH)

    st.markdown("**Gestisci i preferiti**")
    with st.form("add_favorite_form", clear_on_submit=True):
        f1, f2, f3, f4 = st.columns([2, 1, 2, 1])
        new_ticker = f1.text_input("Ticker", key="fav_new_ticker")
        new_ref_price = f2.number_input("Prezzo di riferimento (opzionale)", min_value=0.0, value=0.0, step=0.01)
        new_note = f3.text_input("Nota (opzionale)", key="fav_new_note")
        submitted = f4.form_submit_button("➕ Aggiungi")
    if submitted and new_ticker.strip():
        watch_df = wl.add_ticker(watch_df, new_ticker, new_ref_price or None, new_note)
        wl.save_watchlist(watch_df, WATCHLIST_PATH)
        _push_watchlist()
        st.success(f"{new_ticker.strip().upper()} aggiunto ai preferiti.")
        st.rerun()

    if watch_df.empty:
        st.info("Nessun titolo nei preferiti. Aggiungine uno sopra.")
    else:
        st.dataframe(
            watch_df.rename(columns={"ticker": "Ticker", "reference_price": "Prezzo riferimento",
                                      "note": "Nota", "added_date": "Aggiunto il"}),
            use_container_width=True, hide_index=True,
        )
        remove_choice = st.selectbox("Rimuovi dai preferiti", ["—"] + sorted(watch_df["ticker"].unique()),
                                      key="fav_remove")
        if remove_choice != "—" and st.button("\U0001F5D1️ Rimuovi", key="fav_remove_btn"):
            watch_df = wl.remove_ticker(watch_df, remove_choice)
            wl.save_watchlist(watch_df, WATCHLIST_PATH)
            _push_watchlist()
            st.rerun()

        st.divider()
        st.markdown("**\U0001F514 Avvisi sui preferiti**")
        st.caption(
            "Segnala eventi tecnici recenti su ogni titolo preferito: incrocio RSI 70/30, incrocio "
            "MACD/segnale, rottura di supporto/resistenza, candela o figura di prezzo rilevata "
            "sull'orizzonte medio termine. Va ricalcolato manualmente ad ogni visita."
        )
        if st.button("\U0001F50E Scansiona preferiti", key="scan_favorites"):
            with st.spinner("Scansione dei preferiti in corso..."):
                st.session_state["_fav_scan"] = alerts.scan_watchlist(list(watch_df["ticker"].unique()))

        scan_results = st.session_state.get("_fav_scan")
        if scan_results:
            any_alert = False
            for res in scan_results:
                if res["snapshot"] is None:
                    continue
                if res["alerts"]:
                    any_alert = True
                    st.markdown(f"**{res['symbol']}**")
                    for a in res["alerts"]:
                        kind = ("ok" if a["direction"] == "rialzista"
                                else "bad" if a["direction"] == "ribassista" else "info")
                        st.markdown(f"{badge(a['type'], kind)} {a['message']}", unsafe_allow_html=True)
            if not any_alert:
                st.info("Nessun evento tecnico rilevante sui preferiti al momento.")

        st.divider()
        chosen_fav = st.selectbox("Analizza un preferito", sorted(watch_df["ticker"].unique()), key="fav_ticker")
        ref_price = wl.reference_price_for(watch_df, chosen_fav)
        render_ticker_analysis(chosen_fav, key_prefix="fav", entry_price=ref_price,
                                entry_label="prezzo di riferimento")

with tab_search:
    symbol = st.text_input("Ticker (es. AAPL, ENI.MI, SWDA.MI, VWCE.DE)", value="AAPL",
                            key="search_ticker").strip().upper()
    if symbol:
        search_watch_df = wl.load_watchlist(WATCHLIST_PATH)
        if not wl.is_watched(search_watch_df, symbol) and st.button("⭐ Aggiungi ai Preferiti", key="search_add_fav"):
            search_watch_df = wl.add_ticker(search_watch_df, symbol)
            wl.save_watchlist(search_watch_df, WATCHLIST_PATH)
            _push_watchlist()
            st.success(f"{symbol} aggiunto ai preferiti.")
        render_ticker_analysis(symbol, key_prefix="search")

disclaimer(
    "L'analisi tecnica descrive schemi statistici passati nei prezzi, non previsioni certe. Il "
    "Directional Score e l'Agreement Index sono una lettura quantitativa delle famiglie di indicatori "
    "considerate, non un segnale operativo validato da un backtest. Gli oscillatori danno falsi segnali "
    "nei trend forti, i pattern grafici falliscono, le candele su base giornaliera sono rumorose: da qui "
    "la disciplina della concordanza tra famiglie. Il contesto sul prezzo di ingresso è puramente "
    "descrittivo — non è consulenza finanziaria personalizzata né un'indicazione operativa. Le decisioni "
    "restano tue."
)
