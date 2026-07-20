"""Analisi Fondamentale: tre domande concrete su un singolo titolo — è
profittevole? è sostenibile nel tempo? ha buone prospettive, anche se i
dati storici dicono il contrario? Bilancio storico, ROIC vs WACC, trend
di settore, consensus reale degli analisti e sentiment sulle news, più
un export Excel. Le ETF/comparti hanno una logica diversa (nessun
bilancio proprio) e restano fuori da questa pagina."""
import datetime as dt

import plotly.graph_objects as go
import streamlit as st

from src import data_provider as dp
from src import financials as finmod
from src import fundamental as fnd
from src import fundamental_export as fexp
from src import github_sync
from src import peers as pr
from src.auth import check_password
from src.theme import GOLD, NAVY, apply_theme, badge, disclaimer

st.set_page_config(page_title="Analisi Fondamentale", page_icon="\U0001F9FE", layout="wide")
apply_theme()

if not check_password():
    st.stop()

st.title("\U0001F9FE Analisi Fondamentale")
st.caption(
    "Tre domande su un singolo titolo: è profittevole? è sostenibile nel tempo? ha buone prospettive, "
    "anche se i dati storici dicono il contrario? Per ETF e comparti serve un'altra logica: questa "
    "pagina resta sui singoli titoli."
)

PEERS_PATH = "data/peers.csv"

symbol = st.text_input(
    "Ticker (es. AAPL, ENI.MI, SWDA.MI, VWCE.DE)", value="AAPL", key="fa_symbol"
).strip().upper()

if not symbol:
    st.stop()

peers_df = pr.load_peers(PEERS_PATH)
existing_peers = pr.get_peers(peers_df, symbol)

with st.expander("Confronta con concorrenti (opzionale)", expanded=bool(existing_peers)):
    st.caption(
        "Indica 1-3 ticker di concorrenti diretti per un confronto più preciso su multipli, margini "
        "e crescita, oltre al solo ETF di settore."
    )
    peers_input = st.text_input(
        "Ticker concorrenti (separati da virgola)",
        value=", ".join(existing_peers), key="fa_peers_input",
    )
    if st.button("\U0001F4BE Salva concorrenti", key="fa_save_peers"):
        new_peers = [p.strip().upper() for p in peers_input.split(",") if p.strip()]
        peers_df = pr.set_peers(peers_df, symbol, new_peers)
        pr.save_peers(peers_df, PEERS_PATH)
        if github_sync.is_configured():
            ok, msg = github_sync.push_csv(PEERS_PATH, PEERS_PATH,
                                            f"Aggiorna concorrenti - {dt.date.today().isoformat()}")
            (st.success if ok else st.error)(msg)
        st.success("Concorrenti salvati.")
        st.rerun()

peers = pr.get_peers(peers_df, symbol)

with st.spinner("Analisi fondamentale in corso..."):
    info = dp.get_info(symbol)
    price = dp.get_current_price(symbol)
    narrative = fnd.build_fundamental_narrative(symbol, peers=peers or None)

currency = info.get("currency")
sections = {s["key"]: s for s in narrative["sections"]}
breakdown = narrative.get("score_breakdown", {})

top1, top2 = st.columns([5, 1])
with top1:
    st.subheader(f"{info.get('name', symbol)} ({symbol})")
with top2:
    excel_bytes = fexp.build_excel_report(symbol, info, price, narrative)
    st.download_button(
        "\U0001F4E5 Scarica Excel", data=excel_bytes,
        file_name=f"analisi_fondamentale_{symbol}_{dt.date.today().isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="fa_download_excel",
    )

c1, c2, c3, c4 = st.columns(4)
c1.metric("Prezzo", finmod.format_money(price, currency) if price else "n/d")
c2.metric("Settore", info.get("sector") or "n/d")
c3.metric("Capitalizzazione", finmod.format_money(info.get("market_cap"), currency))
c4.metric("Dividend yield", f"{info.get('dividend_yield')*100:.2f}%" if info.get("dividend_yield") else "n/d")

st.divider()


def render_section(sec: dict):
    st.markdown(
        f"### {sec['icon']} {sec['title']} "
        f"{badge(fnd.FUND_VERDICT_LABELS[sec['verdict']], fnd.FUND_VERDICT_BADGE_KIND[sec['verdict']])}",
        unsafe_allow_html=True,
    )
    st.write(sec["text"])


# --- Domanda 1: È profittevole? ----------------------------------------------
prof_sec = sections["profitability"]
render_section(prof_sec)

annual = prof_sec.get("annual") or {}
margins = prof_sec.get("margins") or {}
ratios = finmod.compute_ratios(annual)
table = finmod.to_display_table(annual, margins, ratios, currency)
if not table.empty:
    st.dataframe(table, use_container_width=True)

    rev, ebitda, ni = annual.get("revenue"), annual.get("ebitda"), annual.get("net_income")
    fig = go.Figure()
    if rev is not None:
        labels = [d.strftime("%Y") if hasattr(d, "strftime") else str(d) for d in rev.index]
        fig.add_trace(go.Bar(x=labels, y=rev.values, name="Ricavi", marker_color=NAVY))
    if ebitda is not None:
        labels = [d.strftime("%Y") if hasattr(d, "strftime") else str(d) for d in ebitda.index]
        fig.add_trace(go.Bar(x=labels, y=ebitda.values, name="EBITDA", marker_color=GOLD))
    if ni is not None:
        labels = [d.strftime("%Y") if hasattr(d, "strftime") else str(d) for d in ni.index]
        fig.add_trace(go.Bar(x=labels, y=ni.values, name="Utile netto", marker_color="#4C7A9E"))
    if fig.data:
        fig.update_layout(barmode="group", height=350, title="Ricavi, EBITDA e utile netto per periodo",
                           legend=dict(orientation="h", yanchor="bottom", y=1.02))
        st.plotly_chart(fig, use_container_width=True, key="fa_financials_chart")
else:
    st.info("Nessun prospetto di bilancio annuale disponibile per questo titolo su Yahoo Finance.")

with st.expander("Dati trimestrali (grezzi)"):
    quarterly = finmod.get_financial_history(symbol, freq="quarterly")
    q_margins = finmod.compute_margins(quarterly)
    q_ratios = finmod.compute_ratios(quarterly)
    q_table = finmod.to_display_table(quarterly, q_margins, q_ratios, currency)
    if not q_table.empty:
        st.dataframe(q_table, use_container_width=True)
    else:
        st.info("Nessun dato trimestrale disponibile per questo titolo.")

st.divider()

# --- Domanda 2: È sostenibile nel tempo? -------------------------------------
render_section(sections["sustainability"])
st.divider()

# --- Domanda 3: Ha buone prospettive? ----------------------------------------
outlook_sec = sections["outlook"]
render_section(outlook_sec)

if outlook_sec.get("peer_table") is not None and not outlook_sec["peer_table"].empty:
    st.caption("Confronto con i concorrenti indicati:")
    st.dataframe(outlook_sec["peer_table"], use_container_width=True, hide_index=True)

news_items = outlook_sec.get("news_items", [])
if news_items:
    with st.expander("News recenti considerate"):
        for item in news_items:
            s = item.get("sentiment", 0)
            kind = "ok" if s > 0 else ("bad" if s < 0 else "info")
            tag = "positiva" if s > 0 else ("negativa" if s < 0 else "neutra")
            title = item.get("title")
            link = item.get("link")
            publisher = item.get("publisher") or ""
            testo = f"[{title}]({link})" if link else (title or "")
            st.markdown(f"{badge(tag, kind)} {testo} · *{publisher}*", unsafe_allow_html=True)

st.divider()

st.markdown("#### \U0001F9ED Sintesi")
st.info(narrative["synthesis"])

with st.expander("Dettaglio punteggio (lettura secondaria, non un rating)"):
    if breakdown.get("sub_scores"):
        labels = {"profitability": "È profittevole", "sustainability": "È sostenibile", "outlook": "Ha buone prospettive"}
        st.caption(" · ".join(f"{labels[k]}: {v:+.2f}" for k, v in breakdown["sub_scores"].items()))
        total = breakdown.get("total")
        if total is not None:
            st.caption(f"Punteggio composito: {total:+.2f} (scala -1/+1, media pesata delle tre domande).")
    else:
        st.caption("Punteggio non disponibile: dati insufficienti.")

disclaimer(
    "L'analisi fondamentale qui presentata usa dati pubblici (Yahoo Finance) e regole esplicite di "
    "interpretazione — non un modello proprietario né dati di ricerca a pagamento, e nessuna stima di "
    "fair value costruita su assunzioni proprie: dove serve un riferimento di prezzo esterno si usa il "
    "consensus reale degli analisti che coprono il titolo, sempre mostrato insieme al numero di analisti "
    "che lo compongono. Il ROIC/WACC e i ratio di bilancio dipendono dalla disponibilità e dalla qualità "
    "delle etichette dei prospetti contabili su Yahoo Finance, che non è garantita per tutti i titoli "
    "(specialmente non statunitensi o a piccola capitalizzazione). Il sentiment sulle news è una "
    "classificazione automatica per parole chiave, da verificare leggendo gli articoli. Il punteggio "
    "composito è una lettura secondaria basata su regole dichiarate, non un rating professionale né un "
    "segnale validato da un backtest. Non è consulenza finanziaria personalizzata."
)
