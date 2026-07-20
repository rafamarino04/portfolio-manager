"""
Motore di segnali per i titoli in Preferiti: scansiona ogni titolo con
l'analisi tecnica (src/technical.py) e segnala eventi tecnici oggettivi
accaduti di recente — non previsioni, solo fatti rilevabili dal grafico.

Eventi rilevati: RSI che entra/esce da ipercomprato-ipervenduto, incrocio
MACD/segnale, rottura di un livello di supporto/resistenza, un pattern di
candlestick sull'ultima barra, una figura di prezzo attiva (doppio
massimo/minimo, triangolo).

Consegna: solo in-app, ricalcolato ogni volta che apri la pagina
Preferiti — nessun invio push/email in questa versione.
"""
from __future__ import annotations

from src import technical as tech

ALERT_HORIZON = "medio"


def _rsi_cross_alert(snap: dict) -> dict | None:
    series = snap["rsi_series"].dropna()
    if len(series) < 2:
        return None
    prev, curr = float(series.iloc[-2]), float(series.iloc[-1])
    if prev < 70 <= curr:
        return {"type": "RSI", "direction": "ribassista",
                "message": f"RSI ha appena superato 70 ({curr:.1f}): ipercomprato."}
    if prev > 30 >= curr:
        return {"type": "RSI", "direction": "rialzista",
                "message": f"RSI ha appena sceso sotto 30 ({curr:.1f}): ipervenduto."}
    return None


def _macd_cross_alert(snap: dict) -> dict | None:
    macd_res = snap["macd"]
    cross = tech._recent_cross(macd_res["macd"], macd_res["signal"], lookback=3)
    if cross == "rialzista":
        return {"type": "MACD", "direction": "rialzista",
                "message": "La linea MACD ha incrociato al rialzo la linea di segnale."}
    if cross == "ribassista":
        return {"type": "MACD", "direction": "ribassista",
                "message": "La linea MACD ha incrociato al ribasso la linea di segnale."}
    return None


def _sr_breakout_alert(snap: dict) -> dict | None:
    close = snap["hist"]["Close"]
    if len(close) < 2:
        return None
    prev, curr = float(close.iloc[-2]), float(close.iloc[-1])
    for lvl in snap.get("support_resistance", []):
        level = lvl["level"]
        if prev <= level < curr:
            return {"type": "Rottura", "direction": "rialzista",
                    "message": f"Prezzo ha rotto al rialzo il livello di {lvl['role']} a {level:.2f}."}
        if prev >= level > curr:
            return {"type": "Rottura", "direction": "ribassista",
                    "message": f"Prezzo ha rotto al ribasso il livello di {lvl['role']} a {level:.2f}."}
    return None


def _candlestick_alert(snap: dict) -> dict | None:
    hist = snap["hist"]
    if hist.empty:
        return None
    last_date = hist.index[-1]
    recent = [c for c in snap.get("candlesticks", []) if c["date"] == last_date]
    if not recent:
        return None
    c = recent[0]
    return {"type": "Candela", "direction": c["direction"], "message": f"{c['pattern']}: {c['note']}"}


def _chart_pattern_alerts(snap: dict) -> list[dict]:
    return [
        {"type": "Figura", "direction": cp["direction"], "message": f"{cp['pattern']}: {cp['note']}"}
        for cp in snap.get("chart_patterns", [])
    ]


def scan_ticker(symbol: str, horizon: str = ALERT_HORIZON) -> dict:
    """Snapshot tecnico + lista di eventi/segnali rilevati per un ticker."""
    snap = tech.technical_snapshot(symbol, horizon)
    if snap is None:
        return {"symbol": symbol, "snapshot": None, "alerts": []}

    events = []
    for fn in (_rsi_cross_alert, _macd_cross_alert, _sr_breakout_alert, _candlestick_alert):
        result = fn(snap)
        if result:
            events.append(result)
    events.extend(_chart_pattern_alerts(snap))

    return {"symbol": symbol, "snapshot": snap, "alerts": events}


def scan_watchlist(tickers: list[str], horizon: str = ALERT_HORIZON) -> list[dict]:
    return [scan_ticker(t, horizon) for t in tickers]
