"""
Sentiment semplice sulle news: classifica ogni headline come
positiva/negativa/neutra in base a un elenco di parole chiave in inglese
(le news di Yahoo Finance sono quasi sempre in inglese anche per titoli
europei). Non è un modello di NLP — è un filtro rapido per farsi un'idea
del tono prevalente delle notizie recenti, da verificare sempre leggendo
gli articoli prima di trarre conclusioni.
"""
from __future__ import annotations

POSITIVE_WORDS = [
    "beat", "beats", "surge", "surges", "record", "upgrade", "upgraded", "growth",
    "profit", "profits", "strong", "raises", "raised", "outperform", "buyback",
    "rally", "soar", "soars", "jump", "jumps", "gain", "gains", "bullish",
    "expansion", "exceeds", "exceeded", "boost", "boosts", "top", "tops",
    "win", "wins", "approval", "approved", "partnership", "innovation", "surpass",
]
NEGATIVE_WORDS = [
    "miss", "misses", "cut", "cuts", "downgrade", "downgraded", "loss", "losses",
    "decline", "declines", "lawsuit", "investigation", "recall", "warn", "warns", "warning",
    "plunge", "plunges", "layoffs", "layoff", "bearish", "weak", "weakness", "slowing",
    "fall", "falls", "drop", "drops", "slump", "concern", "concerns", "fraud",
    "delay", "delayed", "probe", "fine", "fined", "bankruptcy", "default",
]


def score_headline(title: str | None) -> int:
    """+1 se prevalgono parole positive nel titolo, -1 se negative, 0 se
    pari o nessuna corrispondenza."""
    if not title:
        return 0
    t = title.lower()
    pos = sum(1 for w in POSITIVE_WORDS if w in t)
    neg = sum(1 for w in NEGATIVE_WORDS if w in t)
    if pos > neg:
        return 1
    if neg > pos:
        return -1
    return 0


def sentiment_summary(news_items: list[dict]) -> dict:
    """Classifica una lista di news (dict con almeno 'title') e ritorna
    conteggi e un'etichetta di tono complessivo."""
    scored = [{**item, "sentiment": score_headline(item.get("title"))} for item in news_items]
    pos = sum(1 for s in scored if s["sentiment"] > 0)
    neg = sum(1 for s in scored if s["sentiment"] < 0)
    neu = sum(1 for s in scored if s["sentiment"] == 0)
    total = len(scored)

    if total == 0:
        tone = "n/d"
    elif pos > neg * 1.5:
        tone = "prevalentemente positivo"
    elif neg > pos * 1.5:
        tone = "prevalentemente negativo"
    else:
        tone = "misto/neutro"

    return {"items": scored, "positive": pos, "negative": neg, "neutral": neu, "total": total, "tone": tone}
