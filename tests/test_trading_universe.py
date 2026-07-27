"""Test per l'Universo Trading (src/trading_universe.py): la short-list
dei titoli selezionati per il trading tecnico, distinta dai Preferiti.

Il caso più delicato è il TTS congelato: deve sopravvivere a un
aggiornamento della sola nota (altrimenti si perde silenziosamente
l'unico riferimento storico per capire se la tradabilità è peggiorata) e
deve sempre portarsi dietro la data in cui è stato congelato.
"""
import datetime as dt

import pandas as pd
import pytest

from src import trading_universe as tu


@pytest.fixture
def empty_df():
    return tu.load_universe("percorso/che/non/esiste.csv")


def test_load_universe_file_assente_ritorna_df_vuoto_con_colonne(empty_df):
    assert empty_df.empty
    assert list(empty_df.columns) == tu.COLUMNS


def test_add_ticker_normalizza_maiuscole_e_spazi(empty_df):
    df = tu.add_ticker(empty_df, "  swda.mi  ", "ETF core")
    assert df.iloc[0]["ticker"] == "SWDA.MI"
    assert tu.is_in_universe(df, "swda.mi")
    assert tu.is_in_universe(df, "SWDA.MI")


def test_add_ticker_congela_tts_e_data(empty_df):
    df = tu.add_ticker(empty_df, "AAPL", "trend pulito", tts_at_add=78.4)
    assert tu.tts_at_add_for(df, "AAPL") == pytest.approx(78.4)
    assert tu.tts_date_for(df, "AAPL") == dt.date.today().isoformat()
    assert tu.note_for(df, "AAPL") == "trend pulito"


def test_add_ticker_senza_tts_non_inventa_punteggio(empty_df):
    df = tu.add_ticker(empty_df, "XYZ", "da verificare")
    assert tu.tts_at_add_for(df, "XYZ") is None
    assert tu.tts_date_for(df, "XYZ") is None


def test_aggiornare_la_nota_non_cancella_il_tts_congelato(empty_df):
    """Il punto critico: modificare la nota non deve azzerare il punteggio
    storico, che è l'unico riferimento per il confronto nel tempo."""
    df = tu.add_ticker(empty_df, "AAPL", "prima nota", tts_at_add=78.0)
    df = tu.add_ticker(df, "AAPL", "nota aggiornata")
    assert tu.note_for(df, "AAPL") == "nota aggiornata"
    assert tu.tts_at_add_for(df, "AAPL") == pytest.approx(78.0)
    assert tu.tts_date_for(df, "AAPL") == dt.date.today().isoformat()
    assert len(df) == 1  # aggiornamento, non duplicazione


def test_ricongelare_esplicitamente_il_tts_lo_sovrascrive(empty_df):
    df = tu.add_ticker(empty_df, "AAPL", "nota", tts_at_add=78.0)
    df = tu.add_ticker(df, "AAPL", "nota", tts_at_add=51.0)
    assert tu.tts_at_add_for(df, "AAPL") == pytest.approx(51.0)


def test_remove_ticker_case_insensitive(empty_df):
    df = tu.add_ticker(empty_df, "AAPL", "")
    df = tu.add_ticker(df, "MSFT", "")
    df = tu.remove_ticker(df, "aapl")
    assert not tu.is_in_universe(df, "AAPL")
    assert tu.is_in_universe(df, "MSFT")


def test_tickers_ordinati_e_deduplicati(empty_df):
    df = tu.add_ticker(empty_df, "MSFT", "")
    df = tu.add_ticker(df, "AAPL", "")
    df = tu.add_ticker(df, "aapl", "duplicato")  # stesso titolo, aggiornamento
    assert tu.tickers(df) == ["AAPL", "MSFT"]


def test_accessori_su_ticker_assente_ritornano_none(empty_df):
    df = tu.add_ticker(empty_df, "AAPL", "nota", tts_at_add=70.0)
    assert tu.note_for(df, "SCONOSCIUTO") is None
    assert tu.tts_at_add_for(df, "SCONOSCIUTO") is None
    assert tu.tts_date_for(df, "SCONOSCIUTO") is None


def test_save_e_load_roundtrip(tmp_path, empty_df):
    path = str(tmp_path / "trading_universe.csv")
    df = tu.add_ticker(empty_df, "SWDA.MI", "ETF core", tts_at_add=82.5)
    df = tu.add_ticker(df, "AAPL", "", tts_at_add=None)
    tu.save_universe(df, path)

    reloaded = tu.load_universe(path)
    assert tu.tickers(reloaded) == ["AAPL", "SWDA.MI"]
    assert tu.tts_at_add_for(reloaded, "SWDA.MI") == pytest.approx(82.5)
    assert tu.note_for(reloaded, "SWDA.MI") == "ETF core"
    assert tu.tts_at_add_for(reloaded, "AAPL") is None


def test_load_universe_tollera_colonne_mancanti(tmp_path):
    """Un CSV scritto da una versione precedente (solo ticker) deve
    caricarsi senza errori, con i campi nuovi a None invece di far
    fallire la pagina."""
    path = tmp_path / "legacy.csv"
    path.write_text("ticker\nAAPL\nMSFT\n", encoding="utf-8")
    df = tu.load_universe(str(path))
    assert list(df.columns) == tu.COLUMNS
    assert tu.tickers(df) == ["AAPL", "MSFT"]
    assert tu.tts_at_add_for(df, "AAPL") is None


def test_is_in_universe_su_lista_vuota(empty_df):
    assert tu.is_in_universe(empty_df, "AAPL") is False
    assert tu.tickers(empty_df) == []
