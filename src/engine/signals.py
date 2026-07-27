"""
Generatore di segnali — src/engine/signals.py

Wrapper point-in-time attorno al motore di analisi tecnica esistente
(`src/technical.py`). Non reimplementa nessuna logica di segnale: chiama
`technical_snapshot` + `trade_plan`, cioè **esattamente** ciò che l'app
mostra nella pagina Analisi Tecnica. È il punto del progetto in cui si
risponde alla domanda "il piano operativo che vedo a schermo ha un edge?"
— e la risposta ha valore solo se il backtest testa quel piano, non una
sua approssimazione riscritta per comodità.

La regola che rende il tutto point-in-time: al bar `t` si passa a
`technical_snapshot` **solo** lo storico fino a `t` incluso. Nessun
indicatore può quindi vedere dati futuri. La finestra passata ha la
stessa ampiezza che l'app scaricherebbe dal vivo per quell'orizzonte, così
il segnale del backtest coincide con quello che sarebbe apparso a schermo
quel giorno.

Orizzonti supportati: solo quelli su barre daily (`breve`, `medio`).
L'orizzonte `lungo` lavora su barre settimanali e richiederebbe un
ricampionamento con regole di allineamento proprie — è escluso qui invece
di essere approssimato con dati daily, che darebbe risultati diversi da
quelli mostrati nell'app.
"""
from __future__ import annotations

import pandas as pd

from src import technical as tech

# Barre di storico da passare allo snapshot per orizzonte, allineate al
# `period` che l'app scarica dal vivo (6mo ≈ 126 sedute, 2y ≈ 504).
HORIZON_LOOKBACK_BARS = {
    "breve": 126,
    "medio": 504,
}

SUPPORTED_HORIZONS = tuple(HORIZON_LOOKBACK_BARS.keys())


def warmup_bars(horizon: str) -> int:
    """Barre necessarie prima che il primo segnale sia calcolabile.

    Sotto questa soglia `technical_snapshot` restituisce None (medie e
    indicatori non ancora definiti): il backtest deve saltare quei bar
    invece di trattarli come "nessun segnale", che sarebbe un'altra cosa."""
    params = tech.HORIZONS[horizon]
    return max(30, params["ma"][-1] // 2)


def generate_signal(symbol: str, hist_to_date: pd.DataFrame, horizon: str = "medio") -> dict | None:
    """Piano operativo sul close dell'ultimo bar di `hist_to_date`.

    `hist_to_date` deve contenere SOLO barre fino al bar corrente incluso:
    è responsabilità del chiamante (il bar loop) troncarlo correttamente.
    Ritorna il dict di `trade_plan` (con `bias` "long"/"short"/
    "nessun_setup") oppure None se lo snapshot non è calcolabile.

    Ritorna anche la confidenza complessiva del quadro, che il RiskSizer
    usa per l'eventuale scaling: qui è l'Agreement Index dell'orizzonte,
    riportato su scala 0-100. Non si usa `overall_confidence`, che
    richiederebbe anche l'orizzonte superiore e quindi una seconda
    finestra di dati: il segnale testato è quello del singolo orizzonte,
    e mescolarci dentro la gerarchia cambierebbe il segnale in esame."""
    if hist_to_date is None or hist_to_date.empty:
        return None

    lookback = HORIZON_LOOKBACK_BARS.get(horizon, HORIZON_LOOKBACK_BARS["medio"])
    window = hist_to_date.iloc[-lookback:] if len(hist_to_date) > lookback else hist_to_date

    snap = tech.technical_snapshot(symbol, horizon=horizon, hist=window)
    if snap is None:
        return None

    plan = tech.trade_plan(snap)
    if plan is None:
        return None

    plan = dict(plan)
    plan["confidence"] = round(snap["synthesis"]["A"] * 100, 1)
    plan["agreement"] = snap["synthesis"]["A"]
    plan["directional_score"] = snap["synthesis"]["D"]
    return plan
