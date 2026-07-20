"""
Analisi tecnica: trend, supporti/resistenze e trendlines, medie mobili e
bande di Bollinger, oscillatori (RSI, Stocastico, MACD, Williams %R),
pattern di candlestick giapponesi e figure di prezzo con relativi obiettivi
di misurazione.

Metodologia e parametri standard (RSI a 14 periodi con soglie 70/30,
Stocastico 14/3/3 con soglie 80/20, MACD 12/26/9, Bollinger 20 periodi a 2
deviazioni standard, tecniche di misurazione delle figure grafiche come
altezza-proiettata-dalla-rottura) derivano da John J. Murphy, "Analisi
tecnica dei mercati finanziari" — qui reimplementati come regole di calcolo,
non riportati come testo del manuale.

Tre orizzonti temporali (breve/medio/lungo) usano periodo dati e parametri
diversi, secondo l'indicazione del manuale di accorciare gli oscillatori per
il trading di breve periodo e allungarli/applicarli su base settimanale per
l'investimento di lungo periodo.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src import data_provider as dp

HORIZONS = {
    "breve": {
        "label": "Breve termine (trading)",
        "period": "3mo", "interval": "1d",
        "rsi_period": 9, "stoch_k": 14, "stoch_d": 3, "stoch_smooth": 3,
        "ma_fast": 4, "ma_mid": 9, "ma_slow": 18,
        "swing_order": 2,
    },
    "medio": {
        "label": "Medio termine (posizionamento)",
        "period": "1y", "interval": "1d",
        "rsi_period": 14, "stoch_k": 14, "stoch_d": 3, "stoch_smooth": 3,
        "ma_fast": 20, "ma_mid": 50, "ma_slow": 200,
        "swing_order": 4,
    },
    "lungo": {
        "label": "Lungo termine (investimento)",
        "period": "5y", "interval": "1wk",
        "rsi_period": 14, "stoch_k": 14, "stoch_d": 3, "stoch_smooth": 3,
        "ma_fast": 20, "ma_mid": 50, "ma_slow": 200,
        "swing_order": 4,
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _last(series: pd.Series):
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


# ---------------------------------------------------------------------------
# Medie mobili e bande di Bollinger (cap. 9)
# ---------------------------------------------------------------------------

def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def compute_moving_averages(hist: pd.DataFrame, params: dict) -> dict:
    close = hist["Close"]
    fast = sma(close, params["ma_fast"])
    mid = sma(close, params["ma_mid"])
    slow = sma(close, params["ma_slow"])
    fast_val, mid_val, slow_val = _last(fast), _last(mid), _last(slow)

    alignment = None
    if fast_val is not None and mid_val is not None and slow_val is not None:
        if fast_val > mid_val > slow_val:
            alignment = "rialzista"
        elif fast_val < mid_val < slow_val:
            alignment = "ribassista"
        else:
            alignment = "misto"

    cross = _recent_cross(mid, slow)
    return {
        "fast": fast, "mid": mid, "slow": slow,
        "fast_val": fast_val, "mid_val": mid_val, "slow_val": slow_val,
        "alignment": alignment,
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
# Oscillatori (cap. 10)
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
    """Soglie standard 70/30; 80/20 nei mercati con trend molto forte
    (qui usate come soglie 'forte' addizionali)."""
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


# ---------------------------------------------------------------------------
# Trend, supporti/resistenze, trendlines (cap. 4)
# ---------------------------------------------------------------------------

def find_swing_points(hist: pd.DataFrame, order: int = 4):
    """Massimi/minimi locali: un punto è uno swing high/low se è
    l'estremo tra `order` barre prima e dopo. Base per trendlines, S/R e
    riconoscimento delle figure di prezzo."""
    highs, lows = hist["High"], hist["Low"]
    swing_highs, swing_lows = [], []
    n = len(hist)
    for i in range(order, n - order):
        wh = highs.iloc[i - order:i + order + 1]
        wl = lows.iloc[i - order:i + order + 1]
        if highs.iloc[i] == wh.max() and (wh == highs.iloc[i]).sum() == 1:
            swing_highs.append((hist.index[i], float(highs.iloc[i])))
        if lows.iloc[i] == wl.min() and (wl == lows.iloc[i]).sum() == 1:
            swing_lows.append((hist.index[i], float(lows.iloc[i])))
    return swing_highs, swing_lows


def detect_trend(swing_highs, swing_lows) -> str:
    """Massimi e minimi crescenti = rialzista; decrescenti = ribassista;
    altrimenti laterale (concetto base del cap. 4)."""
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return "indeterminato"
    hh = swing_highs[-1][1] > swing_highs[-2][1]
    hl = swing_lows[-1][1] > swing_lows[-2][1]
    lh = swing_highs[-1][1] < swing_highs[-2][1]
    ll = swing_lows[-1][1] < swing_lows[-2][1]
    if hh and hl:
        return "rialzista"
    if lh and ll:
        return "ribassista"
    return "laterale"


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


def fit_trendline(points) -> dict | None:
    """Regressione lineare sui punti (data, prezzo). Servono almeno 2
    punti per tracciarla; il manuale raccomanda un terzo tocco per
    considerarla confermata (qui esposto come `touches`)."""
    if len(points) < 2:
        return None
    x0 = points[0][0]
    xs = np.array([(p[0] - x0).total_seconds() / 86400 for p in points])
    ys = np.array([p[1] for p in points], dtype=float)
    slope, intercept = np.polyfit(xs, ys, 1)
    return {"slope": float(slope), "intercept": float(intercept), "x0": x0,
            "touches": len(points), "confirmed": len(points) >= 3, "points": points}


def _trendline_y(line: dict, x) -> float:
    days = (x - line["x0"]).total_seconds() / 86400
    return line["slope"] * days + line["intercept"]


def support_resistance_levels(hist: pd.DataFrame, swing_highs, swing_lows,
                               tolerance_pct: float = 1.5, max_levels: int = 4) -> list[dict]:
    """Raggruppa gli estremi locali entro `tolerance_pct` per trovare
    livelli orizzontali toccati più volte: più tocchi, più significativo
    il livello di supporto/resistenza."""
    all_points = sorted([p for _, p in swing_highs] + [p for _, p in swing_lows])
    if not all_points:
        return []
    clusters = []
    for p in all_points:
        placed = False
        for c in clusters:
            if abs(p - c["mean"]) / c["mean"] * 100 <= tolerance_pct:
                c["values"].append(p)
                c["mean"] = sum(c["values"]) / len(c["values"])
                placed = True
                break
        if not placed:
            clusters.append({"mean": p, "values": [p]})
    clusters = [c for c in clusters if len(c["values"]) >= 2]
    clusters.sort(key=lambda c: -len(c["values"]))

    current_price = _last(hist["Close"])
    out = []
    for c in clusters[:max_levels]:
        role = "resistenza" if current_price and c["mean"] > current_price else "supporto"
        out.append({"level": round(c["mean"], 4), "touches": len(c["values"]), "role": role})
    out.sort(key=lambda c: c["level"])
    return out


# ---------------------------------------------------------------------------
# Pattern di candlestick giapponesi (cap. 12) — formazioni a 1/2/3 candele
# tra le più codificabili in modo oggettivo da dati OHLC.
# ---------------------------------------------------------------------------

def _candle(row) -> dict:
    o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
    body = abs(c - o)
    rng = (h - l) or 1e-9
    return {
        "o": o, "h": h, "l": l, "c": c, "body": body, "range": rng,
        "upper_shadow": h - max(o, c), "lower_shadow": min(o, c) - l,
        "bullish": c > o, "bearish": c < o,
    }


def detect_candlestick_patterns(hist: pd.DataFrame, lookback: int = 8) -> list[dict]:
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


# ---------------------------------------------------------------------------
# Figure di prezzo con obiettivi di misurazione (cap. 5-6)
# ---------------------------------------------------------------------------

def detect_double_top_bottom(swing_highs, swing_lows, tolerance_pct: float = 3.0) -> list[dict]:
    """Doppio massimo/minimo: due estremi simili con un ritracciamento
    significativo tra i due. Obiettivo di prezzo = altezza della figura
    proiettata dal punto di rottura (cap. 5.9.1)."""
    findings = []
    if len(swing_highs) >= 2:
        h1, h2 = swing_highs[-2], swing_highs[-1]
        if abs(h1[1] - h2[1]) / h1[1] * 100 <= tolerance_pct:
            between = [l for l in swing_lows if h1[0] < l[0] < h2[0]]
            if between:
                trough = min(between, key=lambda x: x[1])
                height = h1[1] - trough[1]
                target = trough[1] - height
                findings.append({
                    "pattern": "Doppio massimo (potenziale)", "direction": "ribassista",
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
                findings.append({
                    "pattern": "Doppio minimo (potenziale)", "direction": "rialzista",
                    "neckline": round(peak[1], 4), "target": round(target, 4),
                    "note": f"Due minimi simili a {l1[1]:.2f} e {l2[1]:.2f}; sopra la rottura di "
                            f"{peak[1]:.2f} l'obiettivo minimo è ~{target:.2f}.",
                })
    return findings


def detect_triangle(swing_highs, swing_lows, min_points: int = 3) -> dict | None:
    """Triangolo simmetrico/ascendente/discendente dall'inclinazione delle
    ultime `min_points` coppie di massimi/minimi. Obiettivo di prezzo =
    altezza della base proiettata dal punto di rottura (cap. 6.23)."""
    if len(swing_highs) < min_points or len(swing_lows) < min_points:
        return None
    highs = swing_highs[-min_points:]
    lows = swing_lows[-min_points:]
    h_slope, l_slope = _slope(highs), _slope(lows)
    ref = (highs[-1][1] + lows[-1][1]) / 2 or 1
    flat_thresh = 0.02 * ref / 30  # inclinazione trascurabile ~ entro 2%/mese

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

    return {
        "pattern": kind, "direction": direction,
        "target": round(target, 4) if target is not None else None,
        "note": f"{kind}: altezza della base (~{base_height:.2f}) proiettata dal punto di rottura "
                f"per l'obiettivo minimo di prezzo" + (f" (~{target:.2f})." if target is not None else "."),
    }


# ---------------------------------------------------------------------------
# Snapshot completo per orizzonte temporale
# ---------------------------------------------------------------------------

def technical_snapshot(symbol: str, horizon: str = "medio") -> dict | None:
    params = HORIZONS.get(horizon, HORIZONS["medio"])
    hist = dp.get_history(symbol, period=params["period"], interval=params["interval"])
    if hist is None or hist.empty or len(hist) < max(30, params["ma_slow"] // 2):
        return None

    close = hist["Close"]
    price = _last(close)

    swing_highs, swing_lows = find_swing_points(hist, order=params["swing_order"])
    trend = detect_trend(swing_highs, swing_lows)

    mov_avg = compute_moving_averages(hist, params)
    boll = bollinger_bands(hist)
    rsi_series = rsi(close, params["rsi_period"])
    rsi_val = _last(rsi_series)
    stoch = stochastic(hist, params["stoch_k"], params["stoch_d"], params["stoch_smooth"])
    macd_res = macd(close)
    wr_series = williams_r(hist)

    sr_levels = support_resistance_levels(hist, swing_highs, swing_lows)
    candlesticks = detect_candlestick_patterns(hist, lookback=8)

    chart_patterns = list(detect_double_top_bottom(swing_highs, swing_lows))
    tri = detect_triangle(swing_highs, swing_lows)
    if tri:
        chart_patterns.append(tri)

    support_line = fit_trendline(swing_lows[-4:]) if len(swing_lows) >= 2 else None
    resistance_line = fit_trendline(swing_highs[-4:]) if len(swing_highs) >= 2 else None

    return {
        "symbol": symbol, "horizon": horizon, "horizon_label": params["label"],
        "hist": hist, "price": price,
        "trend": trend,
        "swing_highs": swing_highs, "swing_lows": swing_lows,
        "moving_averages": mov_avg, "bollinger": boll,
        "rsi": rsi_val, "rsi_signal": rsi_signal(rsi_val), "rsi_series": rsi_series,
        "stochastic": stoch, "macd": macd_res,
        "williams_r": _last(wr_series), "williams_r_series": wr_series,
        "support_resistance": sr_levels,
        "candlesticks": candlesticks,
        "chart_patterns": chart_patterns,
        "support_line": support_line, "resistance_line": resistance_line,
    }


def technical_score(snap: dict | None) -> float | None:
    """Punteggio sintetico da -1 (segnali ribassisti) a +1 (segnali
    rialzisti), media dei contributi di trend, medie mobili, oscillatori,
    Bollinger, candele e figure di prezzo recenti."""
    if not snap:
        return None
    parts = []

    if snap["trend"] == "rialzista":
        parts.append(0.8)
    elif snap["trend"] == "ribassista":
        parts.append(-0.8)
    elif snap["trend"] == "laterale":
        parts.append(0.0)

    ma = snap["moving_averages"]
    if ma.get("alignment") == "rialzista":
        parts.append(0.6)
    elif ma.get("alignment") == "ribassista":
        parts.append(-0.6)
    if ma.get("golden_cross"):
        parts.append(0.7)
    if ma.get("death_cross"):
        parts.append(-0.7)

    rsig = snap.get("rsi_signal")
    if rsig == "ipercomprato_forte":
        parts.append(-0.6)
    elif rsig == "ipercomprato":
        parts.append(-0.3)
    elif rsig == "ipervenduto_forte":
        parts.append(0.6)
    elif rsig == "ipervenduto":
        parts.append(0.3)

    stoch = snap.get("stochastic", {})
    k, d = stoch.get("k_val"), stoch.get("d_val")
    if k is not None and d is not None:
        if d >= 80 and k < d:
            parts.append(-0.4)
        elif d <= 20 and k > d:
            parts.append(0.4)

    macd_res = snap.get("macd", {})
    if macd_res.get("hist_val") is not None:
        parts.append(0.4 if macd_res["hist_val"] > 0 else -0.4)

    pb = snap.get("bollinger", {}).get("percent_b")
    if pb is not None:
        if pb >= 1:
            parts.append(-0.3)
        elif pb <= 0:
            parts.append(0.3)

    for cs in snap.get("candlesticks", [])[-3:]:
        if cs["direction"] == "rialzista":
            parts.append(0.3)
        elif cs["direction"] == "ribassista":
            parts.append(-0.3)

    for cp in snap.get("chart_patterns", []):
        if cp["direction"] == "rialzista":
            parts.append(0.5)
        elif cp["direction"] == "ribassista":
            parts.append(-0.5)

    if not parts:
        return None
    return max(-1.0, min(1.0, sum(parts) / len(parts)))


def interpret(snap: dict | None) -> list[str]:
    """Dettaglio testuale (il 'perché') dietro il punteggio tecnico."""
    if not snap:
        return []
    lines = [f"Trend {snap['horizon_label'].lower()}: {snap['trend']} "
             f"(massimi/minimi crescenti o decrescenti)."]

    ma = snap["moving_averages"]
    if ma.get("alignment") and None not in (ma.get("fast_val"), ma.get("mid_val"), ma.get("slow_val")):
        lines.append(f"Medie mobili: allineamento {ma['alignment']} "
                      f"({ma['fast_val']:.2f} / {ma['mid_val']:.2f} / {ma['slow_val']:.2f}).")
    if ma.get("golden_cross"):
        lines.append("Incrocio rialzista recente tra media media e media lunga (golden cross).")
    if ma.get("death_cross"):
        lines.append("Incrocio ribassista recente tra media media e media lunga (death cross).")

    if snap.get("rsi") is not None:
        lines.append(f"RSI: {snap['rsi']:.1f} — {snap['rsi_signal']} (ipercomprato >70, ipervenduto <30).")

    stoch = snap["stochastic"]
    if stoch.get("k_val") is not None and stoch.get("d_val") is not None:
        lines.append(f"Stocastico %K/%D: {stoch['k_val']:.1f} / {stoch['d_val']:.1f} (soglie 80/20).")

    macd_res = snap["macd"]
    if macd_res.get("hist_val") is not None and macd_res.get("macd_val") is not None:
        pos = "sopra" if macd_res["macd_val"] > macd_res["signal_val"] else "sotto"
        lines.append(f"MACD: istogramma {'positivo' if macd_res['hist_val'] > 0 else 'negativo'} "
                      f"({macd_res['hist_val']:.3f}), linea MACD {pos} il segnale.")

    boll = snap["bollinger"]
    if boll.get("percent_b") is not None:
        posizione = ("vicino/oltre la banda superiore" if boll["percent_b"] >= 0.8
                      else "vicino/oltre la banda inferiore" if boll["percent_b"] <= 0.2 else "centrale")
        extra = " Bande in compressione: possibile nuovo movimento in arrivo." if boll.get("squeeze") else ""
        lines.append(f"Bande di Bollinger: %B = {boll['percent_b']:.2f} ({posizione}).{extra}")

    for lvl in snap.get("support_resistance", []):
        lines.append(f"{lvl['role'].capitalize()} a {lvl['level']:.2f} ({lvl['touches']} tocchi).")

    for cs in snap.get("candlesticks", [])[-3:]:
        lines.append(f"Candela {cs['date'].strftime('%d/%m')}: {cs['pattern']} — {cs['note']}")

    for cp in snap.get("chart_patterns", []):
        lines.append(f"Figura di prezzo: {cp['pattern']} — {cp['note']}")

    return lines


def chart_shapes(snap: dict) -> tuple[list, list]:
    """Shapes/annotations Plotly per disegnare trendlines, livelli di
    supporto/resistenza e marker delle candele direttamente sul grafico
    prezzo — la resa concreta del 'disegnare sul grafico'."""
    shapes, annotations = [], []
    hist = snap["hist"]
    x_start, x_end = hist.index[0], hist.index[-1]

    for lvl in snap.get("support_resistance", []):
        color = "#1E8E5A" if lvl["role"] == "supporto" else "#C0392B"
        shapes.append(dict(type="line", x0=x_start, x1=x_end, y0=lvl["level"], y1=lvl["level"],
                            line=dict(color=color, width=1, dash="dot")))

    for line_key, color in (("support_line", "#1E8E5A"), ("resistance_line", "#C0392B")):
        line = snap.get(line_key)
        if line:
            shapes.append(dict(type="line", x0=x_start, x1=x_end,
                                y0=_trendline_y(line, x_start), y1=_trendline_y(line, x_end),
                                line=dict(color=color, width=1.5)))

    for cs in snap.get("candlesticks", []):
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
    Preferiti non ancora comprato). Le note restano descrittive/statistiche,
    non indicazioni operative dirette."""
    if not snap or not entry_price or entry_price <= 0 or snap.get("price") is None:
        return None

    price = snap["price"]
    pl_pct = (price - entry_price) / entry_price * 100
    notes = []
    notes.append(
        f"Sei {'sopra' if pl_pct >= 0 else 'sotto'} il prezzo di riferimento "
        f"({entry_price:.2f}) del {pl_pct:+.1f}%."
    )

    rsig = snap.get("rsi_signal")
    if pl_pct > 0 and rsig in ("ipercomprato", "ipercomprato_forte"):
        notes.append(
            "Il titolo è in ipercomprato mentre sei in guadagno: in questa condizione alcuni "
            "investitori valutano una presa di profitto parziale, da soppesare col proprio orizzonte."
        )
    if pl_pct < 0 and rsig in ("ipervenduto", "ipervenduto_forte"):
        notes.append(
            "Il titolo è in ipervenduto mentre sei in perdita: storicamente è una zona dove il "
            "ribasso rallenta più spesso, ma non è garanzia di un'inversione."
        )
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
                notes.append(
                    f"Sei vicino (~{dist:.1f}%) a un supporto a {lvl['level']:.2f}: livello spesso "
                    "osservato come area di tenuta del prezzo."
                )
        if lvl["role"] == "resistenza" and price < lvl["level"]:
            dist = (lvl["level"] - price) / price * 100
            if dist < 5:
                notes.append(
                    f"Sei vicino (~{dist:.1f}%) a una resistenza a {lvl['level']:.2f}: livello spesso "
                    "osservato come area di freno del prezzo."
                )

    return {"entry_price": entry_price, "price": price, "pl_pct": pl_pct, "notes": notes}


VERDICT_LABELS = {"rialzista": "Rialzista", "ribassista": "Ribassista", "neutro": "Neutro"}
VERDICT_BADGE_KIND = {"rialzista": "ok", "ribassista": "bad", "neutro": "info"}


def _section_trend(snap: dict) -> dict:
    trend = snap["trend"]
    lines = []
    if trend == "rialzista":
        lines.append(
            "Il titolo è in un trend rialzista: massimi e minimi delle ultime oscillazioni sono "
            "progressivamente più alti, il segno classico di una fase di salita che tende ad "
            "autoalimentarsi finché non si rompe."
        )
        verdict = "rialzista"
    elif trend == "ribassista":
        lines.append(
            "Il titolo è in un trend ribassista: massimi e minimi sono progressivamente più bassi, "
            "la controparte discendente dello stesso principio."
        )
        verdict = "ribassista"
    elif trend == "laterale":
        lines.append(
            "Il titolo si muove lateralmente: non emerge una sequenza chiara di massimi e minimi "
            "crescenti o decrescenti — il mercato non ha ancora scelto una direzione precisa su "
            "questo orizzonte."
        )
        verdict = "neutro"
    else:
        lines.append(
            "Non ci sono ancora abbastanza punti di riferimento sul grafico per stabilire un trend "
            "chiaro su questo orizzonte temporale."
        )
        verdict = "neutro"

    sr = snap.get("support_resistance", [])
    supports = [l for l in sr if l["role"] == "supporto"]
    resistances = [l for l in sr if l["role"] == "resistenza"]
    if supports:
        nearest = max(supports, key=lambda l: l["level"])
        lines.append(
            f"Il supporto più vicino sotto il prezzo attuale (un livello dove la domanda ha fermato "
            f"i ribassi in passato) è a {nearest['level']:.2f}, toccato {nearest['touches']} volte."
        )
    if resistances:
        nearest = min(resistances, key=lambda l: l["level"])
        lines.append(
            f"La resistenza più vicina sopra il prezzo attuale (un livello dove l'offerta ha fermato "
            f"i rialzi in passato) è a {nearest['level']:.2f}, toccata {nearest['touches']} volte."
        )

    for key, label in (("support_line", "di supporto"), ("resistance_line", "di resistenza")):
        line = snap.get(key)
        if line:
            stato = ("confermata da almeno tre punti di contatto" if line["confirmed"]
                      else "ancora provvisoria, con solo due punti di contatto")
            lines.append(f"La trendline {label} disegnata sugli estremi recenti è {stato}.")

    return {"key": "trend", "icon": "📈", "title": "Trend e struttura del prezzo",
            "verdict": verdict, "text": " ".join(lines)}


def _section_moving_averages(snap: dict) -> dict:
    ma = snap["moving_averages"]
    boll = snap["bollinger"]
    params = HORIZONS[snap["horizon"]]
    lines = []
    verdict = "neutro"

    if ma.get("alignment") == "rialzista":
        lines.append(
            f"Le medie mobili sono allineate in ordine rialzista: quella a {params['ma_fast']} periodi "
            f"sta sopra quella a {params['ma_mid']}, a sua volta sopra quella a {params['ma_slow']} — "
            "un contesto che storicamente accompagna i trend più solidi."
        )
        verdict = "rialzista"
    elif ma.get("alignment") == "ribassista":
        lines.append(
            f"Le medie mobili sono allineate in ordine ribassista: quella a {params['ma_fast']} periodi "
            f"sta sotto quella a {params['ma_mid']}, a sua volta sotto quella a {params['ma_slow']}."
        )
        verdict = "ribassista"
    else:
        lines.append(
            "Le medie mobili non sono allineate in un ordine chiaro: spesso un segno di fase di "
            "transizione o di mercato indeciso."
        )

    if ma.get("golden_cross"):
        lines.append(
            "Nelle ultime sedute la media a periodo medio ha incrociato al rialzo quella più lunga "
            "(golden cross): un evento tecnico spesso letto come conferma di un cambio di fase verso l'alto."
        )
        verdict = "rialzista"
    if ma.get("death_cross"):
        lines.append(
            "Nelle ultime sedute la media a periodo medio ha incrociato al ribasso quella più lunga "
            "(death cross): l'evento equivalente in chiave ribassista."
        )
        verdict = "ribassista"

    pb = boll.get("percent_b")
    if pb is not None:
        if pb >= 1:
            lines.append(
                "Il prezzo è sulla banda superiore di Bollinger o sopra (una fascia di volatilità "
                "costruita a due deviazioni standard dalla media a 20 periodi): una condizione di "
                "forza che a volte precede anche una pausa."
            )
        elif pb <= 0:
            lines.append(
                "Il prezzo è sulla banda inferiore di Bollinger o sotto: una condizione di debolezza "
                "che nei titoli storicamente più solidi tende a essere temporanea."
            )
        else:
            lines.append(
                f"Il prezzo è in posizione centrale tra le bande di Bollinger (%B = {pb:.2f}), senza "
                "eccessi in nessuna delle due direzioni."
            )
    if boll.get("squeeze"):
        lines.append(
            "Le bande di Bollinger sono in una fase di compressione (squeeze): la volatilità è bassa, "
            "una condizione che spesso precede un nuovo movimento più ampio — senza però indicarne "
            "la direzione."
        )

    return {"key": "moving_averages", "icon": "📉", "title": "Medie mobili e volatilità",
            "verdict": verdict, "text": " ".join(lines)}


def _section_momentum(snap: dict) -> dict:
    lines = []
    leans = []

    rsig = snap.get("rsi_signal")
    rsi_val = snap.get("rsi")
    if rsi_val is not None:
        if rsig in ("ipercomprato", "ipercomprato_forte"):
            lines.append(
                f"L'RSI (indice di forza relativa: misura se i rialzi recenti sono stati eccessivi) "
                f"è a {rsi_val:.1f}, in zona di ipercomprato."
            )
            leans.append(-1)
        elif rsig in ("ipervenduto", "ipervenduto_forte"):
            lines.append(
                f"L'RSI è a {rsi_val:.1f}, in zona di ipervenduto: il titolo ha subito ribassi rapidi "
                "negli ultimi periodi."
            )
            leans.append(1)
        else:
            lines.append(f"L'RSI è a {rsi_val:.1f}, in zona neutrale: nessun eccesso evidente.")
            leans.append(0)

    stoch = snap.get("stochastic", {})
    k, d = stoch.get("k_val"), stoch.get("d_val")
    if k is not None and d is not None:
        if d >= 80:
            agree = " coerente con l'RSI" if rsig in ("ipercomprato", "ipercomprato_forte") else ""
            lines.append(f"Lo stocastico (%K {k:.1f} / %D {d:.1f}) è anch'esso in ipercomprato{agree}.")
            leans.append(-1)
        elif d <= 20:
            agree = " coerente con l'RSI" if rsig in ("ipervenduto", "ipervenduto_forte") else ""
            lines.append(f"Lo stocastico (%K {k:.1f} / %D {d:.1f}) è in ipervenduto{agree}.")
            leans.append(1)
        else:
            lines.append(f"Lo stocastico (%K {k:.1f} / %D {d:.1f}) è in area neutrale.")
            leans.append(0)

    macd_res = snap.get("macd", {})
    if macd_res.get("hist_val") is not None:
        if macd_res["hist_val"] > 0:
            lines.append(
                "Il MACD ha istogramma positivo, con la linea MACD sopra il segnale: il momentum di "
                "breve termine è a favore dei compratori."
            )
            leans.append(1)
        else:
            lines.append(
                "Il MACD ha istogramma negativo, con la linea MACD sotto il segnale: il momentum di "
                "breve termine è a favore dei venditori."
            )
            leans.append(-1)

    wr = snap.get("williams_r")
    if wr is not None:
        if wr >= -20:
            lines.append(f"Il Williams %R ({wr:.1f}) è anch'esso in ipercomprato.")
            leans.append(-1)
        elif wr <= -80:
            lines.append(f"Il Williams %R ({wr:.1f}) è anch'esso in ipervenduto.")
            leans.append(1)

    if leans:
        pos, neg = leans.count(1), leans.count(-1)
        if pos >= 2 and neg == 0:
            lines.append("Nel complesso gli oscillatori concordano su un momentum rialzista.")
            verdict = "rialzista"
        elif neg >= 2 and pos == 0:
            lines.append("Nel complesso gli oscillatori concordano su un momentum ribassista.")
            verdict = "ribassista"
        elif pos and neg:
            lines.append(
                "Gli oscillatori danno però segnali contrastanti tra loro: alcuni indicano forza, "
                "altri debolezza — una situazione che invita a maggiore cautela nell'interpretazione."
            )
            verdict = "neutro"
        else:
            verdict = "neutro"
    else:
        verdict = "neutro"

    return {"key": "momentum", "icon": "🌊", "title": "Momentum e oscillatori",
            "verdict": verdict, "text": " ".join(lines)}


def _section_patterns(snap: dict) -> dict:
    lines = []
    verdict = "neutro"
    cps = snap.get("chart_patterns", [])
    css = snap.get("candlesticks", [])[-3:]

    if not cps and not css:
        lines.append(
            "Non emergono figure grafiche (doppi massimi/minimi, triangoli) né candele "
            "particolarmente significative nell'orizzonte selezionato: non è un'anomalia, la "
            "maggior parte delle sedute non produce pattern netti."
        )
        return {"key": "patterns", "icon": "🕯️", "title": "Pattern grafici e candlestick",
                "verdict": verdict, "text": " ".join(lines)}

    leans = []
    for cp in cps:
        lines.append(f"È stata individuata una figura di tipo {cp['pattern'].lower()}: {cp['note']}")
        leans.append(1 if cp["direction"] == "rialzista" else (-1 if cp["direction"] == "ribassista" else 0))
    for cs in css:
        lines.append(
            f"Tra le ultime candele, il {cs['date'].strftime('%d/%m')} si segnala un "
            f"{cs['pattern'].lower()}: {cs['note']}"
        )
        leans.append(1 if cs["direction"] == "rialzista" else (-1 if cs["direction"] == "ribassista" else 0))

    pos, neg = leans.count(1), leans.count(-1)
    if pos > neg:
        verdict = "rialzista"
    elif neg > pos:
        verdict = "ribassista"

    return {"key": "patterns", "icon": "🕯️", "title": "Pattern grafici e candlestick",
            "verdict": verdict, "text": " ".join(lines)}


def _write_synthesis(snap: dict, sections: list[dict], entry_price: float | None = None) -> str:
    """Il 'pensiero critico' finale: non concatena le sezioni, ragiona su
    quanto concordano o si contraddicono tra loro, indica cosa monitorare
    e — se fornito — lega il tutto al prezzo di ingresso."""
    verdicts = {s["key"]: s["verdict"] for s in sections}
    votes = list(verdicts.values())
    pos, neg = votes.count("rialzista"), votes.count("ribassista")

    lines = []
    if pos >= 3 and neg == 0:
        lines.append(
            "Il quadro complessivo è coerentemente rialzista: trend, medie mobili e momentum puntano "
            "nella stessa direzione. Quando più famiglie di indicatori concordano il segnale tende a "
            "essere statisticamente più solido rispetto a quando si contraddicono — ma nessuna "
            "convergenza è una garanzia di quanto accadrà dopo."
        )
    elif neg >= 3 and pos == 0:
        lines.append(
            "Il quadro complessivo è coerentemente ribassista: trend, medie mobili e momentum "
            "puntano tutti nella stessa direzione verso il basso. Anche qui la convergenza rende il "
            "quadro più solido, non certo."
        )
    elif pos > neg:
        lines.append(
            "Il quadro è prevalentemente rialzista, ma non del tutto unanime: almeno un fattore si "
            "muove in controtendenza o resta neutro rispetto al resto dell'analisi. Vale la pena "
            "capire quale, prima di trarre conclusioni."
        )
    elif neg > pos:
        lines.append(
            "Il quadro è prevalentemente ribassista, ma non del tutto unanime: almeno un fattore si "
            "muove in controtendenza o resta neutro rispetto al resto dell'analisi."
        )
    else:
        lines.append(
            "Il quadro è misto: non c'è una direzione dominante tra le famiglie di indicatori "
            "analizzate — trend, medie mobili, momentum e pattern non raccontano la stessa storia. "
            "In condizioni come questa molti analisti aspettano una conferma ulteriore prima di "
            "considerare il quadro tecnico decisivo."
        )

    if verdicts.get("trend") == "rialzista" and verdicts.get("momentum") == "ribassista":
        lines.append(
            "In particolare, il trend di fondo resta rialzista ma il momentum è già in ipercomprato: "
            "una combinazione tipica delle fasi avanzate di un rally, dove il prezzo può ancora "
            "salire ma con un margine di sicurezza più basso."
        )
    if verdicts.get("trend") == "ribassista" and verdicts.get("momentum") == "rialzista":
        lines.append(
            "In particolare, il trend di fondo resta ribassista ma il momentum è già in ipervenduto: "
            "una combinazione che spesso precede un rimbalzo tecnico, senza che questo implichi "
            "necessariamente un'inversione del trend principale."
        )

    sr = snap.get("support_resistance", [])
    watch = []
    supports = [l for l in sr if l["role"] == "supporto"]
    resistances = [l for l in sr if l["role"] == "resistenza"]
    if supports:
        watch.append(f"la tenuta del supporto a {max(supports, key=lambda l: l['level'])['level']:.2f}")
    if resistances:
        watch.append(f"un'eventuale rottura della resistenza a {min(resistances, key=lambda l: l['level'])['level']:.2f}")
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
    """Analisi sezionata in stile 'report': una sezione per famiglia di
    indicatori (trend, medie mobili/volatilità, momentum, pattern), ognuna
    con un paragrafo e un verdetto, più una sintesi finale che ragiona
    sull'accordo/disaccordo tra le sezioni."""
    if not snap:
        return None
    sections = [
        _section_trend(snap),
        _section_moving_averages(snap),
        _section_momentum(snap),
        _section_patterns(snap),
    ]
    return {"sections": sections, "synthesis": _write_synthesis(snap, sections, entry_price)}


def multi_horizon_analysis(symbol: str) -> dict:
    """Analisi sui tre orizzonti temporali in un'unica chiamata — usata
    dalla pagina dedicata e, in futuro, dal motore di scoring composito."""
    out = {}
    for h in HORIZONS:
        snap = technical_snapshot(symbol, h)
        out[h] = {
            "snapshot": snap,
            "score": technical_score(snap),
            "interpretation": interpret(snap),
        }
    return out
