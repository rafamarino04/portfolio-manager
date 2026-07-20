"""
Analisi fondamentale in stile Damodaran: il valore di un'azienda dipende
da flussi di cassa, crescita e rischio — non da un multiplo isolato. Qui
si applica quella logica ai dati disponibili: multipli confrontati contro
la storia del titolo stesso (non contro un dato di settore statico, che
richiederebbe un database a pagamento), un costo del capitale via CAPM
costruito su un tasso privo di rischio *live* (non un valore scritto a
mano, che diventerebbe stale in poche settimane), e controlli di qualità
su redditività e leva finanziaria.
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


def cost_of_equity(beta: float | None, risk_free_pct: float | None) -> float | None:
    """CAPM: costo del capitale proprio = risk free + beta * risk premium."""
    if beta is None or risk_free_pct is None:
        return None
    return risk_free_pct + beta * EQUITY_RISK_PREMIUM_PCT


def _rate(x, default=None):
    return x if x is not None else default


def fundamental_snapshot(symbol: str, price: float | None, week52_range: tuple | None = None) -> dict:
    info = dp.get_info(symbol)
    macro_snap = mc.get_macro_snapshot()

    beta = info.get("beta")
    coe = cost_of_equity(beta, macro_snap.get("ten_year_yield"))

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
        "cost_of_equity_pct": coe,
        "dividend_yield": info.get("dividend_yield"),
    }


def fundamental_score(snap: dict) -> float | None:
    """Punteggio sintetico da -1 a +1 sulla base di redditività, crescita,
    leva e valutazione growth-adjusted (PEG)."""
    parts = []

    roe = snap.get("return_on_equity")
    if roe is not None:
        parts.append(1.0 if roe > 0.15 else (-0.5 if roe < 0.05 else 0.0))

    margins = snap.get("profit_margins")
    if margins is not None:
        parts.append(0.7 if margins > 0.15 else (-0.5 if margins < 0.02 else 0.0))

    dte = snap.get("debt_to_equity")
    if dte is not None:
        # debt_to_equity di yfinance e' spesso in percentuale (es. 150 = 1.5x)
        ratio = dte / 100 if dte > 5 else dte
        parts.append(-0.7 if ratio > 2 else (0.3 if ratio < 0.5 else 0.0))

    growth = snap.get("revenue_growth")
    if growth is not None:
        parts.append(0.7 if growth > 0.10 else (-0.3 if growth < 0 else 0.0))

    peg = snap.get("peg_ratio")
    if peg is not None:
        if 0 < peg < 1:
            parts.append(0.7)
        elif peg > 2.5:
            parts.append(-0.7)
        else:
            parts.append(0.0)

    if not parts:
        return None
    return max(-1.0, min(1.0, sum(parts) / len(parts)))


def interpret(snap: dict) -> list[str]:
    lines = []
    if snap.get("return_on_equity") is not None:
        lines.append(f"ROE: {snap['return_on_equity']*100:.1f}%")
    if snap.get("profit_margins") is not None:
        lines.append(f"Margine di profitto: {snap['profit_margins']*100:.1f}%")
    if snap.get("debt_to_equity") is not None:
        lines.append(f"Debito/Equity: {snap['debt_to_equity']:.0f}")
    if snap.get("revenue_growth") is not None:
        lines.append(f"Crescita ricavi: {snap['revenue_growth']*100:.1f}%")
    if snap.get("peg_ratio") is not None:
        lines.append(f"PEG (P/E corretto per la crescita): {snap['peg_ratio']:.2f}")
    if snap.get("cost_of_equity_pct") is not None:
        lines.append(
            f"Costo del capitale (CAPM, beta {snap.get('beta', 0):.2f}): "
            f"{snap['cost_of_equity_pct']:.1f}% — rendimento minimo richiesto dato il rischio"
        )
    return lines


# ---------------------------------------------------------------------------
# Analisi sezionata in stile report (numeri di bilancio, valutazione,
# contesto settoriale, notizie) + sintesi finale — stesso impianto usato
# in src/technical.py per l'analisi tecnica.
# ---------------------------------------------------------------------------

def _section_financials(symbol: str) -> dict:
    annual = finmod.get_financial_history(symbol, freq="annual")
    margins = finmod.compute_margins(annual)
    lines = []
    verdict = "neutro"

    rev = annual.get("revenue")
    ni = annual.get("net_income")
    fcf = annual.get("free_cash_flow")
    debt = annual.get("total_debt")
    equity = annual.get("total_equity")

    if rev is None and ni is None:
        lines.append(
            "Non ci sono prospetti contabili sufficienti per questo titolo su Yahoo Finance "
            "(capita per alcuni titoli non statunitensi o a copertura limitata)."
        )
        return {"key": "financials", "icon": "\U0001F9FE", "title": "Numeri di bilancio",
                "verdict": verdict, "text": " ".join(lines), "annual": annual, "margins": margins}

    if rev is not None and len(rev) >= 2:
        rev_info = finmod.latest_and_yoy(rev)
        rev_cagr = finmod.growth_rate(rev)
        if rev_info["yoy_pct"] is not None:
            direz = "in crescita" if rev_info["yoy_pct"] > 0 else "in calo"
            lines.append(
                f"I ricavi sono {direz} del {rev_info['yoy_pct']:+.1f}% rispetto al periodo "
                f"precedente (ultimo dato disponibile: {rev_info['latest']:,.0f})."
            )
            if rev_cagr is not None and len(rev) > 2:
                lines.append(f"Sull'intero periodo disponibile la crescita media annua dei ricavi è del {rev_cagr:+.1f}%.")
            verdict = "positivo" if rev_info["yoy_pct"] > 0 else "negativo"

    if ni is not None and len(ni) >= 2:
        ni_info = finmod.latest_and_yoy(ni)
        if ni_info["yoy_pct"] is not None:
            direz = "in crescita" if ni_info["yoy_pct"] > 0 else "in calo"
            lines.append(f"L'utile netto è {direz} del {ni_info['yoy_pct']:+.1f}% sull'ultimo periodo.")
        if ni_info["latest"] is not None and ni_info["latest"] < 0:
            lines.append("L'ultimo periodo si è chiuso in perdita.")
            verdict = "negativo"

    net_margin = margins.get("net_margin")
    if net_margin is not None and not net_margin.empty:
        lines.append(f"Il margine netto più recente è del {net_margin.iloc[-1]:.1f}%.")

    if fcf is not None and len(fcf) >= 1:
        latest_fcf = float(fcf.iloc[-1])
        stato = "positivo" if latest_fcf > 0 else "negativo"
        spiegazione = ("l'azienda genera più cassa di quanta ne investa" if latest_fcf > 0
                        else "l'azienda assorbe più cassa di quanta ne generi")
        lines.append(f"Il free cash flow più recente è {stato} ({latest_fcf:,.0f}): {spiegazione}.")

    if debt is not None and equity is not None and len(debt) >= 1 and len(equity) >= 1:
        try:
            d, e = float(debt.iloc[-1]), float(equity.iloc[-1])
            if e:
                lines.append(f"Il rapporto debito/patrimonio netto più recente è {d / e:.2f}.")
        except Exception:
            pass

    if not lines:
        lines.append("Dati di bilancio insufficienti per un giudizio su questo titolo.")

    return {"key": "financials", "icon": "\U0001F9FE", "title": "Numeri di bilancio",
            "verdict": verdict, "text": " ".join(lines), "annual": annual, "margins": margins}


def _section_valuation(symbol: str, price: float | None) -> dict:
    snap = fundamental_snapshot(symbol, price)
    score = fundamental_score(snap)
    lines = []

    roe = snap.get("return_on_equity")
    if roe is not None:
        giudizio = ", un livello solido" if roe > 0.15 else (", piuttosto basso" if roe < 0.05 else "")
        lines.append(f"Il ROE (rendimento sul capitale proprio) è del {roe*100:.1f}%{giudizio}.")

    margins = snap.get("profit_margins")
    if margins is not None:
        giudizio = ", tra i più alti del mercato" if margins > 0.15 else (", contenuto" if margins < 0.02 else "")
        lines.append(f"Il margine di profitto è del {margins*100:.1f}%{giudizio}.")

    dte = snap.get("debt_to_equity")
    if dte is not None:
        ratio = dte / 100 if dte > 5 else dte
        giudizio = (": una leva finanziaria elevata da monitorare" if ratio > 2
                    else (": una leva contenuta" if ratio < 0.5 else ""))
        lines.append(f"Il rapporto debito/equity è {ratio:.2f}{giudizio}.")

    growth = snap.get("revenue_growth")
    if growth is not None:
        giudizio = ", una crescita solida" if growth > 0.10 else (", in calo" if growth < 0 else ", moderata")
        lines.append(f"La crescita dei ricavi è del {growth*100:.1f}%{giudizio}.")

    peg = snap.get("peg_ratio")
    if peg is not None:
        if 0 < peg < 1:
            lines.append(f"Il PEG (P/E corretto per la crescita) è {peg:.2f}: il prezzo appare contenuto rispetto al ritmo di crescita.")
        elif peg > 2.5:
            lines.append(f"Il PEG è {peg:.2f}: il prezzo appare elevato rispetto al ritmo di crescita.")
        else:
            lines.append(f"Il PEG è {peg:.2f}, in una fascia né a buon mercato né eccessiva.")

    coe = snap.get("cost_of_equity_pct")
    if coe is not None:
        lines.append(
            f"Il costo del capitale stimato (CAPM, beta {snap.get('beta', 0):.2f}) è {coe:.1f}%: "
            "il rendimento minimo che un investitore razionale richiederebbe dato il rischio del titolo."
        )

    verdict = "positivo" if score is not None and score > 0.15 else ("negativo" if score is not None and score < -0.15 else "neutro")
    if not lines:
        lines.append("Dati fondamentali insufficienti per una valutazione su questo titolo.")

    return {"key": "valuation", "icon": "\U0001F4B0", "title": "Qualità e valutazione",
            "verdict": verdict, "text": " ".join(lines), "score": score, "snapshot": snap}


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
            lines.append(f"Negli ultimi 3 mesi il settore ha reso il {snap_sector['return_3m']:+.1f}%.")

        if rel and rel.get("relative_3m") is not None:
            comp = "sopra" if rel["relative_3m"] > 0 else "sotto"
            lines.append(
                f"Il titolo ha reso il {rel['stock_3m']:+.1f}% negli ultimi 3 mesi contro il "
                f"{rel['sector_3m']:+.1f}% del settore: {comp} la media del proprio settore di "
                f"{abs(rel['relative_3m']):.1f} punti percentuali."
            )
            verdict = "positivo" if rel["relative_3m"] > 0 else "negativo"

    if peers:
        peer_table = sec.peer_comparison(symbol, peers)
        lines.append(f"Confronto diretto impostato con: {', '.join(peers)} (vedi tabella).")

    if not lines:
        lines.append("Nessun contesto settoriale disponibile per questo titolo.")

    return {"key": "sector", "icon": "\U0001F3ED", "title": "Contesto settoriale",
            "verdict": verdict, "text": " ".join(lines), "peer_table": peer_table,
            "sector_snapshot": snap_sector, "relative_strength": rel}


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


def _write_fundamental_synthesis(sections: list[dict]) -> str:
    verdicts = {s["key"]: s["verdict"] for s in sections}
    votes = list(verdicts.values())
    pos, neg = votes.count("positivo"), votes.count("negativo")

    lines = []
    if pos >= 3 and neg == 0:
        lines.append(
            "Il quadro fondamentale è coerentemente positivo: bilancio, valutazione e contesto "
            "settoriale/news puntano nella stessa direzione. La convergenza rende il quadro più "
            "solido, non una garanzia sui risultati futuri."
        )
    elif neg >= 3 and pos == 0:
        lines.append(
            "Il quadro fondamentale è coerentemente negativo: bilancio, valutazione e contesto "
            "settoriale/news puntano tutti nella stessa direzione sfavorevole."
        )
    elif pos > neg:
        lines.append(
            "Il quadro è prevalentemente positivo, ma non unanime: almeno un fattore si muove in "
            "controtendenza rispetto al resto dell'analisi."
        )
    elif neg > pos:
        lines.append(
            "Il quadro è prevalentemente negativo, ma non unanime: almeno un fattore si muove in "
            "controtendenza rispetto al resto dell'analisi."
        )
    else:
        lines.append(
            "Il quadro è misto: bilancio, valutazione e contesto settoriale/news non raccontano la "
            "stessa storia. In questi casi è particolarmente importante capire quale fattore pesa "
            "di più per le proprie priorità d'investimento."
        )

    if verdicts.get("financials") == "positivo" and verdicts.get("valuation") == "negativo":
        lines.append(
            "In particolare, i numeri di bilancio sono positivi ma la valutazione appare già "
            "elevata: il mercato potrebbe aver già prezzato buona parte della crescita attesa."
        )
    if verdicts.get("financials") == "negativo" and verdicts.get("valuation") == "positivo":
        lines.append(
            "In particolare, la valutazione appare a buon mercato ma i numeri di bilancio si stanno "
            "deteriorando: un multiplo basso da solo non è garanzia di occasione, se i fondamentali "
            "continuano a peggiorare."
        )

    lines.append(
        "Resta un'analisi statistica basata su dati pubblici passati, non una previsione né una "
        "raccomandazione operativa."
    )
    return " ".join(lines)


def build_fundamental_narrative(symbol: str, peers: list[str] | None = None) -> dict:
    """Analisi sezionata in stile report per un singolo titolo: numeri di
    bilancio, qualità/valutazione, contesto settoriale (ETF + peer a
    scelta) e notizie/prospettive, con una sintesi finale che ragiona
    sull'accordo/disaccordo tra le sezioni."""
    info = dp.get_info(symbol)
    price = dp.get_current_price(symbol)
    sections = [
        _section_financials(symbol),
        _section_valuation(symbol, price),
        _section_sector(symbol, info.get("sector"), peers),
        _section_news(symbol),
    ]
    return {"sections": sections, "synthesis": _write_fundamental_synthesis(sections)}
