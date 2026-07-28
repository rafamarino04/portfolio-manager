"""Test del forward paper trading (src/engine/paper.py, src/paper_store.py).

Il test più importante è `test_la_barra_parziale_di_oggi_non_e_mai_usata`:
a mercato aperto yfinance restituisce anche la seduta in corso, il cui
"Close" è solo il prezzo dell'istante. Calcolare il segnale su quella
barra darebbe un valore che cambia di minuto in minuto e che non
corrisponde a nulla di ciò che il backtest ha testato — corrompendo
silenziosamente l'intero confronto, che è lo scopo del forward.

Subito dopo vengono i test sul riuso dei moduli del backtest: le regole di
uscita (stop-first, gap) devono essere le stesse, altrimenti una
differenza di risultato tra backtest e paper non è più attribuibile.

Nessun test tocca la rete: prezzi, storici e valute sono iniettati.
"""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from src import paper_store
from src.engine import paper
from src.engine import signals as sig

TODAY = dt.date(2026, 7, 28)


def _history(n=40, start=100.0, end=140.0, end_date=TODAY, spread=1.0) -> pd.DataFrame:
    """Serie deterministica il cui ultimo bar è la seduta di `end_date`
    (cioè quella in corso, da escludere dal segnale)."""
    idx = pd.bdate_range(end=pd.Timestamp(end_date), periods=n)
    close = np.linspace(start, end, n)
    return pd.DataFrame({"Open": close, "High": close + spread, "Low": close - spread,
                          "Close": close, "Volume": 1e6}, index=idx)


def _config(**kwargs) -> paper.PaperConfig:
    defaults = dict(initial_equity_eur=10_000.0, risk_pct=1.0,
                    order_fee_eur=0.0, fx_cost_pct_per_leg=0.0, slippage_bps_per_side=0.0)
    defaults.update(kwargs)
    return paper.PaperConfig(**defaults)


def _long_signal(stop_offset=5.0, target_offset=8.0, confidence=70.0):
    def signal(symbol, hist, horizon="medio"):
        px = float(hist["Close"].iloc[-1])
        return {"bias": "long", "stop": px - stop_offset, "target": px + target_offset,
                "entry": px, "confidence": confidence}
    return signal


def _step(symbols, state, config, price, hist, monkeypatch, signal=None, today=TODAY):
    monkeypatch.setattr(sig, "generate_signal", signal or _long_signal())
    monkeypatch.setattr(sig, "warmup_bars", lambda horizon: 5)
    histories = hist if isinstance(hist, dict) else {s: hist for s in symbols}
    prices = price if isinstance(price, dict) else {s: price for s in symbols}
    return paper.step(symbols, state, config, today=today,
                       price_fn=lambda s: prices.get(s),
                       history_fn=lambda s: histories.get(s),
                       currency_fn=lambda s: "EUR")


# ---------------------------------------------------------------------------
# La barra in corso non deve mai entrare nel segnale
# ---------------------------------------------------------------------------

def test_completed_bars_esclude_la_seduta_in_corso():
    hist = _history(n=10)
    assert hist.index[-1].date() == TODAY
    cut = paper._completed_bars(hist, TODAY)
    assert TODAY not in [ts.date() for ts in cut.index]
    assert len(cut) == len(hist) - 1


def test_la_barra_parziale_di_oggi_non_e_mai_usata(monkeypatch):
    """Il segnale deve vedere il close di IERI, mai il prezzo parziale di
    oggi travestito da close."""
    hist = _history(n=40)
    visto = {}

    def signal(symbol, h, horizon="medio"):
        visto["ultima_data"] = h.index[-1].date()
        visto["ultimo_close"] = float(h["Close"].iloc[-1])
        return {"bias": "nessun_setup"}

    _step(["TEST"], paper.PaperState(), _config(), 999.0, hist, monkeypatch, signal=signal)

    assert visto["ultima_data"] < TODAY
    assert visto["ultimo_close"] == pytest.approx(float(hist.iloc[-2]["Close"]))


def test_storico_di_soli_bar_incompleti_non_apre_nulla(monkeypatch):
    """Se dopo il troncamento non resta abbastanza storico, non si opera."""
    hist = _history(n=3)
    state, events = _step(["TEST"], paper.PaperState(), _config(), 105.0, hist, monkeypatch)
    assert state.open_positions.empty


# ---------------------------------------------------------------------------
# Apertura al prezzo corrente (scelta dichiarata, diversa dal backtest)
# ---------------------------------------------------------------------------

def test_apertura_al_prezzo_corrente_non_al_close_ne_all_apertura(monkeypatch):
    hist = _history(n=40)
    current = 141.5
    state, events = _step(["TEST"], paper.PaperState(), _config(), current, hist, monkeypatch)

    assert len(state.open_positions) == 1
    pos = state.open_positions.iloc[0]
    assert pos["entry_price"] == pytest.approx(current)
    assert pos["entry_price"] != pytest.approx(float(hist.iloc[-2]["Close"]))
    assert any(e.kind == "apertura" for e in events)


def test_registra_l_apertura_di_oggi_come_riferimento(monkeypatch):
    """Serve a misurare il costo del ritardo di esecuzione: è il prezzo a
    cui il backtest sarebbe entrato."""
    hist = _history(n=40)
    state, _ = _step(["TEST"], paper.PaperState(), _config(), 141.5, hist, monkeypatch)
    pos = state.open_positions.iloc[0]
    assert pos["reference_open_price"] == pytest.approx(float(hist.iloc[-1]["Open"]))


def test_sizing_a_frazione_fissa_come_nel_backtest(monkeypatch):
    hist = _history(n=40)
    state, _ = _step(["TEST"], paper.PaperState(), _config(risk_pct=1.0), 141.5, hist, monkeypatch)
    assert float(state.open_positions.iloc[0]["initial_risk_eur"]) == pytest.approx(100.0, rel=0.01)


def test_nessuna_apertura_se_il_prezzo_e_gia_oltre_lo_stop(monkeypatch):
    """Senza rischio definito il trade non si apre, come nel backtest:
    aprirlo falserebbe tutti gli R successivi."""
    hist = _history(n=40)

    def signal(symbol, h, horizon="medio"):
        return {"bias": "long", "stop": 200.0, "target": 300.0, "entry": 150.0, "confidence": 70.0}

    state, events = _step(["TEST"], paper.PaperState(), _config(), 150.0, hist, monkeypatch,
                           signal=signal)
    assert state.open_positions.empty
    assert any("oltre lo stop" in e.message for e in events)


def test_nessuna_apertura_senza_prezzo_corrente(monkeypatch):
    hist = _history(n=40)
    state, events = _step(["TEST"], paper.PaperState(), _config(), None, hist, monkeypatch)
    assert state.open_positions.empty
    assert any("Prezzo corrente non disponibile" in e.message for e in events)


def test_un_solo_trade_per_simbolo(monkeypatch):
    hist = _history(n=40)
    config = _config()
    state, _ = _step(["TEST"], paper.PaperState(), config, 141.5, hist, monkeypatch)
    assert len(state.open_positions) == 1
    state, _ = _step(["TEST"], state, config, 141.6, hist, monkeypatch)
    assert len(state.open_positions) == 1


def test_segnale_non_operabile_non_apre(monkeypatch):
    hist = _history(n=40)
    state, _ = _step(["TEST"], paper.PaperState(), _config(), 141.5, hist, monkeypatch,
                      signal=lambda s, h, horizon="medio": {"bias": "nessun_setup"})
    assert state.open_positions.empty


# ---------------------------------------------------------------------------
# Uscite: stesse regole del backtest
# ---------------------------------------------------------------------------

def test_uscita_intraday_sul_prezzo_corrente(monkeypatch):
    """Il tocco di stop/target rilevato sul prezzo corrente chiude a quel
    prezzo: è la parte realtime del forward."""
    hist = _history(n=40)
    config = _config()
    state, _ = _step(["TEST"], paper.PaperState(), config, 141.5, hist, monkeypatch)
    stop = float(state.open_positions.iloc[0]["stop"])

    # Nessuna nuova barra completa: solo il prezzo corrente crolla sotto lo stop.
    state, events = _step(["TEST"], state, config, stop - 1.0, hist, monkeypatch)

    assert state.open_positions.empty
    assert len(state.closed_trades) == 1
    trade = state.closed_trades.iloc[0]
    assert trade["exit_reason"] == "stop_intraday"
    assert float(trade["net_r"]) < 0


def test_uscita_su_barra_completa_applica_stop_first(monkeypatch):
    """Una barra successiva che contiene sia stop sia target deve chiudere
    sullo stop, esattamente come nel backtest."""
    hist = _history(n=40)
    config = _config()
    state, _ = _step(["TEST"], paper.PaperState(), config, 141.5, hist, monkeypatch)
    pos = state.open_positions.iloc[0]
    stop, target = float(pos["stop"]), float(pos["target"])

    # Giorno dopo: barra amplissima che tocca entrambi i livelli.
    tomorrow = TODAY + dt.timedelta(days=1)
    extended = hist.copy()
    extended.loc[pd.Timestamp(TODAY)] = {
        "Open": 141.5, "High": target + 5, "Low": stop - 5, "Close": 141.5, "Volume": 1e6}
    extended = extended.sort_index()

    state, events = _step(["TEST"], state, config, 141.5, extended, monkeypatch, today=tomorrow)

    assert len(state.closed_trades) == 1
    trade = state.closed_trades.iloc[0]
    assert trade["exit_reason"] == "stop"
    assert float(trade["exit_price"]) == pytest.approx(stop)


def test_la_seduta_di_ingresso_viene_riesaminata_quando_e_completa(monkeypatch):
    """Regressione di un bug reale trovato dai test.

    Entrando a metà giornata, la barra di quel giorno non è ancora
    completa. Se la si segnasse subito come 'processata', uno stop toccato
    nel resto della stessa seduta non verrebbe mai rilevato: la posizione
    resterebbe aperta all'infinito con una perdita non registrata. La
    barra del giorno di ingresso deve quindi essere riesaminata alla
    prima esecuzione successiva, quando è chiusa."""
    hist = _history(n=40)
    config = _config()
    state, _ = _step(["TEST"], paper.PaperState(), config, 141.5, hist, monkeypatch)
    pos = state.open_positions.iloc[0]
    stop = float(pos["stop"])
    # La seduta di ingresso non risulta già processata.
    assert paper._as_date(pos["last_processed_date"]) < TODAY

    # La seduta di ingresso, una volta completa, era scesa sotto lo stop
    # DOPO il nostro ingresso: deve produrre l'uscita.
    completed = hist.copy()
    completed.loc[pd.Timestamp(TODAY), "Low"] = stop - 3.0
    tomorrow = TODAY + dt.timedelta(days=1)

    state, _ = _step(["TEST"], state, config, 141.5, completed, monkeypatch, today=tomorrow)
    assert len(state.closed_trades) == 1
    assert state.closed_trades.iloc[0]["exit_reason"] == "stop"


def test_calcolo_del_ritardo_di_esecuzione_alla_chiusura(monkeypatch):
    """execution_delay_r misura, in R, la differenza tra entrare al prezzo
    corrente ed entrare all'apertura come nel backtest."""
    hist = _history(n=40)
    config = _config()
    current = 141.5
    state, _ = _step(["TEST"], paper.PaperState(), config, current, hist, monkeypatch)
    pos = state.open_positions.iloc[0]
    ref_open = float(pos["reference_open_price"])
    risk = float(pos["risk_per_unit"])
    stop = float(pos["stop"])

    state, _ = _step(["TEST"], state, config, stop - 1.0, hist, monkeypatch)
    trade = state.closed_trades.iloc[0]

    atteso = (ref_open - current) / risk
    assert float(trade["execution_delay_r"]) == pytest.approx(atteso)
    # Entrare più in alto di un long è uno svantaggio: il delta è negativo.
    assert atteso < 0


def test_i_costi_riducono_il_risultato_netto(monkeypatch):
    hist = _history(n=40)
    config = _config(order_fee_eur=1.0, fx_cost_pct_per_leg=0.5, slippage_bps_per_side=5.0)
    state, _ = _step(["TEST"], paper.PaperState(), config, 141.5, hist, monkeypatch)
    stop = float(state.open_positions.iloc[0]["stop"])
    state, _ = _step(["TEST"], state, config, stop - 1.0, hist, monkeypatch)
    trade = state.closed_trades.iloc[0]
    assert float(trade["costs_eur"]) > 0
    assert float(trade["net_pnl_eur"]) < float(trade["gross_pnl_eur"])
    assert float(trade["net_r"]) < float(trade["gross_r"])


# ---------------------------------------------------------------------------
# Stato e persistenza
# ---------------------------------------------------------------------------

def test_equity_si_aggiorna_dopo_la_chiusura(monkeypatch):
    hist = _history(n=40)
    config = _config()
    state, _ = _step(["TEST"], paper.PaperState(), config, 141.5, hist, monkeypatch)
    equity_aperta = state.equity_eur
    stop = float(state.open_positions.iloc[0]["stop"])
    state, _ = _step(["TEST"], state, config, stop - 1.0, hist, monkeypatch)
    assert state.equity_eur < equity_aperta


def test_roundtrip_salvataggio_e_ricarica(tmp_path, monkeypatch):
    hist = _history(n=40)
    config = _config()
    state, _ = _step(["TEST"], paper.PaperState(), config, 141.5, hist, monkeypatch)

    op = str(tmp_path / "open.csv")
    cp = str(tmp_path / "closed.csv")
    mp = str(tmp_path / "meta.json")
    paper_store.save_state(state, config, op, cp, mp)

    reloaded = paper_store.load_state(op, cp, mp)
    assert len(reloaded.open_positions) == 1
    assert reloaded.open_positions.iloc[0]["symbol"] == "TEST"
    assert reloaded.equity_eur == pytest.approx(state.equity_eur)
    assert reloaded.started_at == state.started_at

    reloaded_config = paper_store.load_config(mp)
    assert reloaded_config.risk_pct == pytest.approx(config.risk_pct)
    assert reloaded_config.leverage_enabled is False


def test_stato_assente_ritorna_stato_vuoto(tmp_path):
    state = paper_store.load_state(str(tmp_path / "a.csv"), str(tmp_path / "b.csv"),
                                    str(tmp_path / "c.json"))
    assert state.open_positions.empty
    assert state.closed_trades.empty
    assert paper_store.is_started(state) is False


def test_la_leva_nasce_disattivata():
    """Stage 3: si opera sempre a 1,0× finché la calibrazione non passa."""
    assert paper.PaperConfig().leverage_enabled is False
    assert _config().risk_config().leverage_enabled is False


def test_step_su_lista_vuota_non_esplode(monkeypatch):
    state, events = _step([], paper.PaperState(), _config(), 100.0, {}, monkeypatch)
    assert state.open_positions.empty
    assert events == []


def test_paper_non_apre_sui_piani_sfavorevoli(monkeypatch):
    """Backtest e forward devono applicare gli stessi filtri: se il paper
    tradasse setup che il backtest scarta, il confronto tra i due — che è
    l'intero scopo del forward — misurerebbe due strategie diverse."""
    hist = _history(n=40)

    def signal(symbol, h, horizon="medio"):
        px = float(h["Close"].iloc[-1])
        return {"bias": "long", "stop": px - 5, "target": px + 2, "entry": px,
                "confidence": 70.0, "risk_reward": 0.4, "rr_unfavorable": True}

    state, events = _step(["TEST"], paper.PaperState(), _config(), 141.5, hist, monkeypatch,
                           signal=signal)
    assert state.open_positions.empty
    assert any("sfavorevole" in e.message for e in events)


def test_paper_filtro_attivo_di_default():
    assert paper.PaperConfig().skip_unfavorable_rr is True
