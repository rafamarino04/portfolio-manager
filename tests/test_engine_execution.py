"""Test delle regole di esecuzione del motore (src/engine/execution.py e
il bar loop in src/engine/core.py).

Sono i test più importanti dell'intero progetto: le tre regole verificate
qui — fill al next-bar-open, stop-first sull'ambiguità intrabar, gap
pagati al prezzo reale — sono esattamente i punti in cui un backtest
smette di dire la verità. Un errore qui non produce un crash: produce
risultati più belli del reale, che è molto peggio.

Tutti i test usano barre costruite a mano con valori scelti perché
l'esito atteso sia calcolabile a mente, senza dati di mercato né rete.
"""
import numpy as np
import pandas as pd
import pytest

from src.engine import core
from src.engine import execution as ex
from src.engine import signals as sig
from src.engine.core import BacktestConfig
from src.engine.costs import CostModel
from src.engine.risk import RiskConfig


# ---------------------------------------------------------------------------
# Regola 2 — ambiguità intrabar risolta con stop-first
# ---------------------------------------------------------------------------

def test_stop_first_quando_il_bar_contiene_sia_stop_sia_target_long():
    """Il caso decisivo: con barre daily non si sa se sia arrivato prima
    il massimo o il minimo. Si deve assumere l'esito peggiore."""
    event = ex.resolve_exit("long", stop=95, target=105, bar_open=100, bar_high=106, bar_low=94)
    assert event.reason == "stop"
    assert event.price == 95
    assert event.is_stop


def test_stop_first_quando_il_bar_contiene_sia_stop_sia_target_short():
    event = ex.resolve_exit("short", stop=105, target=95, bar_open=100, bar_high=106, bar_low=94)
    assert event.reason == "stop"
    assert event.price == 105


def test_target_colpito_da_solo_viene_riconosciuto():
    event = ex.resolve_exit("long", stop=95, target=105, bar_open=100, bar_high=106, bar_low=99)
    assert event.reason == "target"
    assert event.price == 105


def test_nessun_livello_toccato_non_produce_uscita():
    assert ex.resolve_exit("long", stop=95, target=105, bar_open=100, bar_high=102, bar_low=98) is None


# ---------------------------------------------------------------------------
# Regola 3 — i gap si pagano al prezzo reale, non al livello teorico
# ---------------------------------------------------------------------------

def test_gap_oltre_lo_stop_riempie_all_open_peggiore_dello_stop():
    event = ex.resolve_exit("long", stop=95, target=105, bar_open=90, bar_high=92, bar_low=88)
    assert event.reason == "gap_stop"
    assert event.price == 90        # non 95: il gap è slippage reale
    assert event.gapped is True


def test_gap_oltre_il_target_riempie_all_open_migliore_del_target():
    event = ex.resolve_exit("long", stop=95, target=105, bar_open=110, bar_high=112, bar_low=109)
    assert event.reason == "gap_target"
    assert event.price == 110
    assert event.gapped is True


def test_gap_su_short_specchiato():
    stop_event = ex.resolve_exit("short", stop=105, target=95, bar_open=110, bar_high=112, bar_low=108)
    assert stop_event.reason == "gap_stop" and stop_event.price == 110
    target_event = ex.resolve_exit("short", stop=105, target=95, bar_open=90, bar_high=92, bar_low=88)
    assert target_event.reason == "gap_target" and target_event.price == 90


def test_gap_enorme_oltre_entrambi_i_livelli_resta_pessimistico():
    """Un'apertura che supera sia stop sia target deve comunque essere
    trattata come stop: l'assunzione conservativa non si sospende proprio
    nei casi estremi, che sono quelli che contano."""
    event = ex.resolve_exit("long", stop=95, target=96, bar_open=90, bar_high=120, bar_low=89)
    assert event.reason == "gap_stop"


def test_r_realizzato_su_gap_peggiore_di_meno_uno_r():
    """La coda sinistra reale è più lunga del −1R pianificato: è
    l'informazione che la leva amplificherebbe e che non va persa."""
    r = ex.realized_r("long", entry_price=100, exit_price=90, risk_per_unit=5)
    assert r == pytest.approx(-2.0)
    assert ex.realized_r("long", entry_price=100, exit_price=95, risk_per_unit=5) == pytest.approx(-1.0)


# ---------------------------------------------------------------------------
# MAE / MFE
# ---------------------------------------------------------------------------

def test_escursioni_mae_mfe_in_multipli_di_r():
    mae, mfe = ex.update_excursions("long", entry_price=100, risk_per_unit=5,
                                     bar_high=110, bar_low=97.5, mae_r=0.0, mfe_r=0.0)
    assert mae == pytest.approx(0.5)   # (100 − 97,5) / 5
    assert mfe == pytest.approx(2.0)   # (110 − 100) / 5


def test_escursioni_non_diminuiscono_mai():
    mae, mfe = ex.update_excursions("long", 100, 5, 110, 90, mae_r=3.0, mfe_r=4.0)
    assert mae == 3.0 and mfe == 4.0


# ---------------------------------------------------------------------------
# Regola 1 — fill al next-bar-open (test sul bar loop completo)
# ---------------------------------------------------------------------------

def _linear_history(n=60, start=100.0, end=160.0, spread=1.0) -> pd.DataFrame:
    """Serie deterministica e monotona: rende l'esito di ogni trade
    calcolabile a mano, senza casualità."""
    idx = pd.bdate_range("2024-01-01", periods=n)
    close = np.linspace(start, end, n)
    return pd.DataFrame({"Open": close, "High": close + spread, "Low": close - spread,
                          "Close": close, "Volume": 1e6}, index=idx)


def _config(**kwargs) -> BacktestConfig:
    defaults = dict(
        horizon="medio", initial_equity_eur=10_000.0,
        risk=RiskConfig(risk_pct=1.0),
        # Costi azzerati dove il test verifica prezzi e R, così i numeri
        # attesi restano calcolabili a mente.
        costs=CostModel(order_fee_eur=0.0, fx_cost_pct_per_leg=0.0, slippage_bps_per_side=0.0),
    )
    defaults.update(kwargs)
    return BacktestConfig(**defaults)


def _run_with_signal(hist: pd.DataFrame, signal_fn, monkeypatch, config=None, **run_kwargs):
    monkeypatch.setattr(sig, "generate_signal", signal_fn)
    monkeypatch.setattr(sig, "warmup_bars", lambda horizon: 5)
    return core.run_backtest({"TEST": hist}, config=config or _config(),
                              currencies={"TEST": "EUR"}, **run_kwargs)


def test_ingresso_al_next_bar_open_non_al_close_del_segnale(monkeypatch):
    """Il bug di look-ahead classico: eseguire sullo stesso close usato per
    generare il segnale. Qui si verifica che l'ingresso avvenga all'apertura
    del bar SUCCESSIVO, e che quel prezzo sia diverso dal close del segnale."""
    hist = _linear_history()

    def signal(symbol, hist_to_date, horizon="medio"):
        if len(hist_to_date) == 11:
            px = float(hist_to_date["Close"].iloc[-1])
            return {"bias": "long", "stop": px - 5, "target": px + 10, "entry": px, "confidence": 70.0}
        return {"bias": "nessun_setup"}

    result = _run_with_signal(hist, signal, monkeypatch)
    assert len(result.ledger.closed_trades) == 1
    trade = result.ledger.closed_trades[0]

    signal_pos = hist.index.get_loc(pd.Timestamp(trade.signal_date))
    next_open = float(hist.iloc[signal_pos + 1]["Open"])
    signal_close = float(hist.iloc[signal_pos]["Close"])

    assert trade.entry_date > trade.signal_date
    assert trade.entry_price == pytest.approx(next_open)
    assert trade.entry_price != pytest.approx(signal_close)


def test_r_ricalcolato_sull_ingresso_effettivo_non_su_quello_pianificato(monkeypatch):
    """Lo stop resta quello pianificato ieri, ma l'ingresso reale è l'open
    di oggi: il rischio iniziale va misurato sull'ingresso effettivo,
    altrimenti gli R non sono confrontabili."""
    hist = _linear_history()
    planned = {}

    def signal(symbol, hist_to_date, horizon="medio"):
        if len(hist_to_date) == 11:
            px = float(hist_to_date["Close"].iloc[-1])
            planned["entry"] = px
            planned["stop"] = px - 5
            return {"bias": "long", "stop": px - 5, "target": px + 10, "entry": px, "confidence": 70.0}
        return {"bias": "nessun_setup"}

    result = _run_with_signal(hist, signal, monkeypatch)
    trade = result.ledger.closed_trades[0]
    assert trade.risk_per_unit == pytest.approx(trade.entry_price - planned["stop"])
    assert trade.risk_per_unit != pytest.approx(planned["entry"] - planned["stop"])


def test_sizing_a_frazione_fissa_del_rischio(monkeypatch):
    """Con rischio all'1% su 10.000 EUR, il −1R del trade deve valere 100
    EUR indipendentemente dal prezzo dello strumento."""
    hist = _linear_history()

    def signal(symbol, hist_to_date, horizon="medio"):
        if len(hist_to_date) == 11:
            px = float(hist_to_date["Close"].iloc[-1])
            return {"bias": "long", "stop": px - 5, "target": px + 10, "entry": px, "confidence": 70.0}
        return {"bias": "nessun_setup"}

    result = _run_with_signal(hist, signal, monkeypatch)
    trade = result.ledger.closed_trades[0]
    assert trade.initial_risk_eur == pytest.approx(100.0, rel=0.01)


def test_nessun_trade_se_il_segnale_non_e_mai_operabile(monkeypatch):
    hist = _linear_history()
    result = _run_with_signal(hist, lambda s, h, horizon="medio": {"bias": "nessun_setup"}, monkeypatch)
    assert result.ledger.closed_trades == []
    assert result.n_signals_actionable == 0
    assert result.n_signals_evaluated > 0


def test_ordine_rifiutato_se_il_gap_apre_gia_oltre_lo_stop(monkeypatch):
    """Se il prezzo di esecuzione è già oltre lo stop pianificato, il trade
    non ha rischio definito e non va aperto: aprirlo comunque falserebbe
    tutti gli R successivi."""
    idx = pd.bdate_range("2024-01-01", periods=30)
    close = np.full(30, 100.0)
    hist = pd.DataFrame({"Open": close.copy(), "High": close + 1, "Low": close - 1,
                          "Close": close, "Volume": 1e6}, index=idx)
    # Il bar di esecuzione apre molto sotto lo stop pianificato.
    hist.iloc[11, hist.columns.get_loc("Open")] = 80.0
    hist.iloc[11, hist.columns.get_loc("Low")] = 79.0

    def signal(symbol, hist_to_date, horizon="medio"):
        if len(hist_to_date) == 11:
            return {"bias": "long", "stop": 95.0, "target": 110.0, "entry": 100.0, "confidence": 70.0}
        return {"bias": "nessun_setup"}

    result = _run_with_signal(hist, signal, monkeypatch)
    assert result.ledger.closed_trades == []
    assert "apertura oltre lo stop pianificato" in result.rejection_reasons


def test_posizioni_aperte_chiuse_forzatamente_a_fine_periodo(monkeypatch):
    """Lasciare fuori i trade ancora aperti renderebbe i risultati
    sistematicamente migliori del reale: le posizioni in perdita tendono a
    restare aperte più a lungo."""
    hist = _linear_history(n=30)

    def signal(symbol, hist_to_date, horizon="medio"):
        # Target irraggiungibile: la posizione resta aperta fino alla fine.
        if len(hist_to_date) == 11:
            px = float(hist_to_date["Close"].iloc[-1])
            return {"bias": "long", "stop": px - 50, "target": px + 10_000, "entry": px, "confidence": 70.0}
        return {"bias": "nessun_setup"}

    result = _run_with_signal(hist, signal, monkeypatch)
    assert len(result.ledger.closed_trades) == 1
    assert result.ledger.closed_trades[0].exit_reason == "chiusura_forzata"
    assert result.ledger.open_positions == {}


def test_i_costi_riducono_il_pnl_netto_rispetto_al_lordo(monkeypatch):
    hist = _linear_history()

    def signal(symbol, hist_to_date, horizon="medio"):
        if len(hist_to_date) == 11:
            px = float(hist_to_date["Close"].iloc[-1])
            return {"bias": "long", "stop": px - 5, "target": px + 10, "entry": px, "confidence": 70.0}
        return {"bias": "nessun_setup"}

    config = _config(costs=CostModel(order_fee_eur=1.0, fx_cost_pct_per_leg=0.5,
                                      slippage_bps_per_side=5.0))
    result = _run_with_signal(hist, signal, monkeypatch, config=config)
    trade = result.ledger.closed_trades[0]
    assert trade.costs_eur > 0
    assert trade.net_pnl_eur < trade.gross_pnl_eur
    assert trade.net_r < trade.gross_r


def test_un_solo_trade_aperto_per_strumento(monkeypatch):
    """Segnale sempre attivo: il motore non deve accumulare posizioni sullo
    stesso strumento, che moltiplicherebbe il rischio senza dichiararlo."""
    hist = _linear_history(n=80)

    def signal(symbol, hist_to_date, horizon="medio"):
        px = float(hist_to_date["Close"].iloc[-1])
        return {"bias": "long", "stop": px - 5, "target": px + 3, "entry": px, "confidence": 70.0}

    result = _run_with_signal(hist, signal, monkeypatch)
    assert len(result.ledger.open_positions) <= 1
    # I trade non si sovrappongono nel tempo sullo stesso simbolo.
    trades = sorted(result.ledger.closed_trades, key=lambda t: t.entry_date)
    for earlier, later in zip(trades, trades[1:]):
        assert later.entry_date >= earlier.exit_date


def test_equity_curve_registrata_ogni_giorno_operativo(monkeypatch):
    """Senza mark-to-market giornaliero il max drawdown risulterebbe più
    piccolo del reale: un drawdown vissuto a posizioni aperte è comunque
    un drawdown."""
    hist = _linear_history(n=40)

    def signal(symbol, hist_to_date, horizon="medio"):
        if len(hist_to_date) == 11:
            px = float(hist_to_date["Close"].iloc[-1])
            return {"bias": "long", "stop": px - 5, "target": px + 10, "entry": px, "confidence": 70.0}
        return {"bias": "nessun_setup"}

    result = _run_with_signal(hist, signal, monkeypatch)
    assert len(result.ledger.equity_curve) > 30
    assert all(len(point) == 3 for point in result.ledger.equity_curve)


# ---------------------------------------------------------------------------
# Filtro sul rapporto rischio/rendimento
# ---------------------------------------------------------------------------

def test_non_esegue_i_piani_che_il_sistema_segnala_sfavorevoli(monkeypatch):
    """Il difetto originale: il motore ignorava `rr_unfavorable` ed eseguiva
    comunque. Il backtest misurava così setup che il sistema stesso dichiara
    da scartare — sui dati reali era il 76% dei trade eseguiti."""
    hist = _linear_history()

    def signal(symbol, hist_to_date, horizon="medio"):
        if len(hist_to_date) == 11:
            px = float(hist_to_date["Close"].iloc[-1])
            # R:R 0,4 — sotto la soglia minima dichiarata dal sistema.
            return {"bias": "long", "stop": px - 5, "target": px + 2, "entry": px,
                    "confidence": 70.0, "risk_reward": 0.4, "rr_unfavorable": True}
        return {"bias": "nessun_setup"}

    result = _run_with_signal(hist, signal, monkeypatch)
    assert result.ledger.closed_trades == []
    assert any("sfavorevole" in reason for reason in result.rejection_reasons)


def test_esegue_i_piani_con_rapporto_favorevole(monkeypatch):
    hist = _linear_history()

    def signal(symbol, hist_to_date, horizon="medio"):
        if len(hist_to_date) == 11:
            px = float(hist_to_date["Close"].iloc[-1])
            return {"bias": "long", "stop": px - 5, "target": px + 10, "entry": px,
                    "confidence": 70.0, "risk_reward": 2.0, "rr_unfavorable": False}
        return {"bias": "nessun_setup"}

    result = _run_with_signal(hist, signal, monkeypatch)
    assert len(result.ledger.closed_trades) == 1


def test_il_filtro_e_disattivabile_per_confronto(monkeypatch):
    """Disattivarlo serve a misurare quanto pesava il difetto, non a
    tornare al comportamento precedente come impostazione normale."""
    hist = _linear_history()

    def signal(symbol, hist_to_date, horizon="medio"):
        if len(hist_to_date) == 11:
            px = float(hist_to_date["Close"].iloc[-1])
            return {"bias": "long", "stop": px - 5, "target": px + 2, "entry": px,
                    "confidence": 70.0, "risk_reward": 0.4, "rr_unfavorable": True}
        return {"bias": "nessun_setup"}

    result = _run_with_signal(hist, signal, monkeypatch,
                               config=_config(skip_unfavorable_rr=False))
    assert len(result.ledger.closed_trades) == 1


def test_il_filtro_e_attivo_di_default():
    assert BacktestConfig().skip_unfavorable_rr is True
