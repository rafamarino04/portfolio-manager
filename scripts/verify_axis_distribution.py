"""
Script di verifica FIX9 (Prompt_Cowork_Analisi_Fondamentale_v2.1.md,
"Verifica di calibrazione dell'asse Valuation"): con soglie assolute,
in un contesto di mercato mediamente caro l'asse Valuation potrebbe
comprimersi verso il basso per quasi tutti i titoli, restando "onesto"
ma perdendo potere discriminante fra i candidati dell'utente. Questo
script NON corregge nulla da solo: calcola Quality e Valuation su un
campione ampio e diversificato di titoli (>= 30, distribuiti su settori
e fasce di market cap) e riporta la distribuzione dei punteggi (min,
max, mediana, quartili, deviazione standard) così da poter giudicare se
l'asse discrimina o no.

Criterio di accettazione (dalla spec): se oltre l'80% dei titoli cade in
una singola banda (Eccellente/Buono/Discreto/Sufficiente/Debole/Scarso),
l'asse non discrimina abbastanza fra i titoli che l'utente segue.

IMPORTANTE (vincolo esplicito della spec v2.1): se la distribuzione
risulta compressa, la risposta NON è ammorbidire le soglie assolute (il
punteggio resterebbe "onesto" solo se calibrato sul valore intrinseco,
non sul mercato del momento) — la spec chiede di aggiungere un SECONDO
livello di lettura, relativo all'universo di titoli seguito dall'utente
(portafoglio + preferiti), etichettato chiaramente come confronto
relativo e distinto dal punteggio assoluto (es. "Valuation assoluta:
Scarso — ma è il 2° più economico fra i titoli che segui"). Questo
secondo livello NON è implementato da questo script: è un'analisi da
fare quando/se la distribuzione qui misurata risulta davvero compressa,
non un'implementazione preventiva su un solo campione osservato in un
momento di mercato specifico.

Uso:
    PYTHONPATH=. python scripts/verify_axis_distribution.py

Richiede accesso di rete (yfinance). Il campione sotto copre gli 8
bucket di settore di src/sector_thresholds.py e le 3 fasce di market cap
di src/sector_universe.py — scelto per varietà, non backtestato: è un
campione di verifica, non un universo "ufficiale" dell'app.
"""
from __future__ import annotations

import statistics as stats
import sys

sys.path.insert(0, ".")

from src import fundamental_score as fscore  # noqa: E402
from src import sector_thresholds as sth  # noqa: E402
from src import sector_universe as su  # noqa: E402

# Campione diversificato (>= 30 titoli): copre gli 8 bucket settoriali
# (industrial_machinery, software_semis, consumer_staples,
# pharma_healthcare, utility_capital_intensive, energy_materials,
# consumer_cyclical, media_telecom) e le 3 fasce di cap (mega/large, mid,
# small/micro) — scelta editoriale per varietà di copertura, non un
# indice o un universo investibile.
SAMPLE_TICKERS = [
    # Software / Semis
    "AAPL", "MSFT", "NVDA", "CRM", "ADBE", "PLTR", "SMCI",
    # Industrial machinery
    "CAT", "HON", "ETN", "GEV",
    # Consumer staples
    "PG", "KO", "PEP", "CL",
    # Pharma / healthcare
    "JNJ", "LLY", "PFE", "MRNA",
    # Utility / capital intensive
    "NEE", "DUK", "SO",
    # Energy / materials
    "XOM", "CVX", "NEM", "FCX",
    # Consumer cyclical
    "AMZN", "MCD", "NKE", "TSLA",
    # Media / telecom
    "DIS", "CMCSA", "TMUS",
    # Small/mid cap variety
    "ETSY", "RIVN", "CROX",
]

BAND_ORDER = ["Scarso", "Debole", "Sufficiente", "Discreto", "Buono", "Eccellente"]
DOMINANT_BAND_THRESHOLD = 0.80


def _distribution(values: list[float]) -> dict:
    if not values:
        return {}
    values_sorted = sorted(values)
    n = len(values_sorted)
    q1 = values_sorted[int(0.25 * (n - 1))]
    q3 = values_sorted[int(0.75 * (n - 1))]
    return {
        "n": n,
        "min": min(values_sorted),
        "max": max(values_sorted),
        "median": stats.median(values_sorted),
        "q1": q1,
        "q3": q3,
        "std": stats.pstdev(values_sorted) if n > 1 else 0.0,
    }


def _band_concentration(scores: list[float]) -> tuple[str, float]:
    counts = {}
    for s in scores:
        band = fscore.score_band_label(s)
        counts[band] = counts.get(band, 0) + 1
    if not counts:
        return "n/d", 0.0
    dominant_band, dominant_n = max(counts.items(), key=lambda kv: kv[1])
    return dominant_band, dominant_n / len(scores)


def main():
    quality_scores, valuation_scores = [], []
    skipped = []
    print(f"Analisi di {len(SAMPLE_TICKERS)} titoli (rete richiesta, yfinance)...\n")

    for symbol in SAMPLE_TICKERS:
        try:
            result = fscore.build_fundamental_score(symbol)
        except Exception as exc:  # yfinance/rete non disponibile per questo titolo
            skipped.append((symbol, f"errore: {exc}"))
            continue
        if result.get("excluded"):
            skipped.append((symbol, "settore escluso (finanziario)"))
            continue
        q, v = result["quality"].get("score"), result["valuation"].get("score")
        bucket = result.get("bucket_label", "n/d")
        cap = result.get("cap_bucket", "n/d")
        if q is not None:
            quality_scores.append(q)
        if v is not None:
            valuation_scores.append(v)
        print(f"  {symbol:<8} bucket={bucket:<28} cap={cap:<12} Quality={q if q is not None else 'n/d':<6} Valuation={v if v is not None else 'n/d'}")

    print("\n--- Distribuzione asse QUALITY ---")
    q_dist = _distribution(quality_scores)
    print(q_dist)
    q_band, q_conc = _band_concentration(quality_scores)
    print(f"Banda dominante: {q_band} ({q_conc*100:.0f}% dei titoli)")
    if q_conc > DOMINANT_BAND_THRESHOLD:
        print("ATTENZIONE: oltre l'80% dei titoli in una singola banda — l'asse Quality non discrimina abbastanza su questo campione.")

    print("\n--- Distribuzione asse VALUATION ---")
    v_dist = _distribution(valuation_scores)
    print(v_dist)
    v_band, v_conc = _band_concentration(valuation_scores)
    print(f"Banda dominante: {v_band} ({v_conc*100:.0f}% dei titoli)")
    if v_conc > DOMINANT_BAND_THRESHOLD:
        print(
            "ATTENZIONE: oltre l'80% dei titoli in una singola banda — l'asse Valuation non discrimina "
            "abbastanza su questo campione. Per la spec v2.1 (FIX9), la risposta NON è ammorbidire le "
            "soglie assolute, ma aggiungere un secondo livello di lettura RELATIVO all'universo "
            "portafoglio+preferiti dell'utente, etichettato distintamente dal punteggio assoluto."
        )

    if skipped:
        print(f"\nTitoli saltati ({len(skipped)}):")
        for sym, reason in skipped:
            print(f"  {sym}: {reason}")


if __name__ == "__main__":
    main()
