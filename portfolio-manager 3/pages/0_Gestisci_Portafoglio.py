"""
Aggiungi, modifica o elimina azioni / ETF / obbligazioni direttamente
dall'app, senza toccare file o codice.
"""
import datetime as dt
import os

import pandas as pd
import streamlit as st

from src import data_provider as dp
from src import github_sync
from src.auth import check_password

st.set_page_config(page_title="Gestisci Portafoglio", page_icon="\U0001F4BC", layout="wide")

if not check_password():
    st.stop()

st.title("\U0001F4BC Gestisci Portafoglio")
st.caption(
    "Aggiungi righe con il '+' in basso alla tabella, modificale cliccando sulle celle, "
    "elimina una riga selezionandola e premendo il cestino. Poi premi 'Salva modifiche'."
)

CSV_PATH = "data/portfolio.csv"
COLUMNS = [
    "ticker", "quantity", "buy_price", "buy_date",
    "currency", "category", "manual_price", "note",
]


def load() -> pd.DataFrame:
    if os.path.exists(CSV_PATH):
        df = pd.read_csv(CSV_PATH)
    else:
        df = pd.DataFrame(columns=COLUMNS)
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = None
    return df[COLUMNS]


if "portfolio_editor_df" not in st.session_state:
    st.session_state["portfolio_editor_df"] = load()

with st.expander("Come compilare i campi", expanded=False):
    st.markdown(
        "- **ticker**: simbolo Yahoo Finance. Azioni/ETF, es. `AAPL`, `ENI.MI` "
        "(Borsa Italiana), `VWCE.DE` (Xetra) — cerca il titolo su "
        "[finance.yahoo.com](https://finance.yahoo.com) per trovare il simbolo esatto.\n"
        "- **Obbligazioni**: se non trovi un ticker su Yahoo Finance (capita spesso per "
        "singoli BTP/ISIN), scrivi una sigla a tua scelta in `ticker` (es. `BTP-2030`) "
        "e compila `manual_price` con il prezzo corrente — dovrai aggiornarlo tu di tanto "
        "in tanto, dato che per questi strumenti non esiste un prezzo live gratuito "
        "affidabile.\n"
        "- **quantity**: quantita' posseduta (numero di azioni/quote, o nominale per le obbligazioni).\n"
        "- **buy_price**: prezzo medio di carico.\n"
        "- **category**: `Azione`, `ETF`, `Obbligazione` o `Altro` — usata per i grafici di allocazione.\n"
        "- **manual_price**: lascialo vuoto per usare il prezzo live; compilalo per forzarne uno "
        "(obbligatorio per le obbligazioni senza ticker valido)."
    )

edited = st.data_editor(
    st.session_state["portfolio_editor_df"],
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "ticker": st.column_config.TextColumn("Ticker", required=True),
        "quantity": st.column_config.NumberColumn("Quantita'", required=True, min_value=0.0),
        "buy_price": st.column_config.NumberColumn("Prezzo di carico", required=True, min_value=0.0),
        "buy_date": st.column_config.TextColumn("Data acquisto (AAAA-MM-GG)"),
        "currency": st.column_config.TextColumn("Valuta"),
        "category": st.column_config.SelectboxColumn(
            "Categoria", options=["Azione", "ETF", "Obbligazione", "Altro"]
        ),
        "manual_price": st.column_config.NumberColumn("Prezzo manuale (opzionale)", min_value=0.0),
        "note": st.column_config.TextColumn("Note"),
    },
    key="portfolio_data_editor",
)

col_a, col_b, _ = st.columns([1, 1, 3])
verify = col_a.button("Verifica ticker")
save = col_b.button("\U0001F4BE Salva modifiche", type="primary")

if verify:
    st.subheader("Verifica")
    any_ticker = False
    for _, row in edited.iterrows():
        ticker = str(row.get("ticker", "") or "").strip()
        if not ticker:
            continue
        any_ticker = True
        info = dp.get_info(ticker)
        found_name = info.get("name")
        if found_name and found_name != ticker:
            st.success(f"{ticker} -> trovato: {found_name}")
        else:
            st.warning(
                f"{ticker} -> non trovato su Yahoo Finance. "
                "Se e' un'obbligazione, compila 'manual_price'; il prezzo sara' usato comunque."
            )
    if not any_ticker:
        st.info("Nessun ticker da verificare.")

if save:
    clean = edited.dropna(how="all").copy()
    clean["ticker"] = clean["ticker"].astype(str).str.strip()
    missing = clean[(clean["ticker"] == "") | clean["ticker"].isna()]
    if not missing.empty:
        st.error("Ci sono righe senza ticker: compilale o eliminale prima di salvare.")
    else:
        clean.to_csv(CSV_PATH, index=False)
        st.session_state["portfolio_editor_df"] = clean
        st.success("Portafoglio salvato localmente.")

        if github_sync.is_configured():
            ok, msg = github_sync.push_csv(
                CSV_PATH,
                "data/portfolio.csv",
                f"Aggiorna portafoglio - {dt.date.today().isoformat()}",
            )
            (st.success if ok else st.error)(msg)
        else:
            st.warning(
                "GitHub non collegato: questa modifica potrebbe andare persa al prossimo "
                "riavvio o aggiornamento dell'app. Configura GITHUB_TOKEN e GITHUB_REPO "
                "nei secrets per renderla permanente (istruzioni nel README)."
            )
        st.rerun()
