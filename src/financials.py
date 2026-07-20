"""
Numeri di bilancio: storico multi-periodo di ricavi, utile netto,
margini, free cash flow, debito e patrimonio netto, dai prospetti
contabili di Yahoo Finance (conto economico, bilancio, flussi di cassa,
via yfinance).

Le etichette delle righe dei prospetti non sono rigidamente standardizzate
da Yahoo Finance (variano leggermente per settore e nel tempo): ogni
metrica viene quindi cercata provando più varianti, con fallback a None
se non disponibile per quel titolo — tipico per società finanziarie
(niente "Gross Profit") o per titoli a copertura Yahoo Finance più
scarsa (spesso i titoli non statunitensi).
"""
from __future__ import annotations

import pandas as pd

from src import data_provider as dp

_REVENUE_LABELS = ["Total Revenue", "TotalRevenue", "Revenue"]
_NET_INCOME_LABELS = ["Net Income", "Net Income Common Stockholders", "NetIncome"]
_GROSS_PROFIT_LABELS = ["Gross Profit"]
_OPERATING_INCOME_LABELS = ["Operating Income", "Total Operating Income As Reported"]
_OPERATING_CASHFLOW_LABELS = [
    "Operating Cash Flow", "Cash Flow From Continuing Operating Activities",
    "Total Cash From Operating Activities",
]
_CAPEX_LABELS = ["Capital Expenditure", "Capital Expenditures", "Purchase Of PPE"]
_FREE_CASHFLOW_LABELS = ["Free Cash Flow"]
_TOTAL_DEBT_LABELS = ["Total Debt"]
_EQUITY_LABELS = ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"]
_EPS_LABELS = ["Diluted EPS", "Basic EPS"]

METRIC_KEYS = ["revenue", "net_income", "gross_profit", "operating_income",
               "operating_cash_flow", "capex", "free_cash_flow",
               "total_debt", "total_equity", "eps"]


def _find_row(df: pd.DataFrame, candidates: list[str]) -> pd.Series | None:
    if df is None or df.empty:
        return None
    idx_lower = {str(i).strip().lower(): i for i in df.index}
    for cand in candidates:
        key = cand.strip().lower()
        if key in idx_lower:
            return df.loc[idx_lower[key]]
    for cand in candidates:
        key = cand.strip().lower()
        for lower_name, orig in idx_lower.items():
            if key in lower_name:
                return df.loc[orig]
    return None


def _clean(s: pd.Series | None) -> pd.Series | None:
    if s is None:
        return None
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty:
        return None
    return s.sort_index()


def get_financial_history(symbol: str, freq: str = "annual") -> dict:
    """Serie temporali (dalla più vecchia alla più recente) per le
    metriche principali. `freq`: 'annual' o 'quarterly'."""
    out: dict = {k: None for k in METRIC_KEYS}
    try:
        t = dp.get_ticker(symbol)
        if freq == "quarterly":
            income, balance, cash = t.quarterly_income_stmt, t.quarterly_balance_sheet, t.quarterly_cashflow
        else:
            income, balance, cash = t.income_stmt, t.balance_sheet, t.cashflow

        out["revenue"] = _clean(_find_row(income, _REVENUE_LABELS))
        out["net_income"] = _clean(_find_row(income, _NET_INCOME_LABELS))
        out["gross_profit"] = _clean(_find_row(income, _GROSS_PROFIT_LABELS))
        out["operating_income"] = _clean(_find_row(income, _OPERATING_INCOME_LABELS))
        out["operating_cash_flow"] = _clean(_find_row(cash, _OPERATING_CASHFLOW_LABELS))
        out["capex"] = _clean(_find_row(cash, _CAPEX_LABELS))

        fcf = _clean(_find_row(cash, _FREE_CASHFLOW_LABELS))
        if fcf is None and out["operating_cash_flow"] is not None and out["capex"] is not None:
            ocf, capex = out["operating_cash_flow"].align(out["capex"], join="inner")
            if not ocf.empty:
                fcf = ocf + capex  # capex e' tipicamente negativo nei prospetti
        out["free_cash_flow"] = fcf

        out["total_debt"] = _clean(_find_row(balance, _TOTAL_DEBT_LABELS))
        out["total_equity"] = _clean(_find_row(balance, _EQUITY_LABELS))
        out["eps"] = _clean(_find_row(income, _EPS_LABELS))
    except Exception:
        pass
    return out


def compute_margins(hist: dict) -> dict:
    """Margini derivati (lordo/operativo/netto) dalle serie di bilancio,
    quando ricavi e la relativa voce sono entrambi disponibili."""
    out = {"gross_margin": None, "operating_margin": None, "net_margin": None}
    rev = hist.get("revenue")
    if rev is None:
        return out
    for key, out_key in (("gross_profit", "gross_margin"), ("operating_income", "operating_margin"),
                          ("net_income", "net_margin")):
        series = hist.get(key)
        if series is None:
            continue
        aligned_num, aligned_rev = series.align(rev, join="inner")
        if aligned_rev.empty:
            continue
        margin = (aligned_num / aligned_rev * 100).replace([float("inf"), float("-inf")], pd.NA).dropna()
        if not margin.empty:
            out[out_key] = margin
    return out


def growth_rate(series: pd.Series | None) -> float | None:
    """CAGR% tra il primo e l'ultimo periodo disponibile (variazione
    totale se solo due periodi o se i valori non sono entrambi positivi)."""
    if series is None or len(series) < 2:
        return None
    first, last = float(series.iloc[0]), float(series.iloc[-1])
    if pd.isna(first) or pd.isna(last) or first == 0:
        return None
    periods = len(series) - 1
    if periods <= 1 or first <= 0 or last <= 0:
        return (last - first) / abs(first) * 100
    return ((last / first) ** (1 / periods) - 1) * 100


def latest_and_yoy(series: pd.Series | None) -> dict:
    """Ultimo valore, precedente, e variazione percentuale tra i due."""
    if series is None or series.empty:
        return {"latest": None, "prev": None, "yoy_pct": None}
    latest = float(series.iloc[-1])
    prev = float(series.iloc[-2]) if len(series) >= 2 else None
    yoy = ((latest - prev) / abs(prev) * 100) if prev not in (None, 0) else None
    return {"latest": latest, "prev": prev, "yoy_pct": yoy}


def to_display_table(hist: dict, margins: dict) -> pd.DataFrame:
    """Tabella metriche (righe) x periodi (colonne), pronta per la UI."""
    rows = {}
    label_map = [
        ("revenue", "Ricavi"), ("net_income", "Utile netto"),
        ("gross_profit", "Utile lordo"), ("operating_income", "Utile operativo"),
        ("free_cash_flow", "Free cash flow"), ("total_debt", "Debito totale"),
        ("total_equity", "Patrimonio netto"), ("eps", "EPS"),
    ]
    for key, label in label_map:
        s = hist.get(key)
        if s is not None:
            rows[label] = s
    margin_map = [("gross_margin", "Margine lordo %"), ("operating_margin", "Margine operativo %"),
                  ("net_margin", "Margine netto %")]
    for key, label in margin_map:
        s = margins.get(key)
        if s is not None:
            rows[label] = s
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).T
    df.columns = [pd.Timestamp(c).strftime("%Y-%m") if not isinstance(c, str) else c for c in df.columns]
    return df
