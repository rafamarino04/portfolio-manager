"""
Logica di portafoglio: caricamento holdings, arricchimento con prezzi live,
calcolo P&L e allocazione.
"""
from __future__ import annotations

import pandas as pd

from src import data_provider as dp

CATEGORIES = ["Azione", "ETF", "Obbligazione", "Fondo/SICAV", "Liquidità", "Altro"]


def load_portfolio(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    required = {"ticker", "quantity", "buy_price"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Colonne mancanti nel CSV: {missing}")
    df["ticker"] = df["ticker"].astype(str).str.strip()
    if "manual_price" not in df.columns:
        df["manual_price"] = None
    return df


def _to_float_or_none(value) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


CASH_CATEGORY = "Liquidità"


def enrich_with_prices(df: pd.DataFrame) -> pd.DataFrame:
    """Aggiunge prezzo corrente, valore di mercato, costo, P&L assoluto e %.

    Regole per categorie speciali:
    - 'Liquidità': nessuna chiamata a Yahoo Finance, prezzo fisso a 1 (il
      valore e' semplicemente l'importo in 'quantity'), P&L sempre nullo.
    - Altre categorie senza prezzo live (tipico per obbligazioni/fondi non
      coperti da Yahoo Finance): se presente 'manual_price', viene usato al
      posto del prezzo live e la riga e' marcata 'manuale' in price_source.
    """
    rows = []
    for _, row in df.iterrows():
        symbol = row["ticker"]
        category = str(row.get("category") or "").strip()
        manual_price = _to_float_or_none(row.get("manual_price"))

        if category == CASH_CATEGORY:
            price = 1.0
            price_source = "liquidità"
            prev_close = None
            info = {"name": symbol or "Liquidità", "sector": None}
        else:
            price = dp.get_current_price(symbol)
            price_source = "live"
            if price is None:
                if manual_price is not None:
                    price = manual_price
                    price_source = "manuale"
                else:
                    price_source = "n/d"
            prev_close = dp.get_previous_close(symbol) if price_source == "live" else None
            info = dp.get_info(symbol)

        quantity = float(row["quantity"])
        buy_price = 1.0 if category == CASH_CATEGORY else float(row["buy_price"])
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
            "price_source": price_source,
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
