"""
Strategie di segnale — src/engine/strategies.py

Qui vive **una sola strategia**. Le quattro precedenti (Murphy, Donchian,
trend su media, momentum 12-1) sono state rimosse il 15/09/2026, insieme
al ponte `src/engine/signals.py` che traduceva l'analisi tecnica di
Murphy in ordini. Il motore di analisi tecnica (`src/technical.py`) e la
pagina che lo mostra restano: quello che è stato eliminato è il suo uso
come **generatore di segnali di trading**, non come strumento di lettura
del grafico.

**Perché è stato buttato tutto.** Il forward paper trading del
28/07–10/09/2026 ha chiuso 22 trade con un risultato lordo di +2,94R e un
netto di −8,79R. Il segnale non era la voce dominante: lo erano i costi,
perché la durata mediana di un trade era di 3 giorni e lo stop mediano
distava l'1,6% dal prezzo. Con l'identità

    costo_in_R = costo% / stop%

un round trip dell'1,1% (FX in valuta estera) contro uno stop dell'1,6%
significa consegnare due terzi di R all'esecuzione prima ancora di avere
ragione. Nessuna qualità di segnale ripaga quel conto.

---

## Cosa corregge, e con quanta fiducia

Questa strategia e' una **base di partenza provvisoria**, non il risultato
di un'analisi conclusa. Serve a tenere il banco di prova (backtest e
forward) utilizzabile mentre si disegna la strategia vera. Le regole qui
sotto sono ordinate per quanto e' solido il motivo che le sostiene.

**Solide, perche' correggono difetti osservati direttamente.**

- *Nessun target.* Il vecchio impianto accoppiava un ingresso
  trend-following a un'uscita mean-reverting (target sulla resistenza piu'
  vicina), con un R:R mediano di 0,71: guadagni troncati e perdite lasciate
  correre fino allo stop. Un trend-following vive di pochi guadagni molto
  grandi, e un tetto al guadagno li elimina per costruzione.
- *Solo long.* Trade Republic e' spot-only. Il vecchio sistema ha eseguito
  short su TXN, PLTR, NIO: operazioni non eseguibili. Un backtest che opera
  in una direzione preclusa non e' ottimistico, e' finto.
- *Nessun punteggio di confidenza.* Non esiste una misura calibrata della
  bonta' di un singolo segnale, quindi non se ne inventa una.
- *Poche operazioni, tenute a lungo.* La durata mediana del vecchio sistema
  era di **3 sedute**. Qualunque attrito — commissioni, spread, ritardo di
  esecuzione — si paga a ogni giro, e a quella frequenza si paga tante
  volte. Meno giri e' un margine di sicurezza che vale a prescindere da
  quanto costi esattamente un giro.

**Meno solida, perche' poggia su una stima e non su un dato.**

- *Solo strumenti in euro* (`DEFAULT_ALLOWED_CURRENCIES`). Discende
  dall'assunzione di costo FX allo 0,5% per gamba dichiarata in
  `costs.py`, che e' una **stima prudenziale del caso peggiore**, non una
  cifra pubblicata da Trade Republic: dopo il divieto UE di payment for
  order flow il costo di conversione e' incorporato nello spread di
  esecuzione e non e' pubblicato come percentuale. Le stime indipendenti
  vanno dallo 0,10% all'1%. Con lo 0,5% i titoli in dollari sono
  insostenibili; con lo 0,15% non lo sarebbero piu'. **Questa regola va
  rivista appena si conosce il costo reale**, ed e' un parametro
  (`allowed_currencies`) proprio per poterla togliere senza toccare il
  motore.

Quello che NON dipende da nessuna stima e' l'identita'

    costo_in_R = costo% / stop%

e il fatto che la commissione per ordine sia **fissa**: una posizione
piccola paga gli stessi euro di una grande. Da qui segue che stop stretti e
posizioni troncate sono strutturalmente fragili, qualunque sia il livello
dei costi.

## Sull'origine dell'ingresso

L'ingresso su rottura di canale appartiene alla stessa famiglia della
Donchian appena cancellata, ed e' deliberato: era l'unico elemento con
un'evidenza a favore (rendimento positivo, 99o percentile contro l'entrata
casuale). Ma quell'evidenza e' **debole** e va detto: era selezionata fra
otto configurazioni provate, e con otto tentativi la probabilita' che
almeno una superi il 95o percentile per puro caso e' circa un terzo. Vale
come indizio da verificare fuori campione, non come risultato acquisito.

Tutto il resto attorno all'ingresso non e' mai stato testato in nessuna
forma. Va trattato come un'ipotesi da falsificare, e il primo backtest che
ne mostra i numeri e' un esame, non una conferma.

## Parametri

Cinque, tutti dichiarati qui sotto. Ogni parametro in più è un'occasione
in più di adattarsi al passato: la scelta è tenerne pochi e non toccarli
per far tornare un risultato.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from src import technical as tech

# --- Parametri della strategia ---------------------------------------------

# Filtro di regime. La media a 200 giorni è la convenzione più diffusa per
# separare rialzo e ribasso di fondo; la condizione sulla pendenza serve a
# escludere i rimbalzi dentro una discesa, dove la media è ancora sopra il
# prezzo ma sta scendendo.
REGIME_MA_LENGTH = 200
REGIME_SLOPE_BARS = 20

# Ampiezza del canale di rottura, in barre. 60 sedute ≈ tre mesi: abbastanza
# lungo da non scattare sul rumore settimanale, abbastanza corto da non
# perdere l'intero movimento aspettando conferma.
BREAKOUT_CHANNEL_BARS = 60

# ATR: periodo e moltiplicatori. Lo stop iniziale definisce 1R, quindi
# definisce anche la size. Il trailing è più largo dello stop iniziale di
# proposito: una volta che il trade è in guadagno, l'errore costoso non è
# restituire un po' di profitto, è farsi buttare fuori da un ritracciamento
# normale prima che il movimento si esaurisca.
ATR_PERIOD = 20
INITIAL_STOP_ATR_MULT = 2.5
TRAILING_ATR_MULT = 3.5

# Valute ammesse. Default in euro per l'assunzione di costo FX discussa nel
# docstring: e' la regola meno solida dell'insieme, e la prima da rivedere
# quando si conoscera' il costo di conversione realmente applicato.
DEFAULT_ALLOWED_CURRENCIES = ("EUR",)


@dataclass
class Strategy:
    key: str
    label: str
    description: str
    generate: Callable[[str, pd.DataFrame, str], dict | None]
    warmup_bars: Callable[[str], int]
    parameters: str = ""
    # Valute ammesse. None significa "nessun vincolo". Il motore lo usa per
    # escludere gli strumenti prima di simularli, invece di simularli e poi
    # scoprire che i costi li rendono insensati.
    allowed_currencies: tuple[str, ...] | None = None


def _atr_value(hist: pd.DataFrame) -> float | None:
    series = tech.atr(hist, period=ATR_PERIOD).dropna()
    if series.empty:
        return None
    value = float(series.iloc[-1])
    return value if value > 0 else None


def _regime_is_bullish(closes: np.ndarray) -> bool:
    """Prezzo sopra la media a 200 E media in salita sulle ultime 20 barre.

    Entrambe le condizioni servono: la prima da sola lascia passare i
    rimbalzi dentro un ribasso, la seconda da sola lascia passare gli
    ingressi molto sotto una media che sale per inerzia."""
    if len(closes) < REGIME_MA_LENGTH + REGIME_SLOPE_BARS:
        return False
    ma_now = float(np.mean(closes[-REGIME_MA_LENGTH:]))
    ma_before = float(np.mean(closes[-REGIME_MA_LENGTH - REGIME_SLOPE_BARS:-REGIME_SLOPE_BARS]))
    return bool(closes[-1] > ma_now and ma_now > ma_before)


def _is_channel_breakout(closes: np.ndarray) -> bool:
    """Nuovo massimo di chiusura sulle ultime BREAKOUT_CHANNEL_BARS barre.

    Si misura sulle **chiusure** e non sui massimi intraday: un massimo
    intraday può essere un singolo scambio a un prezzo anomalo, mentre la
    chiusura è il prezzo su cui il mercato si è fermato. È una scelta
    dichiarata, non una convenzione universale — i Turtle usavano i
    massimi."""
    if len(closes) < BREAKOUT_CHANNEL_BARS + 1:
        return False
    finestra = closes[-BREAKOUT_CHANNEL_BARS - 1:-1]
    return bool(closes[-1] > finestra.max())


def _breakout_generate(symbol: str, hist: pd.DataFrame, horizon: str) -> dict | None:
    """Piano operativo sulla chiusura dell'ultima barra di `hist`.

    `hist` deve contenere SOLO barre fino a quella corrente inclusa: è il
    bar loop a garantirlo. L'orizzonte non è usato — questa strategia ha
    periodi propri e fissi, e fingere di adattarsi a un orizzonte
    selezionabile darebbe l'impressione di una flessibilità che non ha."""
    if hist is None or len(hist) < REGIME_MA_LENGTH + REGIME_SLOPE_BARS:
        return None

    closes = hist["Close"].to_numpy(dtype=float)
    price = float(closes[-1])
    if not np.isfinite(price) or price <= 0:
        return None

    if not _regime_is_bullish(closes):
        return {"bias": "nessun_setup", "motivo": "regime non rialzista"}
    if not _is_channel_breakout(closes):
        return {"bias": "nessun_setup", "motivo": "nessuna rottura di canale"}

    atr_value = _atr_value(hist)
    if atr_value is None:
        # Senza ATR non si sa dove mettere lo stop, quindi non si sa
        # quanto rischiare: il trade si salta invece di stimare a occhio.
        return {"bias": "nessun_setup", "motivo": "ATR non calcolabile"}

    stop = price - INITIAL_STOP_ATR_MULT * atr_value
    if stop <= 0:
        return {"bias": "nessun_setup", "motivo": "stop sotto zero"}

    return {
        "bias": "long",
        "entry": price,
        "stop": round(stop, 4),
        "target": None,                 # nessun tetto al guadagno
        "trailing_atr_mult": TRAILING_ATR_MULT,
        "risk_reward": None,            # non calcolabile senza target
        "rr_unfavorable": False,
        "stop_source": "atr",
        "target_source": "trailing",
        "confidence": None,             # vedi il docstring del modulo
        "atr": atr_value,
        "price": price,
    }


STRATEGIES: dict[str, Strategy] = {
    "breakout_eur": Strategy(
        key="breakout_eur",
        label=f"Rottura di canale {BREAKOUT_CHANNEL_BARS}g con filtro di regime",
        description=(
            f"Solo long e solo su strumenti in euro. Opera unicamente quando il prezzo sta sopra "
            f"la media a {REGIME_MA_LENGTH} giorni e quella media sale sulle ultime "
            f"{REGIME_SLOPE_BARS} sedute. In quel contesto entra alla prima chiusura sopra il "
            f"massimo di chiusura delle {BREAKOUT_CHANNEL_BARS} barre precedenti. "
            f"Stop iniziale a {INITIAL_STOP_ATR_MULT:g}xATR({ATR_PERIOD}), poi stop in trailing a "
            f"{TRAILING_ATR_MULT:g}xATR dal massimo raggiunto. Nessun obiettivo di prezzo: "
            "l'uscita avviene quando il trend si rompe, non a un livello deciso in partenza. "
            "Base di partenza provvisoria, mai testata: serve a tenere utilizzabile il banco di "
            "prova mentre si disegna la strategia vera."
        ),
        parameters=(f"media {REGIME_MA_LENGTH} - pendenza su {REGIME_SLOPE_BARS} barre - "
                     f"canale {BREAKOUT_CHANNEL_BARS} barre - stop {INITIAL_STOP_ATR_MULT:g}xATR - "
                     f"trailing {TRAILING_ATR_MULT:g}xATR"),
        generate=_breakout_generate,
        warmup_bars=lambda horizon: REGIME_MA_LENGTH + REGIME_SLOPE_BARS + ATR_PERIOD + 5,
        allowed_currencies=DEFAULT_ALLOWED_CURRENCIES,
    ),
}

DEFAULT_STRATEGY = "breakout_eur"


def get(key: str) -> Strategy:
    if key not in STRATEGIES:
        raise ValueError(
            f"Strategia '{key}' sconosciuta. Disponibili: {', '.join(STRATEGIES)}."
        )
    return STRATEGIES[key]


def keys() -> list[str]:
    return list(STRATEGIES)
