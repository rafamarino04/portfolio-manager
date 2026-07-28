"""
Strategie di segnale selezionabili — src/engine/strategies.py

Esiste per rispondere a una domanda che nessun backtest di una singola
strategia può risolvere: **il problema è questo algoritmo, o è l'intero
approccio?** Se una regola da tre righe batte quella da tremila, il
problema è la complessità. Se le batte tutte il buy-and-hold, il problema
è l'universo. Se non funziona niente, la risposta è ancora più utile e ti
risparmia mesi.

Tutte le strategie girano nello **stesso identico apparato**: stessi
costi, stesso sizing, stesse regole di esecuzione, stessi benchmark.
L'unica variabile che cambia è da dove viene il segnale — che è la
condizione perché un confronto significhi qualcosa.

---

**Perché le alternative sono così semplici, e non più sofisticate.**

È controintuitivo ma è il punto. La strategia "murphy" ha decine di regole
interagenti: sette famiglie di voti, pesi di affidabilità delle candele,
stati dei pattern, clustering dei livelli, riconciliazione tra struttura e
medie. Ogni regola è una superficie su cui si annida l'overfitting, e
l'insieme è indiagnosticabile — quando perde, non sai quale pezzo sia il
responsabile.

Le tre alternative hanno due o tre parametri ciascuna. Sono più probabili
a priori (meno gradi di libertà = meno adattamento al rumore) e sono
falsificabili: se non funzionano, sai esattamente cosa non ha funzionato.

**Perché proprio queste tre.** Nella letteratura empirica, la persistenza
dei trend — momentum di serie storica — è l'area dell'analisi tecnica con
l'evidenza più solida e replicata, ed è quella su cui vive da decenni
l'industria dei managed futures. Le figure grafiche e i pattern di candele
hanno evidenza molto più fragile. Queste tre implementano la parte con
evidenza, ognuna in una forma classica diversa:

  - **Donchian**: rottura del massimo a N giorni (l'impianto dei Turtle).
  - **Media 200**: prezzo sopra una media lunga con pendenza positiva.
  - **Momentum 12-1**: rendimento a 12 mesi escluso l'ultimo.

Tutte e tre escono con uno **stop in trailing** e senza obiettivo di
prezzo. È la differenza strutturale rispetto a "murphy", che fissa il
target alla resistenza più vicina: un trend-following vive di pochi
guadagni molto grandi, e un target fisso li tronca per costruzione. Senza
target il guadagno non ha tetto — è ciò che rende possibile la coda destra
da cui dipende l'intera expectancy di questo stile.

**Nessuna di queste soglie è stata scelta guardando i risultati.** Sono i
valori convenzionali della letteratura (Donchian 20/55, media 200, 12-1
mesi, stop a 2-3 ATR). Sceglierle osservando il backtest sarebbe
overfitting, ed è precisamente ciò che questo confronto serve a evitare.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from src import technical as tech
from src.engine import signals as sig

# --- Parametri convenzionali, non ottimizzati -------------------------------
DONCHIAN_ENTRY_BARS = 55        # rottura del massimo/minimo a 55 giorni (Turtle "sistema 2")
MA_TREND_LENGTH = 200           # la media lunga per antonomasia
MA_SLOPE_LOOKBACK = 20          # barre su cui misurare la pendenza della media
MOMENTUM_LOOKBACK = 252         # 12 mesi di borsa
MOMENTUM_SKIP = 21              # meno l'ultimo mese (convenzione 12-1)

TRAILING_ATR_MULT = 3.0         # distanza dello stop in trailing
INITIAL_STOP_ATR_MULT = 2.0     # stop iniziale, prima che il trailing si attivi
ATR_PERIOD = 14


@dataclass
class Strategy:
    key: str
    label: str
    description: str
    generate: Callable[[str, pd.DataFrame, str], dict | None]
    warmup_bars: Callable[[str], int]
    parameters: str = ""


# ---------------------------------------------------------------------------
# Helper comuni alle strategie in trailing
# ---------------------------------------------------------------------------

def _atr_value(hist: pd.DataFrame) -> float | None:
    series = tech.atr(hist, period=ATR_PERIOD).dropna()
    if series.empty:
        return None
    value = float(series.iloc[-1])
    return value if value > 0 else None


def _trailing_plan(direction: str, price: float, atr_value: float) -> dict:
    """Piano con stop iniziale ad ATR e uscita in trailing, senza target.

    Lo stop iniziale serve a definire 1R — il rischio su cui si dimensiona
    la posizione. Da lì in poi lo stop si stringe soltanto, e l'uscita
    avviene quando il trend si rompe, non a un livello deciso in partenza."""
    stop = (price - INITIAL_STOP_ATR_MULT * atr_value if direction == "long"
            else price + INITIAL_STOP_ATR_MULT * atr_value)
    return {
        "bias": direction,
        "entry": price,
        "stop": round(stop, 4),
        "target": None,                       # nessun tetto al guadagno
        "trailing_atr_mult": TRAILING_ATR_MULT,
        "risk_reward": None,                  # non calcolabile senza target
        "rr_unfavorable": False,
        "stop_source": "atr",
        "target_source": "trailing",
        # Le strategie semplici non producono un punteggio di confidenza:
        # dichiararne uno finto renderebbe la calibrazione una finzione.
        "confidence": None,
        "atr": atr_value,
        "price": price,
    }


# ---------------------------------------------------------------------------
# 1. Murphy — la strategia storica, invariata
# ---------------------------------------------------------------------------

def _murphy_generate(symbol: str, hist: pd.DataFrame, horizon: str) -> dict | None:
    return sig.generate_signal(symbol, hist, horizon=horizon)


# ---------------------------------------------------------------------------
# 2. Rottura di Donchian
# ---------------------------------------------------------------------------

def _donchian_generate(symbol: str, hist: pd.DataFrame, horizon: str) -> dict | None:
    """Long se il close supera il massimo delle N barre PRECEDENTI.

    L'esclusione della barra corrente dal canale non è un dettaglio: se il
    massimo includesse il bar di oggi, il confronto sarebbe con se stesso e
    il segnale scatterebbe su qualunque nuovo massimo giornaliero."""
    if len(hist) < DONCHIAN_ENTRY_BARS + 2:
        return None
    close = float(hist["Close"].iloc[-1])
    prior_high = float(hist["High"].iloc[-(DONCHIAN_ENTRY_BARS + 1):-1].max())
    prior_low = float(hist["Low"].iloc[-(DONCHIAN_ENTRY_BARS + 1):-1].min())

    atr_value = _atr_value(hist)
    if atr_value is None:
        return None

    if close > prior_high:
        return _trailing_plan("long", close, atr_value)
    if close < prior_low:
        return _trailing_plan("short", close, atr_value)
    return {"bias": "nessun_setup"}


# ---------------------------------------------------------------------------
# 3. Trend su media lunga
# ---------------------------------------------------------------------------

def _ma_trend_generate(symbol: str, hist: pd.DataFrame, horizon: str) -> dict | None:
    """Long se il prezzo è sopra la media a 200 E la media sale.

    La condizione sulla pendenza è essenziale: il prezzo può stare sopra
    una media che scende, ed è la configurazione tipica di un rimbalzo
    dentro un ribasso — cioè il caso in cui un trend-following perde di
    più."""
    if len(hist) < MA_TREND_LENGTH + MA_SLOPE_LOOKBACK + 2:
        return None
    close_series = hist["Close"]
    ma = close_series.rolling(MA_TREND_LENGTH).mean()
    if pd.isna(ma.iloc[-1]) or pd.isna(ma.iloc[-1 - MA_SLOPE_LOOKBACK]):
        return None

    close = float(close_series.iloc[-1])
    ma_now = float(ma.iloc[-1])
    ma_before = float(ma.iloc[-1 - MA_SLOPE_LOOKBACK])

    atr_value = _atr_value(hist)
    if atr_value is None:
        return None

    if close > ma_now and ma_now > ma_before:
        return _trailing_plan("long", close, atr_value)
    if close < ma_now and ma_now < ma_before:
        return _trailing_plan("short", close, atr_value)
    return {"bias": "nessun_setup"}


# ---------------------------------------------------------------------------
# 4. Momentum 12-1
# ---------------------------------------------------------------------------

def _momentum_generate(symbol: str, hist: pd.DataFrame, horizon: str) -> dict | None:
    """Long se il rendimento a 12 mesi, escluso l'ultimo, è positivo.

    L'ultimo mese si esclude per convenzione consolidata: sul mese più
    recente agisce un effetto di inversione di breve termine che
    contaminerebbe il segnale di momentum vero e proprio."""
    if len(hist) < MOMENTUM_LOOKBACK + 2:
        return None
    close_series = hist["Close"]
    past = float(close_series.iloc[-MOMENTUM_LOOKBACK])
    recent = float(close_series.iloc[-1 - MOMENTUM_SKIP])
    if past <= 0:
        return None
    momentum = recent / past - 1

    close = float(close_series.iloc[-1])
    atr_value = _atr_value(hist)
    if atr_value is None:
        return None

    if momentum > 0:
        return _trailing_plan("long", close, atr_value)
    if momentum < 0:
        return _trailing_plan("short", close, atr_value)
    return {"bias": "nessun_setup"}


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------

STRATEGIES: dict[str, Strategy] = {
    "murphy": Strategy(
        key="murphy", label="Murphy (attuale)",
        description=("Il motore completo di analisi tecnica: trend strutturale riconciliato con le "
                     "medie, oscillatori, volume, pattern grafici e candlestick, sintetizzati in "
                     "Directional Score e Agreement Index. Stop sul supporto/resistenza più vicino "
                     "con buffer ATR, target sul livello opposto più vicino."),
        parameters="decine di regole e soglie interagenti",
        generate=_murphy_generate,
        warmup_bars=lambda horizon: sig.warmup_bars(horizon),
    ),
    "donchian": Strategy(
        key="donchian", label=f"Rottura Donchian {DONCHIAN_ENTRY_BARS} giorni",
        description=(f"Entra quando il prezzo supera il massimo (o rompe il minimo) delle "
                     f"{DONCHIAN_ENTRY_BARS} barre precedenti. Esce con uno stop in trailing a "
                     f"{TRAILING_ATR_MULT:g}×ATR dal massimo raggiunto, senza obiettivo di prezzo. "
                     "È l'impianto classico dei Turtle."),
        parameters=f"canale {DONCHIAN_ENTRY_BARS} barre · stop iniziale {INITIAL_STOP_ATR_MULT:g}×ATR · "
                    f"trailing {TRAILING_ATR_MULT:g}×ATR",
        generate=_donchian_generate,
        warmup_bars=lambda horizon: DONCHIAN_ENTRY_BARS + ATR_PERIOD + 5,
    ),
    "ma_trend": Strategy(
        key="ma_trend", label=f"Trend su media {MA_TREND_LENGTH}",
        description=(f"Entra long quando il prezzo sta sopra la media a {MA_TREND_LENGTH} periodi e "
                     "la media sale (short nel caso speculare). La condizione sulla pendenza evita "
                     "i rimbalzi dentro un ribasso. Uscita in trailing, nessun target."),
        parameters=f"media {MA_TREND_LENGTH} · pendenza su {MA_SLOPE_LOOKBACK} barre · "
                    f"trailing {TRAILING_ATR_MULT:g}×ATR",
        generate=_ma_trend_generate,
        warmup_bars=lambda horizon: MA_TREND_LENGTH + MA_SLOPE_LOOKBACK + 5,
    ),
    "momentum": Strategy(
        key="momentum", label="Momentum 12-1 mesi",
        description=("Entra long se il rendimento degli ultimi 12 mesi, escluso l'ultimo, è "
                     "positivo (short se negativo). È la forma più semplice del momentum di serie "
                     "storica. Uscita in trailing, nessun target."),
        parameters=f"12 mesi meno l'ultimo · trailing {TRAILING_ATR_MULT:g}×ATR",
        generate=_momentum_generate,
        warmup_bars=lambda horizon: MOMENTUM_LOOKBACK + 5,
    ),
}

DEFAULT_STRATEGY = "murphy"


def get(key: str) -> Strategy:
    if key not in STRATEGIES:
        raise ValueError(
            f"Strategia '{key}' sconosciuta. Disponibili: {', '.join(STRATEGIES)}."
        )
    return STRATEGIES[key]


def keys() -> list[str]:
    return list(STRATEGIES)
