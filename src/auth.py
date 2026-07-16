"""Semplice gate a password per proteggere la dashboard, dato che mostra
dati finanziari personali. La password va impostata come secret
APP_PASSWORD nelle impostazioni di Streamlit Community Cloud (mai nel repo).
"""
import streamlit as st


def check_password() -> bool:
    configured = st.secrets.get("APP_PASSWORD")
    if not configured:
        st.warning(
            "Nessuna password configurata (APP_PASSWORD mancante nei secrets). "
            "L'app e' accessibile senza protezione: impostala prima di condividere il link."
        )
        return True

    if st.session_state.get("authenticated"):
        return True

    st.title("Accesso Portfolio Manager")
    pwd = st.text_input("Password", type="password")
    if st.button("Entra") or pwd:
        if pwd == configured:
            st.session_state["authenticated"] = True
            st.rerun()
        elif pwd:
            st.error("Password errata.")
    return False
