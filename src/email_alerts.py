"""
Invio delle email di alert tecnico via Gmail SMTP. Le credenziali
(indirizzo Gmail + password per le app) non vivono mai nel codice o nei
secrets di Streamlit: sono lette da variabili d'ambiente, impostate come
secrets della GitHub Action che esegue scripts/send_technical_alerts.py
(GMAIL_ADDRESS, GMAIL_APP_PASSWORD) — vedi README per i passaggi di
configurazione.

Il template email usa una palette propria, indipendente dal tema scuro
dell'app: la maggior parte dei client di posta ignora i CSS del sito e
renderizza su sfondo bianco, quindi i colori "chiari su scuro" del tema
in-app sarebbero illeggibili qui.
"""
from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

_NAVY = "#1B2A4A"
_GOLD = "#C9A227"
_GREEN = "#1E8E5A"
_RED = "#C0392B"
_GRAY = "#6B7280"
_BG = "#F4F6F9"
_BORDER = "#E3E7EE"


def send_alert_email(subject: str, html_body: str, to_addr: str, from_addr: str,
                      app_password: str) -> tuple[bool, str]:
    """Invia l'email via SMTP Gmail (smtp.gmail.com:587, STARTTLS). Non
    solleva mai eccezioni: torna sempre (ok, messaggio), come gli altri
    moduli dell'app (es. github_sync.push_csv)."""
    if not from_addr or not app_password:
        return False, "GMAIL_ADDRESS / GMAIL_APP_PASSWORD non configurati: email non inviata."
    if not to_addr:
        return False, "Nessun indirizzo destinatario: email non inviata."
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as server:
            server.starttls()
            server.login(from_addr, app_password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
        return True, f"Email inviata a {to_addr}."
    except Exception as e:
        return False, f"Invio email fallito: {type(e).__name__}: {e}"


def _direction_color(direction: str) -> str:
    return {"rialzista": _GREEN, "ribassista": _RED}.get(direction, _GRAY)


def _trade_plan_html(plan: dict | None) -> str:
    if not plan or plan.get("bias") in (None, "nessun_setup"):
        motivo = plan.get("reason") if plan else None
        extra = f" ({motivo})" if motivo else ""
        return (
            f"<p style='font-size:13px;color:{_GRAY};margin:8px 0 0 0;'>"
            f"Quadro non abbastanza direzionale o concorde per un piano operativo{extra}."
            f"</p>"
        )
    bias_color = _GREEN if plan["bias"] == "long" else _RED
    rr = plan.get("risk_reward")
    rr_text = f"{rr:.2f}" if rr else "n/d"
    rr_warn = " — sotto 1:1,5, sfavorevole" if plan.get("rr_unfavorable") else ""
    return f"""
    <table style="width:100%;border-collapse:collapse;margin-top:10px;font-size:13px;">
      <tr>
        <td style="padding:4px 8px;color:{_GRAY};">Impostazione</td>
        <td style="padding:4px 8px;font-weight:600;color:{bias_color};">{plan['bias'].upper()}</td>
      </tr>
      <tr>
        <td style="padding:4px 8px;color:{_GRAY};">Ingresso</td>
        <td style="padding:4px 8px;color:{_NAVY};">{plan['entry']:,.2f}</td>
      </tr>
      <tr>
        <td style="padding:4px 8px;color:{_GRAY};">Stop</td>
        <td style="padding:4px 8px;color:{_NAVY};">{plan['stop']:,.2f}</td>
      </tr>
      <tr>
        <td style="padding:4px 8px;color:{_GRAY};">Target</td>
        <td style="padding:4px 8px;color:{_NAVY};">{plan['target']:,.2f}</td>
      </tr>
      <tr>
        <td style="padding:4px 8px;color:{_GRAY};">Rischio/Rendimento</td>
        <td style="padding:4px 8px;color:{_NAVY};">{rr_text}{rr_warn}</td>
      </tr>
    </table>
    """


def build_alert_email_html(items: list[dict]) -> str:
    """`items`: lista di {"symbol", "alerts": [{"type","direction","message"}], "trade_plan": dict|None}."""
    cards = []
    for item in items:
        events_html = "".join(
            f"<li style='margin-bottom:4px;color:{_NAVY};'>"
            f"<span style='color:{_direction_color(a['direction'])};font-weight:600;'>{a['type']}</span>"
            f" — {a['message']}</li>"
            for a in item["alerts"]
        )
        cards.append(f"""
        <div style="border:1px solid {_BORDER};border-radius:8px;padding:16px;margin-bottom:14px;background:#FFFFFF;">
          <h3 style="margin:0 0 8px 0;color:{_NAVY};font-size:16px;">{item['symbol']}</h3>
          <ul style="margin:0;padding-left:18px;font-size:14px;">{events_html}</ul>
          {_trade_plan_html(item.get("trade_plan"))}
        </div>
        """)

    return f"""
    <div style="font-family:Arial,Helvetica,sans-serif;max-width:600px;margin:0 auto;background:{_BG};padding:24px;">
      <h2 style="color:{_NAVY};margin:0 0 4px 0;">Nuovi segnali tecnici</h2>
      <p style="color:{_GRAY};font-size:13px;margin:0 0 20px 0;">
        Eventi tecnici oggettivi rilevati sui tuoi titoli (portafoglio + preferiti), nuovi rispetto
        all'ultima scansione. Non è consulenza finanziaria personalizzata né un ordine da eseguire —
        il piano operativo, quando mostrato, è costruito su livelli tecnici oggettivi da verificare.
      </p>
      {"".join(cards)}
      <p style="color:{_GRAY};font-size:12px;margin-top:20px;">
        Generato automaticamente da Portfolio Manager. Gestisci gli alert nella pagina
        "Impostazioni Alert e Report" dell'app.
      </p>
    </div>
    """
