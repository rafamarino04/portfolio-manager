"""
Analisi fondamentale in stile Damodaran: il valore di un'azienda dipende
da flussi di cassa, crescita e rischio — non da un multiplo isolato o da
un singolo ratio guardato in isolamento.

L'impianto è organizzato per assi di analisi, ognuno pensato per
rispondere a una domanda concreta che un analista si farebbe prima di
investire, non solo per riportare un numero:

  1. Crescita e profittabilità     -> l'azienda cresce, e cresce con
                                       margini che si mantengono o si
                                       espandono (crescita "di qualità")?
  2. Rendimento sul capitale       -> l'azienda crea valore, cioè rende
     e creazione di valore            di più di quanto costa il capitale
                                       investito (ROIC vs WACC), non solo
                                       "ha un ROE alto"?
  3. Solidità finanziaria e        -> quanto è a rischio in caso di
     qualità degli utili              stress (leva, liquidità, copertura
                                       interessi), e gli utili riportati
                                       si traducono davvero in cassa?
  4. Valutazione                   -> il prezzo attuale è caro o a buon
                                       mercato *rispetto alla storia del
                                       titolo stesso*, non solo rispetto
                                       a un numero assoluto?
  5. Contesto settoriale           -> come si comporta rispetto al
     e competitivo                   proprio settore (ETF proxy) e ai
                                       concorrenti indicati?
  6. Notizie e prospettive         -> cosa raccontano le news recenti e
                                       il contesto macro generale?

Ogni asse produce un sotto-punteggio motivato ed esplicito (non una
scatola nera): la funzione `fundamental_score_breakdown` li combina in un
punteggio composito pensato per essere riusabile come input di un futuro
motore di punteggio multi-fattoriale (che unirà tecnica, fondamentale,
macro). Se un asse è debole o mancante, il peso si ridistribuisce sugli
altri invece di forzare un numero su dati che non ci sono.

Il costo del capitale (CAPM/WACC) usa un tasso privo di rischio *live*
(non un valore scritto a mano, che diventerebbe stale in poche settimane)
e un equity risk premium dichiarato esplicitamente come costante
metodologica. La valutazione resta relativa (multipli confrontati con la
storia del titolo stesso e con eventuali concorrenti), non un fair value
stimato con un DCF: le assunzioni di crescita di lungo periodo
richiederebbero dati che non sono disponibili gratuitamente.
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
# letteratura (Damodaran incluso) per il mercato USA. Non è un dato live —
# è una costante metodologica ragionevole, dichiarata esplicitamente.
EQUITY_RISK_PREMIUM_PCT = 4.5

# Pesi degli assi nel punteggio composito. Si ridistribuiscono sugli assi
# disponibili quando uno manca (es. nessun ratio di leva calcolabile).
AXIS_WEIGHTS = {
    "growth": 0.25,
    "capital_returns": 0.30,
    "financial_health": 0.20,
    "valuation": 0.25,
}


# ---------------------------------------------------------------------------
# Costo del capitale
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


# ---------------------------------------------------------------------------
# Snapshot "puntuale" (usato dalla sezione valutazione)
# ---------------------------------------------------------------------------

def fundamental_snapshot(symbol: str, price: float | None = None) -> dict:
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
# Sezione 1 — Crescita e profittabilità
# ---------------------------------------------------------------------------

def _section_growth_profitability(symbol: str) -> dict:
    annual = finmod.get_financial_history(symbol, freq="annual")
    margins = finmod.compute_margins(annual)
    currency = dp.get_info(symbol).get("currency")
    lines, score_parts = [], []
    verdict = "neutro"

    rev, ni, ebitda = annual.get("revenue"), annual.get("net_income"), annual.get("ebitda")

    if rev is None and ni is None:
        lines.append(
            "Non ci sono prospetti contabili sufficienti per questo titolo su Yahoo Finance "
            "(capita per alcuni titoli non statunitensi o a copertura limitata)."
        )
        return {"key": "growth", "icon": "\U0001F4C8", "title": "Crescita e profittabilità",
                "verdict": verdict, "text": " ".join(lines), "score": None,
                "annual": annual, "margins": margins}

    if rev is not None and len(rev) >= 2:
        rev_info = finmod.latest_and_yoy(rev)
        rev_cagr = finmod.growth_rate(rev)
        rev_trend = finmod.growth_trend(rev)
        if rev_info["yoy_pct"] is not None:
            direz = "in crescita" if rev_info["yoy_pct"] > 0 else "in calo"
            lines.append(
                f"I ricavi sono {direz} del {finmod.format_pct(rev_info['yoy_pct'], signed=True)} "
                f"rispetto al periodo precedente, a {finmod.format_money(rev_info['latest'], currency)}."
            )
            score_parts.append(0.6 if rev_info["yoy_pct"] > 5 else (-0.5 if rev_info["yoy_pct"] < 0 else 0.1))
        if rev_cagr is not None and len(rev) > 2:
            lines.append(f"Sull'intero storico disponibile la crescita media annua (CAGR) è del {finmod.format_pct(rev_cagr, signed=True)}.")
        if rev_trend:
            qualifica = {
                "in accelerazione": "un segnale incoraggiante, non scontato in questa fase.",
                "in decelerazione": "da monitorare se si accompagna anche a margini in calo.",
                "stabile": "senza forti cambi di ritmo.",
            }[rev_trend]
            lines.append(f"Il ritmo di crescita è {rev_trend}: {qualifica}")

    if ebitda is not None and len(ebitda) >= 1:
        ebitda_margin = margins.get("ebitda_margin")
        latest_ebitda = float(ebitda.iloc[-1])
        txt = f"L'EBITDA più recente è {finmod.format_money(latest_ebitda, currency)}"
        if ebitda_margin is not None and not ebitda_margin.empty:
            txt += f", pari a un margine EBITDA del {finmod.format_pct(ebitda_margin.iloc[-1])}"
            trend = finmod.margin_trend(ebitda_margin)
            if trend:
                txt += f" ({trend} nel periodo osservato)"
                score_parts.append(0.5 if trend == "in espansione" else (-0.5 if trend == "in contrazione" else 0.0))
        lines.append(txt + ".")

    if ni is not None and len(ni) >= 1:
        ni_info = finmod.latest_and_yoy(ni)
        if ni_info["yoy_pct"] is not None:
            direz = "in crescita" if ni_info["yoy_pct"] > 0 else "in calo"
            lines.append(f"L'utile netto è {direz} del {finmod.format_pct(ni_info['yoy_pct'], signed=True)} sull'ultimo periodo.")
        if ni_info["latest"] is not None and ni_info["latest"] < 0:
            lines.append("L'ultimo periodo si è chiuso in perdita.")
            score_parts.append(-0.8)

    net_margin = margins.get("net_margin")
    if net_margin is not None and not net_margin.empty:
        nm = net_margin.iloc[-1]
        lines.append(f"Il margine netto più recente è del {finmod.format_pct(nm)}.")
        score_parts.append(0.4 if nm > 10 else (-0.3 if nm < 2 else 0.0))

    score = sum(score_parts) / len(score_parts) if score_parts else None
    if score is not None:
        verdict = "positivo" if score > 0.15 else ("negativo" if score < -0.15 else "neutro")
    if not lines:
        lines.append("Dati di crescita/profittabilità insufficienti per un giudizio su questo titolo.")

    return {"key": "growth", "icon": "\U0001F4C8", "title": "Crescita e profittabilità",
            "verdict": verdict, "text": " ".join(lines), "score": score,
            "annual": annual, "margins": margins}


# ---------------------------------------------------------------------------
# Sezione 2 — Rendimento sul capitale e creazione di valore
# ---------------------------------------------------------------------------

def _section_capital_returns(symbol: str, annual: dict) -> dict:
    info = dp.get_info(symbol)
    macro_snap = mc.get_macro_snapshot()
    ratios = finmod.compute_ratios(annual)
    latest = finmod.latest_ratios(annual, ratios, market_cap=info.get("market_cap"))

    beta = info.get("beta")
    risk_free = macro_snap.get("ten_year_yield")
    coe = cost_of_equity(beta, risk_free)
    debt_latest = finmod._last(annual.get("total_debt"))
    interest_latest = finmod._last(annual.get("interest_expense"))
    cod = cost_of_debt(interest_latest, debt_latest, risk_free)
    w = wacc(coe, cod, latest.get("effective_tax_rate"), info.get("market_cap"), debt_latest)

    roic = latest.get("roic")
    roe = info.get("return_on_equity")
    roe_pct = roe * 100 if roe is not None else None

    lines, score_parts = [], []

    if roe_pct is not None:
        giudizio = "un livello solido" if roe_pct > 15 else ("piuttosto basso" if roe_pct < 5 else "un livello nella media")
        lines.append(f"Il ROE (rendimento sul capitale proprio) è del {finmod.format_pct(roe_pct)}, {giudizio}.")

    if roic is not None and w is not None:
        spread = roic - w
        lines.append(
            f"Il ROIC (rendimento sul capitale investito, comprende anche il debito) è circa "
            f"{finmod.format_pct(roic)}, contro un costo del capitale (WACC) stimato del {finmod.format_pct(w)}: "
            f"uno spread di {finmod.format_pct(spread, signed=True)} punti."
        )
        if spread > 2:
            lines.append("Il capitale investito rende più di quanto costa: l'azienda sta creando valore per gli azionisti.")
            score_parts.append(min(1.0, 0.5 + spread / 20))
        elif spread < -2:
            lines.append("Il capitale investito rende meno di quanto costa: a questi livelli l'azienda distrugge valore, anche se contabilmente è profittevole.")
            score_parts.append(max(-1.0, -0.5 + spread / 20))
        else:
            lines.append("Il rendimento sul capitale è in linea con il suo costo: né creazione né distruzione di valore marcata.")
            score_parts.append(0.0)
    elif roe_pct is not None:
        score_parts.append(0.6 if roe_pct > 15 else (-0.5 if roe_pct < 5 else 0.0))

    if coe is not None:
        beta_txt = f"{beta:.2f}" if beta is not None else "n/d"
        lines.append(
            f"Costo del capitale proprio (CAPM, beta {beta_txt}, tasso privo di rischio live "
            f"{finmod.format_pct(risk_free) if risk_free is not None else 'n/d'}): {finmod.format_pct(coe)} — "
            "il rendimento minimo che un investitore razionale richiederebbe dato il rischio del titolo."
        )

    score = sum(score_parts) / len(score_parts) if score_parts else None
    verdict = "positivo" if score is not None and score > 0.15 else ("negativo" if score is not None and score < -0.15 else "neutro")
    if not lines:
        lines.append("Dati insufficienti per valutare il rendimento sul capitale di questo titolo.")

    return {"key": "capital_returns", "icon": "\U0001F3AF", "title": "Rendimento sul capitale e creazione di valore",
            "verdict": verdict, "text": " ".join(lines), "score": score,
            "roic": roic, "wacc": w, "roe_pct": roe_pct}


# ---------------------------------------------------------------------------
# Sezione 3 — Solidità finanziaria e qualità degli utili
# ---------------------------------------------------------------------------

def _section_financial_health(symbol: str, annual: dict) -> dict:
    ratios = finmod.compute_ratios(annual)
    latest = finmod.latest_ratios(annual, ratios)
    quality = finmod.earnings_quality_flag(annual)

    lines, score_parts = [], []

    nd_ebitda = latest.get("net_debt_to_ebitda")
    if nd_ebitda is not None:
        if nd_ebitda < 0:
            lines.append(f"L'azienda ha più cassa che debito (debito netto/EBITDA {finmod.format_ratio(nd_ebitda)}): la leva finanziaria non è un tema.")
            score_parts.append(0.6)
        else:
            giudizio = "contenuta" if nd_ebitda < 2 else ("elevata" if nd_ebitda > 4 else "moderata")
            lines.append(f"Il debito netto è {finmod.format_ratio(nd_ebitda)} l'EBITDA annuo: leva {giudizio}.")
            score_parts.append(0.4 if nd_ebitda < 2 else (-0.7 if nd_ebitda > 4 else -0.1))

    coverage = latest.get("interest_coverage")
    if coverage is not None:
        giudizio = "ampio margine di sicurezza" if coverage > 8 else ("margine ridotto, da monitorare" if coverage < 2 else "margine adeguato")
        lines.append(f"La copertura degli interessi (utile operativo/interessi passivi) è {finmod.format_ratio(coverage)}: {giudizio}.")
        score_parts.append(0.4 if coverage > 8 else (-0.6 if coverage < 2 else 0.0))

    current_ratio = latest.get("current_ratio")
    if current_ratio is not None:
        giudizio = "buona liquidità a breve termine" if current_ratio > 1.5 else ("liquidità a breve termine tesa" if current_ratio < 1 else "liquidità a breve termine nella norma")
        lines.append(f"Il current ratio (attività correnti/passività correnti) è {finmod.format_ratio(current_ratio)}: {giudizio}.")
        score_parts.append(0.3 if current_ratio > 1.5 else (-0.5 if current_ratio < 1 else 0.0))

    if quality.get("avg_ratio") is not None:
        lines.append(
            f"Negli ultimi {quality['n_periods']} periodi il free cash flow è stato in media il "
            f"{finmod.format_pct(quality['avg_ratio'])} dell'utile netto riportato."
        )
        if quality["flag"]:
            lines.append(
                "Questo è un divario ampio e persistente: un segnale (non definitivo) di qualità "
                "degli utili da approfondire — l'utile contabile non si sta traducendo pienamente in cassa."
            )
            score_parts.append(-0.6)
        else:
            score_parts.append(0.2)

    score = sum(score_parts) / len(score_parts) if score_parts else None
    verdict = "positivo" if score is not None and score > 0.15 else ("negativo" if score is not None and score < -0.15 else "neutro")
    if not lines:
        lines.append("Dati insufficienti per valutare la solidità finanziaria di questo titolo (comune per alcuni titoli non statunitensi).")

    return {"key": "financial_health", "icon": "\U0001F6E1", "title": "Solidità finanziaria e qualità degli utili",
            "verdict": verdict, "text": " ".join(lines), "score": score, "quality": quality}


# ---------------------------------------------------------------------------
# Sezione 4 — Valutazione
# ---------------------------------------------------------------------------

def _section_valuation(symbol: str, price: float | None) -> dict:
    snap = fundamental_snapshot(symbol, price)
    band = finmod.historical_multiple_band(symbol)
    lines, score_parts = [], []

    pe = snap.get("pe_ratio")
    if pe is not None:
        lines.append(f"Il P/E attuale è {finmod.format_ratio(pe, suffix='')}.")

    if band is not None:
        lines.append(
            f"Rispetto allo storico degli ultimi {band['years']} anni, il P/E del titolo ha "
            f"oscillato tra {finmod.format_ratio(band['min'], suffix='')} e {finmod.format_ratio(band['max'], suffix='')} "
            f"(mediana {finmod.format_ratio(band['median'], suffix='')}): il valore attuale si trova al "
            f"{band['percentile']:.0f}° percentile di quel range."
        )
        if band["percentile"] > 80:
            lines.append("Il titolo tratta quindi vicino ai massimi della propria storia recente: una parte importante delle attese positive potrebbe già essere nel prezzo.")
            score_parts.append(-0.6)
        elif band["percentile"] < 20:
            lines.append("Il titolo tratta quindi vicino ai minimi della propria storia recente: a parità di fondamentali, un punto di ingresso più favorevole della media.")
            score_parts.append(0.6)
        else:
            lines.append("Il titolo tratta in una fascia intermedia della propria storia recente, né a sconto né a premio marcato.")
            score_parts.append(0.0)
    elif pe is not None:
        lines.append("Non è stato possibile costruire un range storico del P/E per questo titolo (storico insufficiente su Yahoo Finance): il multiplo va letto solo in valore assoluto, con più cautela.")

    peg = snap.get("peg_ratio")
    if peg is not None:
        if 0 < peg < 1:
            lines.append(f"Il PEG (P/E corretto per la crescita) è {finmod.format_ratio(peg)}: il prezzo appare contenuto rispetto al ritmo di crescita.")
            score_parts.append(0.5)
        elif peg > 2.5:
            lines.append(f"Il PEG è {finmod.format_ratio(peg)}: il prezzo appare elevato rispetto al ritmo di crescita.")
            score_parts.append(-0.5)
        else:
            lines.append(f"Il PEG è {finmod.format_ratio(peg)}, in una fascia né a buon mercato né eccessiva.")
            score_parts.append(0.0)

    pb = snap.get("price_to_book")
    if pb is not None:
        lines.append(f"Il P/B (prezzo/patrimonio netto) è {finmod.format_ratio(pb)}.")

    div_yield = snap.get("dividend_yield")
    if div_yield:
        lines.append(f"Dividend yield: {finmod.format_pct(div_yield*100)}.")

    score = sum(score_parts) / len(score_parts) if score_parts else None
    verdict = "positivo" if score is not None and score > 0.15 else ("negativo" if score is not None and score < -0.15 else "neutro")
    if not lines:
        lines.append("Dati fondamentali insufficienti per una valutazione su questo titolo.")

    return {"key": "valuation", "icon": "\U0001F4B0", "title": "Valutazione",
            "verdict": verdict, "text": " ".join(lines), "score": score,
            "snapshot": snap, "historical_band": band}


# ---------------------------------------------------------------------------
# Sezione 5 — Contesto settoriale e competitivo
# ---------------------------------------------------------------------------

def _section_sector(symbol: str, sector_name: str | None, peers: list[str] | None) -> dict:
    lines = []
    verdict = "neutro"
    peer_table = None

    snap_sector = sec.sector_snapshot(sector_name)
    rel = sec.relative_strength(symbol, sector_name)

    if not sector_name:
        lines.append("Il settore di appartenenza non è disponibile per questo titolo su Yahoo Finance.")
    elif not snap_sector:
        lines.append(
            f"Il titolo appartiene al settore \"{sector_name}\", ma non è stato possibile trovare "
            "un ETF di settore di riferimento per confrontarlo."
        )
    else:
        trend_label = {
            "rialzista": "in un trend rialzista", "ribassista": "in un trend ribassista",
            "laterale": "in una fase laterale",
        }.get(snap_sector["trend"], "senza un trend chiaro")
        lines.append(f"Il settore \"{sector_name}\" (proxy: ETF {snap_sector['etf']}) è {trend_label}.")
        if snap_sector.get("return_3m") is not None:
            lines.append(f"Negli ultimi 3 mesi il settore ha reso il {finmod.format_pct(snap_sector['return_3m'], signed=True)}.")

        if rel and rel.get("relative_3m") is not None:
            comp = "sopra" if rel["relative_3m"] > 0 else "sotto"
            lines.append(
                f"Il titolo ha reso il {finmod.format_pct(rel['stock_3m'], signed=True)} negli ultimi 3 mesi contro il "
                f"{finmod.format_pct(rel['sector_3m'], signed=True)} del settore: {comp} la media del proprio settore di "
                f"{abs(rel['relative_3m']):.1f} punti percentuali."
            )
            verdict = "positivo" if rel["relative_3m"] > 0 else "negativo"

    if peers:
        peer_table = sec.peer_comparison(symbol, peers)
        lines.append(f"Confronto diretto impostato con: {', '.join(peers)} (vedi tabella).")

    if not lines:
        lines.append("Nessun contesto settoriale disponibile per questo titolo.")

    return {"key": "sector", "icon": "\U0001F3ED", "title": "Contesto settoriale e competitivo",
            "verdict": verdict, "text": " ".join(lines), "peer_table": peer_table,
            "sector_snapshot": snap_sector, "relative_strength": rel}


# ---------------------------------------------------------------------------
# Sezione 6 — Notizie e prospettive future
# ---------------------------------------------------------------------------

def _section_news(symbol: str) -> dict:
    news = dp.get_news(symbol, limit=8)
    sentiment = ns.sentiment_summary(news)
    macro_snap = mc.get_macro_snapshot()

    lines = []
    verdict = "neutro"
    if sentiment["total"] == 0:
        lines.append("Non ci sono news recenti disponibili per questo titolo.")
    else:
        lines.append(
            f"Delle ultime {sentiment['total']} notizie, {sentiment['positive']} hanno un tono "
            f"positivo, {sentiment['negative']} negativo, {sentiment['neutral']} neutro: il tono "
            f"complessivo è {sentiment['tone']} (classificazione automatica per parole chiave, da "
            "verificare leggendo gli articoli)."
        )
        if sentiment["tone"] == "prevalentemente positivo":
            verdict = "positivo"
        elif sentiment["tone"] == "prevalentemente negativo":
            verdict = "negativo"

    macro_lines = mc.summary_lines(macro_snap)
    if macro_lines:
        lines.append("Contesto macro generale: " + "; ".join(macro_lines) + ".")

    return {"key": "news", "icon": "\U0001F4F0", "title": "Notizie e prospettive future",
            "verdict": verdict, "text": " ".join(lines), "news_items": sentiment.get("items", [])}


# ---------------------------------------------------------------------------
# Punteggio composito per asse — pensato per essere riusato dal futuro
# motore di punteggio multi-fattoriale (tecnica + fondamentale + macro).
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
    core_axes = ["growth", "capital_returns", "financial_health", "valuation"]
    core_votes = [verdicts[k] for k in core_axes if k in verdicts]
    pos, neg = core_votes.count("positivo"), core_votes.count("negativo")

    lines = []
    total = breakdown.get("total")
    if total is not None:
        lines.append(f"Punteggio fondamentale composito: {total:+.2f} (scala da -1 a +1, media pesata dei quattro assi di analisi principali).")

    if pos >= 3 and neg == 0:
        lines.append(
            "Il quadro fondamentale è coerentemente positivo: crescita, rendimento sul capitale, "
            "solidità finanziaria e valutazione puntano nella stessa direzione. La convergenza rende "
            "il quadro più solido, non una garanzia sui risultati futuri."
        )
    elif neg >= 3 and pos == 0:
        lines.append(
            "Il quadro fondamentale è coerentemente negativo: più assi di analisi puntano nella "
            "stessa direzione sfavorevole."
        )
    elif pos > neg:
        lines.append(
            "Il quadro è prevalentemente positivo, ma non unanime: almeno un asse si muove in "
            "controtendenza rispetto al resto dell'analisi."
        )
    elif neg > pos:
        lines.append(
            "Il quadro è prevalentemente negativo, ma non unanime: almeno un asse si muove in "
            "controtendenza rispetto al resto dell'analisi."
        )
    else:
        lines.append(
            "Il quadro è misto: i diversi assi non raccontano la stessa storia. In questi casi è "
            "particolarmente importante capire quale fattore pesa di più per le proprie priorità "
            "d'investimento."
        )

    if verdicts.get("growth") == "positivo" and verdicts.get("valuation") == "negativo":
        lines.append(
            "In particolare, crescita e profittabilità sono positive ma la valutazione appare già "
            "elevata rispetto alla storia del titolo: il mercato potrebbe aver già prezzato buona "
            "parte delle attese."
        )
    if verdicts.get("growth") == "negativo" and verdicts.get("valuation") == "positivo":
        lines.append(
            "In particolare, la valutazione appare a buon mercato rispetto alla storia del titolo, "
            "ma crescita e profittabilità si stanno deteriorando: un multiplo basso da solo non è "
            "garanzia di occasione, se i fondamentali continuano a peggiorare."
        )
    if verdicts.get("capital_returns") == "negativo" and verdicts.get("financial_health") != "negativo":
        lines.append(
            "Da notare: il capitale investito non sembra rendere a sufficienza rispetto al suo "
            "costo, anche se la solidità finanziaria di per sé non è il problema principale — un "
            "profilo tipico di aziende profittevoli contabilmente ma poco efficienti nell'allocare "
            "capitale."
        )

    lines.append(
        "Resta un'analisi statistica basata su dati pubblici passati, non una previsione né una "
        "raccomandazione operativa."
    )
    return " ".join(lines)


def build_fundamental_narrative(symbol: str, peers: list[str] | None = None) -> dict:
    """Analisi sezionata in stile report per un singolo titolo, sui sei
    assi descritti nel docstring del modulo, con un punteggio composito
    per asse e una sintesi finale che ragiona sull'accordo/disaccordo tra
    gli assi invece di limitarsi a concatenarli."""
    info = dp.get_info(symbol)
    price = dp.get_current_price(symbol)

    growth_sec = _section_growth_profitability(symbol)
    annual = growth_sec.get("annual") or {}

    sections = [
        growth_sec,
        _section_capital_returns(symbol, annual),
        _section_financial_health(symbol, annual),
        _section_valuation(symbol, price),
        _section_sector(symbol, info.get("sector"), peers),
        _section_news(symbol),
    ]
    breakdown = fundamental_score_breakdown(sections)
    return {"sections": sections, "synthesis": _write_fundamental_synthesis(sections, breakdown), "score_breakdown": breakdown}
