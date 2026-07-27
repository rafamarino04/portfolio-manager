"""Analisi Tecnica: hub decisionale sui singoli titoli, ricostruito
secondo Specifica_Analisi_Tecnica_Murphy.md. Tre sezioni — Portafoglio,
Preferiti e Cerca — tutte appoggiate sullo stesso motore (src/technical.py):
trend strutturale (Dow) riconciliato con l'allineamento delle medie,
oscillatori letti nel contesto del trend, volume/OBV, pattern grafici e
candlestick filtrati per affidabilità, e un motore di sintesi a due
numeri distinti — Directional Score e Agreement Index — che separa
esplicitamente "neutro per assenza di direzione" da "conflitto tra
segnali", invece di appiattire tutto in un unico punteggio ambiguo.

Gerarchia dei timeframe (Prompt_Cowork_Gerarchia_Orizzonti.md, §0.2 della
spec Murphy): ogni analisi calcola sempre anche l'orizzonte immediatamente
superiore e mostra un indicatore di ALLINEAMENTO TRA ORIZZONTI
(CONCORDE/DISCORDE/NEUTRO/N/D), una sintesi compatta sui tre orizzonti e
un'etichetta CONTRO-TREND sui piani operativi che vanno contro il trend
dell'orizzonte superiore — senza mai sopprimerli.

Quarta sezione — Idoneità al Trading (Prompt_Cowork_Technical_Tradeability_
Score.md, src/tradeability.py): non l'analisi del singolo titolo per il
timing, ma un punteggio assoluto 0-100 sull'universo portafoglio+preferiti
che misura quanto ogni strumento è STRUTTURALMENTE adatto a un sistema di
trading tecnico trend-following (liquidità, volatilità, trendiness, gap,
sensibilità earnings, autocorrelazione) — non è un segnale operativo."""
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
from src import tradeability as trd
from src import watchlist as wl
from src.portfolio import CASH_CATEGORY
from src.theme import apply_theme, badge, disclaimer

apply_theme()

st.title("Analisi Tecnica")
st.caption(
    "Portafoglio e Preferiti sono già pronti da analizzare, senza doverli ricercare — usa Cerca "
    "per qualsiasi altro titolo. Il motore riconcilia trend strutturale e medie mobili prima di dare "
    "un verdetto, e la sintesi finale mostra due numeri distinti — Directional Score e Agreement "
    "Index — invece di un unico punteggio che confonde 'senza direzione' con 'segnali in conflitto'. "
    "Gli orizzonti breve/medio/lungo non sono più calcolati in isolamento: ogni analisi confronta "
    "sempre l'orizzonte scelto con quello immediatamente superiore (gerarchia dei timeframe, Murphy "
    "§0.2) e segnala esplicitamente quando un piano operativo va contro il trend di fondo."
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


def _alignment_badge_kind(status: str) -> str:
    """Colori del badge di ALLINEAMENTO TRA ORIZZONTI (FIX 2 di
    Prompt_Cowork_Gerarchia_Orizzonti.md): CONCORDE positivo, DISCORDE
    negativo, NEUTRO come avviso (nessun conflitto ma nessuna conferma),
    N/D informativo (orizzonte più alto o dati insufficienti)."""
    return {"CONCORDE": "ok", "DISCORDE": "bad", "NEUTRO": "warn", "N/D": "info"}.get(status, "info")


def _alignment_caption(horizon: str, alignment: dict) -> str:
    """Testo generato dai valori reali dell'allineamento — mai un template
    fisso — che indica sempre quale orizzonte superiore è di riferimento e
    quale verdetto esprime (FIX 2), chiarendo nel caso NEUTRO che l'assenza
    di conflitto non equivale a una conferma."""
    status = alignment["status"]
    sup = alignment.get("superior_horizon")
    if status == "N/D":
        if alignment.get("reason") == "dati_insufficienti":
            return f"Dati storici insufficienti per calcolare l'orizzonte superiore a {horizon}."
        return f"L'orizzonte {horizon} è il più alto della catena: nessun orizzonte superiore a cui applicare la gerarchia."
    label = alignment["superior_verdict_label"]
    if status == "NEUTRO":
        return (f"Orizzonte superiore: {sup} — {label}. Nessun conflitto con l'orizzonte selezionato, ma "
                "l'assenza di conflitto non equivale a una conferma.")
    return f"Orizzonte superiore: {sup} — {label}."


def _render_multi_horizon_summary(multi: dict):
    """FIX 5: sintesi compatta multi-orizzonte, sempre visibile — primo
    elemento che l'utente guarda per orientarsi, prima di scendere nel
    dettaglio dell'orizzonte selezionato più sotto nella pagina."""
    summary = tech.multi_horizon_summary(multi)
    plan_label = {"long": "LONG", "short": "SHORT", "nessun_piano": "Nessun piano"}
    plan_kind = {"long": "ok", "short": "bad", "nessun_piano": "info"}

    st.markdown("##### Sintesi multi-orizzonte")
    st.caption(
        "Verdetto di trend, Directional Score e direzione del piano operativo sui tre orizzonti — "
        "prima di scegliere quale approfondire qui sotto, guarda se concordano o divergono."
    )
    cols = st.columns(3)
    for col, row in zip(cols, summary["rows"]):
        with col:
            st.markdown(f"**{row['label'].split(' (')[0]}**")
            if not row.get("available"):
                st.caption("Dati storici insufficienti su questo orizzonte.")
                continue
            st.markdown(
                badge(tech.VERDICT_LABELS.get(row["trend_simple"], row["trend_simple"].capitalize()),
                      tech.VERDICT_BADGE_KIND.get(row["trend_simple"], "info")),
                unsafe_allow_html=True,
            )
            st.caption(f"Directional Score {row['D']:+.2f}")
            st.markdown(badge(plan_label.get(row["plan_direction"], "n/d"),
                               plan_kind.get(row["plan_direction"], "info")), unsafe_allow_html=True)
    st.info(summary["reading"])


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

    with st.spinner("Calcolo indicatori sui tre orizzonti..."):
        multi = tech.multi_horizon_analysis(symbol)
    snap = multi[horizon]["snapshot"]
    alignment = multi[horizon]["alignment"]
    superior_snap = multi[horizon]["superior_snapshot"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Prezzo", f"{snap['price']:,.2f}" if snap and snap.get("price") else "n/d")
    c2.metric("Settore", info.get("sector") or "n/d")
    c3.metric("Range 52 sett.",
              f"{info.get('week52_low', 0):,.2f} - {info.get('week52_high', 0):,.2f}"
              if info.get("week52_low") else "n/d")
    c4.metric("P/E", f"{info.get('pe_ratio'):.1f}" if info.get("pe_ratio") else "n/d")

    st.divider()
    _render_multi_horizon_summary(multi)
    st.divider()

    if snap is None:
        st.warning("Dati storici insufficienti per questo ticker/orizzonte. Prova un altro orizzonte.")
        return

    synthesis = snap["synthesis"]
    d1, d2, d3, d4 = st.columns([1, 1, 1.3, 1.6])
    d1.metric("Directional Score", f"{synthesis['D']:+.2f}")
    d1.caption("-1 fortemente ribassista … +1 fortemente rialzista")
    d2.metric("Agreement Index", f"{synthesis['A']:.2f}")
    d2.caption(
        f"Coerenza interna all'orizzonte {horizon}: accordo solo tra le famiglie di indicatori di questo "
        "orizzonte — non una misura di affidabilità assoluta del segnale."
    )
    d3.markdown(f"**Verdetto**<br>{badge(synthesis['verdict'], _verdict_badge_kind(synthesis['verdict']))}",
                unsafe_allow_html=True)
    d3.caption(f"{synthesis['n_families']} famiglie di indicatori considerate (Trend, Medie, Momentum, "
               f"Volume, Pattern, Candlestick, Volatilità).")
    d4.markdown(
        f"**Allineamento tra orizzonti**<br>{badge(alignment['status'], _alignment_badge_kind(alignment['status']))}",
        unsafe_allow_html=True,
    )
    d4.caption(_alignment_caption(horizon, alignment))

    st.caption(
        f"Confidenza complessiva: {tech.overall_confidence(synthesis['A'], alignment['status']):.2f} — "
        "Agreement Index corretto per l'allineamento tra orizzonti (stima editoriale interna, non un "
        "indicatore validato da backtest)."
    )
    if alignment["status"] == "DISCORDE":
        st.warning(
            f"Coerenza interna all'orizzonte {horizon}: {synthesis['A']:.2f} — ma il quadro è discorde "
            f"rispetto al trend di {alignment['superior_horizon']} termine "
            f"({alignment['superior_verdict_label']}). Un Agreement Index alto qui misura solo l'accordo "
            "tra le famiglie di indicatori di questo orizzonte, non la solidità del segnale nel quadro "
            "complessivo tra orizzonti."
        )

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
                    f"**{sec['title']}** "
                    f"{badge(tech.VERDICT_LABELS[sec['verdict']], tech.VERDICT_BADGE_KIND[sec['verdict']])}",
                    unsafe_allow_html=True,
                )
                st.write(sec["text"])

        if snap.get("thematic_flags"):
            st.markdown("#### Flag tematici")
            st.caption(
                "Segnali che raccontano la stessa storia, raggruppati in un unico tema invece di "
                "disperdersi in più 'neutri' separati."
            )
            for flag in snap["thematic_flags"]:
                st.markdown(f"- {flag}")

        st.markdown("#### Sintesi")
        st.info(narrative["synthesis"])
    else:
        st.info("Nessun segnale rilevante al momento.")

    st.markdown("### Piano operativo")
    st.caption(
        "Uno schema di ingresso/stop/target costruito solo su livelli tecnici oggettivi (supporti, "
        "resistenze, ATR, obiettivi di figura) — un modello da adattare, non un ordine pronto. Se il "
        "quadro non è direzionale (Directional Score o Agreement Index bassi) l'app si rifiuta di "
        "proporne uno, invece di forzare un piano su un quadro indecidibile."
    )
    plan = tech.trade_plan(snap)
    contro = tech.plan_alignment_warning(plan, superior_snap, alignment.get("superior_horizon"))
    if not plan or plan["bias"] == "nessun_setup":
        motivo = plan.get("reason") if plan else None
        st.info(
            "Il quadro tecnico attuale non è abbastanza direzionale o concorde per costruire un piano "
            "operativo" + (f" ({motivo})." if motivo else ".") +
            " Aspettare un'impostazione più chiara è spesso la scelta più prudente."
        )
    else:
        if contro:
            st.warning(contro["text"])
        bias_kind = "ok" if plan["bias"] == "long" else "bad"
        p1, p2, p3, p4 = st.columns(4)
        setup_badge = badge(plan["bias"].upper(), bias_kind)
        if contro:
            setup_badge += " " + badge("CONTRO-TREND", "warn")
        p1.markdown(f"**Impostazione**<br>{setup_badge}", unsafe_allow_html=True)
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


def _tts_band_badge_kind(band: str) -> str:
    return {
        "Eccellente": "ok", "Buono": "ok", "Discreto": "warn",
        "Debole": "warn", "Inadatto": "bad", "Inadatto (esclusione hard)": "bad",
    }.get(band, "info")


def _render_tradeability_section():
    """Tabella dell'universo di trading (portafoglio + preferiti) ordinata
    per Technical Tradeability Score, con filtro classe e dettaglio per
    titolo — stesso pattern (ranking + dettaglio) usato dalla pagina
    Fattori, applicato qui ai sei criteri di idoneità tecnica invece che
    ai 5 fattori accademici."""
    st.caption(
        "Quanto uno strumento è STRUTTURALMENTE adatto a un sistema di trading tecnico "
        "trend-following — non è un segnale di acquisto/vendita, ma una misura di idoneità "
        "dello strumento all'analisi tecnica stessa. Serve a decidere cosa mettere "
        "nell'universo di trading e cosa testare per primo in backtest/forward test."
    )

    positions = pd.DataFrame()
    if os.path.exists(PORTFOLIO_PATH):
        positions = pf.load_portfolio(PORTFOLIO_PATH)
        if "category" in positions.columns:
            positions = positions[positions["category"] != CASH_CATEGORY]
    portfolio_tickers = sorted(positions["ticker"].unique()) if not positions.empty else []

    watch_df_trd = wl.load_watchlist(WATCHLIST_PATH)
    watchlist_tickers = sorted(watch_df_trd["ticker"].unique()) if not watch_df_trd.empty else []

    target_tickers = sorted(set(portfolio_tickers) | set(watchlist_tickers))
    if not target_tickers:
        st.info(
            "Nessun titolo in portafoglio o nei preferiti: aggiungine dal Registro Transazioni "
            "o dalla tab Preferiti/Cerca per vedere qui la loro idoneità al trading tecnico."
        )
        return

    st.caption(f"Titoli considerati: {', '.join(target_tickers)}")

    if st.button("Calcola idoneità al trading", key="tts_compute"):
        with st.spinner("Calcolo Technical Tradeability Score sui titoli dell'universo..."):
            st.session_state["_tts_report"] = trd.build_tradeability_report(target_tickers)

    report = st.session_state.get("_tts_report")
    if not report:
        st.info(
            "Il calcolo richiede dati storici estesi (fino a 2 anni per titolo) e non viene "
            "rifatto ad ogni apertura pagina: premi il pulsante sopra per calcolarlo o "
            "aggiornarlo."
        )
        return

    ranking = report["ranking"]
    not_computable = report["not_computable"]

    if not_computable:
        with st.expander(f"{len(not_computable)} titolo/i non calcolabile/i"):
            for r in not_computable:
                st.markdown(f"- **{r['symbol']}**: {r.get('reason', 'motivo non specificato')}")

    if not ranking:
        st.warning("Nessun titolo ha prodotto un punteggio calcolabile.")
        return

    classes_available = sorted({r["asset_class_label"] for r in ranking})
    chosen_classes = st.multiselect("Filtra per classe", classes_available, default=classes_available,
                                     key="tts_class_filter")
    filtered = [r for r in ranking if r["asset_class_label"] in chosen_classes]

    rows = []
    for r in filtered:
        s = r["sub_scores"]
        flags = []
        if r["hard_excluded"]:
            flags.append("ESCLUSIONE HARD")
        if r["confidence"] < 1.0:
            flags.append(f"confidenza {r['confidence']:.2f}")
        if r["notes"]:
            flags.append("override/nota")
        if not r["tradable_on_broker"]:
            flags.append("solo backtest yfinance")
        rows.append({
            "Ticker": r["symbol"],
            "Classe": r["asset_class_label"],
            "TTS": f"{r['tts']:.0f}" if r["tts"] is not None else "n/d",
            "Banda": r["band"],
            **{CRITERION_SHORT_LABELS[k]: (f"{s.get(k):.0f}" if s.get(k) is not None else "n/d")
               for k in trd.WEIGHTS},
            "Flag": "; ".join(flags) if flags else "—",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, key="tts_ranking_table")

    st.markdown("### Dettaglio per titolo")
    st.caption(
        "Valori grezzi dietro ogni sub-score, per verificarli — coerentemente col principio di "
        "trasparenza radicale sulle soglie."
    )
    detail_symbol = st.selectbox("Titolo", [r["symbol"] for r in filtered], key="tts_detail_ticker")
    detail = report["results"].get(detail_symbol)
    if not detail or not detail.get("computable"):
        st.info("Dati non disponibili per questo titolo.")
        return

    h1, h2, h3, h4 = st.columns(4)
    h1.metric("TTS", f"{detail['tts']:.0f}/100" if detail["tts"] is not None else "n/d")
    h2.markdown(f"**Banda**<br>{badge(detail['band'], _tts_band_badge_kind(detail['band']))}",
                unsafe_allow_html=True)
    h3.metric("Classe", detail["asset_class_label"])
    h4.metric("Confidenza", f"{detail['confidence']:.2f}")

    if detail["hard_excluded"]:
        st.error(
            "Esclusione hard: " + "; ".join(detail["exclusion_reasons"]) +
            " — un buon punteggio sugli altri criteri non compensa illiquidità o assenza di trend."
        )
    st.markdown(
        badge("Tradabile su Trade Republic" if detail["tradable_on_broker"] else "Solo backtestabile su yfinance",
              "ok" if detail["tradable_on_broker"] else "info"),
        unsafe_allow_html=True,
    )
    if detail["asset_class"] == "EQUITY":
        st.caption(
            f"Prossima data earnings nota: {detail.get('next_earnings_date') or 'n/d'}. Indipendentemente "
            "da questo punteggio, i nuovi segnali tecnici vanno bloccati nella finestra earnings "
            "(regola operativa separata, non ancora automatizzata nel paper trading)."
        )
    for note in detail["notes"]:
        st.caption(f"Nota: {note}")

    sub_rows = []
    for k, label in CRITERION_SHORT_LABELS.items():
        s = detail["sub_scores"].get(k)
        sub_rows.append({
            "Criterio": trd.CRITERION_LABELS_IT[k],
            "Peso": f"{trd.WEIGHTS[k] * 100:.0f}%",
            "Sub-score": f"{s:.0f}/100" if s is not None else "n/d",
        })
    st.dataframe(pd.DataFrame(sub_rows), use_container_width=True, hide_index=True, key="tts_detail_subscores")

    with st.expander("Valori grezzi (per verificare i punteggi)"):
        raw = detail["raw"]
        raw_rows = [
            ("ADV (controvalore medio scambiato, EUR)", raw["liquidity"].get("adv_eur")),
            ("ATR% medio sulla finestra", raw["volatility"].get("atr_pct")),
            ("Efficiency Ratio (Kaufman) medio", raw["trendiness"].get("er")),
            ("ADX medio", raw["trendiness"].get("adx")),
            ("Esponente di Hurst", raw["trendiness"].get("hurst")),
            ("Frequenza dei gap (%)", raw["gap_frequency"].get("gap_frequency_pct")),
            ("Frequenza gap del lunedì (%, rischio weekend)", raw["gap_frequency"].get("weekend_gap_frequency_pct")),
            ("Movimento medio su earnings (%)", raw["earnings"].get("avg_move_pct")),
            ("Numero earnings considerati", raw["earnings"].get("n_events")),
            ("Autocorrelazione media (lag usati)", raw["autocorrelation"].get("ac_used_avg")),
        ]
        st.dataframe(
            pd.DataFrame(
                [(label, f"{v:,.3f}" if isinstance(v, float) else (v if v is not None else "n/d"))
                 for label, v in raw_rows],
                columns=["Valore grezzo", "Dato"],
            ),
            use_container_width=True, hide_index=True,
        )

    disclaimer(
        "Il Technical Tradeability Score misura l'idoneità STRUTTURALE dello strumento a un sistema "
        "di trading tecnico trend-following — non è un segnale di acquisto/vendita né un giudizio "
        "sulla qualità dell'azienda o dello strumento. Ogni soglia è una costante dichiarata ed "
        "editoriale (vedi src/tradeability.py), non calibrata con un backtest. Gli override di "
        "liquidità per FX/crypto e le esclusioni hard sono sempre mostrati esplicitamente, mai "
        "applicati in silenzio. Ricalcola periodicamente: la tradabilità di uno strumento cambia nel "
        "tempo."
    )


CRITERION_SHORT_LABELS = {
    "liquidity": "Liquidità", "volatility": "Volatilità", "trendiness": "Trendiness",
    "gap_frequency": "Gap", "earnings": "Earnings", "autocorrelation": "Autocorr.",
}


tab_portfolio, tab_favorites, tab_search, tab_tradeability = st.tabs(
    ["Portafoglio", "Preferiti", "Cerca", "Idoneità al Trading"]
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
        submitted = f4.form_submit_button("Aggiungi")
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
        if remove_choice != "—" and st.button("Rimuovi", key="fav_remove_btn"):
            watch_df = wl.remove_ticker(watch_df, remove_choice)
            wl.save_watchlist(watch_df, WATCHLIST_PATH)
            _push_watchlist()
            st.rerun()

        st.divider()
        st.markdown("**Avvisi sui preferiti**")
        st.caption(
            "Segnala eventi tecnici recenti su ogni titolo preferito: incrocio RSI 70/30, incrocio "
            "MACD/segnale, rottura di supporto/resistenza, candela o figura di prezzo rilevata "
            "sull'orizzonte medio termine. Va ricalcolato manualmente ad ogni visita."
        )
        if st.button("Scansiona preferiti", key="scan_favorites"):
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
        if not wl.is_watched(search_watch_df, symbol) and st.button("Aggiungi ai Preferiti", key="search_add_fav"):
            search_watch_df = wl.add_ticker(search_watch_df, symbol)
            wl.save_watchlist(search_watch_df, WATCHLIST_PATH)
            _push_watchlist()
            st.success(f"{symbol} aggiunto ai preferiti.")
        render_ticker_analysis(symbol, key_prefix="search")

with tab_tradeability:
    _render_tradeability_section()

disclaimer(
    "L'analisi tecnica descrive schemi statistici passati nei prezzi, non previsioni certe. Il "
    "Directional Score e l'Agreement Index sono una lettura quantitativa delle famiglie di indicatori "
    "considerate, non un segnale operativo validato da un backtest. Gli oscillatori danno falsi segnali "
    "nei trend forti, i pattern grafici falliscono, le candele su base giornaliera sono rumorose: da qui "
    "la disciplina della concordanza tra famiglie. Il contesto sul prezzo di ingresso è puramente "
    "descrittivo — non è consulenza finanziaria personalizzata né un'indicazione operativa. Le decisioni "
    "restano tue."
)
