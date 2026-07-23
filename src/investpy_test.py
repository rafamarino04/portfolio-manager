"""Test sperimentale e completamente isolato di `investpy` (scraping
non ufficiale di Investing.com) come possibile fonte dati alternativa a
yfinance. NON è collegato al resto dell'app: nessun altro modulo importa
questo file, serve solo a verificare — nell'ambiente di produzione
(Streamlit Cloud), dove la rete non è ristretta come nella sandbox di
sviluppo usata per costruire l'app — se Investing.com risponde ancora
alle richieste di investpy o le blocca (le segnalazioni della community,
al momento in cui e' stato scritto questo modulo, dicono di no: la
protezione Cloudflare di Investing.com restituisce 403 alle chiamate di
investpy). Non solleva mai eccezioni verso il chiamante: ogni esito,
successo o fallimento, torna come dict così la pagina può mostrarlo senza
rischiare di andare in crash."""
from __future__ import annotations


def test_historical_data(ticker: str, country: str, from_date: str, to_date: str) -> dict:
    """Prova a scaricare uno storico prezzi con investpy.
    `from_date`/`to_date` nel formato gg/mm/aaaa richiesto da investpy."""
    try:
        import investpy
    except Exception as e:
        return {"ok": False, "stage": "import", "error": f"{type(e).__name__}: {e}"}

    try:
        df = investpy.get_stock_historical_data(
            stock=ticker, country=country, from_date=from_date, to_date=to_date,
        )
        if df is None or df.empty:
            return {"ok": False, "stage": "fetch", "error": "Risposta vuota (nessun dato restituito)."}
        return {"ok": True, "rows": len(df), "preview": df.tail(5)}
    except Exception as e:
        return {"ok": False, "stage": "fetch", "error": f"{type(e).__name__}: {e}"}
