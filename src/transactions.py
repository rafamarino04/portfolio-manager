"""
Registro transazioni: il log di acquisti, vendite e dividendi diventa la
fonte di verità del portafoglio. Le posizioni attuali (quantità, prezzo
medio di carico) sono sempre *derivate* dallo storico con il metodo del
costo medio ponderato, non inserite a mano — così P&L realizzato,
dividendi incassati e rendimento money-weighted (XIRR) sono coerenti tra
loro invece di essere numeri scollegati.
"""
from __future__ import annotations

import datetime as dt
import os

import pandas as pd

TRANSACTION_TYPES = ["Acquisto", "Vendita", "Dividendo"]

COLUMNS = [
    "date", "ticker", "type", "quantity", "price", "amount", "fees",
    "currency", "category", "manual_price", "note",
]


def load_transactions(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(path)
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = None
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "ticker", "type"])
    df["ticker"] = df["ticker"].astype(str).str.strip()
    return df.sort_values("date")[COLUMNS]


def _num(x, default=0.0) -> float:
    try:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def compute_positions(transactions: pd.DataFrame) -> pd.DataFrame:
    """Posizioni attuali derivate dal registro, nella stessa forma di
    portfolio.csv (compatibile con il resto dell'app senza modifiche)."""
    rows = []
    for ticker, group in transactions.groupby("ticker"):
        qty = 0.0
        cost_basis = 0.0
        first_date = None
        currency = category = note = None
        manual_price = None

        for _, tx in group.sort_values("date").iterrows():
            ttype = tx["type"]
            if tx.get("currency"):
                currency = tx["currency"]
            if tx.get("category"):
                category = tx["category"]
            if pd.notna(tx.get("manual_price")):
                manual_price = tx["manual_price"]
            if tx.get("note"):
                note = tx["note"]

            if ttype == "Acquisto":
                q, price, fees = _num(tx["quantity"]), _num(tx["price"]), _num(tx["fees"])
                qty += q
                cost_basis += q * price + fees
                if first_date is None:
                    first_date = tx["date"]
            elif ttype == "Vendita":
                q, price, fees = _num(tx["quantity"]), _num(tx["price"]), _num(tx["fees"])
                avg_cost = (cost_basis / qty) if qty > 0 else 0.0
                sell_qty = min(q, qty)
                cost_basis -= sell_qty * avg_cost
                qty -= sell_qty
                if qty < 1e-9:
                    qty = 0.0
                    cost_basis = 0.0
            # Dividendo non modifica quantità/costo

        if qty > 1e-9:
            rows.append({
                "ticker": ticker,
                "quantity": qty,
                "buy_price": cost_basis / qty,
                "buy_date": first_date.date().isoformat() if first_date is not None else None,
                "currency": currency,
                "category": category or "Altro",
                "manual_price": manual_price,
                "note": note,
            })

    if not rows:
        return pd.DataFrame(columns=[
            "ticker", "quantity", "buy_price", "buy_date", "currency",
            "category", "manual_price", "note",
        ])
    return pd.DataFrame(rows)


def compute_realized_pl(transactions: pd.DataFrame) -> pd.DataFrame:
    """P&L realizzato per ticker con il metodo del costo medio: ogni
    vendita confrontata col costo medio delle quote possedute in quel
    momento (non col prezzo di carico finale, che può includere acquisti
    successivi alla vendita)."""
    rows = []
    for ticker, group in transactions.groupby("ticker"):
        qty = 0.0
        cost_basis = 0.0
        realized = 0.0
        for _, tx in group.sort_values("date").iterrows():
            if tx["type"] == "Acquisto":
                q, price, fees = _num(tx["quantity"]), _num(tx["price"]), _num(tx["fees"])
                qty += q
                cost_basis += q * price + fees
            elif tx["type"] == "Vendita":
                q, price, fees = _num(tx["quantity"]), _num(tx["price"]), _num(tx["fees"])
                avg_cost = (cost_basis / qty) if qty > 0 else 0.0
                sell_qty = min(q, qty)
                realized += sell_qty * (price - avg_cost) - fees
                cost_basis -= sell_qty * avg_cost
                qty -= sell_qty
        if realized != 0:
            rows.append({"ticker": ticker, "realized_pl": realized})
    out = pd.DataFrame(rows)
    return out


def compute_dividends(transactions: pd.DataFrame) -> pd.DataFrame:
    div = transactions[transactions["type"] == "Dividendo"].copy()
    if div.empty:
        return pd.DataFrame(columns=["ticker", "total_dividends"])
    div["amount"] = div["amount"].apply(_num)
    return div.groupby("ticker", as_index=False)["amount"].sum().rename(
        columns={"amount": "total_dividends"}
    )


def _xnpv(rate: float, cashflows: list[tuple[dt.date, float]]) -> float:
    d0 = cashflows[0][0]
    return sum(cf / (1 + rate) ** ((d - d0).days / 365.0) for d, cf in cashflows)


def _xirr(cashflows: list[tuple[dt.date, float]]) -> float | None:
    """Newton-Raphson con fallback a bisezione, senza dipendere da scipy."""
    if len(cashflows) < 2:
        return None
    rate = 0.1
    for _ in range(100):
        npv = _xnpv(rate, cashflows)
        d0 = cashflows[0][0]
        d_npv = sum(
            -((d - d0).days / 365.0) * cf / (1 + rate) ** (((d - d0).days / 365.0) + 1)
            for d, cf in cashflows
        )
        if abs(d_npv) < 1e-12:
            break
        new_rate = rate - npv / d_npv
        if abs(new_rate - rate) < 1e-8:
            return new_rate
        rate = new_rate
        if rate <= -0.999:
            rate = -0.999

    # fallback: bisezione su un intervallo ampio
    lo, hi = -0.99, 10.0
    f_lo, f_hi = _xnpv(lo, cashflows), _xnpv(hi, cashflows)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = _xnpv(mid, cashflows)
        if abs(f_mid) < 1e-6:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def compute_xirr(transactions: pd.DataFrame, current_total_value: float, as_of: dt.date | None = None) -> float | None:
    """Rendimento annualizzato money-weighted: tiene conto di quando sono
    entrati/usciti i soldi, non solo di quanto. Aggiunge il valore attuale
    del portafoglio come flusso finale, come se lo liquidassi oggi."""
    as_of = as_of or dt.date.today()
    flows: list[tuple[dt.date, float]] = []
    for _, tx in transactions.sort_values("date").iterrows():
        d = tx["date"].date() if hasattr(tx["date"], "date") else tx["date"]
        if tx["type"] == "Acquisto":
            amt = -(_num(tx["quantity"]) * _num(tx["price"]) + _num(tx["fees"]))
        elif tx["type"] == "Vendita":
            amt = _num(tx["quantity"]) * _num(tx["price"]) - _num(tx["fees"])
        elif tx["type"] == "Dividendo":
            amt = _num(tx["amount"])
        else:
            continue
        if amt != 0:
            flows.append((d, amt))

    if not flows:
        return None
    flows.append((as_of, current_total_value))
    result = _xirr(flows)
    return result * 100 if result is not None else None
