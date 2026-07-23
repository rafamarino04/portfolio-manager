"""Analisi Fondamentale v2.0: scoring ASSOLUTO calibrato per settore/
archetipo (nessun peer group a runtime, src/sector_thresholds.py),
separato in due assi ortogonali — Quality (redditività, qualità utili,
solidità, crescita) e Valuation (multipli assoluti, storia propria,
earnings yield vs risk-free, growth-adjusted) — presentati in una
matrice 2x2 interpretativa, non fusi in un unico numero. L'archetipo
operativo (Dickinson 2011 + caratteristiche osservabili, src/lifecycle.py)
sostituisce il settore GICS grezzo per i pesi Quality. Un layer di Note
Critiche selettivo (src/critical_notes.py) segnala le situazioni in cui
le metriche standard ingannano (buyback, goodwill, R&D non capitalizzato,
ciclicità, one-off, ecc.), e un modello di confidenza dichiara quanto
fidarsi dello score in base a completezza/freschezza dei dati. Le
banche/assicurazioni restano escluse."""
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
from src import portfolio as pf
from src import watchlist as wl
from src.portfolio import CASH_CATEGORY
from src.theme import (
    ACCENT, BORDER, SURFACE, SURFACE_RAISED, TEXT_MUTED, TEXT_PRIMARY,
    apply_theme, badge, disclaimer,
)

apply_theme()

st.title("Analisi Fondamentale")
st.caption(
    "Quality e Valuation: due punteggi assoluti 0-100 separati (scala fissa calibrata per settore e "
    "archetipo operativo, non un confronto con altri titoli), presentati in una matrice 2x2 invece che "
    "fusi in un unico numero. Le banche/assicurazioni restano fuori: per loro questi ratio non sono "
    "significativi."
)

PORTFOLIO_PATH = "data/portfolio.csv"
WATCHLIST_PATH = "data/watchlist.csv"

BAND_BADGE_KIND = {
    "Eccellente": "ok", "Buono": "ok", "Discreto": "warn",
    "Sufficiente": "warn", "Debole": "bad", "Scarso": "bad", "n/d": "info",
}
CONFIDENCE_BADGE_KIND = {"Alta": "ok", "Media": "warn", "Bassa": "bad"}

METRIC_DISPLAY = {
    "roic": ("ROIC", "pct"), "gross_profits_to_assets": ("Gross profit / Attivo", "pct"),
    "operating_margin_current": ("Margine operativo", "pct"), "shareholder_yield": ("Shareholder yield", "pct"),
    "fcf_conversion": ("FCF conversion", "pct"), "accruals_ratio": ("Accruals ratio (Sloan)", "pct"),
    "net_debt_to_ebitda": ("Debito netto / EBITDA", "ratio"), "interest_coverage": ("Copertura interessi", "ratio"),
    "revenue_cagr": ("CAGR ricavi", "pct"), "eps_cagr": ("CAGR EPS", "pct"), "growth_volatility": ("Volatilità crescita", "pct"),
}
CATEGORY_MEMBER_KEYS = {
    "profitability": ["roic", "gross_profits_to_assets", "operating_margin_current", "shareholder_yield"],
    "earnings_quality": ["fcf_conversion", "accruals_ratio"],
    "financial_strength": ["net_debt_to_ebitda", "interest_coverage"],
    "growth_quality": ["revenue_cagr", "eps_cagr", "growth_volatility"],
}
VALUATION_COMPONENT_LABELS = {
    "sector_multiples": "Multipli assoluti (EV/EBITDA, EV/Sales, P/E) vs settore",
    "own_history": "Storia propria (percentile P/E su finestra storica)",
    "earnings_yield_vs_rf": "EV/EBIT earnings yield vs Treasury 10Y",
    "growth_adjusted": "Growth-adjusted (PEG o Rule of 40)",
}


def _format_metric_value(key: str, value):
    kind = METRIC_DISPLAY.get(key, (key, "pct"))[1]
    if value is None:
        return "n/d"
    if kind == "pct":
        return finmod.format_pct(value, signed=True)
    return finmod.format_ratio(value)


def _wacc_and_risk_free(info: dict, hist: dict) -> tuple[float | None, float | None]:
    from src import macro as mc
    macro_snap = mc.get_macro_snapshot()
    risk_free = macro_snap.get("ten_year_yield")
    coe = fnd.cost_of_equity(info.get("beta"), risk_free)
    debt_latest = finmod._last(hist.get("total_debt"))
    interest_latest = finmod._last(hist.get("interest_expense"))
    cod = fnd.cost_of_debt(interest_latest, debt_latest, risk_free)
    ratios = finmod.compute_ratios(hist)
    tax_rate = finmod._last(ratios.get("effective_tax_rate"))
    w = fnd.wacc(coe, cod, tax_rate, info.get("market_cap"), debt_latest)
    return w, risk_free


def _render_matrix(matrix: dict | None, symbol: str, key_prefix: str):
    """Griglia 2x2 Quality x Valuation. FIX v2.1-1: l'HTML va costruito
    come stringa SENZA indentazione iniziale sulle righe — passato a
    st.markdown con indentazione (come nella versione precedente, dove
    l'f-string multilinea ereditava l'indentazione del blocco Python),
    un blocco di 4+ spazi a inizio riga viene interpretato da CommonMark
    come blocco di codice preformattato, quindi i tag comparivano come
    testo grezzo (es. `</div>` visibile a schermo) invece di essere
    renderizzati. Qui ogni cella è una singola riga di stringa concatenata,
    e il quadrante attivo mostra il ticker realmente analizzato (non un
    placeholder statico)."""
    quadrants = [
        ("high", "cheap", "Alta Quality · Cheap", "wonderful"),
        ("high", "expensive", "Alta Quality · Expensive", "quality_at_price"),
        ("low", "cheap", "Bassa Quality · Cheap", "value_trap"),
        ("low", "expensive", "Bassa Quality · Expensive", "avoid"),
    ]
    active_key = matrix.get("key") if matrix else None
    cols = st.columns(2)
    for i, (_, _, cell_label, cell_key) in enumerate(quadrants):
        is_active = cell_key == active_key
        border_color = ACCENT if is_active else BORDER
        bg_color = SURFACE_RAISED if is_active else SURFACE
        text_color = TEXT_PRIMARY if is_active else TEXT_MUTED
        if is_active:
            marker_html = f'<div style="font-size:12px;color:{ACCENT};margin-top:6px;">● {symbol}</div>'
        else:
            marker_html = f'<div style="font-size:12px;color:{TEXT_MUTED};margin-top:6px;">–</div>'
        cell_html = (
            f'<div style="border:1.5px solid {border_color};background:{bg_color};'
            f'border-radius:8px;padding:14px;margin-bottom:12px;min-height:88px;">'
            f'<div style="font-size:12px;color:{text_color};font-weight:600;">{cell_label}</div>'
            f'{marker_html}'
            f'</div>'
        )
        with cols[i % 2]:
            st.markdown(cell_html, unsafe_allow_html=True)
    if matrix:
        st.markdown(f"**{matrix['label']}**")
        st.caption(matrix["action"])
    else:
        st.caption("Matrice non mostrabile: Quality o Valuation non calcolabili con i dati disponibili.")


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

    with st.spinner("Calcolo Quality/Valuation (soglie assolute per settore/archetipo)..."):
        hist = finmod.get_financial_history(symbol, freq="annual")
        wacc_est, risk_free = _wacc_and_risk_free(info, hist)
        result = fscore.build_fundamental_score(symbol, wacc=wacc_est, risk_free_pct=risk_free)

    if result.get("excluded"):
        st.warning(result["reason"])
        return

    quality, valuation, matrix = result["quality"], result["valuation"], result.get("matrix")

    excel_bytes = fexp.build_excel_report(symbol, info, price, result)
    st.download_button(
        "Scarica Excel", data=excel_bytes,
        file_name=f"analisi_fondamentale_{symbol}_{dt.date.today().isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"{key_prefix}_download_excel",
    )

    st.markdown("#### Tesi in una riga")
    st.markdown(fscore.build_thesis_text(result), unsafe_allow_html=True)

    conf = result["confidence"]
    # FIX v2.1-2: il valore numerico del confidence score è sempre mostrato
    # accanto all'etichetta, per permettere di verificare il badge invece
    # di doversi fidare della sola parola Alta/Media/Bassa.
    confidence_badge_text = f"Affidabilità: {conf['level']} ({conf['score']:.0f}/100)"
    confidence_badge_html = badge(confidence_badge_text, CONFIDENCE_BADGE_KIND.get(conf["level"], "info"))
    st.markdown(
        f"{confidence_badge_html} "
        f"&nbsp; archetipo: **{result['archetype_label']}** "
        f"&nbsp; Dickinson: **{result['dickinson_latest_label']}**"
        + ("" if result["dickinson_stable"] else " (segnale instabile negli anni disponibili)"),
        unsafe_allow_html=True,
    )
    if conf["explanation"]:
        st.caption("Fattori che riducono l'affidabilità: " + "; ".join(conf["explanation"]) + ".")
    if conf.get("downgraded_for_consistency"):
        st.caption(
            "Nota: il punteggio numerico sarebbe in banda \"Alta\", ma l'etichetta è stata declassata a "
            "\"Media\" per coerenza con i fattori di riduzione elencati sopra."
        )
    with st.expander("Perché questo archetipo?"):
        st.caption(" · ".join(result["archetype_reasons"]))
        st.caption(f"Bucket di soglie usato: {result.get('bucket_label', 'n/d')}.")

    st.markdown("#### Quality e Valuation")
    q1, q2 = st.columns(2)
    with q1:
        q_score = quality.get("score")
        st.metric("Quality", f"{q_score:.0f}/100 · {fscore.score_band_label(q_score)}" if q_score is not None else "n/d")
        if quality.get("insufficient_data"):
            st.caption(quality.get("reason", "Dati insufficienti."))
        if quality.get("altman_capped"):
            st.caption("Limitato a 40 per zona di distress Altman (vedi Note Critiche se il segnale è ritenuto inaffidabile).")
    with q2:
        v_score = valuation.get("score")
        st.metric("Valuation", f"{v_score:.0f}/100 · {fscore.score_band_label(v_score)}" if v_score is not None else "n/d")
        st.caption("Punteggio alto = economico. " + (valuation.get("reason", "") if valuation.get("insufficient_data") else ""))

    if result["blended"] is not None:
        st.caption(f"Numero unico secondario (media Quality/Valuation, da non usare come segnale primario): {result['blended']:.0f}/100.")

    st.markdown("#### Matrice Quality x Valuation")
    _render_matrix(matrix, symbol, key_prefix)

    st.markdown("#### Prospettive per categoria (asse Quality)")
    # FIX v2.1-7: la tabella includeva solo le 4 categorie Quality, senza
    # la riga Piotroski F-Score — che però ha un peso proprio nel composito
    # (cap-adjusted, vedi PIOTROSKI_WEIGHT_BY_CAP) — quindi i pesi mostrati
    # non sommavano a 100% e non si poteva verificare il calcolo. Qui si
    # aggiunge la riga Piotroski (col peso EFFETTIVAMENTE applicato a
    # questo titolo, non quello di default) e una riga di totale.
    rows = []
    weights_used = quality.get("category_weights_used", {})
    weight_total = 0.0
    for cat in fscore.CATEGORIES:
        sub = quality["subscores"].get(cat)
        w = weights_used.get(cat)
        if w is not None:
            weight_total += w
        rows.append({
            "Categoria": fscore.CATEGORY_LABELS_IT[cat],
            "Punteggio assoluto": f"{sub:.0f}" if sub is not None else "n/d",
            "Banda": fscore.score_band_label(sub),
            "Peso nel composito": f"{w:.1f}%" if w is not None else "n/d",
        })

    piotroski_weight = quality.get("piotroski_weight_used")
    piotroski_score = result["piotroski"].get("score")
    piotroski_scaled = (piotroski_score / 9 * 100) if piotroski_score is not None else None
    if piotroski_weight is not None:
        weight_total += piotroski_weight
    rows.append({
        "Categoria": "Piotroski F-Score (scalato 0-100)",
        "Punteggio assoluto": f"{piotroski_scaled:.0f}" if piotroski_scaled is not None else "n/d",
        "Banda": fscore.score_band_label(piotroski_scaled) if piotroski_scaled is not None else "n/d",
        "Peso nel composito": f"{piotroski_weight:.1f}%" if piotroski_weight is not None else "n/d",
    })
    rows.append({
        "Categoria": "Totale",
        "Punteggio assoluto": "",
        "Banda": "",
        "Peso nel composito": f"{weight_total:.1f}%" if weight_total else "n/d",
    })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, key=f"{key_prefix}_categories")
    if weight_total and abs(weight_total - 100.0) > 0.5:
        st.caption(
            f"Nota: i pesi mostrati sommano a {weight_total:.1f}% invece di 100% — verificare la copertura "
            "dati (i pesi delle categorie non disponibili vengono redistribuiti sulle altre)."
        )

    with st.expander("Metriche core (per verificare i punteggi)"):
        metrics = result["metrics"]
        stale_fields = metrics.get("stale_fields", {})
        for cat in fscore.CATEGORIES:
            st.markdown(f"**{fscore.CATEGORY_LABELS_IT[cat]}**")
            cols = st.columns(4)
            for i, key in enumerate(CATEGORY_MEMBER_KEYS[cat]):
                label, _ = METRIC_DISPLAY[key]
                with cols[i % 4]:
                    value_str = _format_metric_value(key, metrics.get(key))
                    stale = stale_fields.get(key)
                    # FIX v2.1-4: mai mostrare un valore stale senza
                    # etichetta — l'anno di riferimento va sempre a fianco.
                    if stale:
                        st.metric(label, value_str, help=(
                            f"Dato dell'esercizio {stale['year']} — più vecchio delle altre metriche di "
                            f"questa categoria di circa {stale['months_behind']} mesi. Pesato a metà nel "
                            "sub-score, confidenza ridotta di conseguenza."
                        ))
                        st.markdown(badge(f"dato {stale['year']}", "warn"), unsafe_allow_html=True)
                    else:
                        st.metric(label, value_str)

    st.markdown("#### Componenti Valuation")
    v_rows = []
    for key, label in VALUATION_COMPONENT_LABELS.items():
        val = valuation.get("components", {}).get(key)
        v_rows.append({"Componente": label, "Punteggio": f"{val:.0f}" if val is not None else "n/d"})
    st.dataframe(pd.DataFrame(v_rows), use_container_width=True, hide_index=True, key=f"{key_prefix}_valuation_components")

    st.markdown("#### Piotroski, Altman, Beneish")
    b1, b2, b3 = st.columns(3)
    piotroski = result["piotroski"]
    with b1:
        if piotroski.get("score") is not None:
            st.metric("Piotroski F-Score", f"{piotroski['score']}/9")
        else:
            st.metric("Piotroski F-Score", "n/d")
        if piotroski.get("suspended_variational"):
            st.caption("Criteri variazionali sospesi (one-off/M&A rilevati).")
    with b2:
        altman = result["altman"]
        if altman.get("z") is not None:
            zone_label = {"safe": "Sicura", "grey": "Grigia", "distress": "Distress"}.get(altman["zone"], "n/d")
            zone_kind = {"safe": "ok", "grey": "warn", "distress": "bad"}.get(altman["zone"], "info")
            st.markdown(f"**Altman {altman['variant']}**: {altman['z']:.2f}", unsafe_allow_html=True)
            st.markdown(badge(zone_label, zone_kind), unsafe_allow_html=True)
        else:
            st.markdown("**Altman**: n/d")
        if "suppress_distress_penalty" in result.get("active_rules", set()):
            st.caption("Segnale di distress ritenuto non affidabile (vedi NC-01) e non applicato al punteggio.")
    with b3:
        beneish = result["beneish"]
        if beneish.get("m_score") is not None:
            zone_label = {"possibile_manipolatore": "Possibile manipolatore", "gray_zone": "Gray zone", "pulito": "Pulito"}.get(beneish["zone"], "n/d")
            zone_kind = {"possibile_manipolatore": "bad", "gray_zone": "warn", "pulito": "ok"}.get(beneish["zone"], "info")
            st.markdown(f"**Beneish M-Score** ({beneish['version']}): {beneish['m_score']:.2f}", unsafe_allow_html=True)
            st.markdown(badge(zone_label, zone_kind), unsafe_allow_html=True)
            st.caption("Early warning statistico, non prova di frode.")
        else:
            st.markdown("**Beneish M-Score**: n/d (dati insufficienti)")

    critical_notes = result.get("critical_notes", [])
    if critical_notes:
        st.markdown("#### Note Critiche")
        st.caption("Situazioni diagnosticabili in cui le metriche standard possono ingannare — mostrate solo quando il trigger scatta.")
        for note in critical_notes:
            st.markdown(f"{badge(note['code'], 'warn')} {note['text']}", unsafe_allow_html=True)

    bulls, bears = fscore.build_bull_bear(result)
    st.markdown("#### Punti di forza e di attenzione")
    bull_col, bear_col = st.columns(2)
    with bull_col:
        st.markdown("**Punti di forza**")
        if bulls:
            for b in bulls:
                st.markdown(f"- {b}")
        else:
            st.caption("Nessun punto di forza netto in assoluto.")
    with bear_col:
        st.markdown("**Punti di attenzione**")
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
                f"(copertura reale: {pe_band['years']} anni, {pe_band['eps_periods_available']} trimestri di EPS noti) tra "
                f"{finmod.format_ratio(pe_band['min'], suffix='')} e {finmod.format_ratio(pe_band['max'], suffix='')} "
                f"(mediana {finmod.format_ratio(pe_band['median'], suffix='')}): {pe_band['percentile']:.0f}° percentile "
                "della propria storia recente."
            )
        else:
            st.caption("Range storico del P/E non disponibile per questo titolo (serve almeno 5 anni di storico prezzo).")

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

        if wacc_est is not None and result["metrics"].get("roic") is not None:
            st.caption(
                f"ROIC (media pluriennale): {finmod.format_pct(result['metrics']['roic'])} · "
                f"WACC stimato (CAPM, beta del titolo): {finmod.format_pct(wacc_est)}."
            )

    with st.expander("Bilanci storici (grezzi)"):
        margins = finmod.compute_margins(hist)
        ratios = finmod.compute_ratios(hist)
        table = finmod.to_display_table(hist, margins, ratios, currency)
        if not table.empty:
            st.dataframe(table, use_container_width=True, key=f"{key_prefix}_hist_table")
            n_years = finmod.n_annual_periods(hist)
            if n_years < 8:
                st.caption(
                    f"Yahoo Finance espone {n_years} anni di bilanci gratuiti per questo titolo — meno "
                    "degli 8 anni idealmente usati da alcune metriche (es. normalizzazione mid-cycle, "
                    "percentile storico di valutazione); dove non bastano, il dato viene soppresso "
                    "invece di stimato, e la confidenza si riduce di conseguenza."
                )
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
                st.markdown(f"{badge('Sì' if v else 'No', 'ok' if v else 'bad')} {crit_labels.get(k, k)}", unsafe_allow_html=True)
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


tab_portfolio, tab_favorites, tab_search = st.tabs(["Portafoglio", "Preferiti", "Cerca"])

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
        if not wl.is_watched(search_watch_df, symbol) and st.button("Aggiungi ai Preferiti", key="fa_search_add_fav"):
            search_watch_df = wl.add_ticker(search_watch_df, symbol)
            wl.save_watchlist(search_watch_df, WATCHLIST_PATH)
            if github_sync.is_configured():
                ok, msg = github_sync.push_csv(WATCHLIST_PATH, WATCHLIST_PATH,
                                                f"Aggiorna preferiti - {dt.date.today().isoformat()}")
                (st.success if ok else st.error)(msg)
            st.success(f"{symbol} aggiunto ai preferiti.")
        render_fundamental_card(symbol, key_prefix="fa_search")

disclaimer(
    "L'Analisi Fondamentale v2.0 usa dati pubblici (Yahoo Finance via yfinance) e uno scoring ASSOLUTO "
    "calibrato per settore/archetipo (soglie ispirate al dataset Damodaran e alle convenzioni di rating "
    "S&P/Moody's, non un peer group costruito a runtime): un punteggio alto è oggettivamente buono, non "
    "\"il migliore di un gruppo scarso\". Quality e Valuation sono assi ortogonali per costruzione "
    "(Novy-Marx 2013, Asness/Frazzini/Pedersen 2019): mostrarli fusi in un solo numero distruggerebbe "
    "informazione decisionale, per questo il blended number resta solo un dettaglio secondario. Le Note "
    "Critiche segnalano solo le situazioni diagnosticabili con regole precise, non ogni metrica. "
    "Piotroski, Altman e Beneish sono backward-looking e forensic-statistici, non prove né previsioni. "
    "I fattori quality/value pubblicati in letteratura si sono indeboliti nel tempo (McLean & Pontiff "
    "2016: rendimenti out-of-sample il 26% più bassi, post-pubblicazione il 58% più bassi): trattare "
    "questi punteggi come indicatori di robustezza fondamentale, non come previsioni di rendimento. Le "
    "soglie sono scelte ragionate, non calibrate con un backtest sui titoli in portafoglio — e Yahoo "
    "Finance offre tipicamente 4 anni di bilanci, non gli 8 idealmente usati da alcune metriche: dove i "
    "dati non bastano lo strumento lo dichiara e riduce la confidenza, non inventa un valore. Non è "
    "consulenza finanziaria personalizzata né una raccomandazione operativa: nessuna analisi quantitativa "
    "sostituisce il giudizio su fattori qualitativi (moat, management, contesto macro)."
)
