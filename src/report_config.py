"""
Impostazioni dell'app: allocazione target per il ribilanciamento, benchmark
di riferimento, sezioni incluse nel report periodico. Salvate in
data/settings.json cosi' persistono e vengono lette sia dalle pagine
interattive sia dallo script del report automatico.
"""
from __future__ import annotations

import json
import os

DEFAULT_SETTINGS = {
    "target_allocation": {
        "Azione": 50,
        "ETF": 30,
        "Obbligazione": 15,
        "Fondo/SICAV": 0,
        "Liquidità": 5,
        "Altro": 0,
    },
    "rebalance_tolerance_pct": 5,
    "benchmark_ticker": "SWDA.MI",
    "benchmark_name": "iShares Core MSCI World (proxy)",
    "report_sections": [
        "overview", "allocation", "rebalancing", "benchmark", "opportunities", "news",
    ],
    "report_period": "weekly",
    "alerts_enabled": False,
    "alert_recipient_email": "",
    "alert_event_types": ["RSI", "MACD", "Rottura", "Candela", "Figura"],
}

ALL_SECTIONS = {
    "overview": "Valore, P&L, KPI principali",
    "allocation": "Allocazione per categoria/titolo",
    "rebalancing": "Ribilanciamento (target vs attuale)",
    "benchmark": "Confronto con benchmark e performance",
    "opportunities": "Segnali di opportunità sui titoli",
    "news": "News principali",
}

# Tipi di evento tecnico rilevati da src/alerts.py (vedi ALERT_EVENT_LABELS
# per le etichette leggibili usate in UI) — usati per filtrare quali
# eventi possono generare un'email di alert.
ALERT_EVENT_TYPES = ["RSI", "MACD", "Rottura", "Candela", "Figura"]

ALERT_EVENT_LABELS = {
    "RSI": "Incrocio soglie RSI (70/30 ipercomprato/ipervenduto)",
    "MACD": "Incrocio MACD/segnale",
    "Rottura": "Rottura di supporto/resistenza",
    "Candela": "Pattern di candlestick rilevato",
    "Figura": "Figura di prezzo (doppio massimo/minimo, triangolo)",
}

BENCHMARK_PRESETS = {
    "SWDA.MI": "iShares Core MSCI World (proxy azionario globale)",
    "^GSPC": "S&P 500",
    "^STOXX50E": "Euro Stoxx 50",
    "VWCE.DE": "Vanguard FTSE All-World",
    "^FTSEMIB": "FTSE MIB (Borsa Italiana)",
}


def load_settings(path: str = "data/settings.json") -> dict:
    if not os.path.exists(path):
        return json.loads(json.dumps(DEFAULT_SETTINGS))  # deep copy
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        return json.loads(json.dumps(DEFAULT_SETTINGS))

    merged = json.loads(json.dumps(DEFAULT_SETTINGS))
    merged.update(data)
    # merge nested dict so nuove categorie aggiunte in futuro non spariscano
    merged["target_allocation"] = {
        **DEFAULT_SETTINGS["target_allocation"],
        **data.get("target_allocation", {}),
    }
    return merged


def save_settings(settings: dict, path: str = "data/settings.json") -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
