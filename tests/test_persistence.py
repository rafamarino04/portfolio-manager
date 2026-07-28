"""Test della persistenza dichiarata (src/persistence.py).

Questi test esistono per una ragione concreta: la versione precedente
dell'app perdeva i Preferiti e l'Universo Trading a ogni riavvio, perché
il salvataggio verso GitHub era agganciato come

    if github_sync.is_configured():
        push(...)

cioè in caso di mancata configurazione non faceva **nulla, in silenzio**.
L'utente vedeva la conferma verde e i dati sparivano al primo reboot di
Streamlit Cloud, che ricostruisce il container dal repository.

Il test che conta più di tutti è quindi
`test_mancata_configurazione_non_e_mai_silenziosa`: verifica che il caso
"non configurato" produca sempre un esito esplicito e a rischio, mai un
successo silenzioso.
"""
import pandas as pd
import pytest

from src import github_sync
from src import persistence
from src import trading_universe as tu
from src import watchlist as wl


@pytest.fixture
def scritto(tmp_path):
    """Callable di scrittura che registra se è stata invocata."""
    path = tmp_path / "dati.csv"
    stato = {"chiamato": False}

    def write():
        stato["chiamato"] = True
        path.write_text("ticker\nAAPL\n", encoding="utf-8")

    return write, path, stato


# ---------------------------------------------------------------------------
# Il caso che ha causato la perdita dei dati
# ---------------------------------------------------------------------------

def test_mancata_configurazione_non_e_mai_silenziosa(monkeypatch, scritto):
    """Senza GitHub configurato il salvataggio locale avviene comunque, ma
    l'esito deve dichiarare che NON è permanente."""
    write, path, stato = scritto
    monkeypatch.setattr(github_sync, "is_configured", lambda: False)

    outcome = persistence.save_and_sync(write, str(path), "msg")

    assert stato["chiamato"] is True                    # i dati sono scritti
    assert outcome.status == persistence.STATUS_SESSION_ONLY
    assert outcome.is_permanent is False
    assert outcome.is_at_risk is True
    assert outcome.message                              # mai un messaggio vuoto
    assert "riavvio" in outcome.message.lower()         # l'utente deve capire il rischio


def test_salvataggio_persistito_quando_github_configurato(monkeypatch, scritto):
    write, path, stato = scritto
    monkeypatch.setattr(github_sync, "is_configured", lambda: True)
    monkeypatch.setattr(github_sync, "push_csv", lambda a, b, c: (True, "ok"))

    outcome = persistence.save_and_sync(write, str(path), "msg")
    assert outcome.status == persistence.STATUS_PERSISTED
    assert outcome.is_permanent is True
    assert outcome.is_at_risk is False


def test_sync_fallita_e_segnalata_come_a_rischio(monkeypatch, scritto):
    """Un errore di rete verso GitHub non deve far perdere la scrittura
    locale, ma non deve nemmeno essere nascosto."""
    write, path, stato = scritto
    monkeypatch.setattr(github_sync, "is_configured", lambda: True)
    monkeypatch.setattr(github_sync, "push_csv", lambda a, b, c: (False, "errore 403"))

    outcome = persistence.save_and_sync(write, str(path), "msg")
    assert stato["chiamato"] is True
    assert outcome.status == persistence.STATUS_SYNC_FAILED
    assert outcome.is_permanent is False
    assert outcome.is_at_risk is True
    assert "403" in outcome.message


def test_errore_di_scrittura_non_solleva_ma_dichiara(monkeypatch, tmp_path):
    monkeypatch.setattr(github_sync, "is_configured", lambda: True)

    def write_che_fallisce():
        raise OSError("disco pieno")

    outcome = persistence.save_and_sync(write_che_fallisce, str(tmp_path / "x.csv"), "msg")
    assert outcome.status == persistence.STATUS_WRITE_FAILED
    assert outcome.is_permanent is False
    assert "disco pieno" in outcome.message


def test_scrittura_fallita_non_tenta_la_sincronizzazione(monkeypatch, tmp_path):
    """Non ha senso committare un file che non è stato scritto."""
    chiamate = {"push": 0}
    monkeypatch.setattr(github_sync, "is_configured", lambda: True)

    def conta_push(a, b, c):
        chiamate["push"] += 1
        return True, "ok"

    monkeypatch.setattr(github_sync, "push_csv", conta_push)

    def write_che_fallisce():
        raise ValueError("boom")

    persistence.save_and_sync(write_che_fallisce, str(tmp_path / "x.csv"), "msg")
    assert chiamate["push"] == 0


def test_tutti_gli_esiti_hanno_un_messaggio(monkeypatch, scritto):
    """Nessuno stato può produrre un esito muto: è il punto dell'intero
    modulo."""
    write, path, _ = scritto
    scenari = [
        (False, None, persistence.STATUS_SESSION_ONLY),
        (True, (True, "ok"), persistence.STATUS_PERSISTED),
        (True, (False, "ko"), persistence.STATUS_SYNC_FAILED),
    ]
    for configured, push_result, atteso in scenari:
        monkeypatch.setattr(github_sync, "is_configured", lambda c=configured: c)
        if push_result is not None:
            monkeypatch.setattr(github_sync, "push_csv", lambda a, b, c, r=push_result: r)
        outcome = persistence.save_and_sync(write, str(path), "msg")
        assert outcome.status == atteso
        assert outcome.message.strip()


def test_persistence_is_configured_riflette_github_sync(monkeypatch):
    monkeypatch.setattr(github_sync, "is_configured", lambda: True)
    assert persistence.persistence_is_configured() is True
    monkeypatch.setattr(github_sync, "is_configured", lambda: False)
    assert persistence.persistence_is_configured() is False


# ---------------------------------------------------------------------------
# Normalizzazione per il ripristino da backup
# ---------------------------------------------------------------------------

def test_normalize_watchlist_aggiunge_colonne_mancanti():
    """Un backup con sole colonne parziali deve poter essere ripristinato,
    non far fallire il salvataggio."""
    df = pd.DataFrame({"ticker": [" aapl ", "msft"]})
    out = wl.normalize(df)
    assert list(out.columns) == wl.COLUMNS
    assert out["ticker"].tolist() == ["AAPL", "MSFT"]


def test_normalize_universe_aggiunge_colonne_mancanti():
    df = pd.DataFrame({"ticker": ["swda.mi"]})
    out = tu.normalize(df)
    assert list(out.columns) == tu.COLUMNS
    assert out["ticker"].tolist() == ["SWDA.MI"]


def test_normalize_universe_preserva_i_dati_esistenti():
    df = pd.DataFrame({"ticker": ["AAPL"], "note": ["x"],
                        "tts_at_add": [78.0], "tts_date": ["2026-01-10"]})
    out = tu.normalize(df)
    assert tu.tts_at_add_for(out, "AAPL") == pytest.approx(78.0)
    assert tu.note_for(out, "AAPL") == "x"


def test_normalize_e_salvataggio_roundtrip(tmp_path):
    """Il percorso completo di ripristino: CSV parziale -> normalize ->
    save -> load."""
    df = pd.DataFrame({"ticker": ["AAPL", "MSFT"]})
    path = str(tmp_path / "u.csv")
    tu.save_universe(tu.normalize(df), path)
    reloaded = tu.load_universe(path)
    assert tu.tickers(reloaded) == ["AAPL", "MSFT"]
