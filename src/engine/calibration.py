"""
Calibrazione della confidenza — src/engine/calibration.py

Stage 4 di BACKTEST AND FORWARD.pdf. Risponde a una domanda precisa: il
punteggio di confidenza **significa** quello che dice? Se i segnali
etichettati "70 di confidenza" vincono davvero circa il 70% delle volte,
il punteggio è calibrato; se vincono il 40%, quel numero è decorazione.

Il modo di misurarlo è il diagramma di affidabilità: si raggruppano i
trade chiusi per banda di confidenza, si calcola il win rate realizzato
di ogni banda e lo si confronta con la confidenza predetta. Un sistema
ben calibrato sta vicino alla diagonale a 45°.

**Perché serve prima di toccare la leva.** La specifica lo pone come
cancello empirico allo Stage 4: la leva scalata sulla confidenza è
difendibile solo se la confidenza è calibrata, perché la leva amplifica
l'errore di stima. Scalare la size su un punteggio non calibrato
significa mettere più capitale proprio dove il modello si illude di più.

**Gli intervalli di Wilson su ogni banda non sono un ornamento.** Con
pochi trade per bucket — la condizione normale per mesi — il win rate di
una banda oscilla enormemente. Senza intervallo si leggerebbe una banda
da 6 trade come se dicesse qualcosa, e si sbloccherebbe la leva su
rumore. Una banda è considerata calibrata solo se la confidenza predetta
**cade dentro** l'intervallo di confidenza del win rate realizzato.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.engine.metrics import wilson_interval

# Bande allineate a quelle della mappa confidenza→leva in src/engine/risk.py:
# calibrare su intervalli diversi da quelli su cui si deciderebbe la leva
# non direbbe nulla di utile.
CONFIDENCE_BUCKETS = [
    (50, 69, "50-69"),
    (70, 84, "70-84"),
    (85, 100, "85-100"),
]

# Trade minimi perché una banda sia interpretabile. Sotto questa soglia il
# bucket viene mostrato ma dichiarato non interpretabile: è il punto in
# cui un diagramma di affidabilità inganna più facilmente.
MIN_TRADES_PER_BUCKET = 20

# Trade totali minimi prima che la calibrazione possa essere considerata
# un cancello superato (Stage 3 della specifica: 50-100 trade chiusi).
MIN_TOTAL_TRADES_FOR_GATE = 50


@dataclass
class BucketCalibration:
    label: str
    lo: int
    hi: int
    n_trades: int
    predicted_win_rate: float | None      # centro della banda, in frazione
    realized_win_rate: float | None
    ci_low: float | None
    ci_high: float | None
    avg_r: float | None
    is_interpretable: bool = False

    @property
    def is_calibrated(self) -> bool:
        """La confidenza predetta cade dentro l'intervallo di Wilson del
        win rate realizzato. Con pochi trade l'intervallo è largo e quasi
        tutto risulta "calibrato": per questo il giudizio vale solo se il
        bucket è interpretabile."""
        if not self.is_interpretable or self.predicted_win_rate is None:
            return False
        if self.ci_low is None or self.ci_high is None:
            return False
        return self.ci_low <= self.predicted_win_rate <= self.ci_high

    @property
    def error(self) -> float | None:
        if self.predicted_win_rate is None or self.realized_win_rate is None:
            return None
        return self.realized_win_rate - self.predicted_win_rate


@dataclass
class CalibrationReport:
    buckets: list[BucketCalibration] = field(default_factory=list)
    n_trades: int = 0
    n_with_confidence: int = 0
    mean_absolute_error: float | None = None
    leverage_gate_passed: bool = False
    gate_reason: str = ""
    notes: list[str] = field(default_factory=list)


def _is_winner(net_pnl, net_r) -> bool:
    """Vincente si giudica sul netto, coerentemente con il resto del
    motore: un trade positivo al lordo ma negativo dopo i costi non è una
    vittoria."""
    try:
        if net_pnl is not None and not pd.isna(net_pnl):
            return float(net_pnl) > 0
    except (TypeError, ValueError):
        pass
    try:
        return float(net_r) > 0
    except (TypeError, ValueError):
        return False


def build_calibration(closed_trades: pd.DataFrame) -> CalibrationReport:
    """Diagramma di affidabilità sui trade chiusi.

    `closed_trades` deve avere le colonne `confidence`, `net_pnl_eur` e
    `net_r` (il formato prodotto da src/engine/paper.py). I trade senza
    confidenza registrata vengono contati ma esclusi dai bucket, e la cosa
    è dichiarata invece di essere ignorata."""
    report = CalibrationReport()
    if closed_trades is None or closed_trades.empty:
        report.gate_reason = "Nessun trade chiuso: la calibrazione non è ancora calcolabile."
        return report

    df = closed_trades.copy()
    report.n_trades = len(df)

    df["_conf"] = pd.to_numeric(df.get("confidence"), errors="coerce")
    with_conf = df[df["_conf"].notna()]
    report.n_with_confidence = len(with_conf)
    if report.n_with_confidence < report.n_trades:
        report.notes.append(
            f"{report.n_trades - report.n_with_confidence} trade su {report.n_trades} non hanno una "
            "confidenza registrata e restano fuori dai bucket."
        )

    errors = []
    for lo, hi, label in CONFIDENCE_BUCKETS:
        subset = with_conf[(with_conf["_conf"] >= lo) & (with_conf["_conf"] <= hi)]
        n = len(subset)
        predicted = (lo + hi) / 2 / 100.0

        if n == 0:
            report.buckets.append(BucketCalibration(label, lo, hi, 0, predicted,
                                                     None, None, None, None, False))
            continue

        wins = sum(1 for _, t in subset.iterrows()
                   if _is_winner(t.get("net_pnl_eur"), t.get("net_r")))
        realized = wins / n
        ci_low, ci_high = wilson_interval(wins, n)
        avg_r = pd.to_numeric(subset.get("net_r"), errors="coerce").dropna()
        bucket = BucketCalibration(
            label=label, lo=lo, hi=hi, n_trades=n, predicted_win_rate=predicted,
            realized_win_rate=realized, ci_low=ci_low, ci_high=ci_high,
            avg_r=float(avg_r.mean()) if not avg_r.empty else None,
            is_interpretable=n >= MIN_TRADES_PER_BUCKET,
        )
        report.buckets.append(bucket)
        if bucket.is_interpretable:
            errors.append(abs(realized - predicted))

    if errors:
        report.mean_absolute_error = float(np.mean(errors))

    report.leverage_gate_passed, report.gate_reason = _evaluate_gate(report)
    return report


def _evaluate_gate(report: CalibrationReport) -> tuple[bool, str]:
    """Cancello per lo sblocco della leva scalata sulla confidenza.

    Deliberatamente severo: la leva è la funzione a rischio più alto
    dell'intero sistema, e sbloccarla su un campione insufficiente
    concentrerebbe capitale proprio dove l'errore di stima è massimo."""
    if report.n_with_confidence < MIN_TOTAL_TRADES_FOR_GATE:
        return False, (
            f"Servono almeno {MIN_TOTAL_TRADES_FOR_GATE} trade chiusi con confidenza registrata: "
            f"ora sono {report.n_with_confidence}. Fino ad allora la leva resta a 1,0×."
        )

    interpretable = [b for b in report.buckets if b.is_interpretable]
    if not interpretable:
        return False, (
            f"Nessuna banda ha raggiunto i {MIN_TRADES_PER_BUCKET} trade necessari per essere "
            "interpretabile: il campione è distribuito troppo sottilmente tra le bande."
        )

    non_calibrated = [b for b in interpretable if not b.is_calibrated]
    if non_calibrated:
        etichette = ", ".join(b.label for b in non_calibrated)
        return False, (
            f"Bande non calibrate: {etichette}. La confidenza predetta cade fuori dall'intervallo "
            "di Wilson del win rate realizzato, quindi il punteggio non vale quello che promette."
        )

    return True, (
        f"Tutte le bande interpretabili ({len(interpretable)}) risultano calibrate su "
        f"{report.n_with_confidence} trade. È la condizione empirica che la specifica richiede "
        "prima di considerare la leva scalata sulla confidenza — restano validi i tetti rigidi."
    )


def reliability_points(report: CalibrationReport) -> pd.DataFrame:
    """Dati pronti per il diagramma di affidabilità (il rendering resta
    nella pagina, questo modulo non dipende dalla grafica)."""
    rows = []
    for b in report.buckets:
        rows.append({
            "Banda": b.label,
            "Trade": b.n_trades,
            "Confidenza predetta": b.predicted_win_rate,
            "Win rate realizzato": b.realized_win_rate,
            "CI 95% basso": b.ci_low,
            "CI 95% alto": b.ci_high,
            "R medio": b.avg_r,
            "Interpretabile": b.is_interpretable,
            "Calibrata": b.is_calibrated,
        })
    return pd.DataFrame(rows)
