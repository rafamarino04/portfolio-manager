"""
Wrapper attorno a yfinance per prezzi, storico, fondamentali e news.
Tutte le funzioni sono difensive: se una chiamata fallisce (rate limit,
ticker non valido, rete assente) restituiscono un valore vuoto/neutro
invece di far crashare l'app.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache

import pandas as pd
import yfinance as yf


@lru_cache(maxsize=256)
def get_ticker(symbol: str) -> yf.Ticker:
    return yf.Ticker(symbol)


def get_current_price(symbol: str) -> float | None:
    """Ultimo prezzo disponibile (quasi real-time, delay tipico 15-20 min)."""
    try:
        t = get_ticker(symbol)
        fi = t.fast_info
        price = fi.get("lastPrice") or fi.get("last_price")
        if price:
            return float(price)
    except Exception:
        pass
    try:
        hist = get_history(symbol, period="5d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


def get_previous_close(symbol: str) -> float | None:
    try:
        t = get_ticker(symbol)
        fi = t.fast_info
        prev = fi.get("previousClose") or fi.get("regularMarketPreviousClose")
        if prev:
            return float(prev)
    except Exception:
        pass
    return None


def get_history(symbol: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
    try:
        t = get_ticker(symbol)
        hist = t.history(period=period, interval=interval)
        return hist
    except Exception:
        return pd.DataFrame()


def get_quote_type(symbol: str) -> str | None:
    """Tipo di strumento secondo yfinance (EQUITY, ETF, INDEX, CURRENCY,
    CRYPTOCURRENCY, FUTURE, MUTUALFUND, ...). Usato per adattare criteri
    che dipendono dalla classe di strumento (es. Technical Tradeability
    Score, src/tradeability.py) senza mai hardcodare un elenco di ticker."""
    try:
        t = get_ticker(symbol)
        qt = t.info.get("quoteType")
        return str(qt).upper() if qt else None
    except Exception:
        return None


def get_earnings_dates(symbol: str, limit: int = 16) -> pd.DataFrame:
    """Date storiche/future degli utili trimestrali, se disponibili.
    DataFrame vuoto se lo strumento non ha earnings (ETF, indici, FX,
    crypto, future) o se yfinance non fornisce il dato per questo ticker."""
    try:
        t = get_ticker(symbol)
        df = t.get_earnings_dates(limit=limit)
        return df if df is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def get_fx_rate(quote_currency: str | None, base_currency: str = "EUR") -> float | None:
    """Quante unità di `quote_currency` per 1 unità di `base_currency`,
    via il ticker yfinance standard (es. EURUSD=X = quanti USD per 1
    EUR). None se la coppia non è quotata o il dato non è disponibile —
    il chiamante deve trattare None come "conversione non disponibile",
    mai come tasso 1:1 implicito."""
    if not quote_currency:
        return None
    if quote_currency.upper() == base_currency.upper():
        return 1.0
    pair = f"{base_currency.upper()}{quote_currency.upper()}=X"
    try:
        hist = get_history(pair, period="5d", interval="1d")
        if hist is not None and not hist.empty:
            val = hist["Close"].dropna()
            if not val.empty:
                return float(val.iloc[-1])
    except Exception:
        pass
    return None


def get_info(symbol: str) -> dict:
    """Nome, settore, valuta, market cap, P/E, range 52 settimane, e segnali
    per la pagina Opportunità (target price analisti, dividend yield, beta)."""
    out = {
        "name": symbol,
        "sector": None,
        "currency": None,
        "market_cap": None,
        "pe_ratio": None,
        "forward_pe": None,
        "week52_low": None,
        "week52_high": None,
        "target_mean_price": None,
        "recommendation_key": None,
        "num_analyst_opinions": None,
        "dividend_yield": None,
        "beta": None,
        "price_to_book": None,
        "return_on_equity": None,
        "debt_to_equity": None,
        "profit_margins": None,
        "revenue_growth": None,
        "free_cashflow": None,
        "trailing_eps": None,
        "forward_eps": None,
        "industry": None,
        "enterprise_value": None,
        "ev_to_ebitda": None,
        "ev_to_revenue": None,
        "shares_outstanding": None,
        "quick_ratio": None,
        "current_ratio_info": None,
        "payout_ratio": None,
        "earnings_growth": None,
        "operating_cashflow": None,
        "gross_margins": None,
        "operating_margins": None,
        "ebitda_margins": None,
    }
    try:
        t = get_ticker(symbol)
        info = t.info
        out["name"] = info.get("shortName") or info.get("longName") or symbol
        out["sector"] = info.get("sector")
        out["industry"] = info.get("industry")
        out["currency"] = info.get("currency")
        out["market_cap"] = info.get("marketCap")
        out["pe_ratio"] = info.get("trailingPE")
        out["forward_pe"] = info.get("forwardPE")
        out["week52_low"] = info.get("fiftyTwoWeekLow")
        out["week52_high"] = info.get("fiftyTwoWeekHigh")
        out["target_mean_price"] = info.get("targetMeanPrice")
        out["recommendation_key"] = info.get("recommendationKey")
        out["num_analyst_opinions"] = info.get("numberOfAnalystOpinions")
        out["dividend_yield"] = info.get("dividendYield")
        out["beta"] = info.get("beta")
        out["price_to_book"] = info.get("priceToBook")
        out["return_on_equity"] = info.get("returnOnEquity")
        out["debt_to_equity"] = info.get("debtToEquity")
        out["profit_margins"] = info.get("profitMargins")
        out["revenue_growth"] = info.get("revenueGrowth")
        out["free_cashflow"] = info.get("freeCashflow")
        out["trailing_eps"] = info.get("trailingEps")
        out["forward_eps"] = info.get("forwardEps")
        out["enterprise_value"] = info.get("enterpriseValue")
        out["ev_to_ebitda"] = info.get("enterpriseToEbitda")
        out["ev_to_revenue"] = info.get("enterpriseToRevenue")
        out["shares_outstanding"] = info.get("sharesOutstanding")
        out["quick_ratio"] = info.get("quickRatio")
        out["current_ratio_info"] = info.get("currentRatio")
        out["payout_ratio"] = info.get("payoutRatio")
        out["earnings_growth"] = info.get("earningsGrowth")
        out["operating_cashflow"] = info.get("operatingCashflow")
        out["gross_margins"] = info.get("grossMargins")
        out["operating_margins"] = info.get("operatingMargins")
        out["ebitda_margins"] = info.get("ebitdaMargins")
    except Exception:
        pass
    return out


def get_news(symbol: str, limit: int = 5) -> list[dict]:
    """News recenti collegate al titolo. Ogni item: title, publisher, link, time."""
    items = []
    try:
        t = get_ticker(symbol)
        raw = t.news or []
        for n in raw[:limit]:
            content = n.get("content", n)  # yfinance ha cambiato schema nel tempo
            title = content.get("title") or n.get("title")
            link = (content.get("canonicalUrl", {}) or {}).get("url") or n.get("link")
            publisher = (content.get("provider", {}) or {}).get("displayName") or n.get("publisher")
            pub_date = content.get("pubDate") or n.get("providerPublishTime")
            if title:
                items.append({
                    "title": title,
                    "link": link,
                    "publisher": publisher,
                    "time": pub_date,
                })
    except Exception:
        pass
    return items


MARKET_NEWS_FEEDS = {
    "Mercati (Reuters Business)": "https://feeds.reuters.com/reuters/businessNews",
    "Yahoo Finance": "https://finance.yahoo.com/news/rssindex",
}


def get_market_news(limit: int = 8) -> list[dict]:
    """News generali di mercato via RSS (nessuna API key richiesta)."""
    import feedparser

    items = []
    for source, url in MARKET_NEWS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[: max(1, limit // len(MARKET_NEWS_FEEDS))]:
                items.append({
                    "title": entry.get("title"),
                    "link": entry.get("link"),
                    "publisher": source,
                    "time": entry.get("published"),
                })
        except Exception:
            continue
    return items[:limit]
