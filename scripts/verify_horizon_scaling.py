"""
Script di verifica FIX 8 (Prompt_Cowork_Gerarchia_Orizzonti.md, "Verificare
lo scaling effettivo dei livelli per orizzonte"): la tabella maestra di
src/technical.py (HORIZONS) fa scalare con l'orizzonte lookback del trend,
swing sensitivity, periodi delle medie e finestra di ricerca dei livelli
S/R — ma senza una verifica su dati reali resta un'assunzione, non un
fatto: se i livelli S/R e il moltiplicatore ATR non scalano DAVVERO con
l'orizzonte, un piano di medio termine può risultare stretto quanto uno di
breve, il che ne comprometterebbe la logica (l'utente crede di vedere un
piano di posizionamento e ne riceve uno di trading).

Questo script NON corregge nulla da solo: calcola, per un campione ampio
e diversificato di titoli (>= 20), il piano operativo (src/technical.py::
trade_plan) sui tre orizzonti e riporta, per ciascun orizzonte, la
distribuzione (min, mediana, quartili, max) della distanza percentuale di
stop e target dal prezzo di ingresso.

Criterio di accettazione (dalla richiesta FIX 8): le ampiezze devono
crescere in modo MARCATO e MONOTONO passando da breve a medio a lungo. Se
le distribuzioni si sovrappongono largamente (es. la mediana di un
orizzonte superiore non supera chiaramente il terzo quartile di quello
inferiore), lo scaling non sta funzionando e va corretto ALLA RADICE nella
tabella maestra (HORIZONS) o nella logica di trade_plan() — non
compensato con un fattore moltiplicativo arbitrario aggiunto sopra.

Uso:
    PYTHONPATH=. python scripts/verify_horizon_scaling.py

Richiede accesso di rete (yfinance): non eseguibile in un ambiente senza
uscita di rete verso Yahoo Finance (stesso vincolo di
scripts/verify_axis_distribution.py).
"""
from __future__ import annotations

import statistics as stats
import sys

sys.path.insert(0, ".")

from src import technical as tech  # noqa: E402

# Campione diversificato (>= 20 titoli): copre settori e fasce di
# capitalizzazione diverse — scelta editoriale per varietà di copertura,
# non un indice o un universo investibile, non backtestato.
SAMPLE_TICKERS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "JPM", "BAC", "GS",
    "JNJ", "PFE", "UNH",
    "XOM", "CVX",
    "PG", "KO", "PEP",
    "CAT", "HON",
    "DIS", "NFLX",
    "TSLA", "NKE",
]

HORIZON_ORDER = tech.HORIZON_CHAIN  # ["breve", "medio", "lungo"], dalla tabella maestra


def _pct_distance(reference: float, level: float) -> float:
    return abs(level - reference) / reference * 100 if reference else float("nan")


def _distribution(values: list[float]) -> dict:
    if not values:
        return {}
    values_sorted = sorted(values)
    n = len(values_sorted)
    q1 = values_sorted[int(0.25 * (n - 1))]
    q3 = values_sorted[int(0.75 * (n - 1))]
    return {
        "n": n, "min": round(min(values_sorted), 2), "median": round(stats.median(values_sorted), 2),
        "q1": round(q1, 2), "q3": round(q3, 2), "max": round(max(values_sorted), 2),
    }


def main():
    stop_pct = {h: [] for h in HORIZON_ORDER}
    target_pct = {h: [] for h in HORIZON_ORDER}
    skipped = []

    print(f"Analisi di {len(SAMPLE_TICKERS)} titoli su {len(HORIZON_ORDER)} orizzonti (rete richiesta, yfinance)...\n")

    for symbol in SAMPLE_TICKERS:
        for horizon in HORIZON_ORDER:
            try:
                snap = tech.technical_snapshot(symbol, horizon)
                plan = tech.trade_plan(snap)
            except Exception as exc:  # yfinance/rete non disponibile per questo titolo/orizzonte
                skipped.append((symbol, horizon, f"errore: {exc}"))
                continue
            if not plan or plan.get("bias") == "nessun_setup":
                skipped.append((symbol, horizon, "nessun piano generato (quadro non direzionale)"))
                continue
            entry = plan["entry"]
            stop_pct[horizon].append(_pct_distance(entry, plan["stop"]))
            target_pct[horizon].append(_pct_distance(entry, plan["target"]))
            print(f"  {symbol:<6} {horizon:<6} stop {stop_pct[horizon][-1]:.2f}%  target {target_pct[horizon][-1]:.2f}%")

    print("\n--- Distribuzione distanza % dello STOP dal prezzo di ingresso, per orizzonte ---")
    stop_dists = {}
    for h in HORIZON_ORDER:
        stop_dists[h] = _distribution(stop_pct[h])
        print(f"  {h:<6}: {stop_dists[h]}")

    print("\n--- Distribuzione distanza % del TARGET dal prezzo di ingresso, per orizzonte ---")
    target_dists = {}
    for h in HORIZON_ORDER:
        target_dists[h] = _distribution(target_pct[h])
        print(f"  {h:<6}: {target_dists[h]}")

    def _check_monotonic(dists: dict, label: str):
        medians = [dists[h].get("median") for h in HORIZON_ORDER if dists[h]]
        if len(medians) < len(HORIZON_ORDER):
            print(f"\n{label}: dati insufficienti su almeno un orizzonte, impossibile verificare la monotonicità.")
            return
        ok = all(medians[i] < medians[i + 1] for i in range(len(medians) - 1))
        if ok:
            print(f"\n{label}: mediane monotone crescenti per orizzonte ({' < '.join(f'{m:.2f}%' for m in medians)}) — OK.")
        else:
            per_horizon = ", ".join(f"{h}={dists[h].get('median')}%" for h in HORIZON_ORDER)
            print(
                f"\n{label}: ATTENZIONE — le mediane NON crescono in modo monotono per orizzonte "
                f"({per_horizon}). Lo scaling non sta funzionando: va corretto alla radice nella tabella "
                "maestra HORIZONS o in trade_plan(), non compensato con un fattore moltiplicativo aggiunto sopra."
            )
        # Sovrapposizione: la mediana di un orizzonte dovrebbe superare
        # chiaramente il terzo quartile di quello inferiore, non solo la
        # mediana — altrimenti le distribuzioni si sovrappongono troppo
        # perché lo scaling sia "marcato" come richiesto dal FIX 8.
        for i in range(len(HORIZON_ORDER) - 1):
            lo, hi = HORIZON_ORDER[i], HORIZON_ORDER[i + 1]
            if not dists[lo] or not dists[hi]:
                continue
            if dists[hi]["median"] <= dists[lo]["q3"]:
                print(
                    f"  ATTENZIONE: la mediana di '{hi}' ({dists[hi]['median']}%) non supera il terzo "
                    f"quartile di '{lo}' ({dists[lo]['q3']}%) — sovrapposizione ampia, scaling non marcato."
                )

    _check_monotonic(stop_dists, "STOP")
    _check_monotonic(target_dists, "TARGET")

    if skipped:
        print(f"\nCasi saltati ({len(skipped)}):")
        for sym, horizon, reason in skipped:
            print(f"  {sym} [{horizon}]: {reason}")


if __name__ == "__main__":
    main()
