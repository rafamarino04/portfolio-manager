"""
Logica di portafoglio: caricamento holdings, arricchimento con prezzi live,
calcolo P&L e allocazione.
"""
from __future__ import annotations

import pandas as pd

from src import data_provider as dp


def load_portfolio(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    required = {"ticker", "quantity", "buy_price"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Colonne mancanti nel CSV: {missing}")
    df["ticker"] = df["ticker"].astype(str).str.strip()
    return df


def enrich_with_prices(df: pd.DataFrame) -> pd.DataFrame:
    """Aggiunge prezzo corrente, valore di mercato, costo, P&L assoluto e %."""
    rows = []
    for _, row in df.iterrows():
        symbol = row["ticker"]
        price = dp.get_current_price(symbol)
        prev_close = dp.get_previous_close(symbol)
        info = dp.get_info(symbol)

        quantity = float(row["quantity"])
        buy_price = float(row["buy_price"])
        cost_basis = quantity * buy_price
        market_value = quantity * price if price is not None else None
        pl_abs = (market_value - cost_basis) if market_value is not None else None
        pl_pct = (pl_abs / cost_basis * 100) if pl_abs is not None and cost_basis else None
        day_change_pct = (
            ((price - prev_close) / prev_close * 100)
            if price is not None and prev_close
            else None
        )

        rows.append({
            **row.to_dict(),
            "name": info.get("name", symbol),
            "sector": info.get("sector"),
            "price": price,
            "market_value": market_value,
            "cost_basis": cost_basis,
            "pl_abs": pl_abs,
            "pl_pct": pl_pct,
            "day_change_pct": day_change_pct,
        })
    out = pd.DataFrame(rows)
    total_value = out["market_value"].sum(skipna=True)
    out["weight_pct"] = (
        out["market_value"] / total_value * 100 if total_value else 0
    )
    return out


def portfolio_summary(enriched: pd.DataFrame) -> dict:
    total_value = enriched["market_value"].sum(skipna=True)
    total_cost = enriched["cost_basis"].sum(skipna=True)
    total_pl = total_value - total_cost if total_value is not None else None
    total_pl_pct = (total_pl / total_cost * 100) if total_cost else None

    best = worst = None
    valid = enriched.dropna(subset=["pl_pct"])
    if not valid.empty:
        best = valid.loc[valid["pl_pct"].idxmax()]
        worst = valid.loc[valid["pl_pct"].idxmin()]

    return {
        "total_value": total_value,
        "total_cost": total_cost,
        "total_pl": total_pl,
        "total_pl_pct": total_pl_pct,
        "best": best,
        "worst": worst,
    }
