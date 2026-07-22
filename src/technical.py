"""
Analisi tecnica — ricostruita secondo Specifica_Analisi_Tecnica_Murphy.md
e il modulo di riferimento ta_core.py forniti dall'utente. Segue
l'impianto di J. J. Murphy (*Analisi tecnica dei mercati finanziari*) su
tre premesse: il prezzo sconta tutto, i prezzi si muovono in trend, la
storia si ripete. Ogni output è uno schema statistico descrittivo sui
dati passati, mai una previsione.

Principi architetturali (§0 della specifica), tutti implementati qui:
  1. Ogni finestra di calcolo scala con l'orizzonte scelto (breve/medio/
     lungo) — niente più trend detector a finestra fissa che produce
     verdetti sbagliati su orizzonti diversi da quello per cui è tarato.
  2. Gerarchia dei timeframe: il trend strutturale (Dow, swing HH/HL vs
     LH/LL) e l'allineamento delle medie mobili si riconciliano con una
     regola deterministica (§2) — una debolezza di breve dentro un
     allineamento rialzista delle medie è un *pullback*, non un'inversione.
  3. Concordanza prima del verdetto: il motore di sintesi (§11) produce
     due numeri distinti — Directional Score e Agreement Index — e
     distingue esplicitamente "neutro per assenza di direzione" da
     "conflitto tra segnali" (oggi confusi in un unico "neutro ~0").
  4. Descrittivo, non predittivo: i disclaimer restano ovunque.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src import data_provider as dp

# ---------------------------------------------------------------------------
# §0 — Tabella maestra: parametri per orizzonte (fedele a ta_core.py)
# ---------------------------------------------------------------------------
HORIZONS = {
    "breve": {
        "label": "Breve termine (trading)",
        "period": "6mo", "interval": "1d",
        "swing_order": 3,            # fractal stretti (2-3 bar)
        "trend_lookback": 60,
        "ma": (10, 20, 50),
        "rsi_period": 14, "stoch": (14, 3, 3), "has_stochastic": True,
        "sr_lookback_bars": 63,       # ultimi ~3 mesi di borsa
    },
    "medio": {
        "label": "Medio termine (posizionamento)",
        "period": "2y", "interval": "1d",
        "swing_order": 5,            # fractal medi
        "trend_lookback": 160,
        "ma": (20, 50, 200),
        "rsi_period": 14, "stoch": (14, 3, 3), "has_stochastic": True,
        "sr_lookback_bars": 210,      # ultimi ~9-12 mesi
    },
    "lungo": {
        "label": "Lungo termine (investimento)",
        "period": "10y", "interval": "1wk",
        "swing_order": 9,            # fractal ampi (8-10 bar, su settimanale)
        "trend_lookback": 150,        # ~2-3 anni di settimane
        "ma": (30, 50, 200),
        "rsi_period": 14, "stoch": (14, 3, 3), "has_stochastic": False,
        "sr_lookback_bars": None,      # multi-anno: usa tutta la storia disponibile
    },
}


# ---------------------------------------------------------------------------
# Helpers generici
# ---------------------------------------------------------------------------

def _last(series: pd.Series | None):
    if series is None:
        return None
    s = series.dropna()
    return float(s.iloc[-1]) if not s.empty else None


def _recent_cross(fast: pd.Series, slow: pd.Series, lookback: int = 5):
    """Rialzista/ribassista se le due serie si sono incrociate negli ultimi
    `lookback` periodi, altrimenti None."""
    idx = fast.dropna().index.intersection(slow.dropna().index)
    if len(idx) < 2:
        return None
    diff = (fast.loc[idx] - slow.loc[idx]).tail(lookback + 1)
    if len(diff) < 2:
        return None
    sign = np.sign(diff.values)
    for i in range(1, len(sign)):
        if sign[i - 1] < 0 and sign[i] > 0:
            return "rialzista"
        if sign[i - 1] > 0 and sign[i] < 0:
            return "ribassista"
    return None


def _slope_sign(series: pd.Series, min_points: int = 5) -> int:
    """Segno della pendenza di una regressione lineare sulla serie
    (usato per le divergenze prezzo/oscillatore e prezzo/OBV)."""
    s = series.dropna()
    if len(s) < min_points:
        return 0
    x = np.arange(len(s))
    slope, _ = np.polyfit(x, s.values.astype(float), 1)
    if abs(slope) < 1e-9:
        return 0
    return 1 if slope > 0 else -1


# ---------------------------------------------------------------------------
# §1 — Swing detection e trend strutturale (Dow Theory), da ta_core.py
# ---------------------------------------------------------------------------

def detect_swings(hist: pd.DataFrame, order: int) -> list[dict]:
    """Rileva swing high/low come massimi/minimi locali su finestra +/-
    `order` (fractal). `order` scala con l'orizzonte (vedi HORIZONS).
    Ritorna una lista cronologica alternata H/L: [{'date','price','kind'}]."""
    highs = hist["High"].to_numpy()
    lows = hist["Low"].to_numpy()
    idx = hist.index
    n = len(hist)
    raw: list[dict] = []

    for i in range(order, n - order):
        win_h = highs[i - order:i + order + 1]
        win_l = lows[i - order:i + order + 1]
        if highs[i] == win_h.max() and win_h.argmax() == order:
            raw.append({"date": idx[i], "price": float(highs[i]), "kind": "H"})
        elif lows[i] == win_l.min() and win_l.argmin() == order:
            raw.append({"date": idx[i], "price": float(lows[i]), "kind": "L"})

    # Alterna H/L: se due swing consecutivi sono dello stesso tipo, tieni il più estremo
    cleaned: list[dict] = []
    for s in raw:
        if cleaned and cleaned[-1]["kind"] == s["kind"]:
            if s["kind"] == "H" and s["price"] > cleaned[-1]["price"]:
                cleaned[-1] = s
            elif s["kind"] == "L" and s["price"] < cleaned[-1]["price"]:
                cleaned[-1] = s
        else:
            cleaned.append(s)
    return cleaned


def swings_by_kind(swings: list[dict]) -> tuple[list[tuple], list[tuple]]:
    """Converte la lista cronologica alternata in due liste separate
    (date, price) — formato retro-compatibile per trendline/S-R/pattern."""
    highs = [(s["date"], s["price"]) for s in swings if s["kind"] == "H"]
    lows = [(s["date"], s["price"]) for s in swings if s["kind"] == "L"]
    return highs, lows


def classify_structural_trend(swings: list[dict]) -> str:
    """Trend per struttura di swing (§1), non per una singola media:
    HH+HL = rialzista, LH+LL = ribassista, altrimenti laterale. Guarda gli
    ultimi 2 massimi e ultimi 2 minimi rilevanti (gli ultimi ~3-4 swing)."""
    highs = [s for s in swings if s["kind"] == "H"]
    lows = [s for s in swings if s["kind"] == "L"]
    if len(highs) < 2 or len(lows) < 2:
        return "laterale"

    hh = highs[-1]["price"] > highs[-2]["price"]
    hl = lows[-1]["price"] > lows[-2]["price"]
    lh = highs[-1]["price"] < highs[-2]["price"]
    ll = lows[-1]["price"] < lows[-2]["price"]

    if hh and hl:
        return "rialzista"
    if lh and ll:
        return "ribassista"
    return "laterale"


def recent_swing_strength(swings: list[dict]) -> str:
    """Forza/debolezza di brevissimo termine tra gli ultimi due swing:
    serve alla riconciliazione per distinguere un pullback da un'inversione
    vera. Ritorna 'up' | 'down' | 'flat'."""
    if len(swings) < 2:
        return "flat"
    last, prev = swings[-1], swings[-2]
    if last["price"] > prev["price"]:
        return "up"
    if last["price"] < prev["price"]:
        return "down"
    return "flat"


# ---------------------------------------------------------------------------
# §4 — Medie mobili e allineamento
# ---------------------------------------------------------------------------

def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def ma_alignment_from_values(price, fast_val, mid_val, slow_val) -> str:
    if None in (price, fast_val, mid_val, slow_val) or any(pd.isna(v) for v in (price, fast_val, mid_val, slow_val)):
        return "misto"
    if price > fast_val > mid_val > slow_val:
        return "rialzista"
    if price < fast_val < mid_val < slow_val:
        return "ribassista"
    return "misto"


def compute_moving_averages(hist: pd.DataFrame, ma_tuple: tuple[int, int, int]) -> dict:
    close = hist["Close"]
    fast_n, mid_n, slow_n = ma_tuple
    fast = sma(close, fast_n)
    mid = sma(close, mid_n)
    slow = sma(close, slow_n)
    fast_val, mid_val, slow_val = _last(fast), _last(mid), _last(slow)
    price = _last(close)

    alignment = ma_alignment_from_values(price, fast_val, mid_val, slow_val)
    # Pendenza della media media: piatta = mercato laterale (§4), da non
    # interpretare come trend nemmeno se il prezzo la attraversa spesso.
    mid_slope = _slope_sign(mid.tail(10))
    is_flat = mid_slope == 0

    cross = _recent_cross(mid, slow)
    return {
        "fast": fast, "mid": mid, "slow": slow,
        "fast_n": fast_n, "mid_n": mid_n, "slow_n": slow_n,
        "fast_val": fast_val, "mid_val": mid_val, "slow_val": slow_val,
        "alignment": alignment, "is_flat": is_flat,
        "golden_cross": cross == "rialzista",
        "death_cross": cross == "ribassista",
    }


def bollinger_bands(hist: pd.DataFrame, window: int = 20, num_std: float = 2.0) -> dict:
    close = hist["Close"]
    mid = sma(close, window)
    std = close.rolling(window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std

    price = _last(close)
    u, l, m = _last(upper), _last(lower), _last(mid)
    percent_b = (price - l) / (u - l) if price is not None and u and l and u != l else None

    bw_series = (upper - lower) / mid
    bandwidth = _last(bw_series)
    squeeze = None
    bw_recent = bw_series.dropna().tail(60)
    if len(bw_recent) > 10 and bandwidth is not None:
        squeeze = bool(bandwidth < bw_recent.quantile(0.2))

    return {
        "upper": upper, "mid": mid, "lower": lower,
        "upper_val": u, "lower_val": l, "mid_val": m,
        "percent_b": percent_b, "bandwidth": bandwidth, "squeeze": squeeze,
    }


# ---------------------------------------------------------------------------
# §2 — RICONCILIAZIONE trend <-> medie (fix del bug principale)
# ---------------------------------------------------------------------------

def reconcile_trend(struct: str, ma_align: str, strength: str) -> dict:
    """Regola deterministica (§2): concilia struttura swing e allineamento
    medie PRIMA di emettere il verdetto. Risolve sia il verdetto errato
    ("Trend Ribassista" con prezzo ai massimi) sia la contraddizione
    interna ("Ribassista" + "Medie rialziste" mostrati insieme).

    Ritorna sia un'etichetta descrittiva (`verdict_label`, con la nuance
    pullback/rimbalzo) sia una categoria semplice (`verdict_simple`, per
    badge/scoring) e un voto direzionale (d, c) pronto per il motore di
    sintesi (§11)."""
    if struct == "rialzista" and ma_align == "rialzista":
        return {"verdict_label": "Rialzista (alta confidenza)", "verdict_simple": "rialzista", "d": 0.9, "c": 0.9}
    if struct == "ribassista" and ma_align == "ribassista":
        return {"verdict_label": "Ribassista (alta confidenza)", "verdict_simple": "ribassista", "d": -0.9, "c": 0.9}
    if ma_align == "rialzista" and strength == "down":
        return {"verdict_label": "Rialzista con pullback in corso", "verdict_simple": "rialzista", "d": 0.35, "c": 0.6}
    if ma_align == "ribassista" and strength == "up":
        return {"verdict_label": "Ribassista con rimbalzo in corso", "verdict_simple": "ribassista", "d": -0.35, "c": 0.6}
    if struct == "rialzista":
        return {"verdict_label": "Rialzista (media confidenza)", "verdict_simple": "rialzista", "d": 0.6, "c": 0.5}
    if struct == "ribassista":
        return {"verdict_label": "Ribassista (media confidenza)", "verdict_simple": "ribassista", "d": -0.6, "c": 0.5}
    return {"verdict_label": "Laterale / senza trend", "verdict_simple": "laterale", "d": 0.0, "c": 0.4}


def analyze_trend(hist: pd.DataFrame, params: dict) -> dict:
    """Pipeline completa di trend per un orizzonte: swing scalati, trend
    strutturale, allineamento medie, riconciliazione. Finestra di calcolo
    che scala con l'orizzonte scelto (§0.1) — l'errore #1 dell'implementazione
    precedente era una finestra fissa e corta indipendente dall'orizzonte."""
    lookback = params["trend_lookback"]
    window = hist.iloc[-lookback:] if len(hist) > lookback else hist
    swings = detect_swings(window, params["swing_order"])
    struct = classify_structural_trend(swings)
    strength = recent_swing_strength(swings)

    ma = compute_moving_averages(hist, params["ma"])
    recon = reconcile_trend(struct, ma["alignment"], strength)

    swing_highs, swing_lows = swings_by_kind(swings)
    return {
        "struct": struct, "ma_alignment": ma["alignment"], "recent_strength": strength,
        "verdict_label": recon["verdict_label"], "verdict_simple": recon["verdict_simple"],
        "d": recon["d"], "c": recon["c"],
        "n_swings": len(swings), "swings": swings,
        "swing_highs": swing_highs, "swing_lows": swing_lows,
    }


# ---------------------------------------------------------------------------
# Oscillatori (RSI, Stocastico, MACD, Williams %R) — formule standard
# ---------------------------------------------------------------------------

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI di Wilder: RS = media mobile (smussata) dei rialzi / media
    mobile (smussata) dei ribassi su `period` periodi."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    out = out.where(avg_loss != 0, 100.0)
    out = out.where(avg_gain != 0, 0.0)
    return out


def rsi_signal(value: float | None) -> str | None:
    """Soglie fisse e uniformi (fix §5): >70 ipercomprato, <30 ipervenduto
    — sempre le stesse, cosi' il testo generato dai flag reali non produce
    più non-sequitur tipo 'RSI neutrale... stocastico anch'esso ipercomprato'."""
    if value is None:
        return None
    if value >= 80:
        return "ipercomprato_forte"
    if value >= 70:
        return "ipercomprato"
    if value <= 20:
        return "ipervenduto_forte"
    if value <= 30:
        return "ipervenduto"
    return "neutrale"


def detect_rsi_divergence(close: pd.Series, rsi_series: pd.Series, lookback: int = 30) -> str | None:
    """Divergenza (§5, §11): il prezzo fa un nuovo estremo ma l'RSI no —
    segnale di indebolimento del momentum. 'ribassista' = prezzo ai
    massimi con RSI più debole del suo massimo recente; 'rialzista' =
    simmetrico sui minimi."""
    c = close.tail(lookback).dropna()
    r = rsi_series.tail(lookback).dropna()
    if len(c) < 10 or len(r) < 10:
        return None
    if c.iloc[-1] >= c.max() * 0.999 and r.idxmax() != r.index[-1] and r.iloc[-1] < r.max() * 0.98:
        return "ribassista"
    if c.iloc[-1] <= c.min() * 1.001 and r.idxmin() != r.index[-1] and r.iloc[-1] > r.min() * 1.02:
        return "rialzista"
    return None


def stochastic(hist: pd.DataFrame, k_period: int = 14, d_period: int = 3, smooth: int = 3) -> dict:
    """Stocastico lento: %K grezzo smussato su `smooth` periodi, %D = media
    mobile a `d_period` periodi del %K smussato. Soglie standard 80/20."""
    low_min = hist["Low"].rolling(k_period).min()
    high_max = hist["High"].rolling(k_period).max()
    raw_k = 100 * (hist["Close"] - low_min) / (high_max - low_min)
    slow_k = raw_k.rolling(smooth).mean()
    slow_d = slow_k.rolling(d_period).mean()
    return {"k": slow_k, "d": slow_d, "k_val": _last(slow_k), "d_val": _last(slow_d)}


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """MACD di Appel: differenza tra EMA 12 e 26, linea di segnale = EMA 9
    della linea MACD, istogramma = MACD - segnale."""
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    hist_line = macd_line - signal_line
    return {
        "macd": macd_line, "signal": signal_line, "hist": hist_line,
        "macd_val": _last(macd_line), "signal_val": _last(signal_line), "hist_val": _last(hist_line),
    }


def williams_r(hist: pd.DataFrame, period: int = 14) -> pd.Series:
    """%R di Larry Williams, scala -100..0: ipercomprato sopra -20,
    ipervenduto sotto -80 (equivalenti alle soglie 80/20 del manuale su
    scala invertita)."""
    high_max = hist["High"].rolling(period).max()
    low_min = hist["Low"].rolling(period).min()
    return -100 * (high_max - hist["Close"]) / (high_max - low_min)


def atr(hist: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range di Wilder: volatilità media recente in punti di
    prezzo, usata per calibrare stop/target nel piano operativo (§13) —
    non è nel materiale delle tecniche di misurazione delle figure di
    Murphy usato per il resto del modulo, ma è uno standard ampiamente
    diffuso (stesso autore dell'RSI) necessario per un piano operativo."""
    high, low, close = hist["High"], hist["Low"], hist["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


# ---------------------------------------------------------------------------
# §7 — Volume e On-Balance Volume
# ---------------------------------------------------------------------------

def obv(hist: pd.DataFrame) -> pd.Series:
    """On-Balance Volume: cumula il volume col segno della variazione di
    chiusura — proxy sintetico del flusso (§7)."""
    close = hist["Close"]
    volume = hist["Volume"]
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def volume_analysis(hist: pd.DataFrame, lookback: int) -> dict:
    """Volume come conferma (Murphy, §7): espande nella direzione del
    trend = conferma, contrae = cautela. Divergenza OBV/prezzo = early
    warning. Spike di volume = maggiore affidabilità di un eventuale
    breakout."""
    volume = hist["Volume"]
    close = hist["Close"]
    obv_series = obv(hist)
    window = min(lookback, len(hist))

    vol_trend = None
    if window >= 10:
        half = window // 2
        recent_vol = volume.tail(half).mean()
        prior_vol = volume.tail(window).head(window - half).mean()
        if prior_vol and prior_vol > 0:
            change = (recent_vol - prior_vol) / prior_vol
            vol_trend = "in espansione" if change > 0.1 else ("in contrazione" if change < -0.1 else "stabile")

    price_slope = _slope_sign(close.tail(window))
    obv_slope = _slope_sign(obv_series.tail(window))
    divergence = None
    if price_slope != 0 and obv_slope != 0 and price_slope != obv_slope:
        divergence = "ribassista" if price_slope > 0 else "rialzista"

    avg_vol = volume.tail(window).mean() if window >= 5 else None
    last_vol = float(volume.iloc[-1]) if len(volume) else None
    spike = bool(last_vol and avg_vol and avg_vol > 0 and last_vol > 1.5 * avg_vol)

    return {
        "obv_series": obv_series, "obv_val": _last(obv_series),
        "volume_trend": vol_trend, "divergence": divergence, "volume_spike": spike,
        "price_slope": price_slope, "obv_slope": obv_slope,
    }


# ---------------------------------------------------------------------------
# §3 — Supporti/resistenze (fix: primo livello sotto/sopra il prezzo,
# non il più toccato in assoluto) e trendline validate
# ---------------------------------------------------------------------------

def support_resistance_levels(hist: pd.DataFrame, swing_highs, swing_lows,
                               ma_dict: dict, sr_lookback_bars: int | None,
                               tolerance_pct: float = 1.5, max_levels: int = 8) -> list[dict]:
    """Livelli pesati per numero di tocchi + recency + volume ai tocchi
    (§3). Include le medie mobili come supporti/resistenze dinamici —
    spesso il primo livello reale, non un vecchio massimo lontano. Il
    ruolo (supporto/resistenza) è sempre relativo al prezzo attuale: si
    scambia dopo la rottura, come in Murphy."""
    current_price = _last(hist["Close"])
    if current_price is None:
        return []

    # Limita gli swing all'orizzonte S/R richiesto (non tutto lo storico
    # scaricato, che può coprire anni anche per l'orizzonte breve).
    if sr_lookback_bars:
        cutoff = hist.index[-sr_lookback_bars] if len(hist) > sr_lookback_bars else hist.index[0]
        swing_highs = [(d, p) for d, p in swing_highs if d >= cutoff]
        swing_lows = [(d, p) for d, p in swing_lows if d >= cutoff]

    n = len(hist)
    volume = hist["Volume"] if "Volume" in hist.columns else None

    def _recency_score(date) -> float:
        pos = hist.index.get_loc(date)
        return pos / max(1, n - 1)  # 0 (vecchio) .. 1 (recente)

    def _volume_score(date) -> float:
        if volume is None:
            return 0.5
        avg = volume.tail(min(n, 60)).mean()
        v = float(volume.loc[date]) if date in volume.index else None
        if not v or not avg:
            return 0.5
        return min(1.0, v / (2 * avg))

    all_points = [(d, p) for d, p in swing_highs] + [(d, p) for d, p in swing_lows]
    clusters = []
    for d, p in sorted(all_points, key=lambda x: x[1]):
        placed = False
        for c in clusters:
            if abs(p - c["mean"]) / c["mean"] * 100 <= tolerance_pct:
                c["values"].append(p)
                c["dates"].append(d)
                c["mean"] = sum(c["values"]) / len(c["values"])
                placed = True
                break
        if not placed:
            clusters.append({"mean": p, "values": [p], "dates": [d]})

    levels = []
    for c in clusters:
        touches = len(c["values"])
        recency = max((_recency_score(d) for d in c["dates"]), default=0.0)
        vol_score = max((_volume_score(d) for d in c["dates"]), default=0.5)
        robustness = touches * 1.0 + recency * 2.0 + vol_score * 1.0
        role = "resistenza" if c["mean"] > current_price else "supporto"
        levels.append({
            "level": round(c["mean"], 4), "touches": touches, "recency": round(recency, 2),
            "volume_score": round(vol_score, 2), "robustness": round(robustness, 2),
            "role": role, "source": "swing",
        })

    # Medie mobili come livelli dinamici (§3): spesso il vero primo livello.
    for key, label in (("fast", "MA breve"), ("mid", "MA media"), ("slow", "MA lunga")):
        val = ma_dict.get(f"{key}_val")
        if val is None or pd.isna(val):
            continue
        role = "resistenza" if val > current_price else "supporto"
        levels.append({
            "level": round(float(val), 4), "touches": 1, "recency": 1.0, "volume_score": 0.5,
            "robustness": 2.5, "role": role, "source": label,
        })

    levels.sort(key=lambda l: l["level"])
    if len(levels) > max_levels:
        levels.sort(key=lambda l: -l["robustness"])
        levels = levels[:max_levels]
        levels.sort(key=lambda l: l["level"])
    return levels


def nearest_support(levels: list[dict], price: float) -> dict | None:
    """Fix del bug 'supporto più vicino a 276 con prezzo a 325': il primo
    supporto è sempre quello più vicino SOTTO il prezzo, per distanza —
    non il livello con più tocchi in assoluto, che può essere lontano."""
    candidates = [l for l in levels if l["role"] == "supporto" and l["level"] < price]
    if not candidates:
        return None
    return max(candidates, key=lambda l: l["level"])  # il più vicino sotto = il più alto tra i supporti


def nearest_resistance(levels: list[dict], price: float) -> dict | None:
    candidates = [l for l in levels if l["role"] == "resistenza" and l["level"] > price]
    if not candidates:
        return None
    return min(candidates, key=lambda l: l["level"])  # il più vicino sopra = il più basso tra le resistenze


def _slope(points) -> float:
    if len(points) < 2:
        return 0.0
    x0 = points[0][0]
    xs = np.array([(p[0] - x0).total_seconds() / 86400 for p in points])
    ys = np.array([p[1] for p in points], dtype=float)
    if xs.max() == xs.min():
        return 0.0
    slope, _ = np.polyfit(xs, ys, 1)
    return float(slope)


def fit_trendline(points: list[tuple], kind: str, hist: pd.DataFrame, atr_val: float | None) -> dict | None:
    """Fit su swing omogenei (solo minimi per una linea di supporto, solo
    massimi per una di resistenza — garantito dal chiamante). Richiede
    >=3 punti di contatto per essere mostrata (§3). Valida che la linea
    non attraversi la serie prezzi nel range di fit (tolleranza ATR):
    fix del bug "resistenza a 120 con prezzo a 210"."""
    if len(points) < 3:
        return None
    pts = sorted(points, key=lambda p: p[0])
    x0 = pts[0][0]
    xs = np.array([(p[0] - x0).total_seconds() / 86400 for p in pts])
    ys = np.array([p[1] for p in pts], dtype=float)
    if xs.max() == xs.min():
        return None
    slope, intercept = np.polyfit(xs, ys, 1)

    tol = 0.4 * atr_val if atr_val else 0.01 * float(np.mean(ys))
    start, end = pts[0][0], pts[-1][0]
    window = hist.loc[(hist.index >= start) & (hist.index <= end)]
    violations = 0
    for d, row in window.iterrows():
        days = (d - x0).total_seconds() / 86400
        line_y = slope * days + intercept
        if kind == "support" and line_y > row["Low"] + tol:
            violations += 1
        elif kind == "resistance" and line_y < row["High"] - tol:
            violations += 1
    valid = len(window) == 0 or (violations / max(1, len(window))) <= 0.1

    # Scarta pendenze che portano a valori fuori scala rispetto al range prezzi del periodo
    price_range = float(hist["Close"].max() - hist["Close"].min()) or 1.0
    end_days = (end - x0).total_seconds() / 86400
    edge_val = slope * end_days + intercept
    if abs(edge_val - float(np.mean(ys))) > 5 * price_range:
        valid = False

    if not valid:
        return None

    return {"slope": float(slope), "intercept": float(intercept), "x0": x0, "kind": kind,
            "touches": len(pts), "confirmed": len(pts) >= 3, "points": pts}


def _trendline_y(line: dict, x) -> float:
    days = (x - line["x0"]).total_seconds() / 86400
    return line["slope"] * days + line["intercept"]


# ---------------------------------------------------------------------------
# §9 — Pattern di candlestick con filtro affidabilità/recency/contesto
# ---------------------------------------------------------------------------

_CANDLE_RELIABILITY = {
    "Doji": 1, "Hammer": 1, "Hanging man": 1, "Inverted hammer / Shooting star": 1,
    "Engulfing rialzista": 2, "Engulfing ribassista": 2,
    "Piercing line": 2, "Dark cloud cover": 2,
    "Morning star": 3, "Evening star": 3,
}


def _candle(row) -> dict:
    o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
    body = abs(c - o)
    rng = (h - l) or 1e-9
    return {
        "o": o, "h": h, "l": l, "c": c, "body": body, "range": rng,
        "upper_shadow": h - max(o, c), "lower_shadow": min(o, c) - l,
        "bullish": c > o, "bearish": c < o,
    }


def detect_candlestick_patterns(hist: pd.DataFrame, lookback: int = 12) -> list[dict]:
    """Rilevamento grezzo (1/2/3 candele) — il filtro di affidabilità e
    contesto è applicato separatamente da `filter_candlestick_patterns`."""
    patterns = []
    n = len(hist)
    start = max(2, n - lookback)
    for i in range(start, n):
        row = hist.iloc[i]
        m = _candle(row)
        date = hist.index[i]

        if m["body"] <= 0.1 * m["range"]:
            patterns.append({"date": date, "pattern": "Doji", "direction": "neutro",
                              "note": "Apertura e chiusura quasi coincidenti: indecisione del mercato."})

        if m["body"] > 0 and m["lower_shadow"] >= 2 * m["body"] and m["upper_shadow"] <= 0.3 * m["body"]:
            prior_avg = hist["Close"].iloc[max(0, i - 5):i].mean()
            if prior_avg and row["Close"] > prior_avg:
                patterns.append({"date": date, "pattern": "Hanging man", "direction": "ribassista",
                                  "note": "Ombra inferiore lunga dopo un uptrend: possibile inversione, da confermare."})
            else:
                patterns.append({"date": date, "pattern": "Hammer", "direction": "rialzista",
                                  "note": "Ombra inferiore lunga dopo un downtrend: possibile inversione, da confermare."})

        if m["body"] > 0 and m["upper_shadow"] >= 2 * m["body"] and m["lower_shadow"] <= 0.3 * m["body"]:
            patterns.append({"date": date, "pattern": "Inverted hammer / Shooting star", "direction": "da_confermare",
                              "note": "Ombra superiore lunga, corpo piccolo in basso: potenziale inversione, serve conferma."})

        prev = hist.iloc[i - 1]
        pm = _candle(prev)
        if pm["bearish"] and m["bullish"] and m["o"] <= pm["c"] and m["c"] >= pm["o"]:
            patterns.append({"date": date, "pattern": "Engulfing rialzista", "direction": "rialzista",
                              "note": "Il corpo bianco avvolge completamente il corpo nero precedente."})
        if pm["bullish"] and m["bearish"] and m["o"] >= pm["c"] and m["c"] <= pm["o"]:
            patterns.append({"date": date, "pattern": "Engulfing ribassista", "direction": "ribassista",
                              "note": "Il corpo nero avvolge completamente il corpo bianco precedente."})
        if pm["bearish"] and m["bullish"] and m["o"] < pm["l"] and pm["c"] < m["c"] < pm["o"]:
            patterns.append({"date": date, "pattern": "Piercing line", "direction": "rialzista",
                              "note": "Apertura sotto il minimo precedente, chiusura oltre la metà del corpo nero precedente."})
        if pm["bullish"] and m["bearish"] and m["o"] > pm["h"] and pm["c"] > m["c"] > pm["o"]:
            patterns.append({"date": date, "pattern": "Dark cloud cover", "direction": "ribassista",
                              "note": "Apertura sopra il massimo precedente, chiusura oltre la metà del corpo bianco precedente."})

        if i >= 2:
            p1, p2 = hist.iloc[i - 2], hist.iloc[i - 1]
            m1, m2 = _candle(p1), _candle(p2)
            if (m1["bearish"] and m1["body"] > m1["range"] * 0.5 and m2["body"] < m1["body"] * 0.5
                    and m["bullish"] and m["c"] > (m1["o"] + m1["c"]) / 2):
                patterns.append({"date": date, "pattern": "Morning star", "direction": "rialzista",
                                  "note": "Tre candele: forte ribasso, indecisione, forte recupero: inversione rialzista."})
            if (m1["bullish"] and m1["body"] > m1["range"] * 0.5 and m2["body"] < m1["body"] * 0.5
                    and m["bearish"] and m["c"] < (m1["o"] + m1["c"]) / 2):
                patterns.append({"date": date, "pattern": "Evening star", "direction": "ribassista",
                                  "note": "Tre candele: forte rialzo, indecisione, forte ribasso: inversione ribassista."})

    return patterns


def filter_candlestick_patterns(raw_patterns: list[dict], hist: pd.DataFrame, trend_struct: str,
                                 sr_levels: list[dict], max_output: int = 3) -> dict:
    """Fix §9: peso di affidabilità (3 candele > 2 > 1) + bonus di
    coerenza con trend/livello + filtro di contesto (pattern opposti
    ravvicinati si annullano, invece di essere elencati entrambi come
    validi con pari dignità — il problema concreto di evening star e
    piercing line consecutivi). Limita l'output alle ultime ~2-3 candele
    davvero significative."""
    if not raw_patterns:
        return {"patterns": [], "had_conflict": False}

    weighted = []
    for p in raw_patterns:
        w = _CANDLE_RELIABILITY.get(p["pattern"], 1)
        coherence = 0
        if p["date"] in hist.index:
            close_at = float(hist.loc[p["date"], "Close"])
            near_support = any(l["role"] == "supporto" and l["level"] > 0
                                and abs(l["level"] - close_at) / l["level"] < 0.02 for l in sr_levels)
            near_resistance = any(l["role"] == "resistenza" and l["level"] > 0
                                   and abs(l["level"] - close_at) / l["level"] < 0.02 for l in sr_levels)
            if p["direction"] == "rialzista" and (trend_struct == "ribassista" or near_support):
                coherence = 1
            if p["direction"] == "ribassista" and (trend_struct == "rialzista" or near_resistance):
                coherence = 1
        weighted.append({**p, "weight": w, "coherence": coherence})

    cancelled = set()
    for i in range(len(weighted) - 1):
        a, b = weighted[i], weighted[i + 1]
        if a["direction"] in ("rialzista", "ribassista") and b["direction"] in ("rialzista", "ribassista") \
                and a["direction"] != b["direction"]:
            try:
                idx_a, idx_b = hist.index.get_loc(a["date"]), hist.index.get_loc(b["date"])
            except KeyError:
                continue
            if idx_b - idx_a <= 2 and abs(a["weight"] - b["weight"]) <= 1:
                cancelled.add(i)
                cancelled.add(i + 1)

    had_conflict = bool(cancelled)
    survivors = [w for i, w in enumerate(weighted) if i not in cancelled]
    survivors.sort(key=lambda p: (p["weight"] + p["coherence"], p["date"]), reverse=True)
    top = survivors[:max_output]
    top.sort(key=lambda p: p["date"])
    return {"patterns": top, "had_conflict": had_conflict}


# ---------------------------------------------------------------------------
# §8 — Figure di prezzo con stato (in formazione / completato / invalidato)
# ---------------------------------------------------------------------------

def detect_double_top_bottom(swing_highs, swing_lows, hist: pd.DataFrame, tolerance_pct: float = 3.0) -> list[dict]:
    """Doppio massimo/minimo con stato esplicito: un pattern non confermato
    dal break della neckline resta 'in formazione', non va pesato come
    completato (§8)."""
    findings = []
    close_last = _last(hist["Close"])

    if len(swing_highs) >= 2:
        h1, h2 = swing_highs[-2], swing_highs[-1]
        if abs(h1[1] - h2[1]) / h1[1] * 100 <= tolerance_pct:
            between = [l for l in swing_lows if h1[0] < l[0] < h2[0]]
            if between:
                trough = min(between, key=lambda x: x[1])
                height = h1[1] - trough[1]
                target = trough[1] - height
                state = "in formazione"
                if close_last is not None:
                    if close_last < trough[1]:
                        state = "completato"
                    elif close_last > max(h1[1], h2[1]) * 1.01:
                        state = "invalidato"
                findings.append({
                    "pattern": "Doppio massimo", "direction": "ribassista", "state": state,
                    "neckline": round(trough[1], 4), "target": round(target, 4),
                    "note": f"Due massimi simili a {h1[1]:.2f} e {h2[1]:.2f}; sotto la rottura di "
                            f"{trough[1]:.2f} l'obiettivo minimo è ~{target:.2f}.",
                })
    if len(swing_lows) >= 2:
        l1, l2 = swing_lows[-2], swing_lows[-1]
        if abs(l1[1] - l2[1]) / l1[1] * 100 <= tolerance_pct:
            between = [h for h in swing_highs if l1[0] < h[0] < l2[0]]
            if between:
                peak = max(between, key=lambda x: x[1])
                height = peak[1] - l1[1]
                target = peak[1] + height
                state = "in formazione"
                if close_last is not None:
                    if close_last > peak[1]:
                        state = "completato"
                    elif close_last < min(l1[1], l2[1]) * 0.99:
                        state = "invalidato"
                findings.append({
                    "pattern": "Doppio minimo", "direction": "rialzista", "state": state,
                    "neckline": round(peak[1], 4), "target": round(target, 4),
                    "note": f"Due minimi simili a {l1[1]:.2f} e {l2[1]:.2f}; sopra la rottura di "
                            f"{peak[1]:.2f} l'obiettivo minimo è ~{target:.2f}.",
                })
    return findings


def detect_triangle(swing_highs, swing_lows, hist: pd.DataFrame, min_points: int = 3) -> dict | None:
    """Triangolo simmetrico/ascendente/discendente, con stato esplicito
    (in formazione finché non c'è break oltre il lato del triangolo)."""
    if len(swing_highs) < min_points or len(swing_lows) < min_points:
        return None
    highs = swing_highs[-min_points:]
    lows = swing_lows[-min_points:]
    h_slope, l_slope = _slope(highs), _slope(lows)
    ref = (highs[-1][1] + lows[-1][1]) / 2 or 1
    flat_thresh = 0.02 * ref / 30

    kind, direction = None, None
    if h_slope < -flat_thresh and l_slope > flat_thresh:
        kind, direction = "Triangolo simmetrico", "da_confermare"
    elif abs(h_slope) <= flat_thresh and l_slope > flat_thresh:
        kind, direction = "Triangolo ascendente", "rialzista"
    elif h_slope < -flat_thresh and abs(l_slope) <= flat_thresh:
        kind, direction = "Triangolo discendente", "ribassista"
    if not kind:
        return None

    base_height = highs[0][1] - lows[0][1]
    target = None
    if direction == "rialzista":
        target = highs[-1][1] + base_height
    elif direction == "ribassista":
        target = lows[-1][1] - base_height

    close_last = _last(hist["Close"])
    state = "in formazione"
    if close_last is not None and direction in ("rialzista", "ribassista"):
        boundary = highs[-1][1] if direction == "rialzista" else lows[-1][1]
        if direction == "rialzista" and close_last > boundary:
            state = "completato"
        elif direction == "ribassista" and close_last < boundary:
            state = "completato"

    return {
        "pattern": kind, "direction": direction, "state": state,
        "target": round(target, 4) if target is not None else None,
        "note": f"{kind}: altezza della base (~{base_height:.2f}) proiettata dal punto di rottura "
                f"per l'obiettivo minimo di prezzo" + (f" (~{target:.2f})." if target is not None else "."),
    }


# ---------------------------------------------------------------------------
# §11 — Motore di sintesi: Directional Score + Agreement Index
# (adattamento — stessa formula di ta_core.py::synthesize, qui su dict
# invece che su dataclass Vote, per uniformità con lo stile del modulo)
# ---------------------------------------------------------------------------

def synthesize_votes(votes: list[dict]) -> dict:
    """Due output DISTINTI, non uno solo (§11):
      - Directional Score D = sum(d*c) / sum(c)          in [-1, +1]
      - Agreement Index   A = |sum(d*c)| / sum(c*|d|)    in [0, 1]
    con un verdetto che distingue 'neutro laterale' da 'conflitto tra
    segnali' (oggi appiattiti in un unico '-0.03 ~ neutro')."""
    if not votes:
        return {"D": 0.0, "A": 0.0, "verdict": "Dati insufficienti", "n_families": 0, "votes": []}

    sum_c = sum(v["c"] for v in votes)
    sum_dc = sum(v["d"] * v["c"] for v in votes)
    sum_c_absd = sum(v["c"] * abs(v["d"]) for v in votes)

    D = sum_dc / sum_c if sum_c > 0 else 0.0
    A = abs(sum_dc) / sum_c_absd if sum_c_absd > 1e-9 else 0.0

    small_D = abs(D) < 0.20
    high_A = A >= 0.60

    if small_D and high_A:
        verdict = "Neutro: mercato senza direzione"
    elif small_D and not high_A:
        verdict = "Conflitto tra segnali: quadro non decidibile"
    elif not small_D and high_A:
        verdict = ("Rialzista" if D > 0 else "Ribassista") + " con buona coerenza"
    else:
        verdict = "Direzione debole e contrastata: cautela"

    return {"D": round(D, 3), "A": round(A, 3), "verdict": verdict, "n_families": len(votes), "votes": votes}


def build_thematic_flags(votes_by_family: dict, snap: dict) -> list[str]:
    """Aggregazione dei segnali che raccontano la stessa storia (§11):
    invece di disperdere stocastico ipercomprato + candela ribassista in
    'neutri' separati, un unico flag tematico."""
    flags = []
    trend_simple = snap.get("trend", "indeterminato")

    momentum_d = votes_by_family.get("Momentum", {}).get("d", 0.0)
    candle_d = votes_by_family.get("Candlestick", {}).get("d", 0.0)

    if trend_simple == "rialzista" and momentum_d < -0.3:
        dettagli = ["oscillatori in ipercomprato"]
        if candle_d < -0.05:
            dettagli.append("segnali candlestick ribassisti recenti")
        flags.append(f"Rischio di pullback di breve termine: {', '.join(dettagli)}, dentro un trend di fondo ancora rialzista.")
    if trend_simple == "ribassista" and momentum_d > 0.3:
        dettagli = ["oscillatori in ipervenduto"]
        if candle_d > 0.05:
            dettagli.append("segnali candlestick rialzisti recenti")
        flags.append(f"Possibile rimbalzo tecnico di breve termine: {', '.join(dettagli)}, dentro un trend di fondo ancora ribassista.")

    if snap.get("rsi_divergence"):
        flags.append(f"Divergenza {snap['rsi_divergence']} tra prezzo e RSI: il momentum si sta indebolendo rispetto al prezzo.")
    vol = snap.get("volume", {})
    if vol.get("divergence"):
        flags.append(f"Divergenza {vol['divergence']} tra prezzo e OBV: il flusso di volume non conferma pienamente il movimento di prezzo.")
    if snap.get("bollinger", {}).get("squeeze"):
        flags.append("Bande di Bollinger in compressione (squeeze): volatilità bassa, spesso precede un movimento più ampio (direzione non indicata).")
    if snap.get("candlestick_conflict"):
        flags.append("Segnali candlestick contrastanti nelle ultime sedute: bassa affidabilità, si annullano a vicenda.")

    return flags


def _build_votes(snap: dict) -> dict:
    """Costruisce i voti (d, c) per ciascuna delle 7 famiglie (§11):
    Trend, Medie, Momentum/Oscillatori, Volume, Pattern, Candlestick,
    Volatilità."""
    votes = {}

    trend = snap["trend_detail"]
    votes["Trend"] = {"family": "Trend", "d": trend["d"], "c": trend["c"]}

    ma = snap["moving_averages"]
    if ma["alignment"] == "rialzista":
        votes["Medie"] = {"family": "Medie", "d": 0.7, "c": 0.7}
    elif ma["alignment"] == "ribassista":
        votes["Medie"] = {"family": "Medie", "d": -0.7, "c": 0.7}
    else:
        votes["Medie"] = {"family": "Medie", "d": 0.0, "c": 0.4 if ma["is_flat"] else 0.3}
    if ma.get("golden_cross"):
        votes["Medie"]["d"] = max(votes["Medie"]["d"], 0.6)
        votes["Medie"]["c"] = max(votes["Medie"]["c"], 0.6)
    if ma.get("death_cross"):
        votes["Medie"]["d"] = min(votes["Medie"]["d"], -0.6)
        votes["Medie"]["c"] = max(votes["Medie"]["c"], 0.6)

    # Momentum/Oscillatori: letti nel CONTESTO del trend (§5) — in trend
    # forte un oscillatore ipercomprato è conferma di forza, non segnale
    # di vendita. Qui costruiamo comunque un voto "grezzo" di estremo, che
    # la sintesi tematica (build_thematic_flags) e la sezione testuale
    # ricontestualizzano esplicitamente.
    mom_parts = []
    rsig = snap.get("rsi_signal")
    if rsig == "ipercomprato_forte":
        mom_parts.append((-0.7, 0.6))
    elif rsig == "ipercomprato":
        mom_parts.append((-0.4, 0.5))
    elif rsig == "ipervenduto_forte":
        mom_parts.append((0.7, 0.6))
    elif rsig == "ipervenduto":
        mom_parts.append((0.4, 0.5))
    else:
        mom_parts.append((0.0, 0.3))

    stoch = snap.get("stochastic") or {}
    k, d = stoch.get("k_val"), stoch.get("d_val")
    if k is not None and d is not None:
        if d >= 80:
            mom_parts.append((-0.4, 0.4))
        elif d <= 20:
            mom_parts.append((0.4, 0.4))
        else:
            mom_parts.append((0.0, 0.2))

    macd_res = snap.get("macd", {})
    if macd_res.get("hist_val") is not None:
        strength = min(1.0, abs(macd_res["hist_val"]) / (abs(macd_res.get("macd_val") or 1) + 1e-9))
        mom_parts.append((0.5 if macd_res["hist_val"] > 0 else -0.5, 0.5))

    wr = snap.get("williams_r")
    if wr is not None:
        if wr >= -20:
            mom_parts.append((-0.3, 0.3))
        elif wr <= -80:
            mom_parts.append((0.3, 0.3))

    sum_c = sum(c for _, c in mom_parts)
    d_mom = sum(dd * c for dd, c in mom_parts) / sum_c if sum_c > 0 else 0.0
    votes["Momentum"] = {"family": "Momentum", "d": round(d_mom, 3), "c": min(0.9, sum_c / max(1, len(mom_parts)) + 0.2)}

    # Volume: conferma del trend se espande nella direzione del trend
    vol = snap.get("volume", {})
    trend_sign = 1 if snap["trend"] == "rialzista" else (-1 if snap["trend"] == "ribassista" else 0)
    if vol.get("volume_trend") == "in espansione" and trend_sign != 0:
        votes["Volume"] = {"family": "Volume", "d": 0.5 * trend_sign, "c": 0.5}
    elif vol.get("volume_trend") == "in contrazione":
        votes["Volume"] = {"family": "Volume", "d": 0.0, "c": 0.2}
    else:
        votes["Volume"] = {"family": "Volume", "d": 0.0, "c": 0.15}

    # Pattern grafici: solo quelli "completati" pesano pieno; "in formazione" pesa poco; "invalidato" escluso
    cp_parts = []
    for cp in snap.get("chart_patterns", []):
        sign = 1 if cp["direction"] == "rialzista" else (-1 if cp["direction"] == "ribassista" else 0)
        if sign == 0 or cp.get("state") == "invalidato":
            continue
        if cp.get("state") == "completato":
            cp_parts.append((0.7 * sign, 0.6))
        else:
            cp_parts.append((0.3 * sign, 0.3))
    if cp_parts:
        sum_c = sum(c for _, c in cp_parts)
        votes["Pattern"] = {"family": "Pattern", "d": round(sum(dd * c for dd, c in cp_parts) / sum_c, 3), "c": min(0.8, sum_c)}
    else:
        votes["Pattern"] = {"family": "Pattern", "d": 0.0, "c": 0.1}

    # Candlestick: dal risultato gia' filtrato (peso*coerenza)
    cs_patterns = snap.get("candlesticks", [])
    if cs_patterns:
        cs_parts = []
        for cs in cs_patterns:
            sign = 1 if cs["direction"] == "rialzista" else (-1 if cs["direction"] == "ribassista" else 0)
            if sign == 0:
                continue
            w = cs.get("weight", 1) + cs.get("coherence", 0)
            cs_parts.append((sign * min(1.0, 0.2 * w), min(0.6, 0.15 * w)))
        if cs_parts:
            sum_c = sum(c for _, c in cs_parts)
            votes["Candlestick"] = {"family": "Candlestick", "d": round(sum(dd * c for dd, c in cs_parts) / sum_c, 3), "c": sum_c}
        else:
            votes["Candlestick"] = {"family": "Candlestick", "d": 0.0, "c": 0.1}
    else:
        votes["Candlestick"] = {"family": "Candlestick", "d": 0.0, "c": 0.1 if not snap.get("candlestick_conflict") else 0.05}

    # Volatilita (Bollinger): principalmente informativa; un %B estremo
    # ha una lieve inclinazione direzionale, non un segnale di inversione.
    pb = snap.get("bollinger", {}).get("percent_b")
    if pb is not None:
        if pb >= 1:
            votes["Volatilità"] = {"family": "Volatilità", "d": 0.2, "c": 0.25}
        elif pb <= 0:
            votes["Volatilità"] = {"family": "Volatilità", "d": -0.2, "c": 0.25}
        else:
            votes["Volatilità"] = {"family": "Volatilità", "d": 0.0, "c": 0.1}
    else:
        votes["Volatilità"] = {"family": "Volatilità", "d": 0.0, "c": 0.05}

    return votes


# ---------------------------------------------------------------------------
# Snapshot completo per orizzonte temporale
# ---------------------------------------------------------------------------

def technical_snapshot(symbol: str, horizon: str = "medio") -> dict | None:
    params = HORIZONS.get(horizon, HORIZONS["medio"])
    hist = dp.get_history(symbol, period=params["period"], interval=params["interval"])
    min_bars = max(30, params["ma"][-1] // 2)
    if hist is None or hist.empty or len(hist) < min_bars:
        return None

    close = hist["Close"]
    price = _last(close)

    trend = analyze_trend(hist, params)
    ma = compute_moving_averages(hist, params["ma"])
    boll = bollinger_bands(hist)

    rsi_series = rsi(close, params["rsi_period"])
    rsi_val = _last(rsi_series)
    rsi_div = detect_rsi_divergence(close, rsi_series)

    stoch = stochastic(hist, *params["stoch"]) if params.get("has_stochastic", True) else None
    macd_res = macd(close)
    wr_series = williams_r(hist)
    atr_series = atr(hist)
    vol = volume_analysis(hist, params["trend_lookback"])

    sr_levels = support_resistance_levels(hist, trend["swing_highs"], trend["swing_lows"], ma,
                                           params.get("sr_lookback_bars"))
    raw_candles = detect_candlestick_patterns(hist, lookback=12)
    candle_result = filter_candlestick_patterns(raw_candles, hist, trend["struct"], sr_levels)

    chart_patterns = list(detect_double_top_bottom(trend["swing_highs"], trend["swing_lows"], hist))
    tri = detect_triangle(trend["swing_highs"], trend["swing_lows"], hist)
    if tri:
        chart_patterns.append(tri)

    atr_val = _last(atr_series)
    support_points = trend["swing_lows"][-6:] if len(trend["swing_lows"]) >= 3 else []
    resistance_points = trend["swing_highs"][-6:] if len(trend["swing_highs"]) >= 3 else []
    support_line = fit_trendline(support_points, "support", hist, atr_val) if support_points else None
    resistance_line = fit_trendline(resistance_points, "resistance", hist, atr_val) if resistance_points else None

    snap = {
        "symbol": symbol, "horizon": horizon, "horizon_label": params["label"],
        "hist": hist, "price": price,
        "trend": trend["verdict_simple"], "trend_detail": trend,
        "swing_highs": trend["swing_highs"], "swing_lows": trend["swing_lows"],
        "moving_averages": ma, "bollinger": boll,
        "rsi": rsi_val, "rsi_signal": rsi_signal(rsi_val), "rsi_series": rsi_series,
        "rsi_divergence": rsi_div,
        "stochastic": stoch, "macd": macd_res,
        "williams_r": _last(wr_series), "williams_r_series": wr_series,
        "atr": atr_val, "atr_series": atr_series,
        "volume": vol,
        "support_resistance": sr_levels,
        "candlesticks": candle_result["patterns"], "candlestick_conflict": candle_result["had_conflict"],
        "chart_patterns": chart_patterns,
        "support_line": support_line, "resistance_line": resistance_line,
    }

    votes_by_family = _build_votes(snap)
    synthesis = synthesize_votes(list(votes_by_family.values()))
    snap["votes_by_family"] = votes_by_family
    snap["synthesis"] = synthesis
    snap["thematic_flags"] = build_thematic_flags(votes_by_family, snap)
    return snap


def technical_score(snap: dict | None) -> float | None:
    """Wrapper retro-compatibile: Directional Score del motore di sintesi
    (§11). Preferire `snap['synthesis']` per l'Agreement Index e il
    verdetto completo — questo resta solo per compatibilità puntuale."""
    if not snap:
        return None
    return snap.get("synthesis", {}).get("D")


# ---------------------------------------------------------------------------
# Sezioni narrative (una per famiglia) e sintesi finale
# ---------------------------------------------------------------------------

VERDICT_LABELS = {"rialzista": "Rialzista", "ribassista": "Ribassista", "laterale": "Laterale", "neutro": "Neutro"}
VERDICT_BADGE_KIND = {"rialzista": "ok", "ribassista": "bad", "laterale": "warn", "neutro": "info"}


def _section_trend(snap: dict) -> dict:
    trend = snap["trend_detail"]
    lines = [
        f"{trend['verdict_label']}: struttura di swing {trend['struct']}, medie mobili allineate in "
        f"ordine {trend['ma_alignment']}."
    ]
    if trend["verdict_simple"] == "rialzista" and "pullback" in trend["verdict_label"]:
        lines.append(
            "Le medie restano allineate al rialzo ma gli ultimi swing mostrano una debolezza di breve: "
            "un ritracciamento dentro il trend, non un'inversione — a meno che la struttura non peggiori ulteriormente."
        )
    elif trend["verdict_simple"] == "ribassista" and "rimbalzo" in trend["verdict_label"]:
        lines.append(
            "Le medie restano allineate al ribasso ma gli ultimi swing mostrano un recupero di breve: "
            "un rimbalzo tecnico dentro il trend ribassista, non necessariamente un'inversione."
        )

    price = snap.get("price")
    sr = snap.get("support_resistance", [])
    sup = nearest_support(sr, price) if price else None
    res = nearest_resistance(sr, price) if price else None
    if sup:
        lines.append(
            f"Il supporto più vicino sotto il prezzo attuale è a {sup['level']:.2f} "
            f"(fonte: {sup['source']}, {sup['touches']} tocchi, robustezza {sup['robustness']:.1f})."
        )
    if res:
        lines.append(
            f"La resistenza più vicina sopra il prezzo attuale è a {res['level']:.2f} "
            f"(fonte: {res['source']}, {res['touches']} tocchi, robustezza {res['robustness']:.1f})."
        )

    for key, label in (("support_line", "di supporto"), ("resistance_line", "di resistenza")):
        line = snap.get(key)
        if line:
            lines.append(f"Trendline {label} confermata da {line['touches']} punti di contatto, validata contro la serie prezzi.")

    verdict = trend["verdict_simple"]
    return {"key": "trend", "icon": "📈", "title": "Trend e struttura del prezzo",
            "verdict": verdict, "text": " ".join(lines)}


def _section_moving_averages(snap: dict) -> dict:
    ma = snap["moving_averages"]
    boll = snap["bollinger"]
    lines = []
    verdict = "neutro"

    if ma.get("alignment") == "rialzista":
        lines.append(
            f"Le medie mobili sono allineate in ordine rialzista: quella a {ma['fast_n']} periodi sta sopra "
            f"quella a {ma['mid_n']}, a sua volta sopra quella a {ma['slow_n']} ({ma['fast_val']:.2f} / "
            f"{ma['mid_val']:.2f} / {ma['slow_val']:.2f})."
        )
        verdict = "rialzista"
    elif ma.get("alignment") == "ribassista":
        lines.append(
            f"Le medie mobili sono allineate in ordine ribassista: quella a {ma['fast_n']} periodi sta sotto "
            f"quella a {ma['mid_n']}, a sua volta sotto quella a {ma['slow_n']} ({ma['fast_val']:.2f} / "
            f"{ma['mid_val']:.2f} / {ma['slow_val']:.2f})."
        )
        verdict = "ribassista"
    elif ma.get("is_flat"):
        lines.append(
            "Le medie mobili sono piatte e intrecciate: un mercato laterale, da non interpretare come un "
            "cambio di trend ad ogni incrocio (whipsaw)."
        )
    else:
        lines.append("Le medie mobili non sono allineate in un ordine chiaro: fase di transizione.")

    if ma.get("golden_cross"):
        lines.append("Nelle ultime sedute la media media ha incrociato al rialzo quella lunga (golden cross).")
        verdict = "rialzista"
    if ma.get("death_cross"):
        lines.append("Nelle ultime sedute la media media ha incrociato al ribasso quella lunga (death cross).")
        verdict = "ribassista"

    pb = boll.get("percent_b")
    if pb is not None:
        if pb >= 1:
            lines.append(
                "Il prezzo è sulla banda superiore di Bollinger o sopra: una condizione di forza che, "
                "dentro un trend rialzista confermato, è più spesso conferma che segnale di vendita."
            )
        elif pb <= 0:
            lines.append("Il prezzo è sulla banda inferiore di Bollinger o sotto: condizione di debolezza.")
        else:
            lines.append(f"Il prezzo è in posizione centrale tra le bande di Bollinger (%B = {pb:.2f}).")
    if boll.get("squeeze"):
        lines.append("Bande di Bollinger in compressione (squeeze): bassa volatilità, spesso precede un nuovo movimento — senza indicarne la direzione.")

    return {"key": "moving_averages", "icon": "📉", "title": "Medie mobili e volatilità",
            "verdict": verdict, "text": " ".join(lines)}


def _section_momentum(snap: dict) -> dict:
    lines = []
    trend_simple = snap.get("trend")
    rsig = snap.get("rsi_signal")
    rsi_val = snap.get("rsi")
    in_strong_trend = snap["trend_detail"]["c"] >= 0.8

    if rsi_val is not None:
        base = f"L'RSI è a {rsi_val:.1f}"
        if rsig in ("ipercomprato", "ipercomprato_forte"):
            if trend_simple == "rialzista" and in_strong_trend:
                lines.append(f"{base}, in ipercomprato — ma dentro un trend rialzista forte questo è più spesso conferma di forza che segnale di vendita imminente.")
            else:
                lines.append(f"{base}, in zona di ipercomprato.")
        elif rsig in ("ipervenduto", "ipervenduto_forte"):
            if trend_simple == "ribassista" and in_strong_trend:
                lines.append(f"{base}, in ipervenduto — dentro un trend ribassista forte può restarci a lungo senza che il trend si inverta.")
            else:
                lines.append(f"{base}, in zona di ipervenduto.")
        else:
            lines.append(f"{base}, in zona neutrale: nessun eccesso evidente.")

    if snap.get("rsi_divergence"):
        lines.append(f"Divergenza {snap['rsi_divergence']} tra prezzo e RSI: il prezzo fa un nuovo estremo che l'RSI non conferma, segnale di indebolimento del momentum.")

    stoch = snap.get("stochastic")
    if stoch and stoch.get("k_val") is not None and stoch.get("d_val") is not None:
        k, d = stoch["k_val"], stoch["d_val"]
        if d >= 80:
            lines.append(f"Lo stocastico (%K {k:.1f} / %D {d:.1f}) è in ipercomprato.")
        elif d <= 20:
            lines.append(f"Lo stocastico (%K {k:.1f} / %D {d:.1f}) è in ipervenduto.")
        else:
            lines.append(f"Lo stocastico (%K {k:.1f} / %D {d:.1f}) è in area neutrale.")

    macd_res = snap.get("macd", {})
    if macd_res.get("hist_val") is not None:
        pos = "sopra" if macd_res["macd_val"] > macd_res["signal_val"] else "sotto"
        lines.append(
            f"Il MACD ha istogramma {'positivo' if macd_res['hist_val'] > 0 else 'negativo'} "
            f"({macd_res['hist_val']:.3f}), linea MACD {pos} il segnale."
        )

    wr = snap.get("williams_r")
    if wr is not None:
        if wr >= -20:
            lines.append(f"Il Williams %R ({wr:.1f}) conferma l'ipercomprato.")
        elif wr <= -80:
            lines.append(f"Il Williams %R ({wr:.1f}) conferma l'ipervenduto.")

    mom_vote = snap.get("votes_by_family", {}).get("Momentum", {})
    d = mom_vote.get("d", 0.0)
    verdict = "rialzista" if d > 0.2 else ("ribassista" if d < -0.2 else "neutro")

    return {"key": "momentum", "icon": "🌊", "title": "Momentum e oscillatori",
            "verdict": verdict, "text": " ".join(lines)}


def _section_volume(snap: dict) -> dict:
    vol = snap.get("volume", {})
    lines = []
    trend_simple = snap.get("trend")

    if vol.get("volume_trend"):
        lines.append(f"Il volume è {vol['volume_trend']} rispetto al periodo precedente.")
        if vol["volume_trend"] == "in espansione" and trend_simple in ("rialzista", "ribassista"):
            lines.append(f"L'espansione di volume conferma il trend {trend_simple} in corso.")
        elif vol["volume_trend"] == "in contrazione":
            lines.append("Un volume in contrazione invita a maggiore cautela sulla tenuta del movimento in corso.")

    if vol.get("divergence"):
        lines.append(f"Divergenza {vol['divergence']} tra prezzo e OBV (On-Balance Volume): il flusso di volume non conferma pienamente il movimento di prezzo — un early warning, non una certezza.")
    if vol.get("volume_spike"):
        lines.append("L'ultima seduta ha un volume nettamente superiore alla media recente: se coincide con una rottura di livello, ne aumenta l'affidabilità.")
    if not lines:
        lines.append("Nessun segnale particolare dal volume in questo momento.")

    vote = snap.get("votes_by_family", {}).get("Volume", {})
    d = vote.get("d", 0.0)
    verdict = "rialzista" if d > 0.15 else ("ribassista" if d < -0.15 else "neutro")
    return {"key": "volume", "icon": "📊", "title": "Volume", "verdict": verdict, "text": " ".join(lines)}


def _section_patterns(snap: dict) -> dict:
    lines = []
    cps = snap.get("chart_patterns", [])
    css = snap.get("candlesticks", [])

    if not cps and not css and not snap.get("candlestick_conflict"):
        lines.append(
            "Non emergono figure grafiche (doppi massimi/minimi, triangoli) né candele particolarmente "
            "significative nell'orizzonte selezionato: non è un'anomalia, la maggior parte delle sedute "
            "non produce pattern netti."
        )
        return {"key": "patterns", "icon": "🕯️", "title": "Pattern grafici e candlestick",
                "verdict": "neutro", "text": " ".join(lines)}

    for cp in cps:
        lines.append(f"Figura di tipo {cp['pattern'].lower()} ({cp['state']}): {cp['note']}")
    if snap.get("candlestick_conflict") and not css:
        lines.append("Segnali candlestick contrastanti nelle ultime sedute: si annullano a vicenda, bassa affidabilità.")
    for cs in css:
        lines.append(f"Candela del {cs['date'].strftime('%d/%m')}: {cs['pattern']} — {cs['note']}")

    pattern_d = snap.get("votes_by_family", {}).get("Pattern", {}).get("d", 0.0)
    candle_d = snap.get("votes_by_family", {}).get("Candlestick", {}).get("d", 0.0)
    combined = pattern_d + candle_d
    verdict = "rialzista" if combined > 0.15 else ("ribassista" if combined < -0.15 else "neutro")

    return {"key": "patterns", "icon": "🕯️", "title": "Pattern grafici e candlestick",
            "verdict": verdict, "text": " ".join(lines)}


def _write_synthesis(snap: dict, sections: list[dict], entry_price: float | None = None) -> str:
    """Sintesi finale basata sul Directional Score + Agreement Index
    (§11), non sul conteggio dei verdetti di sezione: distingue "neutro
    per assenza di direzione" da "conflitto tra segnali"."""
    synthesis = snap["synthesis"]
    D, A, verdict = synthesis["D"], synthesis["A"], synthesis["verdict"]

    lines = [
        f"Directional Score: {D:+.2f} (da -1 fortemente ribassista a +1 fortemente rialzista) · "
        f"Agreement Index: {A:.2f} (0 = famiglie in conflitto, 1 = pienamente allineate). {verdict}."
    ]

    for flag in snap.get("thematic_flags", []):
        lines.append(flag)

    sr = snap.get("support_resistance", [])
    price = snap.get("price")
    watch = []
    sup = nearest_support(sr, price) if price else None
    res = nearest_resistance(sr, price) if price else None
    if sup:
        watch.append(f"la tenuta del supporto a {sup['level']:.2f}")
    if res:
        watch.append(f"un'eventuale rottura della resistenza a {res['level']:.2f}")
    if watch:
        lines.append("I livelli da monitorare per capire se questo quadro cambia sono " + " e ".join(watch) + ".")

    if entry_price:
        ctx = entry_context(snap, entry_price)
        if ctx:
            extra = " ".join(ctx["notes"][1:]) if len(ctx["notes"]) > 1 else "nessuna nota aggiuntiva in questo momento."
            lines.append(
                f"Rispetto al tuo prezzo di riferimento ({entry_price:.2f}), sei "
                f"{'sopra' if ctx['pl_pct'] >= 0 else 'sotto'} del {abs(ctx['pl_pct']):.1f}%: {extra}"
            )

    lines.append("Resta un quadro statistico basato su dati passati, non una previsione né una raccomandazione operativa.")
    return " ".join(lines)


def build_narrative(snap: dict | None, entry_price: float | None = None) -> dict | None:
    """Analisi sezionata in stile 'report': una sezione per famiglia
    (trend, medie/volatilità, momentum, volume, pattern/candlestick), più
    una sintesi finale basata su Directional Score + Agreement Index."""
    if not snap:
        return None
    sections = [
        _section_trend(snap),
        _section_moving_averages(snap),
        _section_momentum(snap),
        _section_volume(snap),
        _section_patterns(snap),
    ]
    return {"sections": sections, "synthesis": _write_synthesis(snap, sections, entry_price)}


def interpret(snap: dict | None) -> list[str]:
    """Dettaglio testuale piatto (compatibilità con usi puntuali): estrae
    le righe di testo di tutte le sezioni."""
    narrative = build_narrative(snap)
    if not narrative:
        return []
    lines = []
    for sec in narrative["sections"]:
        lines.append(sec["text"])
    return lines


def chart_shapes(snap: dict) -> tuple[list, list]:
    """Shapes/annotations Plotly per disegnare trendlines, livelli di
    supporto/resistenza e marker delle candele direttamente sul grafico."""
    shapes, annotations = [], []
    hist = snap["hist"]
    x_start, x_end = hist.index[0], hist.index[-1]

    for lvl in snap.get("support_resistance", []):
        color = "#1E8E5A" if lvl["role"] == "supporto" else "#C0392B"
        width = 1 if lvl["source"] != "swing" else max(1, min(3, round(lvl["robustness"] / 2)))
        shapes.append(dict(type="line", x0=x_start, x1=x_end, y0=lvl["level"], y1=lvl["level"],
                            line=dict(color=color, width=width, dash="dot")))

    for line_key, color in (("support_line", "#1E8E5A"), ("resistance_line", "#C0392B")):
        line = snap.get(line_key)
        if line:
            shapes.append(dict(type="line", x0=x_start, x1=x_end,
                                y0=_trendline_y(line, x_start), y1=_trendline_y(line, x_end),
                                line=dict(color=color, width=1.5)))

    for cs in snap.get("candlesticks", []):
        if cs["date"] not in hist.index:
            continue
        if cs["direction"] == "rialzista":
            y = float(hist.loc[cs["date"], "Low"]) * 0.985
            arrow_color = "#1E8E5A"
        elif cs["direction"] == "ribassista":
            y = float(hist.loc[cs["date"], "High"]) * 1.015
            arrow_color = "#C0392B"
        else:
            y = float(hist.loc[cs["date"], "High"]) * 1.01
            arrow_color = "#6B7280"
        annotations.append(dict(x=cs["date"], y=y, text=cs["pattern"], showarrow=True,
                                 arrowhead=1, arrowcolor=arrow_color, font=dict(size=9, color=arrow_color)))

    return shapes, annotations


def entry_context(snap: dict | None, entry_price: float | None) -> dict | None:
    """Contestualizza uno snapshot tecnico rispetto a un prezzo di
    ingresso — il prezzo medio di carico reale (da un titolo in
    portafoglio) o un prezzo di riferimento pianificato (da un titolo in
    Preferiti non ancora comprato). Le note restano descrittive/statistiche."""
    if not snap or not entry_price or entry_price <= 0 or snap.get("price") is None:
        return None

    price = snap["price"]
    pl_pct = (price - entry_price) / entry_price * 100
    notes = [f"Sei {'sopra' if pl_pct >= 0 else 'sotto'} il prezzo di riferimento ({entry_price:.2f}) del {pl_pct:+.1f}%."]

    rsig = snap.get("rsi_signal")
    if pl_pct > 0 and rsig in ("ipercomprato", "ipercomprato_forte"):
        notes.append("Il titolo è in ipercomprato mentre sei in guadagno: in questa condizione alcuni investitori valutano una presa di profitto parziale, da soppesare col proprio orizzonte.")
    if pl_pct < 0 and rsig in ("ipervenduto", "ipervenduto_forte"):
        notes.append("Il titolo è in ipervenduto mentre sei in perdita: storicamente è una zona dove il ribasso rallenta più spesso, ma non è garanzia di un'inversione.")
    if pl_pct < 0 and snap.get("trend") == "ribassista":
        notes.append("Il trend resta ribassista: nessun segnale tecnico di inversione rilevato per ora.")
    if pl_pct > 0 and snap.get("trend") == "rialzista":
        notes.append("Il trend resta rialzista e coerente con la tua posizione in guadagno.")
    if pl_pct > 0 and snap.get("trend") == "ribassista":
        notes.append("Sei ancora in guadagno ma il trend è girato ribassista: una situazione da monitorare.")
    if pl_pct < 0 and snap.get("trend") == "rialzista":
        notes.append("Sei in perdita ma il trend è rialzista: il ribasso recente potrebbe essere una correzione entro un trend più ampio.")

    for lvl in snap.get("support_resistance", []):
        if lvl["role"] == "supporto" and price > lvl["level"]:
            dist = (price - lvl["level"]) / price * 100
            if dist < 5:
                notes.append(f"Sei vicino (~{dist:.1f}%) a un supporto a {lvl['level']:.2f}.")
        if lvl["role"] == "resistenza" and price < lvl["level"]:
            dist = (lvl["level"] - price) / price * 100
            if dist < 5:
                notes.append(f"Sei vicino (~{dist:.1f}%) a una resistenza a {lvl['level']:.2f}.")

    return {"entry_price": entry_price, "price": price, "pl_pct": pl_pct, "notes": notes}


def numeric_summary(snap: dict) -> list[tuple[str, str]]:
    """Elenco (etichetta, valore) di tutti i numeri calcolati."""
    if not snap:
        return []
    sr = snap.get("support_resistance", [])
    supports = sorted(l["level"] for l in sr if l["role"] == "supporto")
    resistances = sorted(l["level"] for l in sr if l["role"] == "resistenza")
    ma = snap["moving_averages"]
    boll = snap["bollinger"]
    stoch = snap.get("stochastic") or {}
    macd_res = snap["macd"]

    def _fmt(x, decimals=2):
        return f"{x:.{decimals}f}" if x is not None else "n/d"

    rows = [
        ("Supporti", ", ".join(f"{s:.2f}" for s in supports) or "n/d"),
        ("Resistenze", ", ".join(f"{r:.2f}" for r in resistances) or "n/d"),
        (f"Media mobile ({ma['fast_n']})", _fmt(ma.get("fast_val"))),
        (f"Media mobile ({ma['mid_n']})", _fmt(ma.get("mid_val"))),
        (f"Media mobile ({ma['slow_n']})", _fmt(ma.get("slow_val"))),
        ("Bollinger — banda superiore", _fmt(boll.get("upper_val"))),
        ("Bollinger — mediana (20)", _fmt(boll.get("mid_val"))),
        ("Bollinger — banda inferiore", _fmt(boll.get("lower_val"))),
        ("Bollinger — %B", _fmt(boll.get("percent_b"))),
        ("RSI", _fmt(snap.get("rsi"), 1)),
        ("Stocastico %K", _fmt(stoch.get("k_val"), 1)),
        ("Stocastico %D", _fmt(stoch.get("d_val"), 1)),
        ("MACD", _fmt(macd_res.get("macd_val"), 3)),
        ("Segnale MACD", _fmt(macd_res.get("signal_val"), 3)),
        ("Istogramma MACD", _fmt(macd_res.get("hist_val"), 3)),
        ("Williams %R", _fmt(snap.get("williams_r"), 1)),
        ("ATR (volatilità media)", _fmt(snap.get("atr"))),
        ("OBV", _fmt(snap.get("volume", {}).get("obv_val"), 0)),
        ("Directional Score", _fmt(snap.get("synthesis", {}).get("D"), 2)),
        ("Agreement Index", _fmt(snap.get("synthesis", {}).get("A"), 2)),
    ]
    for cp in snap.get("chart_patterns", []):
        if cp.get("target") is not None:
            rows.append((f"Obiettivo di prezzo — {cp['pattern']} ({cp['state']})", f"{cp['target']:.2f}"))
    return rows


def trade_plan(snap: dict | None) -> dict | None:
    """Piano operativo (§13): ingresso/stop/target su livelli oggettivi
    (S/R, ATR, obiettivi di figura). Si rifiuta di produrre un piano
    quando il quadro non è direzionale (|D| basso o A basso) — la
    disciplina esplicitamente richiesta dalla specifica, non solo quando
    lo score puntuale è vicino a zero come prima."""
    if not snap or snap.get("price") is None or not snap.get("atr"):
        return None

    price = snap["price"]
    atr_val = snap["atr"]
    synthesis = snap["synthesis"]
    D, A = synthesis["D"], synthesis["A"]

    if abs(D) < 0.20 or A < 0.45:
        return {"bias": "nessun_setup", "D": D, "A": A, "atr": atr_val, "price": price,
                "reason": synthesis["verdict"]}

    sr = snap.get("support_resistance", [])
    supports = sorted((l["level"] for l in sr if l["role"] == "supporto" and l["level"] < price), reverse=True)
    resistances = sorted(l["level"] for l in sr if l["role"] == "resistenza" and l["level"] > price)
    up_targets = sorted(cp["target"] for cp in snap.get("chart_patterns", [])
                         if cp.get("target") and cp["direction"] == "rialzista" and cp["target"] > price
                         and cp.get("state") != "invalidato")
    down_targets = sorted((cp["target"] for cp in snap.get("chart_patterns", [])
                            if cp.get("target") and cp["direction"] == "ribassista" and cp["target"] < price
                            and cp.get("state") != "invalidato"), reverse=True)

    bias = "long" if D > 0 else "short"

    if bias == "long":
        nearest_sup = supports[0] if supports else None
        if nearest_sup is not None and (price - nearest_sup) <= 3 * atr_val:
            stop = nearest_sup - 0.5 * atr_val
            stop_basis = f"leggermente sotto il supporto più vicino ({nearest_sup:.2f})"
        else:
            stop = price - 1.5 * atr_val
            stop_basis = "1,5 volte l'ATR sotto il prezzo attuale (nessun supporto vicino)"
        candidates = resistances[:1] + up_targets[:1]
        target = min(candidates) if candidates else price + 2 * atr_val
        target_basis = "la resistenza o l'obiettivo di figura più vicino" if candidates else "2 volte l'ATR sopra il prezzo (nessun livello vicino)"
        risk = price - stop
        reward = target - price
    else:
        nearest_res = resistances[0] if resistances else None
        if nearest_res is not None and (nearest_res - price) <= 3 * atr_val:
            stop = nearest_res + 0.5 * atr_val
            stop_basis = f"leggermente sopra la resistenza più vicina ({nearest_res:.2f})"
        else:
            stop = price + 1.5 * atr_val
            stop_basis = "1,5 volte l'ATR sopra il prezzo attuale (nessuna resistenza vicina)"
        candidates = supports[:1] + down_targets[:1]
        target = max(candidates) if candidates else price - 2 * atr_val
        target_basis = "il supporto o l'obiettivo di figura più vicino" if candidates else "2 volte l'ATR sotto il prezzo (nessun livello vicino)"
        risk = stop - price
        reward = price - target

    rr = (reward / risk) if risk and risk > 0 else None
    rr_unfavorable = bool(rr is not None and rr < 1.5)

    return {
        "bias": bias, "D": D, "A": A, "atr": atr_val, "price": price,
        "entry": price, "stop": round(stop, 4), "target": round(target, 4),
        "stop_basis": stop_basis, "target_basis": target_basis,
        "risk": round(risk, 4) if risk else None, "reward": round(reward, 4) if reward else None,
        "risk_reward": round(rr, 2) if rr else None, "rr_unfavorable": rr_unfavorable,
    }


def multi_horizon_analysis(symbol: str) -> dict:
    """Analisi sui tre orizzonti temporali in un'unica chiamata."""
    out = {}
    for h in HORIZONS:
        snap = technical_snapshot(symbol, h)
        out[h] = {
            "snapshot": snap,
            "synthesis": snap.get("synthesis") if snap else None,
            "interpretation": interpret(snap),
        }
    return out
