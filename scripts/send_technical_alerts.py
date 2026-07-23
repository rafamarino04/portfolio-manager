"""
Scansiona portafoglio + preferiti con il motore tecnico (src/alerts.py,
orizzonte medio termine) e manda un'email solo se ci sono segnali NUOVI
rispetto all'ultima scansione (deduplica su data/alert_state.json, così
non si riceve la stessa notifica ogni giorno). Per ogni titolo con un
segnale nuovo allega anche il piano operativo (entrata/stop/target) da
src/technical.trade_plan(), quando il quadro è abbastanza direzionale da
giustificarne uno.

Eseguito automaticamente nei giorni feriali da
.github/workflows/technical_alerts.yml (GitHub Actions, gratuito), dopo
la chiusura di Wall Street. Può essere lanciato anche a mano:
    python scripts/send_technical_alerts.py

Le credenziali email (GMAIL_ADDRESS, GMAIL_APP_PASSWORD) sono lette da
variabili d'ambiente — mai dal codice o da data/settings.json — impostate
come secrets della GitHub Action (vedi README).
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src import alerts  # noqa: E402
from src import email_alerts as ea  # noqa: E402
from src import portfolio as pf  # noqa: E402
from src import report_config as cfg  # noqa: E402
from src import technical as tech  # noqa: E402
from src import watchlist as wl  # noqa: E402
from src.portfolio import CASH_CATEGORY  # noqa: E402

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
STATE_PATH = os.path.join(BASE_DIR, "data", "alert_state.json")
PORTFOLIO_PATH = os.path.join(BASE_DIR, "data", "portfolio.csv")
WATCHLIST_PATH = os.path.join(BASE_DIR, "data", "watchlist.csv")


def load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def collect_tickers() -> list[str]:
    tickers: set[str] = set()
    if os.path.exists(PORTFOLIO_PATH):
        try:
            positions = pf.load_portfolio(PORTFOLIO_PATH)
            if "category" in positions.columns:
                positions = positions[positions["category"] != CASH_CATEGORY]
            tickers |= set(positions["ticker"].dropna().astype(str).str.strip().unique())
        except Exception as e:
            print(f"Impossibile leggere il portafoglio: {e}")
    watch_df = wl.load_watchlist(WATCHLIST_PATH)
    if not watch_df.empty:
        tickers |= set(watch_df["ticker"].dropna().astype(str).str.strip().unique())
    return sorted(t for t in tickers if t)


def main() -> None:
    settings = cfg.load_settings()
    if not settings.get("alerts_enabled", False):
        print("Alert disattivati in Impostazioni Alert e Report: nessuna scansione.")
        return

    enabled_types = set(settings.get("alert_event_types", cfg.ALERT_EVENT_TYPES))
    tickers = collect_tickers()
    if not tickers:
        print("Nessun titolo in portafoglio/preferiti: nessuna scansione.")
        return

    print(f"Scansione di {len(tickers)} titoli: {', '.join(tickers)}")
    state = load_state()
    updated_state = dict(state)
    new_items = []

    for res in alerts.scan_watchlist(tickers):
        symbol = res["symbol"]
        if res["snapshot"] is None:
            continue
        filtered = [a for a in res["alerts"] if a["type"] in enabled_types]
        if not filtered:
            continue

        messages = [a["message"] for a in filtered]
        prev_messages = set(state.get(symbol, {}).get("messages", []))
        new_messages = {m for m in messages if m not in prev_messages}
        updated_state[symbol] = {"messages": messages, "date": dt.date.today().isoformat()}

        if new_messages:
            plan = None
            try:
                plan = tech.trade_plan(res["snapshot"])
            except Exception as e:
                print(f"{symbol}: trade_plan() fallito ({e}), proseguo senza piano operativo.")
            new_items.append({
                "symbol": symbol,
                "alerts": [a for a in filtered if a["message"] in new_messages],
                "trade_plan": plan,
            })

    save_state(updated_state)

    if not new_items:
        print("Nessun nuovo segnale rispetto all'ultima scansione: nessuna email inviata.")
        return

    gmail_address = os.environ.get("GMAIL_ADDRESS", "")
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    recipient = settings.get("alert_recipient_email") or gmail_address

    subject = (
        f"Portfolio Manager - {len(new_items)} nuovo/i segnale/i tecnico/i - "
        f"{dt.date.today().strftime('%d/%m/%Y')}"
    )
    html = ea.build_alert_email_html(new_items)
    ok, msg = ea.send_alert_email(subject, html, recipient, gmail_address, gmail_app_password)
    print(msg)
    if not ok:
        # Non fa fallire il workflow: lo stato va comunque salvato/commesso
        # per non ripetere lo stesso controllo il giorno dopo.
        print("Lo stato dei segnali è stato comunque salvato.")


if __name__ == "__main__":
    main()
