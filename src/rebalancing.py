"""
Ribilanciamento: confronta l'allocazione attuale per categoria con
un'allocazione target impostata dall'utente, e suggerisce l'importo da
comprare/vendere per riportarla in equilibrio entro una banda di tolleranza.
"""
from __future__ import annotations

import pandas as pd

from src.portfolio import CATEGORIES


def compute_rebalancing(
    enriched: pd.DataFrame,
    target_allocation: dict,
    tolerance_pct: float = 5.0,
) -> pd.DataFrame:
    total_value = enriched["market_value"].sum(skipna=True)

    by_cat = (
        enriched.groupby("category", dropna=False)["market_value"]
        .sum(min_count=1)
        .to_dict()
    )

    rows = []
    all_categories = set(CATEGORIES) | set(target_allocation.keys()) | set(by_cat.keys())
    for cat in all_categories:
        cat = cat if isinstance(cat, str) and cat.strip() else "Altro"
        actual_value = by_cat.get(cat, 0) or 0
        actual_pct = (actual_value / total_value * 100) if total_value else 0
        target_pct = float(target_allocation.get(cat, 0) or 0)
        drift_pct = actual_pct - target_pct
        drift_value = (drift_pct / 100) * total_value if total_value else 0

        if target_pct == 0 and actual_pct == 0:
            continue

        if abs(drift_pct) <= tolerance_pct:
            action = "In linea"
        elif drift_pct > 0:
            action = "Vendi (sovrappeso)"
        else:
            action = "Compra (sottopeso)"

        rows.append({
            "category": cat,
            "target_pct": target_pct,
            "actual_pct": actual_pct,
            "drift_pct": drift_pct,
            "amount_to_trade": abs(drift_value),
            "action": action,
        })

    out = pd.DataFrame(rows).sort_values("target_pct", ascending=False).reset_index(drop=True)
    return out


def target_sums_to_100(target_allocation: dict, tolerance: float = 0.5) -> bool:
    total = sum(float(v or 0) for v in target_allocation.values())
    return abs(total - 100) <= tolerance
