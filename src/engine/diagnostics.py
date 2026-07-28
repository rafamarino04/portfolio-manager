"""
Diagnostica: dove si perde valore — src/engine/diagnostics.py

Serve a rispondere a una domanda precisa che un risultato negativo, da
solo, non permette di risolvere: **il problema è il segnale o è la
struttura che gli sta attorno?** Sono due diagnosi opposte e portano a due
lavori completamente diversi.

Il sistema ha tre punti di guasto possibili, e questo modulo li separa:

1. **Le meccaniche del motore** (fill, uscite, costi, sizing). Già
   verificate da test su barre costruite a mano con esito calcolabile a
   mente: non è lì che si indaga.
2. **Il ponte tra analisi tecnica e motore** — quali piani vengono
   effettivamente tradati e con che geometria. Qui vivono i difetti
   misurabili da `plan_quality()` e `cost_drag()`.
3. **Il segnale in sé** — isolato da `signal_quality()`, che guarda i
   rendimenti dopo un segnale senza che stop, target e costi c'entrino
   nulla.

Il discriminante principale tra (3) e il resto resta il **benchmark a
entrata casuale**, già prodotto dal motore: stesse uscite, stesso sizing,
stessi costi, cambia solo da dove viene l'ingresso. Se il segnale reale
non batte il caso, il problema è il segnale. Se lo batte e il sistema
perde comunque, il problema è la struttura.

Nessuna funzione qui modifica il comportamento del sistema: leggono e
basta.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.engine import signals as sig

# Soglia oltre la quale il costo di un trade è considerato divorante.
# Un'expectancy realistica sta tra +0,2R e +0,5R: un costo che si avvicina
# a 0,2R si mangia da solo l'intero margine atteso.
COST_ALARM_R = 0.20

# Divario oltre il quale l'uscita è considerata prematura: se in media i
# trade vincenti hanno toccato molto più di quanto abbiano portato a casa,
# il problema non è trovare la direzione ma tenerla.
MFE_GAP_ALARM_R = 1.0


@dataclass
class CostDiagnosis:
    n_trades: int = 0
    mean_cost_r: float | None = None
    median_cost_r: float | None = None
    total_costs_eur: float = 0.0
    gross_pnl_eur: float = 0.0
    net_pnl_eur: float = 0.0
    cost_share_of_gross_pct: float | None = None
    by_symbol: pd.DataFrame = field(default_factory=pd.DataFrame)
    verdict: str = ""


@dataclass
class ExitDiagnosis:
    n_trades: int = 0
    n_winners: int = 0
    mean_mfe_r: float | None = None
    mean_realized_r_winners: float | None = None
    mean_gap_r: float | None = None          # quanto lasciato sul tavolo
    mean_mae_r: float | None = None
    exit_reasons: pd.DataFrame = field(default_factory=pd.DataFrame)
    best_trade_r: float | None = None
    worst_trade_r: float | None = None
    win_loss_size_ratio: float | None = None
    verdict: str = ""


@dataclass
class PlanDiagnosis:
    n_trades: int = 0
    mean_planned_rr: float | None = None
    median_planned_rr: float | None = None
    share_unfavorable_pct: float | None = None
    share_stop_from_atr_pct: float | None = None
    share_target_from_atr_pct: float | None = None
    rr_distribution: pd.DataFrame = field(default_factory=pd.DataFrame)
    verdict: str = ""


def _series(trades: list, attr: str) -> pd.Series:
    return pd.to_numeric(pd.Series([getattr(t, attr, None) for t in trades]),
                          errors="coerce").dropna()


# ---------------------------------------------------------------------------
# 1. Quanto pesano i costi
# ---------------------------------------------------------------------------

def cost_drag(trades: list) -> CostDiagnosis:
    """Costo dei trade espresso in R, che è l'unità in cui va giudicato.

    Il costo in euro non dice nulla da solo: 20 euro su un trade che
    rischia 500 euro è irrilevante, sullo stesso trade che ne rischia 50 è
    letale. Il rapporto costo/rischio è anche il motivo per cui gli stop
    stretti sono pericolosi con costi percentuali: la size cresce quando lo
    stop si avvicina, e i costi percentuali crescono con essa mentre il
    rischio in euro resta fisso."""
    d = CostDiagnosis(n_trades=len(trades))
    if not trades:
        d.verdict = "Nessun trade: nulla da analizzare."
        return d

    rows = []
    for t in trades:
        risk = getattr(t, "initial_risk_eur", 0) or 0
        cost = getattr(t, "costs_eur", 0) or 0
        rows.append({
            "symbol": getattr(t, "symbol", "?"),
            "cost_r": (cost / risk) if risk else np.nan,
            "cost_eur": cost,
            "gross": getattr(t, "gross_pnl_eur", 0) or 0,
            "net": getattr(t, "net_pnl_eur", 0) or 0,
        })
    df = pd.DataFrame(rows)
    cost_r = df["cost_r"].dropna()

    d.mean_cost_r = float(cost_r.mean()) if not cost_r.empty else None
    d.median_cost_r = float(cost_r.median()) if not cost_r.empty else None
    d.total_costs_eur = float(df["cost_eur"].sum())
    d.gross_pnl_eur = float(df["gross"].sum())
    d.net_pnl_eur = float(df["net"].sum())
    if d.gross_pnl_eur != 0:
        d.cost_share_of_gross_pct = abs(d.total_costs_eur / d.gross_pnl_eur) * 100

    grouped = df.groupby("symbol").agg(
        trade=("cost_r", "size"), costo_medio_r=("cost_r", "mean"),
        costi_eur=("cost_eur", "sum"), pnl_netto_eur=("net", "sum"))
    d.by_symbol = grouped.sort_values("costo_medio_r", ascending=False).reset_index()

    if d.mean_cost_r is None:
        d.verdict = "Costo per trade non calcolabile."
    elif d.mean_cost_r >= COST_ALARM_R:
        d.verdict = (
            f"I costi valgono in media {d.mean_cost_r:.2f}R per trade. È una quota che si mangia da "
            "sola l'intera expectancy attesa di un sistema sano (+0,2/+0,5R): con questi costi il "
            "segnale dovrebbe essere eccezionale solo per andare in pari. La leva su cui agire non è "
            "la dimensione del trade ma la distanza dello stop e la valuta dello strumento — il "
            "costo in R vale circa costo%/stop%, quindi stop stretti su strumenti in valuta estera "
            "sono la combinazione peggiore."
        )
    elif d.mean_cost_r >= COST_ALARM_R / 2:
        d.verdict = (f"I costi valgono in media {d.mean_cost_r:.2f}R per trade: pesante ma non "
                     "necessariamente fatale, dipende dall'expectancy lorda.")
    else:
        d.verdict = (f"I costi valgono in media {d.mean_cost_r:.2f}R per trade: non sono loro il "
                     "problema principale.")
    return d


# ---------------------------------------------------------------------------
# 2. Le uscite lasciano soldi sul tavolo?
# ---------------------------------------------------------------------------

def exit_quality(trades: list) -> ExitDiagnosis:
    """Confronta quanto un trade ha toccato (MFE) con quanto ha portato a
    casa. È il test decisivo per l'ipotesi "i target sono troppo bassi".

    Se i trade vincenti arrivano regolarmente a 2-3R prima di chiudere a
    0,8R, il segnale la direzione la trova e sono le uscite a buttarla
    via: il lavoro è sulle uscite, non sul segnale. Se invece l'MFE è
    basso quanto il risultato, il prezzo non è mai andato a favore e il
    problema sta a monte."""
    d = ExitDiagnosis(n_trades=len(trades))
    if not trades:
        d.verdict = "Nessun trade: nulla da analizzare."
        return d

    winners = [t for t in trades if getattr(t, "net_pnl_eur", 0) > 0]
    losers = [t for t in trades if getattr(t, "net_pnl_eur", 0) <= 0]
    d.n_winners = len(winners)

    mfe = _series(trades, "mfe_r")
    mae = _series(trades, "mae_r")
    d.mean_mfe_r = float(mfe.mean()) if not mfe.empty else None
    d.mean_mae_r = float(mae.mean()) if not mae.empty else None

    if winners:
        win_r = _series(winners, "net_r")
        win_mfe = _series(winners, "mfe_r")
        d.mean_realized_r_winners = float(win_r.mean()) if not win_r.empty else None
        if not win_r.empty and not win_mfe.empty:
            d.mean_gap_r = float(win_mfe.mean() - win_r.mean())

    all_r = _series(trades, "net_r")
    if not all_r.empty:
        d.best_trade_r = float(all_r.max())
        d.worst_trade_r = float(all_r.min())
    if winners and losers:
        w = _series(winners, "net_r").mean()
        l = abs(_series(losers, "net_r").mean())
        if l:
            d.win_loss_size_ratio = float(w / l)

    reasons = pd.Series([getattr(t, "exit_reason", "?") for t in trades]).value_counts()
    d.exit_reasons = reasons.rename_axis("motivo").reset_index(name="trade")

    if d.mean_gap_r is None:
        d.verdict = "Nessun trade vincente: il confronto MFE/risultato non è calcolabile."
    elif d.mean_gap_r >= MFE_GAP_ALARM_R:
        d.verdict = (
            f"I trade vincenti hanno toccato in media {d.mean_gap_r:.2f}R in più di quanto abbiano "
            "portato a casa. Il segnale la direzione la trova: sono le uscite a buttarla via. "
            "Un target fissato alla resistenza più vicina tronca i vincitori per costruzione, ed è "
            "incompatibile con un trend-following, che vive di pochi guadagni molto grandi."
        )
    else:
        d.verdict = (
            f"I trade vincenti hanno lasciato sul tavolo in media {d.mean_gap_r:.2f}R: le uscite non "
            "sembrano essere il collo di bottiglia principale. Se il sistema perde comunque, guarda "
            "prima costi e qualità del segnale."
        )
    return d


# ---------------------------------------------------------------------------
# 3. Che piani sono stati effettivamente tradati?
# ---------------------------------------------------------------------------

def plan_quality(trades: list) -> PlanDiagnosis:
    """Geometria dei piani che il motore ha davvero eseguito.

    Due cose da guardare. La quota di piani che il sistema stesso aveva
    già segnalato come sfavorevoli (R:R sotto la propria soglia minima):
    se è alta, il backtest sta misurando setup che non prenderesti. E la
    quota di piani caduti nel ramo di ripiego puramente ad ATR, che nasce
    con un R:R fisso e — con i parametri attuali — sotto la soglia."""
    d = PlanDiagnosis(n_trades=len(trades))
    if not trades:
        d.verdict = "Nessun trade: nulla da analizzare."
        return d

    rr = _series(trades, "planned_rr")
    if not rr.empty:
        d.mean_planned_rr = float(rr.mean())
        d.median_planned_rr = float(rr.median())
        bins = [0, 0.5, 1.0, 1.5, 2.0, 3.0, np.inf]
        labels = ["< 0,5", "0,5–1", "1–1,5", "1,5–2", "2–3", "> 3"]
        dist = pd.cut(rr, bins=bins, labels=labels, right=False).value_counts().sort_index()
        d.rr_distribution = dist.rename_axis("R:R pianificato").reset_index(name="trade")

    unfav = [getattr(t, "rr_unfavorable", None) for t in trades]
    unfav = [u for u in unfav if u is not None]
    if unfav:
        d.share_unfavorable_pct = 100 * sum(1 for u in unfav if u) / len(unfav)

    stop_src = [getattr(t, "stop_source", None) for t in trades]
    stop_src = [s for s in stop_src if s]
    if stop_src:
        d.share_stop_from_atr_pct = 100 * sum(1 for s in stop_src if s == "atr") / len(stop_src)

    tgt_src = [getattr(t, "target_source", None) for t in trades]
    tgt_src = [s for s in tgt_src if s]
    if tgt_src:
        d.share_target_from_atr_pct = 100 * sum(1 for s in tgt_src if s == "atr") / len(tgt_src)

    parti = []
    if d.share_unfavorable_pct is not None:
        parti.append(
            f"il {d.share_unfavorable_pct:.0f}% dei trade eseguiti era già segnalato come "
            "rischio/rendimento sfavorevole dal sistema stesso"
        )
    if d.median_planned_rr is not None:
        parti.append(f"il R:R mediano pianificato è {d.median_planned_rr:.2f}")
    if parti:
        d.verdict = (
            "Piani effettivamente tradati: " + "; ".join(parti) + ". "
            "Un R:R mediano sotto 1,5 richiede un win rate superiore al 40% per il solo pareggio, "
            "mentre un trend-following ne fa tipicamente 30-45%: la geometria del piano, non il "
            "segnale, può bastare a rendere il sistema perdente."
        )
    else:
        d.verdict = "Dati di piano non disponibili sui trade (backtest eseguito prima della diagnostica)."
    return d


# ---------------------------------------------------------------------------
# 4. Il segnale, isolato da uscite e costi
# ---------------------------------------------------------------------------

@dataclass
class SignalQuality:
    horizon_bars: int
    n_signals: int = 0
    n_baseline: int = 0
    mean_signal_return_pct: float | None = None
    mean_baseline_return_pct: float | None = None
    edge_pct: float | None = None
    hit_rate_signal: float | None = None
    hit_rate_baseline: float | None = None
    t_stat: float | None = None
    verdict: str = ""


def signal_quality(histories: dict[str, pd.DataFrame], horizon: str = "medio",
                    forward_bars: int = 20, max_symbols: int | None = None,
                    progress_callback=None) -> SignalQuality:
    """Rendimento medio nei `forward_bars` successivi a un segnale,
    confrontato con quello di tutte le altre barre.

    È il test che isola l'analisi tecnica: non ci sono stop, non ci sono
    target, non ci sono costi e non c'è sizing. Se dopo un segnale long il
    prezzo non sale più di quanto salga in un giorno qualunque, il segnale
    non contiene informazione e nessuna correzione di uscite o costi potrà
    salvarlo. Se invece l'edge grezzo c'è, il problema sta a valle.

    Il rendimento si misura dall'apertura della barra successiva al
    segnale, coerentemente con la regola di esecuzione del backtest: usare
    il close del bar del segnale introdurrebbe il look-ahead che il motore
    evita per costruzione.

    La statistica t è indicativa: le osservazioni si sovrappongono nel
    tempo e non sono indipendenti, quindi va letta come ordine di
    grandezza, non come test formale."""
    out = SignalQuality(horizon_bars=forward_bars)
    symbols = list(histories)[:max_symbols] if max_symbols else list(histories)
    warmup = sig.warmup_bars(horizon)

    signal_returns: list[float] = []
    baseline_returns: list[float] = []

    for n_sym, symbol in enumerate(symbols):
        hist = histories.get(symbol)
        if hist is None or len(hist) < warmup + forward_bars + 2:
            continue
        opens = hist["Open"].to_numpy(dtype=float)
        closes = hist["Close"].to_numpy(dtype=float)
        n = len(hist)

        for i in range(warmup, n - forward_bars - 1):
            entry = opens[i + 1]
            if entry <= 0:
                continue
            fwd = (closes[i + 1 + forward_bars] / entry - 1) * 100
            baseline_returns.append(fwd)

            plan = sig.generate_signal(symbol, hist.iloc[:i + 1], horizon=horizon)
            if not plan or plan.get("bias") not in ("long", "short"):
                continue
            # Gli short si valutano a segno invertito: un segnale short è
            # "giusto" se il prezzo scende.
            signal_returns.append(fwd if plan["bias"] == "long" else -fwd)

        if progress_callback:
            progress_callback((n_sym + 1) / max(1, len(symbols)), symbol)

    out.n_signals = len(signal_returns)
    out.n_baseline = len(baseline_returns)
    if not signal_returns or not baseline_returns:
        out.verdict = "Dati insufficienti per valutare la qualità del segnale."
        return out

    s = np.asarray(signal_returns, dtype=float)
    b = np.asarray(baseline_returns, dtype=float)
    out.mean_signal_return_pct = float(s.mean())
    out.mean_baseline_return_pct = float(b.mean())
    out.edge_pct = out.mean_signal_return_pct - out.mean_baseline_return_pct
    out.hit_rate_signal = float((s > 0).mean())
    out.hit_rate_baseline = float((b > 0).mean())

    se = s.std(ddof=1) / np.sqrt(len(s)) if len(s) > 1 else None
    if se and se > 0:
        out.t_stat = float(out.edge_pct / se)

    if out.edge_pct is None:
        out.verdict = "Edge non calcolabile."
    elif out.edge_pct <= 0:
        out.verdict = (
            f"Dopo un segnale il prezzo si muove a favore dello {out.mean_signal_return_pct:+.2f}% "
            f"in {forward_bars} barre, contro il {out.mean_baseline_return_pct:+.2f}% di una barra "
            "qualunque: il segnale NON contiene informazione direzionale. Il problema è a monte, "
            "nell'analisi tecnica: correggere uscite e costi non può salvare un segnale senza edge."
        )
    elif out.t_stat is not None and abs(out.t_stat) < 2:
        out.verdict = (
            f"Edge grezzo di {out.edge_pct:+.2f}% su {forward_bars} barre, ma statisticamente "
            f"debole (t ≈ {out.t_stat:.1f}). Il segnale potrebbe contenere qualcosa, ma non "
            "abbastanza da distinguerlo dal rumore su questo campione."
        )
    else:
        out.verdict = (
            f"Il segnale ha un edge grezzo: {out.mean_signal_return_pct:+.2f}% contro "
            f"{out.mean_baseline_return_pct:+.2f}% di una barra qualunque, cioè {out.edge_pct:+.2f}% "
            f"di differenza su {forward_bars} barre (t ≈ {out.t_stat:.1f}). L'analisi tecnica "
            "individua direzione: se il sistema perde comunque, il valore si distrugge a valle — "
            "nelle uscite, nella geometria del piano o nei costi."
        )
    return out


# ---------------------------------------------------------------------------
# Sintesi: dove intervenire
# ---------------------------------------------------------------------------

def overall_diagnosis(cost: CostDiagnosis, exits: ExitDiagnosis, plans: PlanDiagnosis,
                       beats_random: bool | None) -> str:
    """Indicazione di priorità, costruita dalle sole misure disponibili.

    Non promette che correggendo il punto indicato il sistema diventi
    profittevole: dice solo dove si sta perdendo più valore, che è una
    domanda diversa e molto più modesta."""
    cause = []
    if cost.mean_cost_r is not None and cost.mean_cost_r >= COST_ALARM_R:
        cause.append(f"costi ({cost.mean_cost_r:.2f}R per trade)")
    if exits.mean_gap_r is not None and exits.mean_gap_r >= MFE_GAP_ALARM_R:
        cause.append(f"uscite premature ({exits.mean_gap_r:.2f}R lasciati sul tavolo)")
    if plans.share_unfavorable_pct is not None and plans.share_unfavorable_pct >= 30:
        cause.append(f"piani sfavorevoli tradati comunque ({plans.share_unfavorable_pct:.0f}%)")

    if beats_random is False:
        testa = ("Il sistema non batte l'entrata casuale a parità di uscite, sizing e costi: "
                 "l'edge, se c'è, non viene dal segnale. ")
    elif beats_random is True:
        testa = ("Il sistema batte l'entrata casuale a parità di uscite, sizing e costi: "
                 "il segnale contiene qualcosa. ")
    else:
        testa = ""

    if not cause:
        return testa + ("Nessuna delle cause strutturali misurate qui risulta dominante: il valore "
                        "non si perde in modo concentrato in costi, uscite o geometria del piano.")
    return testa + "Le cause strutturali con più peso, in ordine: " + ", ".join(cause) + "."
