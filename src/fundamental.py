"""
Analisi fondamentale organizzata attorno a tre domande concrete — quelle
che contano davvero per decidere se un titolo merita attenzione, non un
elenco di metriche fine a se stesso:

  1. È profittevole?               -> ricavi, EBITDA, utile netto e i
                                       relativi margini, letti sui dati
                                       storici reali (nessuna proiezione).
  2. È sostenibile nel tempo?       -> la profittabilità regge nel tempo?
                                       ROIC confrontato col costo del
                                       capitale (WACC) per capire se
                                       l'azienda crea o distrugge valore,
                                       leva finanziaria (in aumento o in
                                       calo), liquidità, e se l'utile
                                       riportato si traduce davvero in
                                       cassa (qualità degli utili).
  3. Ha buone prospettive, anche    -> qui i numeri storici da soli non
     se i dati storici dicono          bastano: si guarda al trend del
     il contrario?                     settore (ETF proxy) e alla forza
                                       relativa del titolo, al consensus
                                       reale degli analisti che coprono
                                       il titolo (target price e
                                       raccomandazione, non una stima di
                                       questa app), e al tono delle news
                                       recenti — con lettura esplicita di
                                       quando questo quadro conferma o
                                       contraddice i numeri storici.

Deliberatamente NON include stime di fair value costruite su assunzioni
proprie (formule alla Graham, reversione di un multiplo su una crescita
attesa indovinata): quel tipo di calcolo trasforma un'assunzione in un
numero dall'aria precisa, senza però aggiungere affidabilità reale. Dove
serve un riferimento di prezzo "esterno", si usa il consensus degli
analisti — un dato di mercato reale, non un'invenzione di questa app — e
si mostra sempre insieme al numero di analisti che lo compongono, così
si può giudicare quanto pesarlo.

Il costo del capitale (CAPM/WACC, usato solo per il test ROIC vs WACC
nella domanda "è sostenibile") resta l'eccezione: non è una stima di
fair value, è un confronto tra il rendimento operativo dell'azienda e il
suo costo del capitale — una verifica di logica economica, non una
previsione di prezzo.

Ogni domanda produce un punteggio motivato (-1/+1); un punteggio composito
li combina con pesi dichiarati, pensato come base per un futuro motore
multi-fattoriale (tecnica + fondamentale + macro) — ma resta una lettura
secondaria rispetto ai tre verdetti in chiaro, che sono il vero output di
questa sezione.
"""
from __future__ import annotations

from src import data_provider as dp
from src import financials as finmod
from src import macro as mc
from src import news_sentiment as ns
from src import sector as sec

FUND_VERDICT_LABELS = {"positivo": "Positivo", "negativo": "Negativo", "neutro": "Neutro"}
FUND_VERDICT_BADGE_KIND = {"positivo": "ok", "negativo": "bad", "neutro": "info"}

# Equity risk premium: stima di lungo periodo ampiamente citata nella
# letteratura per il mercato USA. Non è un dato live — è una costante
# metodologica ragionevole, dichiarata esplicitamente, e serve solo al
# test ROIC vs WACC (creazione di valore), non a un prezzo obiettivo.
EQUITY_RISK_PREMIUM_PCT = 4.5

# Pesi delle tre domande nel punteggio composito. Si ridistribuiscono
# sulle domande disponibili quando una manca (es. nessun dato di bilancio).
AXIS_WEIGHTS = {
    "profitability": 0.35,
    "sustainability": 0.35,
    "outlook": 0.30,
}


# ---------------------------------------------------------------------------
# Costo del capitale — usato solo per il test ROIC vs WACC (creazione di
# valore), nella domanda "è sostenibile", non per stimare un prezzo.
# ---------------------------------------------------------------------------

def cost_of_equity(beta: float | None, risk_free_pct: float | None) -> float | None:
    """CAPM: costo del capitale proprio = risk free + beta * risk premium."""
    if beta is None or risk_free_pct is None:
        return None
    return risk_free_pct + beta * EQUITY_RISK_PREMIUM_PCT


def cost_of_debt(interest_expense: float | None, total_debt: float | None, risk_free_pct: float | None) -> float | None:
    """Proxy del costo del debito: interessi pagati / debito totale. Se
    non disponibile (spesso per titoli non-US), fallback a risk free + uno
    spread di credito tipico per debito investment-grade (dichiarato)."""
    if interest_expense is not None and total_debt and total_debt > 0:
        return abs(interest_expense) / total_debt * 100
    if risk_free_pct is not None:
        return risk_free_pct + 1.5  # spread di credito generico, non dato live
    return None


def wacc(coe_pct: float | None, cod_pct: float | None, tax_rate_pct: float | None,
         market_cap: float | None, total_debt: float | None) -> float | None:
    """Costo medio ponderato del capitale: pesa capitale proprio (a
    valore di mercato) e debito per il rispettivo costo, con il debito
    scontato dello scudo fiscale. Se manca la struttura del capitale
    (market cap o debito), assume prudenzialmente un'azienda a capitale
    interamente proprio e usa solo il costo dell'equity."""
    if coe_pct is None:
        return None
    if not market_cap or total_debt is None:
        return coe_pct
    total = market_cap + total_debt
    if total <= 0:
        return coe_pct
    we, wd = market_cap / total, total_debt / total
    if cod_pct is None:
        return coe_pct
    rate = (tax_rate_pct / 100) if tax_rate_pct is not None and 0 <= tax_rate_pct <= 100 else 0.21
    return we * coe_pct + wd * cod_pct * (1 - rate)


def _ratio_trend(series, threshold: float = 0.5) -> str | None:
    """Direzione di un ratio (es. debito netto/EBITDA) tra inizio e fine
    dello storico disponibile — non un giudizio su livello, solo su verso."""
    if series is None or len(series) < 3:
        return None
    diff = float(series.iloc[-1]) - float(series.iloc[0])
    if diff > threshold:
        return "in aumento"
    if diff < -threshold:
        return "in diminuzione"
    return "stabile"


def fundamental_snapshot(symbol: str, price: float | None = None) -> dict:
    """Multipli e ratio "puntuali" da Yahoo Finance, usati come dati di
    supporto nella domanda sulle prospettive (nessuna stima propria)."""
    info = dp.get_info(symbol)
    macro_snap = mc.get_macro_snapshot()

    beta = info.get("beta")
    risk_free = macro_snap.get("ten_year_yield")
    coe = cost_of_equity(beta, risk_free)

    peg = None
    pe = info.get("pe_ratio")
    growth = info.get("revenue_growth")
    if pe and growth and growth > 0:
        peg = pe / (growth * 100)

    return {
        "pe_ratio": pe,
        "forward_pe": info.get("forward_pe"),
        "price_to_book": info.get("price_to_book"),
        "return_on_equity": info.get("return_on_equity"),
        "debt_to_equity": info.get("debt_to_equity"),
        "profit_margins": info.get("profit_margins"),
        "revenue_growth": growth,
        "peg_ratio": peg,
        "beta": beta,
        "risk_free_pct": risk_free,
        "cost_of_equity_pct": coe,
        "dividend_yield": info.get("dividend_yield"),
        "market_cap": info.get("market_cap"),
        "currency": info.get("currency"),
    }


# ---------------------------------------------------------------------------
# Domanda 1 — È profittevole?
# ---------------------------------------------------------------------------

def _section_profitability(symbol: str) -> dict:
    annual = finmod.get_financial_history(symbol, freq="annual")
    margins = finmod.compute_margins(annual)
    currency = dp.get_info(symbol).get("currency")
    lines, score_parts = [], []
    verdict = "neutro"

    rev, ni, ebitda = annual.get("revenue"), annual.get("net_income"), annual.get("ebitda")

    if rev is None and ni is None:
        lines.append(
            "Non ci sono prospetti contabili sufficienti per questo titolo su Yahoo Finance "
            "(capita per alcuni titoli non statunitensi o a copertura limitata): non è possibile "
            "rispondere con dati reali a questa domanda."
        )
        return {"key": "profitability", "icon": "\U0001F4C8", "title": "È profittevole?",
                "verdict": verdict, "text": " ".join(lines), "score": None,
                "annual": annual, "margins": margins}

    if rev is not None and len(rev) >= 2:
        rev_info = finmod.latest_and_yoy(rev)
        rev_cagr = finmod.growth_rate(rev)
        if rev_info["yoy_pct"] is not None:
            direz = "in crescita" if rev_info["yoy_pct"] > 0 else "in calo"
            lines.append(
                f"I ricavi sono {direz} del {finmod.format_pct(rev_info['yoy_pct'], signed=True)} "
                f"rispetto al periodo precedente, a {finmod.format_money(rev_info['latest'], currency)}"
                + (f" (crescita media annua sull'intero storico: {finmod.format_pct(rev_cagr, signed=True)})." if rev_cagr is not None and len(rev) > 2 else ".")
            )

    if ebitda is not None and len(ebitda) >= 1:
        ebitda_margin = margins.get("ebitda_margin")
        latest_ebitda = float(ebitda.iloc[-1])
        txt = f"L'EBITDA più recente è {finmod.format_money(latest_ebitda, currency)}"
        if ebitda_margin is not None and not ebitda_margin.empty:
            txt += f", pari a un margine EBITDA del {finmod.format_pct(ebitda_margin.iloc[-1])}"
        lines.append(txt + ".")

    if ni is not None and len(ni) >= 1:
        ni_info = finmod.latest_and_yoy(ni)
        n_losses = int((ni < 0).sum())
        if ni_info["yoy_pct"] is not None:
            direz = "in crescita" if ni_info["yoy_pct"] > 0 else "in calo"
            lines.append(f"L'utile netto è {direz} del {finmod.format_pct(ni_info['yoy_pct'], signed=True)} sull'ultimo periodo.")
        if n_losses == 0:
            lines.append(f"L'azienda è stata in utile in tutti i {len(ni)} periodi disponibili: profittabilità coerente, non un episodio isolato.")
            score_parts.append(0.5)
        elif n_losses == len(ni):
            lines.append(f"L'azienda è stata in perdita in tutti i {len(ni)} periodi disponibili.")
            score_parts.append(-0.9)
        else:
            lines.append(f"L'azienda è stata in perdita in {n_losses} dei {len(ni)} periodi disponibili: profittabilità non ancora del tutto consolidata.")
            score_parts.append(-0.3)

    net_margin = margins.get("net_margin")
    if net_margin is not None and not net_margin.empty:
        nm = net_margin.iloc[-1]
        lines.append(f"Il margine netto più recente è del {finmod.format_pct(nm)}.")
        score_parts.append(0.5 if nm > 10 else (-0.4 if nm < 2 else 0.1))

    score = sum(score_parts) / len(score_parts) if score_parts else None
    if score is not None:
        verdict = "positivo" if score > 0.15 else ("negativo" if score < -0.15 else "neutro")
    if not lines:
        lines.append("Dati insufficienti per rispondere a questa domanda su questo titolo.")

    return {"key": "profitability", "icon": "\U0001F4C8", "title": "È profittevole?",
            "verdict": verdict, "text": " ".join(lines), "score": score,
            "annual": annual, "margins": margins}


# ---------------------------------------------------------------------------
# Domanda 2 — È sostenibile nel tempo?
# ---------------------------------------------------------------------------

def _section_sustainability(symbol: str, annual: dict) -> dict:
    info = dp.get_info(symbol)
    macro_snap = mc.get_macro_snapshot()
    ratios = finmod.compute_ratios(annual)
    latest = finmod.latest_ratios(annual, ratios, market_cap=info.get("market_cap"))
    quality = finmod.earnings_quality_flag(annual)

    beta = info.get("beta")
    risk_free = macro_snap.get("ten_year_yield")
    coe = cost_of_equity(beta, risk_free)
    debt_latest = finmod._last(annual.get("total_debt"))
    interest_latest = finmod._last(annual.get("interest_expense"))
    cod = cost_of_debt(interest_latest, debt_latest, risk_free)
    w = wacc(coe, cod, latest.get("effective_tax_rate"), info.get("market_cap"), debt_latest)
    roic = latest.get("roic")

    lines, score_parts = [], []

    margins = finmod.compute_margins(annual)
    net_margin_trend = finmod.margin_trend(margins.get("net_margin"))
    if net_margin_trend:
        qualifica = {
            "in espansione": "un segnale positivo di sostenibilità: l'azienda guadagna una quota crescente di ogni euro/dollaro di ricavo.",
            "in contrazione": "da monitorare: anche se profittevole oggi, la redditività per unità di ricavo si sta riducendo.",
            "stabile": "senza segnali né di miglioramento né di deterioramento marcato.",
        }[net_margin_trend]
        lines.append(f"Il margine netto è {net_margin_trend} nel periodo osservato: {qualifica}")
        score_parts.append(0.4 if net_margin_trend == "in espansione" else (-0.4 if net_margin_trend == "in contrazione" else 0.0))

    if roic is not None and w is not None:
        spread = roic - w
        lines.append(
            f"Il ROIC (rendimento sul capitale investito) è circa {finmod.format_pct(roic)}, contro un "
            f"costo del capitale (WACC) stimato del {finmod.format_pct(w)}: uno spread di "
            f"{finmod.format_pct(spread, signed=True)} punti."
        )
        if spread > 2:
            lines.append("Il capitale investito rende più di quanto costa: la redditività non dipende solo dalla contabilità, crea valore economico reale.")
            score_parts.append(min(1.0, 0.5 + spread / 20))
        elif spread < -2:
            lines.append("Il capitale investito rende meno di quanto costa: anche se in utile, l'azienda potrebbe non essere sostenibile a questi livelli di rendimento sul capitale.")
            score_parts.append(max(-1.0, -0.5 + spread / 20))
        else:
            lines.append("Il rendimento sul capitale è in linea con il suo costo.")
            score_parts.append(0.0)

    nd_ebitda = latest.get("net_debt_to_ebitda")
    nd_trend = _ratio_trend(ratios.get("net_debt_to_ebitda"))
    if nd_ebitda is not None:
        if nd_ebitda < 0:
            lines.append(f"L'azienda ha più cassa che debito (debito netto/EBITDA {finmod.format_ratio(nd_ebitda)}): la leva finanziaria non è un rischio per la sostenibilità.")
            score_parts.append(0.5)
        else:
            giudizio = "contenuta" if nd_ebitda < 2 else ("elevata" if nd_ebitda > 4 else "moderata")
            trend_txt = f", {nd_trend} nel periodo osservato" if nd_trend else ""
            lines.append(f"Il debito netto è {finmod.format_ratio(nd_ebitda)} l'EBITDA annuo (leva {giudizio}{trend_txt}).")
            base = 0.3 if nd_ebitda < 2 else (-0.6 if nd_ebitda > 4 else -0.1)
            if nd_trend == "in aumento":
                base -= 0.2
            elif nd_trend == "in diminuzione":
                base += 0.2
            score_parts.append(base)

    coverage = latest.get("interest_coverage")
    if coverage is not None:
        giudizio = "ampio margine di sicurezza" if coverage > 8 else ("margine ridotto, da monitorare" if coverage < 2 else "margine adeguato")
        lines.append(f"La copertura degli interessi è {finmod.format_ratio(coverage)}: {giudizio}.")
        score_parts.append(0.3 if coverage > 8 else (-0.6 if coverage < 2 else 0.0))

    current_ratio = latest.get("current_ratio")
    if current_ratio is not None:
        giudizio = "buona liquidità a breve termine" if current_ratio > 1.5 else ("liquidità a breve termine tesa" if current_ratio < 1 else "liquidità nella norma")
        lines.append(f"Il current ratio è {finmod.format_ratio(current_ratio)}: {giudizio}.")
        score_parts.append(0.2 if current_ratio > 1.5 else (-0.5 if current_ratio < 1 else 0.0))

    if quality.get("avg_ratio") is not None:
        lines.append(
            f"Negli ultimi {quality['n_periods']} periodi il free cash flow è stato in media il "
            f"{finmod.format_pct(quality['avg_ratio'])} dell'utile netto riportato."
        )
        if quality["flag"]:
            lines.append(
                "Un divario ampio e persistente tra utile netto e cassa generata: segnale (non "
                "definitivo) che la profittabilità riportata potrebbe non essere pienamente sostenibile "
                "così com'è oggi — da approfondire prima di considerarla solida."
            )
            score_parts.append(-0.6)
        else:
            score_parts.append(0.2)

    score = sum(score_parts) / len(score_parts) if score_parts else None
    verdict = "positivo" if score is not None and score > 0.15 else ("negativo" if score is not None and score < -0.15 else "neutro")
    if not lines:
        lines.append("Dati insufficienti per rispondere a questa domanda su questo titolo (comune per alcuni titoli non statunitensi).")

    return {"key": "sustainability", "icon": "\U0001F6E1", "title": "È sostenibile nel tempo?",
            "verdict": verdict, "text": " ".join(lines), "score": score,
            "roic": roic, "wacc": w, "quality": quality}


# ---------------------------------------------------------------------------
# Domanda 3 — Ha buone prospettive, anche se i dati storici dicono il
# contrario? Qui contano il trend di settore, il consensus reale degli
# analisti e il sentiment sulle news — non altre formule.
# ---------------------------------------------------------------------------

def _section_outlook(symbol: str, price: float | None, peers: list[str] | None) -> dict:
    info = dp.get_info(symbol)
    sector_name = info.get("sector")
    snap = fundamental_snapshot(symbol, price)
    band = finmod.historical_multiple_band(symbol)
    snap_sector = sec.sector_snapshot(sector_name)
    rel = sec.relative_strength(symbol, sector_name)
    peer_table = sec.peer_comparison(symbol, peers) if peers else None
    news = dp.get_news(symbol, limit=8)
    sentiment = ns.sentiment_summary(news)
    macro_snap = mc.get_macro_snapshot()

    lines, score_parts = [], []

    # --- Dove tratta oggi rispetto alla propria storia (dato descrittivo,
    # nessun prezzo target inventato) ---------------------------------
    if band is not None:
        lines.append(
            f"Il titolo tratta oggi a un P/E di {finmod.format_ratio(snap.get('pe_ratio'), suffix='')}, "
            f"contro un range storico (ultimi {band['years']} anni) tra {finmod.format_ratio(band['min'], suffix='')} "
            f"e {finmod.format_ratio(band['max'], suffix='')} (mediana {finmod.format_ratio(band['median'], suffix='')}): "
            f"{band['percentile']:.0f}° percentile della propria storia recente."
        )
        if band["percentile"] > 80:
            lines.append("Buona parte di eventuali buone prospettive potrebbe quindi essere già scontata nel prezzo.")
            score_parts.append(-0.3)
        elif band["percentile"] < 20:
            lines.append("Il prezzo attuale lascia più margine perché eventuali buone notizie vengano ancora premiate.")
            score_parts.append(0.3)

    # --- Consensus reale degli analisti (dato di mercato, non una stima
    # di questa app) ----------------------------------------------------
    target = info.get("target_mean_price")
    n_analysts = info.get("num_analyst_opinions")
    rec = info.get("recommendation_key")
    if target and price and n_analysts:
        implied_return = (target / price - 1) * 100
        comp = "sopra" if implied_return >= 0 else "sotto"
        lines.append(
            f"Il target price medio di {n_analysts} analisti che coprono il titolo è "
            f"{finmod.format_money(target, info.get('currency'))}, un {finmod.format_pct(implied_return, signed=True)} "
            f"{comp} il prezzo attuale (raccomandazione aggregata: {rec or 'n/d'}). È un'opinione di mercato "
            "reale — da pesare in base a quanti analisti la sostengono, non un dato infallibile."
        )
        analyst_score = 0.6 if implied_return > 10 else (-0.6 if implied_return < -10 else 0.0)
        if n_analysts < 3:
            analyst_score *= 0.3  # poca copertura -> peso quasi nullo, dichiarato
        score_parts.append(analyst_score)
    elif target is None:
        lines.append("Nessun target price di analisti disponibile per questo titolo su Yahoo Finance (copertura limitata, tipico per titoli più piccoli o non statunitensi).")

    # --- Trend di settore e forza relativa -----------------------------
    if not sector_name:
        lines.append("Il settore di appartenenza non è disponibile per questo titolo su Yahoo Finance.")
    elif not snap_sector:
        lines.append(f"Il titolo appartiene al settore \"{sector_name}\", ma non è stato possibile trovare un ETF di settore di riferimento.")
    else:
        trend_label = {
            "rialzista": "in un trend rialzista", "ribassista": "in un trend ribassista",
            "laterale": "in una fase laterale",
        }.get(snap_sector["trend"], "senza un trend chiaro")
        lines.append(f"Il settore \"{sector_name}\" (proxy: ETF {snap_sector['etf']}) è {trend_label}"
                     + (f", con un rendimento del {finmod.format_pct(snap_sector['return_3m'], signed=True)} negli ultimi 3 mesi." if snap_sector.get("return_3m") is not None else "."))
        sector_score = {"rialzista": 0.4, "ribassista": -0.4, "laterale": 0.0}.get(snap_sector["trend"], 0.0)
        score_parts.append(sector_score)

        if rel and rel.get("relative_3m") is not None:
            comp = "sopra" if rel["relative_3m"] > 0 else "sotto"
            lines.append(
                f"Il titolo ha reso il {finmod.format_pct(rel['stock_3m'], signed=True)} negli ultimi 3 mesi contro il "
                f"{finmod.format_pct(rel['sector_3m'], signed=True)} del settore: {comp} la media del proprio settore."
            )
            score_parts.append(0.4 if rel["relative_3m"] > 0 else -0.4)

    if peers:
        lines.append(f"Confronto diretto impostato con: {', '.join(peers)} (vedi tabella).")

    # --- Sentiment sulle news recenti ------------------------------------
    if sentiment["total"] == 0:
        lines.append("Non ci sono news recenti disponibili per questo titolo.")
    else:
        lines.append(
            f"Delle ultime {sentiment['total']} notizie, {sentiment['positive']} hanno un tono positivo, "
            f"{sentiment['negative']} negativo, {sentiment['neutral']} neutro: il tono complessivo è "
            f"{sentiment['tone']} (classificazione automatica per parole chiave, da verificare leggendo "
            "gli articoli)."
        )
        if sentiment["tone"] == "prevalentemente positivo":
            score_parts.append(0.3)
        elif sentiment["tone"] == "prevalentemente negativo":
            score_parts.append(-0.3)

    macro_lines = mc.summary_lines(macro_snap)
    if macro_lines:
        lines.append("Contesto macro generale: " + "; ".join(macro_lines) + ".")

    score = sum(score_parts) / len(score_parts) if score_parts else None
    verdict = "positivo" if score is not None and score > 0.15 else ("negativo" if score is not None and score < -0.15 else "neutro")
    if not lines:
        lines.append("Dati insufficienti per rispondere a questa domanda su questo titolo.")

    return {"key": "outlook", "icon": "\U0001F52D", "title": "Ha buone prospettive, anche se i dati storici dicono il contrario?",
            "verdict": verdict, "text": " ".join(lines), "score": score,
            "historical_band": band, "peer_table": peer_table, "news_items": sentiment.get("items", []),
            "snapshot": snap, "sector_snapshot": snap_sector, "relative_strength": rel}


# ---------------------------------------------------------------------------
# Punteggio composito — lettura secondaria rispetto ai tre verdetti in
# chiaro, pensata come base per un futuro motore multi-fattoriale.
# ---------------------------------------------------------------------------

def fundamental_score_breakdown(sections: list[dict]) -> dict:
    by_key = {s["key"]: s for s in sections}
    sub_scores = {}
    for axis in AXIS_WEIGHTS:
        s = by_key.get(axis)
        if s is not None and s.get("score") is not None:
            sub_scores[axis] = s["score"]

    if not sub_scores:
        return {"sub_scores": {}, "weights_used": {}, "total": None}

    total_weight = sum(AXIS_WEIGHTS[k] for k in sub_scores)
    weights_used = {k: AXIS_WEIGHTS[k] / total_weight for k in sub_scores}
    total = sum(sub_scores[k] * weights_used[k] for k in sub_scores)
    return {"sub_scores": sub_scores, "weights_used": weights_used, "total": max(-1.0, min(1.0, total))}


def _write_fundamental_synthesis(sections: list[dict], breakdown: dict) -> str:
    verdicts = {s["key"]: s["verdict"] for s in sections}
    profitability, sustainability, outlook = verdicts.get("profitability"), verdicts.get("sustainability"), verdicts.get("outlook")

    lines = []

    # Le tre risposte in chiaro, prima di ogni altra considerazione.
    resp = {"positivo": "sì", "negativo": "no", "neutro": "parzialmente/misto"}
    if profitability:
        lines.append(f"È profittevole: {resp[profitability]}.")
    if sustainability:
        lines.append(f"È sostenibile nel tempo: {resp[sustainability]}.")
    if outlook:
        lines.append(f"Ha buone prospettive: {resp[outlook]}.")

    # Il caso che conta di più: le prospettive vanno in direzione diversa
    # dai numeri storici (esattamente la domanda "anche se i dati dicono
    # il contrario").
    historical = [v for v in (profitability, sustainability) if v]
    if outlook and historical:
        hist_pos = historical.count("positivo")
        hist_neg = historical.count("negativo")
        if outlook == "positivo" and hist_neg > hist_pos:
            lines.append(
                "Da notare: i numeri storici sono deboli, ma il quadro prospettico (settore, consensus "
                "analisti, sentiment) è positivo — un possibile segnale di inversione, da verificare nei "
                "prossimi trimestri prima di considerarlo confermato."
            )
        elif outlook == "negativo" and hist_pos > hist_neg:
            lines.append(
                "Da notare: i numeri storici sono solidi, ma il quadro prospettico (settore, consensus "
                "analisti, sentiment) è negativo — il mercato potrebbe star scontando un rallentamento "
                "futuro non ancora visibile nei dati passati."
            )
        elif outlook == hist_pos and outlook != "neutro":
            pass  # coerenza già chiara dalle risposte sopra

    total = breakdown.get("total")
    if total is not None:
        lettura = "solida" if total > 0.3 else ("debole" if total < -0.3 else "mista")
        lines.append(f"Lettura sintetica complessiva: {lettura} (punteggio composito {total:+.2f} su scala -1/+1, media pesata delle tre domande).")

    lines.append(
        "Resta un'analisi statistica basata su dati pubblici passati e sul consensus di mercato attuale, "
        "non una previsione né una raccomandazione operativa."
    )
    return " ".join(lines)


def build_fundamental_narrative(symbol: str, peers: list[str] | None = None) -> dict:
    """Analisi organizzata sulle tre domande descritte nel docstring del
    modulo, con un punteggio per domanda e una sintesi finale che
    risponde in chiaro e segnala esplicitamente quando le prospettive
    vanno in direzione diversa dai numeri storici."""
    price = dp.get_current_price(symbol)

    profitability_sec = _section_profitability(symbol)
    annual = profitability_sec.get("annual") or {}

    sections = [
        profitability_sec,
        _section_sustainability(symbol, annual),
        _section_outlook(symbol, price, peers),
    ]
    breakdown = fundamental_score_breakdown(sections)
    return {"sections": sections, "synthesis": _write_fundamental_synthesis(sections, breakdown), "score_breakdown": breakdown}
