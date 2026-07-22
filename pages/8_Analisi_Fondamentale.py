"""Analisi Fondamentale: Fundamental Score (0-100) costruito secondo
Specifica_Fundamental_Score_yfinance.md — un core parsimonioso di 8
metriche a bassa correlazione reciproca (creazione di valore, qualità
degli utili, leva, valutazione, capital allocation) più i badge Piotroski
F-Score e Altman Z-Score, normalizzati a percentile contro un peer group
curato per settore (src/sector_universe.py, con caching locale in
src/fundamental_cache.py). Non è un modello di fair value: è uno
strumento di screening comparabile su portafoglio, preferiti e ricerca
libera, pensato per un orizzonte di medio termine. I settori finanziari
(banche/assicurazioni) restano esclusi perché EBITDA/ROIC/EV/Piotroski/
Altman non sono metriche significative per il loro modello di business."""
import datetime as dt
import os

import pandas as pd
import streamlit as st

from src import data_provider as dp
from src import financials as finmod
from src import fundamental as fnd
from src import fundamental_export as fexp
from src import fundamental_score as fscore
from src import github_sync
from src import macro as mc
from src import portfolio as pf
from src import watchlist as wl
from src.auth import check_password
from src.portfolio import CASH_CATEGORY
from src.theme import apply_theme, badge, disclaimer

st.set_page_config(page_title="Analisi Fondamentale", page_icon="\U0001F9FE", layout="wide")
apply_theme()

if not check_password():
    st.stop()

st.title("\U0001F9FE Analisi Fondamentale")
st.caption(
    "Fundamental Score (0-100): un nucleo di 8 metriche a bassa correlazione — creazione di valore, "
    "qualità degli utili, leva, valutazione, capital allocation — più i badge Piotroski F-Score e "
    "Altman Z-Score, sempre confrontati con un peer group di settore, non con soglie assolute. "
    "Le banche/assicurazioni restano fuori: per loro questi ratio non sono significativi."
)

PORTFOLIO_PATH = "data/portfolio.csv"
WATCHLIST_PATH = "data/watchlist.csv"

BAND_BADGE_KIND = {
    "Eccellente": "ok", "Solido": "ok", "Nella media": "warn",
    "Debole": "bad", "Scarso": "bad", "n/d": "info",
}
METRIC_DISPLAY = {
    "roic": ("ROIC", "pct"),
    "gross_profits_to_assets": ("Gross profit / Attivo", "pct"),
    "fcf_conversion": ("FCF conversion (FCF/Utile netto)", "pct"),
    "accruals_ratio": ("Accruals ratio (Sloan)", "pct"),
    "net_debt_to_ebitda": ("Debito netto / EBITDA", "ratio"),
    "interest_coverage": ("Copertura interessi (EBIT/int.)", "ratio"),
    "ev_ebit_yield": ("EV/EBIT earnings yield", "pct"),
    "shareholder_yield": ("Shareholder yield", "pct"),
    "revenue_cagr": ("CAGR ricavi", "pct"),
    "eps_cagr": ("CAGR EPS", "pct"),
    "growth_volatility": ("Volatilità crescita ricavi", "pct"),
}


def _percentile_badge_kind(pct: float | None) -> str:
    if pct is None:
        return "info"
    return "ok" if pct >= 70 else ("bad" if pct <= 30 else "warn")


def _format_metric_value(key: str, value):
    kind = METRIC_DISPLAY.get(key, (key, "pct"))[1]
    if kind == "pct":
        return finmod.format_pct(value, signed=True)
    return finmod.format_ratio(value)


def _wacc_for(info: dict, hist: dict) -> float | None:
    """Costo medio ponderato del capitale (CAPM/WACC), riusato da
    src/fundamental.py — serve solo per il flag "ROIC sotto il WACC"
    (§9), non per stimare un prezzo."""
    macro_snap = mc.get_macro_snapshot()
    risk_free = macro_snap.get("ten_year_yield")
    coe = fnd.cost_of_equity(info.get("beta"), risk_free)
    debt_latest = finmod._last(hist.get("total_debt"))
    interest_latest = finmod._last(hist.get("interest_expense"))
    cod = fnd.cost_of_debt(interest_latest, debt_latest, risk_free)
    ratios = finmod.compute_ratios(hist)
    tax_rate = finmod._last(ratios.get("effective_tax_rate"))
    return fnd.wacc(coe, cod, tax_rate, info.get("market_cap"), debt_latest)


# La tesi in una riga e i punti di forza/attenzione sono costruiti da
# src.fundamental_score (build_thesis_text/build_bull_bear) cosi' pagina
# ed export Excel restano sempre coerenti tra loro.


def render_fundamental_card(symbol: str, key_prefix: str):
    info = dp.get_info(symbol)
    st.subheader(f"{info.get('name', symbol)} ({symbol})")

    price = dp.get_current_price(symbol)
    currency = info.get("currency")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Prezzo", finmod.format_money(price, currency) if price else "n/d")
    c2.metric("Settore", info.get("sector") or "n/d")
    c3.metric("Capitalizzazione", finmod.format_money(info.get("market_cap"), currency))
    c4.metric("P/E", f"{info.get('pe_ratio'):.1f}" if info.get("pe_ratio") else "n/d")

    with st.spinner("Calcolo Fundamental Score (bilanci + peer group di settore)..."):
        hist = finmod.get_financial_history(symbol, freq="annual")
        wacc_est = _wacc_for(info, hist)
        result = fscore.build_fundamental_score(symbol, use_cache=True, sync_cache=False, wacc=wacc_est)

    if result.get("excluded"):
        st.warning(result["reason"])
        return

    if result.get("needs_reit_override"):
        st.caption(
            "⚠️ Settore Real Estate: la specifica prevede un profilo REIT dedicato (FFO/AFFO al posto "
            "di EPS/P/E) non ancora implementato — qui usa il profilo generico Utilities/Defensive più "
            "vicino, da considerare copertura parziale (Stage 2 del piano di implementazione)."
        )

    composite = result["composite"]
    band = composite.get("band", "n/d")

    excel_bytes = fexp.build_excel_report(symbol, info, price, result)
    st.download_button(
        "\U0001F4E5 Scarica Excel", data=excel_bytes,
        file_name=f"fundamental_score_{symbol}_{dt.date.today().isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"{key_prefix}_download_excel",
    )

    st.markdown("#### Tesi in una riga")
    st.markdown(
        f"{badge(band, BAND_BADGE_KIND.get(band, 'info'))} {fscore.build_thesis_text(result, info)}",
        unsafe_allow_html=True,
    )

    if composite.get("insufficient_data"):
        st.info(composite.get("reason", "Copertura dati insufficiente per mostrare uno score."))

    b1, b2 = st.columns(2)
    piotroski = result["piotroski"]
    with b1:
        if piotroski.get("score") is not None:
            st.metric("Piotroski F-Score", f"{piotroski['score']}/9")
        else:
            st.metric("Piotroski F-Score", "n/d")
    with b2:
        altman = result["altman"]
        if altman.get("z") is not None:
            zone_label = {"safe": "Sicura", "grey": "Grigia", "distress": "Distress"}.get(altman["zone"], "n/d")
            zone_kind = {"safe": "ok", "grey": "warn", "distress": "bad"}.get(altman["zone"], "info")
            st.markdown(
                f"**Altman {altman['variant']}**: {altman['z']:.2f} — {badge(zone_label, zone_kind)}",
                unsafe_allow_html=True,
            )
        else:
            st.markdown("**Altman Z**: n/d")

    st.markdown("#### Le 8 metriche core (+ crescita)")
    st.caption("Percentile rispetto al peer group di settore (winsorizzato al 5°/95°) — non una soglia assoluta.")
    metrics = result["metrics"]
    percentiles = result["metric_percentiles"]
    metric_keys = list(METRIC_DISPLAY.keys())
    cols = st.columns(4)
    for i, key in enumerate(metric_keys):
        label, _ = METRIC_DISPLAY[key]
        val = metrics.get(key)
        pct = percentiles.get(key)
        with cols[i % 4]:
            st.metric(label, _format_metric_value(key, val) if val is not None else "n/d")
            if pct is not None:
                st.markdown(badge(f"{pct:.0f}° percentile", _percentile_badge_kind(pct)), unsafe_allow_html=True)
            else:
                st.caption("percentile n/d")

    st.markdown("#### Prospettive per categoria")
    rows = []
    weights_used = composite.get("category_weights_used", {})
    for cat in fscore.CATEGORIES:
        sub = result["subscores"].get(cat)
        rows.append({
            "Categoria": fscore.CATEGORY_LABELS_IT[cat],
            "Sub-score": f"{sub:.0f}" if sub is not None else "n/d",
            "Banda": fscore.score_band_label(sub),
            "Peso nel composito": f"{weights_used.get(cat, 0):.1f}%" if weights_used.get(cat) is not None else "n/d",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, key=f"{key_prefix}_categories")

    bulls, bears = fscore.build_bull_bear(result)
    st.markdown("#### Punti di forza e di attenzione")
    bull_col, bear_col = st.columns(2)
    with bull_col:
        st.markdown("**\U0001F7E2 Punti di forza**")
        if bulls:
            for b in bulls:
                st.markdown(f"- {b}")
        else:
            st.caption("Nessun punto di forza netto rispetto al peer group.")
    with bear_col:
        st.markdown("**\U0001F534 Punti di attenzione**")
        if bears:
            for b in bears:
                st.markdown(f"- {b}")
        else:
            st.caption("Nessun segnale di attenzione rilevato.")

    with st.expander("Contesto di valutazione e consensus analisti (on-demand)"):
        pe_band = result.get("pe_band")
        if pe_band:
            st.markdown(
                f"P/E attuale {finmod.format_ratio(pe_band['current'], suffix='')} contro un range storico "
                f"(ultimi {pe_band['years']} anni) tra {finmod.format_ratio(pe_band['min'], suffix='')} e "
                f"{finmod.format_ratio(pe_band['max'], suffix='')} (mediana {finmod.format_ratio(pe_band['median'], suffix='')}): "
                f"{pe_band['percentile']:.0f}° percentile della propria storia recente."
            )
        else:
            st.caption("Range storico del P/E non disponibile per questo titolo.")

        target = info.get("target_mean_price")
        n_analysts = info.get("num_analyst_opinions")
        rec = info.get("recommendation_key")
        if target and price and n_analysts:
            implied_return = (target / price - 1) * 100
            st.markdown(
                f"Target price medio di {n_analysts} analisti: {finmod.format_money(target, currency)} "
                f"({finmod.format_pct(implied_return, signed=True)} rispetto al prezzo attuale, "
                f"raccomandazione aggregata: {rec or 'n/d'}). Dato di mercato reale, non una stima di questa app."
            )
        else:
            st.caption("Nessun target price di analisti disponibile per questo titolo.")

        if wacc_est is not None and metrics.get("roic") is not None:
            st.caption(
                f"ROIC (media pluriennale): {finmod.format_pct(metrics['roic'])} · "
                f"WACC stimato (CAPM): {finmod.format_pct(wacc_est)}."
            )

    with st.expander("Bilanci storici (grezzi)"):
        margins = finmod.compute_margins(hist)
        ratios = finmod.compute_ratios(hist)
        table = finmod.to_display_table(hist, margins, ratios, currency)
        if not table.empty:
            st.dataframe(table, use_container_width=True, key=f"{key_prefix}_hist_table")
        else:
            st.info("Nessun prospetto di bilancio annuale disponibile per questo titolo su Yahoo Finance.")

    with st.expander("Dettaglio criteri Piotroski F-Score"):
        crit = piotroski.get("criteria", {})
        if crit:
            crit_labels = {
                "roa_positivo": "ROA positivo", "cfo_positivo": "Cash flow operativo positivo",
                "roa_in_crescita": "ROA in crescita vs anno precedente",
                "cfo_supera_utile": "CFO supera l'utile netto (qualità utili)",
                "leva_ltd_in_calo": "Leva a lungo termine in calo",
                "current_ratio_in_crescita": "Current ratio in crescita",
                "nessuna_diluizione": "Nessuna nuova emissione netta di azioni",
                "margine_lordo_in_crescita": "Margine lordo in crescita",
                "turnover_in_crescita": "Asset turnover in crescita",
            }
            for k, v in crit.items():
                st.markdown(f"{badge('✓' if v else '✗', 'ok' if v else 'bad')} {crit_labels.get(k, k)}", unsafe_allow_html=True)
        else:
            st.info("Dati insufficienti per calcolare i criteri Piotroski su questo titolo.")

    with st.expander("News recenti"):
        news = dp.get_news(symbol, limit=6)
        if news:
            for n in news:
                link, title, publisher = n.get("link"), n.get("title"), n.get("publisher") or ""
                st.markdown(f"- [{title}]({link}) · *{publisher}*" if link else f"- {title} · *{publisher}*")
        else:
            st.info("Nessuna news trovata per questo ticker al momento.")


tab_portfolio, tab_favorites, tab_search = st.tabs(["\U0001F4BC Portafoglio", "⭐ Preferiti", "\U0001F50D Cerca"])

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
        chosen = st.selectbox("Titolo in portafoglio", tickers, key="fa_pf_ticker")
        render_fundamental_card(chosen, key_prefix="fa_pf")

with tab_favorites:
    watch_df = wl.load_watchlist(WATCHLIST_PATH)
    if watch_df.empty:
        st.info("Nessun titolo nei preferiti. Aggiungine uno dalla pagina Analisi Tecnica o da Cerca qui sotto.")
    else:
        chosen_fav = st.selectbox("Analizza un preferito", sorted(watch_df["ticker"].unique()), key="fa_fav_ticker")
        render_fundamental_card(chosen_fav, key_prefix="fa_fav")

with tab_search:
    symbol = st.text_input(
        "Ticker (es. AAPL, ENI.MI, SWDA.MI, VWCE.DE)", value="AAPL", key="fa_search_ticker"
    ).strip().upper()
    if symbol:
        search_watch_df = wl.load_watchlist(WATCHLIST_PATH)
        if not wl.is_watched(search_watch_df, symbol) and st.button("⭐ Aggiungi ai Preferiti", key="fa_search_add_fav"):
            search_watch_df = wl.add_ticker(search_watch_df, symbol)
            wl.save_watchlist(search_watch_df, WATCHLIST_PATH)
            if github_sync.is_configured():
                ok, msg = github_sync.push_csv(WATCHLIST_PATH, WATCHLIST_PATH,
                                                f"Aggiorna preferiti - {dt.date.today().isoformat()}")
                (st.success if ok else st.error)(msg)
            st.success(f"{symbol} aggiunto ai preferiti.")
        render_fundamental_card(symbol, key_prefix="fa_search")

disclaimer(
    "Il Fundamental Score usa dati pubblici (Yahoo Finance via yfinance, libreria non ufficiale) e "
    "regole di calcolo esplicite (Piotroski 2000, Altman Z, Novy-Marx, Sloan) — non è un modello "
    "proprietario né dati di ricerca a pagamento, e non è un fair value: è uno strumento di screening "
    "comparativo su un peer group curato per settore. Il ranking a percentile è relativo: in un "
    "settore uniformemente debole, uno score alto significa \"il migliore di un gruppo scarso\", non "
    "un titolo oggettivamente solido — guardare sempre gli anchor assoluti (ROIC vs WACC, bande di "
    "leva, bande Altman) accanto al percentile. Altman e Piotroski sono backward-looking (bilanci già "
    "pubblicati): sono filtri di rischio, non segnali predittivi standalone. I pesi settoriali sono un "
    "punto di partenza ragionato, non calibrato con un backtest. Non è consulenza finanziaria "
    "personalizzata né una raccomandazione operativa."
)
