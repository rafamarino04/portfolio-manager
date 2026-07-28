"""
Persistenza dichiarata — src/persistence.py

Esiste per rendere **impossibile** un salvataggio silenziosamente non
permanente.

Il problema che risolve, concreto e già costato dei dati: Streamlit
Community Cloud ricostruisce il container da GitHub a ogni riavvio o
redeploy. Sopravvive solo ciò che è nel repository. Un file scritto a
runtime in `data/` vive esclusivamente nel container in esecuzione e
sparisce al primo reboot.

L'app ha sempre avuto la rete di sicurezza giusta (`src/github_sync.py`,
che committa i CSV su GitHub), ma era agganciata in modo asimmetrico:
la pagina Portafoglio avvisava quando GitHub non era collegato, mentre i
percorsi di Preferiti e Universo Trading facevano

    if github_sync.is_configured():
        push(...)

cioè in caso di mancata configurazione **non facevano assolutamente
nulla**. L'utente vedeva "aggiunto ai preferiti" in verde e aveva ogni
ragione di crederlo salvato. Al primo riavvio dell'app quei dati non
c'erano più.

Da qui la regola che questo modulo impone: ogni scrittura di dati passa
per `save_and_sync`, che ritorna **sempre** un esito esplicito, e
`render_outcome` lo mostra sempre — successo o meno. Non esiste un
percorso in cui il salvataggio non persistente sia silenzioso, perché il
caso "non configurato" non è un ramo vuoto ma uno degli esiti previsti,
con il suo messaggio.

È l'applicazione del principio di trasparenza radicale del progetto a un
posto in cui mancava: se una cosa non è permanente, l'utente deve
saperlo **prima** di perderla, non dopo.
"""
from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from src import github_sync

# Esiti possibili di un salvataggio.
STATUS_PERSISTED = "persistito"        # scritto su disco E committato su GitHub
STATUS_SESSION_ONLY = "solo_sessione"  # scritto su disco, ma GitHub non è configurato
STATUS_SYNC_FAILED = "sync_fallita"    # GitHub configurato ma il commit non è riuscito
STATUS_WRITE_FAILED = "scrittura_fallita"

SESSION_ONLY_WARNING = (
    "Salvato solo in questa sessione: GitHub non è collegato, quindi questa modifica "
    "**andrà persa al prossimo riavvio dell'app**. Streamlit Cloud ricostruisce l'app da "
    "GitHub ad ogni riavvio e tiene solo ciò che è nel repository. Per rendere permanenti i "
    "salvataggi imposta GITHUB_TOKEN e GITHUB_REPO in App > Settings > Secrets (vedi README). "
    "Nel frattempo usa il pulsante di backup per scaricare una copia."
)


@dataclass
class SaveOutcome:
    status: str
    message: str

    @property
    def is_permanent(self) -> bool:
        return self.status == STATUS_PERSISTED

    @property
    def is_at_risk(self) -> bool:
        """True quando il dato è scritto ma non al sicuro da un riavvio."""
        return self.status in (STATUS_SESSION_ONLY, STATUS_SYNC_FAILED)


def persistence_is_configured() -> bool:
    return github_sync.is_configured()


def save_and_sync(write_fn, local_path: str, commit_message: str) -> SaveOutcome:
    """Scrive i dati e prova a renderli permanenti, dichiarando l'esito.

    `write_fn` è una callable senza argomenti che effettua la scrittura su
    disco (es. `lambda: wl.save_watchlist(df, path)`), così questo modulo
    resta indipendente dal formato dei dati.

    Non solleva eccezioni per gli errori di sincronizzazione: li traduce
    in un esito. Un fallimento di rete verso GitHub non deve far perdere
    la scrittura locale, ma non deve nemmeno essere nascosto."""
    try:
        write_fn()
    except Exception as exc:
        return SaveOutcome(STATUS_WRITE_FAILED, f"Salvataggio non riuscito: {exc}")

    if not github_sync.is_configured():
        return SaveOutcome(STATUS_SESSION_ONLY, SESSION_ONLY_WARNING)

    ok, msg = github_sync.push_csv(local_path, local_path, commit_message)
    if ok:
        return SaveOutcome(STATUS_PERSISTED, "Salvato su GitHub: la modifica è permanente.")
    return SaveOutcome(
        STATUS_SYNC_FAILED,
        f"Scritto in locale ma NON su GitHub, quindi a rischio al prossimo riavvio. {msg}",
    )


def render_outcome(outcome: SaveOutcome, success_prefix: str = "") -> None:
    """Mostra sempre l'esito. Il caso non permanente è un avviso, non un
    silenzio: è precisamente l'omissione che ha causato la perdita dei
    Preferiti e dell'Universo Trading."""
    if outcome.status == STATUS_PERSISTED:
        st.success(f"{success_prefix} {outcome.message}".strip())
    elif outcome.status == STATUS_SESSION_ONLY:
        if success_prefix:
            st.info(success_prefix)
        st.warning(outcome.message)
    elif outcome.status == STATUS_SYNC_FAILED:
        if success_prefix:
            st.info(success_prefix)
        st.error(outcome.message)
    else:
        st.error(outcome.message)


PENDING_OUTCOME_KEY = "_persistence_pending_outcome"


def remember_outcome(outcome: SaveOutcome, success_prefix: str = "") -> None:
    """Mette l'esito in sessione invece di stamparlo subito.

    Serve ovunque il salvataggio sia seguito da `st.rerun()`: un messaggio
    stampato prima del rerun verrebbe cancellato, e l'avviso di "non
    permanente" sparirebbe senza che l'utente lo veda — ricreando
    esattamente il silenzio che ha causato la perdita dei dati."""
    st.session_state[PENDING_OUTCOME_KEY] = (outcome, success_prefix)


def render_pending_outcome() -> None:
    """Mostra l'esito dell'ultimo salvataggio, dopo l'eventuale rerun."""
    pending = st.session_state.pop(PENDING_OUTCOME_KEY, None)
    if pending:
        outcome, prefix = pending
        render_outcome(outcome, prefix)


def save_sync_and_remember(write_fn, local_path: str, commit_message: str,
                            success_prefix: str = "") -> SaveOutcome:
    """Scorciatoia per il caso più comune: salva, sincronizza e memorizza
    l'esito perché sopravviva al rerun successivo."""
    outcome = save_and_sync(write_fn, local_path, commit_message)
    remember_outcome(outcome, success_prefix)
    return outcome


def render_global_status_banner() -> None:
    """Banner di stato mostrato su tutte le pagine.

    Serve a rendere lo stato effimero noto **prima** di inserire dati, non
    dopo averli persi: è la differenza tra un avviso utile e un necrologio."""
    if persistence_is_configured():
        return
    st.warning(
        "**I salvataggi non sono permanenti.** GitHub non è collegato: preferiti, universo "
        "trading, transazioni e impostazioni vivono solo in questa sessione e si perdono al "
        "riavvio dell'app. Imposta GITHUB_TOKEN e GITHUB_REPO in App > Settings > Secrets "
        "(istruzioni nel README). Fino ad allora, scarica i backup dalle rispettive sezioni."
    )
