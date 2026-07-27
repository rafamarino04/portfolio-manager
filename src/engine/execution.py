"""
Simulatore di esecuzione — src/engine/execution.py

Questo è il modulo in cui un backtest mente a se stesso o resta onesto.
Tre regole, tutte deliberatamente pessimistiche.

**1. Fill degli ingressi al next-bar-open.** Il segnale nasce sul close
del bar t e viene eseguito all'open del bar t+1. Eseguire sullo stesso
close che hai usato per calcolare il segnale è il bug di look-ahead
classico: nella realtà il close lo conosci solo a bar chiuso, quindi la
prima occasione di eseguire è l'apertura successiva.

**2. Ambiguità intrabar: stop-first.** Con dati OHLC daily non si può
ricostruire il percorso dei prezzi dentro il bar. Se in un singolo bar il
range [low, high] contiene sia lo stop sia il target, non si sa quale sia
stato toccato per primo: si assume lo **stop**, cioè l'esito peggiore.
(È l'opposto dell'assunzione ottimistica open→low→high→close usata per
default da alcuni emulatori: quella fa apparire migliori i risultati
proprio nei bar più volatili, dove si decide gran parte del P&L.)

**3. I gap si pagano al prezzo reale.** Se il bar apre già oltre lo stop,
il fill avviene all'open — peggiore dello stop teorico — perché quel gap
è slippage vero e non lo si può evitare mettendo un ordine. Simmetrico
sul target: un'apertura oltre il target riempie all'open, che in quel
caso è un prezzo migliore. Riempire sempre al livello teorico
significherebbe regalarsi un'esecuzione che nella realtà non si ottiene.

L'ordine di valutazione dentro un bar riflette queste regole: prima si
controlla il gap in apertura (che ha priorità su tutto, perché è la prima
cosa che accade nel bar), poi il tocco intrabar con la precedenza allo
stop.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExitEvent:
    """Esito della valutazione di un bar su una posizione aperta."""
    price: float
    reason: str          # "stop" | "target" | "gap_stop" | "gap_target" | "chiusura_forzata"
    gapped: bool = False

    @property
    def is_stop(self) -> bool:
        return self.reason in ("stop", "gap_stop")


def resolve_exit(direction: str, stop: float, target: float,
                  bar_open: float, bar_high: float, bar_low: float) -> ExitEvent | None:
    """Decide se e a quale prezzo una posizione esce durante questo bar.

    `direction` è "long" o "short". Ritorna None se il bar non tocca né
    stop né target.

    Precedenze, nell'ordine in cui gli eventi accadono realmente:
      1. Gap in apertura oltre lo stop  -> fill all'open (peggio dello stop).
      2. Gap in apertura oltre il target -> fill all'open (meglio del target).
      3. Range del bar che contiene entrambi -> stop (regola conservativa).
      4. Range che contiene solo uno dei due -> quello.

    Il gap sullo stop viene controllato prima del gap sul target: se
    l'apertura è oltre entrambi (possibile su un gap enorme in un trade
    con range stretto) vale ancora l'assunzione pessimistica."""
    if direction == "long":
        # 1. Apertura già sotto lo stop: il gap è slippage reale.
        if bar_open <= stop:
            return ExitEvent(price=bar_open, reason="gap_stop", gapped=True)
        # 2. Apertura già sopra il target.
        if bar_open >= target:
            return ExitEvent(price=bar_open, reason="gap_target", gapped=True)
        hit_stop = bar_low <= stop
        hit_target = bar_high >= target
        # 3./4. Con entrambi dentro il range vince lo stop.
        if hit_stop:
            return ExitEvent(price=stop, reason="stop")
        if hit_target:
            return ExitEvent(price=target, reason="target")
        return None

    # short: tutto specchiato
    if bar_open >= stop:
        return ExitEvent(price=bar_open, reason="gap_stop", gapped=True)
    if bar_open <= target:
        return ExitEvent(price=bar_open, reason="gap_target", gapped=True)
    hit_stop = bar_high >= stop
    hit_target = bar_low <= target
    if hit_stop:
        return ExitEvent(price=stop, reason="stop")
    if hit_target:
        return ExitEvent(price=target, reason="target")
    return None


def fill_price_next_open(bar_open: float) -> float:
    """Prezzo di esecuzione di un ordine generato sul close precedente.

    Funzione volutamente banale: esiste per rendere la regola
    *esplicita e cercabile* nel codice invece di lasciarla implicita in
    un indice `+1` sparso nel bar loop, dove sarebbe facile romperla
    senza accorgersene."""
    return bar_open


def update_excursions(direction: str, entry_price: float, risk_per_unit: float,
                       bar_high: float, bar_low: float,
                       mae_r: float, mfe_r: float) -> tuple[float, float]:
    """Aggiorna MAE/MFE (massima escursione avversa/favorevole) in
    multipli di R.

    Servono a tarare le uscite: un trade che va a +2,5R prima di tornare
    indietro e chiudere a −1R racconta qualcosa che il solo esito finale
    nasconde. Entrambi sono espressi in R, non in valuta, per restare
    confrontabili tra strumenti."""
    if risk_per_unit <= 0:
        return mae_r, mfe_r
    if direction == "long":
        adverse = (entry_price - bar_low) / risk_per_unit
        favorable = (bar_high - entry_price) / risk_per_unit
    else:
        adverse = (bar_high - entry_price) / risk_per_unit
        favorable = (entry_price - bar_low) / risk_per_unit
    return max(mae_r, max(0.0, adverse)), max(mfe_r, max(0.0, favorable))


def realized_r(direction: str, entry_price: float, exit_price: float,
                risk_per_unit: float) -> float:
    """R-multiplo realizzato, al lordo dei costi.

    Il rischio al denominatore è quello **iniziale** (entry − stop al
    momento dell'ingresso): è la definizione che rende gli R confrontabili
    tra trade. Un'uscita in gap oltre lo stop produce correttamente un
    valore peggiore di −1R, che è esattamente l'informazione da non
    perdere: la coda sinistra reale è più lunga del −1R pianificato."""
    if risk_per_unit <= 0:
        return 0.0
    delta = (exit_price - entry_price) if direction == "long" else (entry_price - exit_price)
    return delta / risk_per_unit
