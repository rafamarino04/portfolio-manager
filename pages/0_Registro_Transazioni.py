"""
Registro Transazioni: la fonte di verità del portafoglio. Ogni acquisto,
vendita e dividendo si registra qui — le posizioni attuali (quantità,
prezzo medio di carico) si calcolano automaticamente da questo storico,
insieme a P&L realizzato, dividendi incassati e rendimento reale (XIRR).
"""
import datetime as dt
import os

import pandas as pd
import streamlit as st

from src import github_sync
from src import portfolio as pf
from src import transactions as tx
from src.auth import check_password
from src.portfolio import CATEGORIES
from src.theme import apply_theme

st.set_page_config(page_title="Registro Transazioni", page_icon="\U0001F4D2", layout="wide")
apply_theme()

if not check_password():
    st.stop()

st.title("\U0001F4D2 Registro Transazioni")
st.caption(
    "Ogni riga è un movimento reale: acquisto, vendita o dividendo. Le posizioni, il P&L "
    "realizzato e il rendimento (XIRR) si calcolano automaticamente da qui — non si modificano "
    "più a mano."
)

TX_PATH = "data/transactions.csv"
PORTFOLIO_PATH = "data/portfolio.csv"

if "tx_editor_df" not in st.session_state:
    st.session_state["tx_editor_df"] = tx.load_transactions(TX_PATH)

with st.expander("Come compilare i campi", expanded=False):
    st.markdown(
        "- **type**: `Acquisto`, `Vendita` o `Dividendo`.\n"
        "- **Acquisto/Vendita**: compila `quantity` e `price` (prezzo per quota/azione), "
        "`fees` per le commissioni (opzionale).\n"
        "- **Dividendo**: compila solo `amount` con l'importo netto incassato.\n"
        "- **ticker**: simbolo Yahoo Finance, o un'etichetta libera per liquidità/obbligazioni "
        "senza ticker (es. `Conto Deposito XYZ`, `BTP-2030`).\n"
        "- **category/currency/manual_price**: servono solo sul *primo* acquisto di un titolo "
        "nuovo — impostano i metadati usati per l'allocazione e (se serve) il prezzo manuale."
    )

edited = st.data_editor(
    st.session_state["tx_editor_df"],
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "date": st.column_config.DateColumn("Data", required=True),
        "ticker": st.column_config.TextColumn("Ticker / Etichetta", required=True),
        "type": st.column_config.SelectboxColumn("Tipo", options=tx.TRANSACTION_TYPES, required=True),
        "quantity": st.column_config.NumberColumn("Quantità", min_value=0.0),
        "price": st.column_config.NumberColumn("Prezzo", min_value=0.0),
        "amount": st.column_config.NumberColumn("Importo (dividendi)", min_value=0.0),
        "fees": st.column_config.NumberColumn("Commissioni", min_value=0.0),
        "currency": st.column_config.TextColumn("Valuta"),
        "category": st.column_config.SelectboxColumn("Categoria", options=CATEGORIES),
        "manual_price": st.column_config.NumberColumn("Prezzo manuale", min_value=0.0),
        "note": st.column_config.TextColumn("Note"),
    },
    key="tx_data_editor",
)

col_a, col_b, _ = st.columns([1, 1, 3])
save = col_a.button("\U0001F4BE Salva movimenti", type="primary")


def _persist(clean: pd.DataFrame):
    clean.to_csv(TX_PATH, index=False)
    st.session_state["tx_editor_df"] = tx.load_transactions(TX_PATH)

    positions = tx.compute_positions(tx.load_transactions(TX_PATH))
    positions.to_csv(PORTFOLIO_PATH, index=False)

    st.success("Movimenti salvati e posizioni ricalcolate.")
    if github_sync.is_configured():
        today = dt.date.today().isoformat()
        ok1, msg1 = github_sync.push_csv(TX_PATH, TX_PATH, f"Aggiorna transazioni - {today}")
        ok2, msg2 = github_sync.push_csv(PORTFOLIO_PATH, PORTFOLIO_PATH, f"Ricalcola posizioni - {today}")
        (st.success if ok1 else st.error)(msg1)
        (st.success if ok2 else st.error)(msg2)
    else:
        st.warning(
            "GitHub non collegato: le modifiche potrebbero perdersi al prossimo riavvio. "
            "Configura GITHUB_TOKEN e GITHUB_REPO nei secrets (vedi README)."
        )


if save:
    clean = edited.dropna(how="all").copy()
    clean["ticker"] = clean["ticker"].astype(str).str.strip()
    bad = clean[(clean["ticker"] == "") | clean["date"].isna() | clean["type"].isna()]
    if not bad.empty:
        st.error("Ci sono righe senza data, ticker o tipo: completale o eliminale prima di salvare.")
    else:
        _persist(clean)
        st.rerun()

st.divider()

current_tx = tx.load_transactions(TX_PATH) if os.path.exists(TX_PATH) else pd.DataFrame(columns=tx.COLUMNS)

if not current_tx.empty:
    positions = tx.compute_positions(current_tx)
    realized = tx.compute_realized_pl(current_tx)
    dividends = tx.compute_dividends(current_tx)

    total_realized = realized["realized_pl"].sum() if not realized.empty else 0.0
    total_dividends = dividends["total_dividends"].sum() if not dividends.empty else 0.0

    with st.spinner("Calcolo valore attuale per il rendimento (XIRR)..."):
        try:
            enriched = pf.enrich_with_prices(positions) if not positions.empty else pd.DataFrame()
            current_value = enriched["market_value"].sum(skipna=True) if not enriched.empty else 0.0
        except Exception:
            current_value = 0.0

    xirr_value = tx.compute_xirr(current_tx, current_total_value=current_value)

    st.subheader("Riepilogo")
    c1, c2, c3 = st.columns(3)
    c1.metric("P&L realizzato (vendite chiuse)", f"{total_realized:,.2f}")
    c2.metric("Dividendi incassati", f"{total_dividends:,.2f}")
    c3.metric("Rendimento reale (XIRR)", f"{xirr_value:.2f}%" if xirr_value is not None else "n/d")
    st.caption(
        "XIRR = rendimento annualizzato che tiene conto di *quando* sono entrati e usciti i "
        "soldi, non solo di quanto — più accurato del semplice P&L% quando versi o prelevi nel tempo."
    )
else:
    st.info("Registra il primo movimento per vedere qui il riepilogo.")
