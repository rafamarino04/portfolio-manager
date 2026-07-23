"""Impostazioni Alert e Report: alert email sui segnali tecnici di
portafoglio/preferiti (motore src/alerts.py, invio via
scripts/send_technical_alerts.py su GitHub Actions) e contenuto del
report periodico generato automaticamente ogni lunedì. L'allocazione
target e il benchmark si impostano invece nella pagina Portafoglio
Personale, accanto a dove si usano."""
import datetime as dt

import streamlit as st

from src import github_sync
from src import report_config as cfg
from src.theme import apply_theme

apply_theme()

st.title("Impostazioni Alert e Report")
st.caption(
    "L'allocazione target e il benchmark si configurano nella pagina Portafoglio Personale, "
    "accanto ai grafici che li usano. Qui restano gli alert email sui segnali tecnici e il "
    "contenuto del report periodico automatico."
)

settings = cfg.load_settings()

st.subheader("Contenuto del report periodico")
selected_sections = []
for key, label in cfg.ALL_SECTIONS.items():
    checked = st.checkbox(label, value=key in settings["report_sections"], key=f"section_{key}")
    if checked:
        selected_sections.append(key)

period = st.selectbox(
    "Periodicità (informativo — la cadenza reale è impostata nel workflow GitHub Actions)",
    options=["weekly", "monthly"],
    index=["weekly", "monthly"].index(settings.get("report_period", "weekly")),
    format_func=lambda x: "Settimanale" if x == "weekly" else "Mensile",
)

st.divider()
st.subheader("Alert email su segnali tecnici")
st.caption(
    "Scansiona ogni giorno feriale (via GitHub Actions, dopo la chiusura di Wall Street) "
    "il portafoglio e i preferiti con il motore di analisi tecnica, e invia un'email solo "
    "quando compare un segnale nuovo rispetto all'ultima scansione — niente notifiche ripetute "
    "per lo stesso evento."
)

with st.container(border=True):
    alerts_enabled = st.checkbox(
        "Attiva alert email",
        value=settings.get("alerts_enabled", False),
        key="alerts_enabled",
    )
    alert_recipient_email = st.text_input(
        "Email destinatario",
        value=settings.get("alert_recipient_email", ""),
        placeholder="tuo.indirizzo@gmail.com",
        help="Se lasciato vuoto, l'email viene inviata all'indirizzo Gmail mittente configurato nei secrets.",
        key="alert_recipient_email",
    )

    st.markdown("**Tipi di evento da segnalare**")
    selected_event_types = []
    for evt_key in cfg.ALERT_EVENT_TYPES:
        checked = st.checkbox(
            cfg.ALERT_EVENT_LABELS.get(evt_key, evt_key),
            value=evt_key in settings.get("alert_event_types", cfg.ALERT_EVENT_TYPES),
            key=f"alert_evt_{evt_key}",
        )
        if checked:
            selected_event_types.append(evt_key)

with st.expander("Come configurare l'invio (Gmail App Password + secrets GitHub)"):
    st.markdown(
        """
L'invio usa il tuo account Gmail via SMTP — non serve un servizio esterno, ma serve
una **password per le app** dedicata (diversa dalla password normale del tuo account).

**1. Genera la password per le app Gmail**

1. Vai su [myaccount.google.com/security](https://myaccount.google.com/security)
2. Attiva la **Verifica in due passaggi**, se non è già attiva (obbligatoria per le password per le app)
3. Vai su [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
4. Crea una nuova password per le app (es. nome "Portfolio Manager"), copia il codice di 16 caratteri

**2. Aggiungi i secrets su GitHub**

1. Vai sulla pagina del repository su GitHub
2. **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
3. Crea due secrets:
   - `GMAIL_ADDRESS` → il tuo indirizzo Gmail completo
   - `GMAIL_APP_PASSWORD` → il codice di 16 caratteri generato al passo precedente

Questi sono secrets di GitHub Actions, distinti da quelli di Streamlit Cloud (`APP_PASSWORD`,
`GITHUB_TOKEN`, `GITHUB_REPO`) usati per l'app in sé.

**3. Attiva gli alert qui sopra e salva**

Da quel momento, ogni giorno feriale dopo la chiusura di Wall Street, il workflow
"Alert tecnici via email" scansiona i titoli e ti scrive solo se c'è qualcosa di nuovo.
Puoi anche lanciarlo a mano da GitHub → **Actions** → **Alert tecnici via email** → **Run workflow**,
utile per un primo test.
"""
    )

st.divider()
if st.button("Salva impostazioni", type="primary"):
    new_settings = dict(settings)
    new_settings["report_sections"] = selected_sections
    new_settings["report_period"] = period
    new_settings["alerts_enabled"] = alerts_enabled
    new_settings["alert_recipient_email"] = alert_recipient_email.strip()
    new_settings["alert_event_types"] = selected_event_types
    cfg.save_settings(new_settings)
    st.success("Impostazioni salvate localmente.")

    if github_sync.is_configured():
        ok, msg = github_sync.push_csv(
            "data/settings.json", "data/settings.json",
            f"Aggiorna impostazioni - {dt.date.today().isoformat()}",
        )
        (st.success if ok else st.error)(msg)
    else:
        st.warning(
            "GitHub non collegato: questa modifica potrebbe andare persa al prossimo "
            "riavvio dell'app. Configura GITHUB_TOKEN e GITHUB_REPO nei secrets per "
            "renderla permanente (vedi README)."
        )
    st.rerun()
