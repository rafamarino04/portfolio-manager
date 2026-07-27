"""Test per la gerarchia dei timeframe (Prompt_Cowork_Gerarchia_Orizzonti.md)
aggiunta a src/technical.py: classify_horizon_alignment (FIX 2),
plan_alignment_warning (FIX 4), multi_horizon_summary/_build_hierarchy_reading
(FIX 5) e il bug del buffer ATR non dichiarato in trade_plan (FIX 7).

Le funzioni di allineamento operano su dizionari "snapshot" già calcolati:
qui li costruiamo a mano (niente rete, niente yfinance) per testare la
logica in isolamento e in modo deterministico — i sei criteri di
validazione della spec (tutti concordi / breve discorde dal medio / medio
discorde dal lungo / superiore laterale / orizzonte lungo / quadro non
direzionale) sono coperti uno a uno più sotto.

Un test di integrazione con una serie storica sintetica (senza rete)
verifica poi che l'intera pipeline (technical_snapshot -> multi_horizon_analysis)
non vada in eccezione e produca una struttura coerente.
"""
import re

import numpy as np
import pandas as pd
import pytest

from src import technical as tech


# ---------------------------------------------------------------------------
# Helper per costruire snapshot minimi (solo le chiavi lette dalle funzioni
# di gerarchia) e piani operativi minimi.
# ---------------------------------------------------------------------------

def _snap(trend_simple: str, verdict_label: str, D: float, A: float = 0.7) -> dict:
    return {
        "trend": trend_simple,
        "trend_detail": {"verdict_simple": trend_simple, "verdict_label": verdict_label},
        "synthesis": {"D": D, "A": A, "verdict": "test"},
    }


def _plan(bias: str, rr: float | None = None, rr_unfavorable: bool = False) -> dict:
    return {"bias": bias, "risk_reward": rr, "rr_unfavorable": rr_unfavorable}


# ---------------------------------------------------------------------------
# FIX 2 — classify_horizon_alignment
# ---------------------------------------------------------------------------

def test_alignment_concorde_quando_direzioni_coincidono():
    breve = _snap("rialzista", "Rialzista (alta confidenza)", 0.6)
    medio = _snap("rialzista", "Rialzista (alta confidenza)", 0.65)
    out = tech.classify_horizon_alignment(breve, medio, "medio")
    assert out["status"] == "CONCORDE"
    assert out["superior_horizon"] == "medio"
    assert out["superior_verdict_label"] == "Rialzista (alta confidenza)"


def test_alignment_discorde_quando_direzioni_opposte():
    breve = _snap("rialzista", "Rialzista con rimbalzo in corso", 0.4)
    medio = _snap("ribassista", "Ribassista (alta confidenza)", -0.7)
    out = tech.classify_horizon_alignment(breve, medio, "medio")
    assert out["status"] == "DISCORDE"


def test_alignment_neutro_quando_superiore_laterale():
    breve = _snap("rialzista", "Rialzista (media confidenza)", 0.5)
    medio = _snap("laterale", "Laterale / senza trend", 0.05)
    out = tech.classify_horizon_alignment(breve, medio, "medio")
    assert out["status"] == "NEUTRO"


def test_alignment_neutro_quando_superiore_sotto_soglia_direzionalita():
    breve = _snap("rialzista", "Rialzista (media confidenza)", 0.5)
    medio = _snap("rialzista", "Rialzista (media confidenza)", 0.1)  # |D| < 0.20
    out = tech.classify_horizon_alignment(breve, medio, "medio")
    assert out["status"] == "NEUTRO"


def test_alignment_neutro_quando_selezionato_laterale_ma_superiore_direzionale():
    """Caso non esplicitamente coperto dalla spec (che parla solo del
    superiore laterale/debole): un selezionato laterale non "coincide" né è
    "opposto" al superiore, quindi non è né CONCORDE né DISCORDE — scelta
    editoriale dichiarata nel docstring di classify_horizon_alignment."""
    breve = _snap("laterale", "Laterale / senza trend", 0.05)
    medio = _snap("ribassista", "Ribassista (alta confidenza)", -0.8)
    out = tech.classify_horizon_alignment(breve, medio, "medio")
    assert out["status"] == "NEUTRO"


def test_alignment_nd_su_orizzonte_piu_alto_della_catena():
    lungo = _snap("rialzista", "Rialzista (alta confidenza)", 0.7)
    out = tech.classify_horizon_alignment(lungo, None, None)
    assert out["status"] == "N/D"
    assert out["reason"] == "orizzonte_massimo"
    assert out["superior_horizon"] is None


def test_alignment_nd_quando_dati_superiore_mancanti():
    breve = _snap("rialzista", "Rialzista (alta confidenza)", 0.7)
    out = tech.classify_horizon_alignment(breve, None, "medio")
    assert out["status"] == "N/D"
    assert out["reason"] == "dati_insufficienti"


# ---------------------------------------------------------------------------
# FIX 4 — plan_alignment_warning (etichettatura contro-trend)
# ---------------------------------------------------------------------------

def test_plan_alignment_warning_contro_trend_segnala_senza_sopprimere():
    plan = _plan("long")  # bias rialzista sull'orizzonte selezionato
    superior = _snap("ribassista", "Ribassista (alta confidenza)", -0.7)
    warn = tech.plan_alignment_warning(plan, superior, "medio")
    assert warn is not None
    assert warn["is_contro_trend"] is True
    assert "CONTRO-TREND" not in warn["text"]  # l'etichetta la mette la UI col badge, il testo descrive
    assert "rimbalzo" in warn["text"].lower() or "pullback" in warn["text"].lower()
    assert "ribassista" in warn["text"]
    assert "medio" in warn["text"]


def test_plan_alignment_warning_collega_rr_sfavorevole_quando_presente():
    plan = _plan("short", rr=0.8, rr_unfavorable=True)
    superior = _snap("rialzista", "Rialzista (alta confidenza)", 0.6)
    warn = tech.plan_alignment_warning(plan, superior, "lungo")
    assert warn is not None
    assert "0.80" in warn["text"]
    assert "non è una coincidenza" in warn["text"]


def test_plan_alignment_warning_nessun_avviso_se_coerente_col_superiore():
    plan = _plan("long")
    superior = _snap("rialzista", "Rialzista (alta confidenza)", 0.6)
    assert tech.plan_alignment_warning(plan, superior, "medio") is None


def test_plan_alignment_warning_nessun_avviso_se_superiore_laterale():
    """Criterio di validazione #4: orizzonte superiore laterale -> nessun
    avviso di conflitto, anche se il piano ha una direzione netta."""
    plan = _plan("long")
    superior = _snap("laterale", "Laterale / senza trend", 0.02)
    assert tech.plan_alignment_warning(plan, superior, "medio") is None


def test_plan_alignment_warning_nessun_avviso_su_orizzonte_massimo():
    """Criterio di validazione #5: analisi sull'orizzonte lungo, nessun
    superiore -> nessun avviso, nessun errore."""
    plan = _plan("short")
    assert tech.plan_alignment_warning(plan, None, None) is None


def test_plan_alignment_warning_nessun_avviso_se_nessun_piano():
    """Criterio di validazione #6: quadro non direzionale -> bias
    'nessun_setup', nessun piano da etichettare."""
    plan = _plan("nessun_setup")
    superior = _snap("ribassista", "Ribassista (alta confidenza)", -0.8)
    assert tech.plan_alignment_warning(plan, superior, "medio") is None


# ---------------------------------------------------------------------------
# FIX 5 — multi_horizon_summary / _build_hierarchy_reading
# ---------------------------------------------------------------------------

def _multi_from_snaps(breve, medio, lungo, align_breve, align_medio):
    """Costruisce l'oggetto 'multi' nello stesso formato di
    multi_horizon_analysis(), per testare multi_horizon_summary() senza
    rete."""
    return {
        "breve": {"snapshot": breve, "synthesis": breve["synthesis"], "interpretation": [],
                   "alignment": align_breve, "superior_snapshot": medio},
        "medio": {"snapshot": medio, "synthesis": medio["synthesis"], "interpretation": [],
                   "alignment": align_medio, "superior_snapshot": lungo},
        "lungo": {"snapshot": lungo, "synthesis": lungo["synthesis"], "interpretation": [],
                   "alignment": {"status": "N/D", "superior_horizon": None, "reason": "orizzonte_massimo",
                                 "superior_label": None, "superior_verdict_label": None,
                                 "superior_trend_simple": None, "superior_D": None},
                   "superior_snapshot": None},
    }


def test_criterio_1_tutti_concordi(monkeypatch):
    """Criterio di validazione #1: tutti gli orizzonti concordi ->
    CONCORDE ovunque, sintesi coerente."""
    breve = _snap("rialzista", "Rialzista (alta confidenza)", 0.6)
    medio = _snap("rialzista", "Rialzista (alta confidenza)", 0.65)
    lungo = _snap("rialzista", "Rialzista (alta confidenza)", 0.7)
    align_breve = tech.classify_horizon_alignment(breve, medio, "medio")
    align_medio = tech.classify_horizon_alignment(medio, lungo, "lungo")
    assert align_breve["status"] == align_medio["status"] == "CONCORDE"

    monkeypatch.setattr(tech, "trade_plan", lambda snap: {"bias": "long"} if snap is breve else
                         ({"bias": "long"} if snap is medio else {"bias": "long"}))
    multi = _multi_from_snaps(breve, medio, lungo, align_breve, align_medio)
    summary = tech.multi_horizon_summary(multi)
    assert summary["reading"] == "Tutti gli orizzonti concordano: quadro rialzista su breve, medio e lungo."
    assert all(r["plan_direction"] == "long" for r in summary["rows"])


def test_criterio_2_breve_discorde_dal_medio(monkeypatch):
    """Criterio di validazione #2: breve discorde dal medio -> DISCORDE,
    piano di breve etichettabile contro-trend."""
    breve = _snap("rialzista", "Rialzista con rimbalzo in corso", 0.35)
    medio = _snap("ribassista", "Ribassista (alta confidenza)", -0.7)
    lungo = _snap("ribassista", "Ribassista (alta confidenza)", -0.75)
    align_breve = tech.classify_horizon_alignment(breve, medio, "medio")
    align_medio = tech.classify_horizon_alignment(medio, lungo, "lungo")
    assert align_breve["status"] == "DISCORDE"
    assert align_medio["status"] == "CONCORDE"

    breve_plan = _plan("long")
    warn = tech.plan_alignment_warning(breve_plan, medio, "medio")
    assert warn is not None and warn["is_contro_trend"]

    monkeypatch.setattr(tech, "trade_plan", lambda snap: {"bias": "long"} if snap is breve else
                         {"bias": "short"})
    multi = _multi_from_snaps(breve, medio, lungo, align_breve, align_medio)
    summary = tech.multi_horizon_summary(multi)
    assert "Rimbalzo di breve dentro un trend ribassista di medio termine" in summary["reading"]


def test_criterio_3_medio_discorde_dal_lungo():
    """Criterio di validazione #3: stessa logica applicata al livello
    superiore della catena (medio vs lungo)."""
    breve = _snap("rialzista", "Rialzista (alta confidenza)", 0.6)
    medio = _snap("rialzista", "Rialzista (alta confidenza)", 0.6)
    lungo = _snap("ribassista", "Ribassista (alta confidenza)", -0.7)
    align_breve = tech.classify_horizon_alignment(breve, medio, "medio")
    align_medio = tech.classify_horizon_alignment(medio, lungo, "lungo")
    assert align_breve["status"] == "CONCORDE"
    assert align_medio["status"] == "DISCORDE"

    multi = _multi_from_snaps(breve, medio, lungo, align_breve, align_medio)
    reading = tech._build_hierarchy_reading(tech.multi_horizon_summary(multi)["rows"])
    assert "Possibile inversione di medio termine contro il trend di lungo" in reading


def test_criterio_4_superiore_laterale_neutro_senza_falsa_conferma():
    """Criterio di validazione #4: orizzonte superiore laterale ->
    allineamento NEUTRO, nessun avviso di conflitto ma nessuna falsa
    conferma nel testo generato."""
    breve = _snap("rialzista", "Rialzista (media confidenza)", 0.5)
    medio = _snap("laterale", "Laterale / senza trend", 0.05)
    align = tech.classify_horizon_alignment(breve, medio, "medio")
    assert align["status"] == "NEUTRO"
    assert tech.plan_alignment_warning(_plan("long"), medio, "medio") is None


def test_criterio_5_orizzonte_lungo_nd_gestito_senza_errori():
    """Criterio di validazione #5: nessun riferimento a un orizzonte
    superiore inesistente quando si analizza il lungo termine."""
    lungo = _snap("ribassista", "Ribassista (media confidenza)", -0.5)
    align = tech.classify_horizon_alignment(lungo, None, None)
    assert align["status"] == "N/D"
    assert align["superior_horizon"] is None
    assert align["superior_label"] is None


def test_criterio_6_quadro_non_direzionale_nessun_piano(monkeypatch):
    """Criterio di validazione #6: quadro non direzionale su un orizzonte
    -> nessun piano, la sintesi multi-orizzonte lo riporta come tale."""
    breve = _snap("laterale", "Laterale / senza trend", 0.05)
    medio = _snap("rialzista", "Rialzista (alta confidenza)", 0.5)
    lungo = _snap("rialzista", "Rialzista (alta confidenza)", 0.5)
    align_breve = tech.classify_horizon_alignment(breve, medio, "medio")
    align_medio = tech.classify_horizon_alignment(medio, lungo, "lungo")

    monkeypatch.setattr(tech, "trade_plan", lambda snap: {"bias": "nessun_setup"} if snap is breve else
                         {"bias": "long"})
    multi = _multi_from_snaps(breve, medio, lungo, align_breve, align_medio)
    summary = tech.multi_horizon_summary(multi)
    rows_by_h = {r["horizon"]: r for r in summary["rows"]}
    assert rows_by_h["breve"]["plan_direction"] == "nessun_piano"


# ---------------------------------------------------------------------------
# overall_confidence (FIX 3, confidenza complessiva)
# ---------------------------------------------------------------------------

def test_overall_confidence_pesa_di_piu_il_conflitto_del_neutro():
    concorde = tech.overall_confidence(0.8, "CONCORDE")
    neutro = tech.overall_confidence(0.8, "NEUTRO")
    discorde = tech.overall_confidence(0.8, "DISCORDE")
    assert concorde == 0.8
    assert discorde < neutro < concorde


# ---------------------------------------------------------------------------
# FIX 7 — il bug del buffer ATR non dichiarato in trade_plan()
# ---------------------------------------------------------------------------

def _fake_snap_for_plan(price, atr, D, A=0.7, supports=(), resistances=(), chart_patterns=()):
    sr = ([{"level": s, "role": "supporto"} for s in supports] +
          [{"level": r, "role": "resistenza"} for r in resistances])
    return {
        "price": price, "atr": atr,
        "synthesis": {"D": D, "A": A, "verdict": "test"},
        "support_resistance": sr,
        "chart_patterns": list(chart_patterns),
    }


def _basis_number(text: str) -> float:
    """Estrae l'ultimo numero in fondo a una stringa di spiegazione livelli
    (dopo '=', es. '... = 96.00', oppure il livello S/R citato direttamente,
    es. '... a 108.00') — usato per verificare che il testo non contraddica
    mai il valore numerico effettivamente usato dal piano (FIX 7)."""
    match = re.search(r"(-?\d+(?:[.,]\d+)?)\s*$", text.strip())
    assert match, f"nessun valore numerico trovato in fondo al testo: {text!r}"
    return float(match.group(1).replace(",", "."))


def test_trade_plan_stop_basis_dichiara_il_buffer_atr_long():
    snap = _fake_snap_for_plan(price=100.0, atr=2.0, D=0.5, supports=[97.0], resistances=[110.0])
    plan = tech.trade_plan(snap)
    assert plan["bias"] == "long"
    # Bug originale: il testo diceva solo "leggermente sotto il supporto",
    # senza menzionare il buffer di 0.5*ATR effettivamente sottratto.
    assert "leggermente" not in plan["stop_basis"]
    assert "buffer" in plan["stop_basis"]
    assert "ATR" in plan["stop_basis"]
    # Lo stop reale è 97 - 0.5*2 = 96.0: il testo deve dichiararlo esplicitamente.
    assert plan["stop"] == pytest.approx(96.0)
    assert _basis_number(plan["stop_basis"]) == pytest.approx(plan["stop"], abs=0.01)


def test_trade_plan_stop_basis_dichiara_il_buffer_atr_short():
    snap = _fake_snap_for_plan(price=100.0, atr=2.0, D=-0.5, supports=[90.0], resistances=[103.0])
    plan = tech.trade_plan(snap)
    assert plan["bias"] == "short"
    assert "leggermente" not in plan["stop_basis"]
    assert "buffer" in plan["stop_basis"]
    assert plan["stop"] == pytest.approx(104.0)  # 103 + 0.5*2
    assert _basis_number(plan["stop_basis"]) == pytest.approx(plan["stop"], abs=0.01)


def test_trade_plan_stop_basis_senza_livello_vicino_dichiara_atr_puro():
    snap = _fake_snap_for_plan(price=100.0, atr=2.0, D=0.5, supports=[50.0])  # troppo lontano (> 3*ATR)
    plan = tech.trade_plan(snap)
    assert "nessun supporto" in plan["stop_basis"]
    assert plan["stop"] == pytest.approx(97.0)  # 100 - 1.5*2
    assert _basis_number(plan["stop_basis"]) == pytest.approx(plan["stop"], abs=0.01)


def test_trade_plan_target_basis_sceglie_e_dichiara_il_livello_piu_vicino():
    snap = _fake_snap_for_plan(
        price=100.0, atr=2.0, D=0.5, supports=[97.0], resistances=[110.0],
        chart_patterns=[{"target": 108.0, "direction": "rialzista", "state": "completato"}],
    )
    plan = tech.trade_plan(snap)
    assert plan["target"] == pytest.approx(108.0)
    assert "obiettivo di figura" in plan["target_basis"]
    assert "108" in plan["target_basis"]
    assert _basis_number(plan["target_basis"]) == pytest.approx(plan["target"], abs=0.01)


def test_trade_plan_target_basis_senza_livelli_dichiara_atr_puro():
    snap = _fake_snap_for_plan(price=100.0, atr=2.0, D=0.5, supports=[97.0])  # nessuna resistenza/pattern
    plan = tech.trade_plan(snap)
    assert plan["target"] == pytest.approx(104.0)  # 100 + 2*2
    assert "nessuna resistenza" in plan["target_basis"]
    assert _basis_number(plan["target_basis"]) == pytest.approx(plan["target"], abs=0.01)


def test_trade_plan_nessun_setup_sotto_soglia_direzionalita():
    snap = _fake_snap_for_plan(price=100.0, atr=2.0, D=0.05, A=0.9)
    plan = tech.trade_plan(snap)
    assert plan["bias"] == "nessun_setup"


# ---------------------------------------------------------------------------
# Integrazione: pipeline completa su una serie storica sintetica (nessuna
# rete). Verifica che technical_snapshot -> multi_horizon_analysis non vada
# in eccezione e che l'orizzonte lungo risulti sempre N/D per costruzione
# (nessun orizzonte superiore possibile), indipendentemente dai dati.
# ---------------------------------------------------------------------------

def _make_synthetic_history(n=900, drift=0.0012, noise=0.006, start=100.0, seed=42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = rng.normal(drift, noise, n)
    close = start * np.exp(np.cumsum(steps))
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    base_high = np.maximum(close, np.roll(close, 1))
    base_low = np.minimum(close, np.roll(close, 1))
    high = base_high * (1 + rng.uniform(0.0005, 0.006, n))
    low = base_low * (1 - rng.uniform(0.0005, 0.006, n))
    open_ = close * (1 + rng.normal(0, 0.002, n))
    volume = rng.integers(1_000_000, 5_000_000, n).astype(float)
    df = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=idx)
    df.iloc[0, df.columns.get_loc("High")] = max(df.iloc[0]["Open"], df.iloc[0]["Close"]) * 1.001
    df.iloc[0, df.columns.get_loc("Low")] = min(df.iloc[0]["Open"], df.iloc[0]["Close"]) * 0.999
    return df


def test_pipeline_completa_multi_horizon_analysis_senza_eccezioni(monkeypatch):
    synthetic = _make_synthetic_history()
    monkeypatch.setattr(tech.dp, "get_history", lambda symbol, period="6mo", interval="1d": synthetic)

    multi = tech.multi_horizon_analysis("SYN.TEST")

    assert set(multi.keys()) == {"breve", "medio", "lungo"}
    for h in tech.HORIZON_CHAIN:
        entry = multi[h]
        assert entry["snapshot"] is not None
        assert entry["alignment"]["status"] in {"CONCORDE", "DISCORDE", "NEUTRO", "N/D"}

    # L'orizzonte più alto della catena non ha mai un superiore, qualunque
    # sia la serie storica in ingresso.
    assert multi["lungo"]["alignment"]["status"] == "N/D"
    assert multi["lungo"]["alignment"]["superior_horizon"] is None
    assert multi["lungo"]["superior_snapshot"] is None

    summary = tech.multi_horizon_summary(multi)
    assert len(summary["rows"]) == 3
    assert isinstance(summary["reading"], str) and summary["reading"]
