"""Analisi Fondamentale: come sta lavorando l'azienda a livello di
numeri e quali sono i prospetti futuri, per un singolo titolo — bilancio
storico, qualità/valutazione, contesto settoriale (ETF + concorrenti a
scelta) e notizie con sentiment. Le ETF/comparti hanno una logica diversa
(nessun bilancio proprio) e restano fuori da questa pagina."""
import datetime as dt

import plotly.graph_objects as go
import streamlit as st

from src import data_provider as dp
from src import financials as finmod
from src import fundamental as fnd
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
    "Come sta lavorando l'azienda a livello di numeri, e quali sono i prospetti futuri — bilancio, "
    "valutazione, settore e news, con una sintesi finale. Per ETF e comparti serve un'altra logica: "
    "questa pagina resta sui singoli titoli."
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

st.subheader(f"{info.get('name', symbol)} ({symbol})")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Prezzo", f"{price:,.2f}" if price else "n/d")
c2.metric("Settore", info.get("sector") or "n/d")
c3.metric("Capitalizzazione", f"{info.get('market_cap'):,.0f}" if info.get("market_cap") else "n/d")
c4.metric("Dividend yield", f"{info.get('dividend_yield')*100:.2f}%" if info.get("dividend_yield") else "n/d")

sections = {s["key"]: s for s in narrative["sections"]}

# --- Numeri di bilancio -----------------------------------------------------
fin_sec = sections["financials"]
st.markdown(
    f"### {fin_sec['icon']} {fin_sec['title']} "
    f"{badge(fnd.FUND_VERDICT_LABELS[fin_sec['verdict']], fnd.FUND_VERDICT_BADGE_KIND[fin_sec['verdict']])}",
    unsafe_allow_html=True,
)
st.write(fin_sec["text"])

annual = fin_sec.get("annual") or {}
margins = fin_sec.get("margins") or {}
table = finmod.to_display_table(annual, margins)
if not table.empty:
    st.dataframe(table, use_container_width=True)

    rev, ni = annual.get("revenue"), annual.get("net_income")
    if rev is not None and ni is not None:
        aligned_rev, aligned_ni = rev.align(ni, join="inner")
        if not aligned_rev.empty:
            labels = [d.strftime("%Y") if hasattr(d, "strftime") else str(d) for d in aligned_rev.index]
            fig = go.Figure()
            fig.add_trace(go.Bar(x=labels, y=aligned_rev.values, name="Ricavi", marker_color=NAVY))
            fig.add_trace(go.Bar(x=labels, y=aligned_ni.values, name="Utile netto",
                                  marker_color=GOLD))
            fig.update_layout(barmode="group", height=350, title="Ricavi e utile netto per periodo",
                               legend=dict(orientation="h", yanchor="bottom", y=1.02))
            st.plotly_chart(fig, use_container_width=True, key="fa_financials_chart")
else:
    st.info("Nessun prospetto di bilancio annuale disponibile per questo titolo su Yahoo Finance.")

with st.expander("Dati trimestrali (grezzi)"):
    quarterly = finmod.get_financial_history(symbol, freq="quarterly")
    q_margins = finmod.compute_margins(quarterly)
    q_table = finmod.to_display_table(quarterly, q_margins)
    if not q_table.empty:
        st.dataframe(q_table, use_container_width=True)
    else:
        st.info("Nessun dato trimestrale disponibile per questo titolo.")

st.divider()

# --- Qualità e valutazione ---------------------------------------------------
val_sec = sections["valuation"]
st.markdown(
    f"### {val_sec['icon']} {val_sec['title']} "
    f"{badge(fnd.FUND_VERDICT_LABELS[val_sec['verdict']], fnd.FUND_VERDICT_BADGE_KIND[val_sec['verdict']])}",
    unsafe_allow_html=True,
)
st.write(val_sec["text"])

st.divider()

# --- Contesto settoriale -----------------------------------------------------
sec_sec = sections["sector"]
st.markdown(
    f"### {sec_sec['icon']} {sec_sec['title']} "
    f"{badge(fnd.FUND_VERDICT_LABELS[sec_sec['verdict']], fnd.FUND_VERDICT_BADGE_KIND[sec_sec['verdict']])}",
    unsafe_allow_html=True,
)
st.write(sec_sec["text"])
if sec_sec.get("peer_table") is not None and not sec_sec["peer_table"].empty:
    st.dataframe(sec_sec["peer_table"], use_container_width=True, hide_index=True)

st.divider()

# --- Notizie e prospettive future --------------------------------------------
news_sec = sections["news"]
st.markdown(
    f"### {news_sec['icon']} {news_sec['title']} "
    f"{badge(fnd.FUND_VERDICT_LABELS[news_sec['verdict']], fnd.FUND_VERDICT_BADGE_KIND[news_sec['verdict']])}",
    unsafe_allow_html=True,
)
st.write(news_sec["text"])
for item in news_sec.get("news_items", []):
    s = item.get("sentiment", 0)
    kind = "ok" if s > 0 else ("bad" if s < 0 else "info")
    tag = "positiva" if s > 0 else ("negativa" if s < 0 else "neutra")
    title = item.get("title")
    link = item.get("link")
    publisher = item.get("publisher") or ""
    testo = f"[{title}]({link})" if link else (title or "")
    st.markdown(f"{badge(tag, kind)} {testo} · *{publisher}*", unsafe_allow_html=True)

st.markdown("#### \U0001F9ED Sintesi")
st.info(narrative["synthesis"])

disclaimer(
    "L'analisi fondamentale qui presentata usa dati pubblici (Yahoo Finance) e regole esplicite di "
    "interpretazione — non un modello proprietario né dati di ricerca a pagamento. La valutazione è "
    "relativa (multipli confrontati con la storia del titolo e con eventuali concorrenti indicati), "
    "non un fair value stimato con un DCF: le assunzioni di crescita di lungo periodo richiederebbero "
    "dati che non sono disponibili gratuitamente. Il sentiment sulle news è una classificazione "
    "automatica per parole chiave, da verificare leggendo gli articoli. Non è consulenza finanziaria "
    "personalizzata."
)
