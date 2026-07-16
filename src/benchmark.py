"""
Confronto tra il portafoglio e un benchmark di mercato, e attribuzione
della performance (quanto ogni posizione ha contribuito al P&L totale).

Due prospettive, entrambe approssimate per natura dato che non abbiamo
accesso allo storico reale del conto:
- "da quando hai iniziato": confronta il rendimento % del portafoglio
  (rispetto al costo) con il rendimento % del benchmark nello stesso
  periodo, usando la data del primo acquisto come inizio.
- "tracciato nel tempo": usa gli snapshot settimanali salvati in
  reports/history.csv, che si arricchisce settimana dopo settimana.
"""
from __future__ import annotations

import datetime as dt
import os

import pandas as pd

from src import data_provider as dp


def since_inception_comparison(raw_portfolio: pd.DataFrame, summary: dict, benchmark_ticker: str) -> dict | None:
    dates = pd.to_datetime(raw_portfolio.get("buy_date"), errors="coerce").dropna()
    if dates.empty or summary.get("total_pl_pct") is None:
        return None

    start_date = dates.min().date()
    hist = dp.get_history(benchmark_ticker, period="5y", interval="1d")
    if hist.empty:
        return None
    hist = hist[hist.index.date >= start_date]
    if hist.empty:
        return None

    bench_start = hist["Close"].iloc[0]
    bench_end = hist["Close"].iloc[-1]
    bench_return_pct = (bench_end - bench_start) / bench_start * 100

    return {
        "start_date": start_date,
        "portfolio_return_pct": summary["total_pl_pct"],
        "benchmark_return_pct": bench_return_pct,
        "difference_pct": summary["total_pl_pct"] - bench_return_pct,
    }


def tracked_history_vs_benchmark(history_csv_path: str, benchmark_ticker: str) -> pd.DataFrame | None:
    if not os.path.exists(history_csv_path):
        return None
    hist = pd.read_csv(history_csv_path)
    if hist.empty or len(hist) < 2:
        return None

    hist["date"] = pd.to_datetime(hist["date"])
    hist = hist.sort_values("date")

    bench = dp.get_history(benchmark_ticker, period="2y", interval="1d")
    if bench.empty:
        return None
    bench = bench.copy()
    bench["date_only"] = pd.to_datetime(bench.index).date

    rows = []
    base_portfolio = hist["total_value"].iloc[0]
    base_bench = None
    for _, r in hist.iterrows():
        target_date = r["date"].date()
        candidates = bench[bench["date_only"] <= target_date]
        if candidates.empty:
            continue
        bench_close = candidates.iloc[-1]["Close"]
        if base_bench is None:
            base_bench = bench_close
        rows.append({
            "date": r["date"],
            "Portafoglio": r["total_value"] / base_portfolio * 100,
            "Benchmark": bench_close / base_bench * 100,
        })
    if not rows:
        return None
    return pd.DataFrame(rows)


def performance_attribution(enriched: pd.DataFrame) -> pd.DataFrame:
    """Contributo di ciascuna posizione al P&L totale del portafoglio."""
    valid = enriched.dropna(subset=["pl_abs"]).copy()
    if valid.empty:
        return valid
    total_pl = valid["pl_abs"].sum()
    valid["contribution_pct"] = (
        (valid["pl_abs"] / total_pl * 100) if total_pl else 0
    )
    return valid[["ticker", "name", "pl_abs", "pl_pct", "contribution_pct"]].sort_values(
        "pl_abs", ascending=False
    )
