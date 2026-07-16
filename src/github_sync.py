"""
Sincronizza i file dati (transazioni, portafoglio, impostazioni) con il
repository GitHub, cosi' le modifiche fatte dentro l'app sopravvivono ai
riavvii e ai redeploy di Streamlit Community Cloud, che altrimenti ripartono sempre
dall'ultima versione salvata su GitHub.

Richiede due secrets (vedi README per come crearli):
  GITHUB_TOKEN  - personal access token con permesso "Contents: read and
                  write" limitato al solo repository di questa app
  GITHUB_REPO   - "utente/nome-repo", es. "rafamarino04/portfolio-manager"
  GITHUB_BRANCH - opzionale, default "main"

Se questi secrets non sono configurati, l'app funziona comunque: salva solo
in locale e lo segnala chiaramente all'utente.
"""
from __future__ import annotations

import base64

import requests
import streamlit as st

API_ROOT = "https://api.github.com"


def is_configured() -> bool:
    try:
        return bool(st.secrets.get("GITHUB_TOKEN")) and bool(st.secrets.get("GITHUB_REPO"))
    except Exception:
        return False


def push_csv(local_path: str, repo_path: str, commit_message: str) -> tuple[bool, str]:
    """Legge local_path e lo committa su GitHub al posto di repo_path."""
    if not is_configured():
        return False, "GitHub non configurato (manca GITHUB_TOKEN o GITHUB_REPO nei secrets)."

    token = st.secrets["GITHUB_TOKEN"]
    repo = st.secrets["GITHUB_REPO"]
    branch = st.secrets.get("GITHUB_BRANCH", "main")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    url = f"{API_ROOT}/repos/{repo}/contents/{repo_path}"

    try:
        with open(local_path, "rb") as f:
            content_bytes = f.read()
        content_b64 = base64.b64encode(content_bytes).decode()

        # Serve lo sha del file attuale su GitHub per poterlo sovrascrivere
        get_resp = requests.get(url, headers=headers, params={"ref": branch}, timeout=15)
        sha = get_resp.json().get("sha") if get_resp.status_code == 200 else None

        payload = {"message": commit_message, "content": content_b64, "branch": branch}
        if sha:
            payload["sha"] = sha

        put_resp = requests.put(url, headers=headers, json=payload, timeout=15)
        if put_resp.status_code in (200, 201):
            return True, "Salvato anche su GitHub: la modifica e' permanente."

        try:
            err = put_resp.json().get("message", put_resp.text)
        except Exception:
            err = put_resp.text
        return False, f"Salvato solo in locale — errore GitHub ({put_resp.status_code}): {err}"
    except Exception as e:
        return False, f"Salvato solo in locale — errore di connessione a GitHub: {e}"
