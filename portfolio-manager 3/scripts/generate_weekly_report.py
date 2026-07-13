"""
Genera il report settimanale del portafoglio in Markdown e aggiorna lo
storico (reports/history.csv) usato per il grafico dell'andamento nel tempo.

Eseguito automaticamente ogni lunedi' da .github/workflows/weekly_report.yml
(GitHub Actions, gratuito). Puoi anche lanciarlo a mano:
    python scripts/generate_weekly_report.py
"""
import csv
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src import data_provider as dp  # noqa: E402
from src import portfolio as pf  # noqa: E402

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")
HISTORY_CSV = os.path.join(REPORTS_DIR, "history.csv")
CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "portfolio.csv")


def append_history(summary: dict, today: str) -> None:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    is_new = not os.path.exists(HISTORY_CSV)
    with open(HISTORY_CSV, "a", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["date", "total_value", "total_cost", "total_pl", "total_pl_pct"])
        writer.writerow([
            today,
            summary.get("total_value"),
            summary.get("total_cost"),
            summary.get("total_pl"),
            summary.get("total_pl_pct"),
        ])


def build_report(enriched, summary, today: str) -> str:
    lines = [f"# Report settimanale portafoglio — {today}", ""]

    tv = summary.get("total_value")
    tc = summary.get("total_cost")
    tp = summary.get("total_pl")
    tpp = summary.get("total_pl_pct")
    lines.append(f"**Valore totale:** {tv:,.2f}" if tv is not None else "**Valore totale:** n/d")
    lines.append(f"**Costo totale:** {tc:,.2f}" if tc is not None else "**Costo totale:** n/d")
    lines.append(
        f"**P&L totale:** {tp:,.2f} ({tpp:.2f}%)" if tp is not None and tpp is not None else "**P&L totale:** n/d"
    )
    lines.append("")

    best = summary.get("best")
    worst = summary.get("worst")
    if best is not None:
        lines.append(f"**Miglior titolo:** {best['ticker']} ({best['pl_pct']:.2f}%)")
    if worst is not None:
        lines.append(f"**Peggior titolo:** {worst['ticker']} ({worst['pl_pct']:.2f}%)")
    lines.append("")

    lines.append("## Posizioni")
    lines.append("")
    lines.append("| Ticker | Prezzo | Valore | P&L | P&L % |")
    lines.append("|---|---|---|---|---|")
    for _, row in enriched.iterrows():
        price = f"{row['price']:.2f}" if row["price"] is not None else "n/d"
        mv = f"{row['market_value']:,.2f}" if row["market_value"] is not None else "n/d"
        pl = f"{row['pl_abs']:,.2f}" if row["pl_abs"] is not None else "n/d"
        plp = f"{row['pl_pct']:.2f}%" if row["pl_pct"] is not None else "n/d"
        lines.append(f"| {row['ticker']} | {price} | {mv} | {pl} | {plp} |")
    lines.append("")

    lines.append("## News principali")
    for _, row in enriched.iterrows():
        ticker = row["ticker"]
        news = dp.get_news(ticker, limit=2)
        if news:
            lines.append(f"**{ticker}**")
            for n in news:
                title = n.get("title")
                link = n.get("link")
                lines.append(f"- [{title}]({link})" if link else f"- {title}")
    lines.append("")

    return "\n".join(lines)


def main():
    today = dt.date.today().isoformat()
    raw = pf.load_portfolio(CSV_PATH)
    enriched = pf.enrich_with_prices(raw)
    summary = pf.portfolio_summary(enriched)

    os.makedirs(REPORTS_DIR, exist_ok=True)
    report_md = build_report(enriched, summary, today)

    with open(os.path.join(REPORTS_DIR, f"{today}.md"), "w") as f:
        f.write(report_md)
    with open(os.path.join(REPORTS_DIR, "latest.md"), "w") as f:
        f.write(report_md)

    append_history(summary, today)
    print(f"Report generato: reports/{today}.md")


if __name__ == "__main__":
    main()
