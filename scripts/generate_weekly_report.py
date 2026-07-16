"""
Genera il report periodico del portafoglio in Markdown e aggiorna lo
storico (reports/history.csv) usato per il grafico dell'andamento nel tempo.
Le sezioni incluse dipendono da data/settings.json (pagina "Impostazioni
Report" dell'app).

Eseguito automaticamente ogni lunedi' da .github/workflows/weekly_report.yml
(GitHub Actions, gratuito). Puoi anche lanciarlo a mano:
    python scripts/generate_weekly_report.py
"""
import csv
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src import benchmark as bm  # noqa: E402
from src import data_provider as dp  # noqa: E402
from src import opportunities as opp  # noqa: E402
from src import portfolio as pf  # noqa: E402
from src import rebalancing as rb  # noqa: E402
from src import report_config as cfg  # noqa: E402

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")
HISTORY_CSV = os.path.join(REPORTS_DIR, "history.csv")
CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "portfolio.csv")
SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "settings.json")


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


def section_overview(summary: dict) -> list[str]:
    tv, tc = summary.get("total_value"), summary.get("total_cost")
    tp, tpp = summary.get("total_pl"), summary.get("total_pl_pct")
    lines = [
        f"**Valore totale:** {tv:,.2f}" if tv is not None else "**Valore totale:** n/d",
        f"**Costo totale:** {tc:,.2f}" if tc is not None else "**Costo totale:** n/d",
        f"**P&L totale:** {tp:,.2f} ({tpp:.2f}%)" if tp is not None and tpp is not None else "**P&L totale:** n/d",
        "",
    ]
    best, worst = summary.get("best"), summary.get("worst")
    if best is not None:
        lines.append(f"**Miglior titolo:** {best['ticker']} ({best['pl_pct']:.2f}%)")
    if worst is not None:
        lines.append(f"**Peggior titolo:** {worst['ticker']} ({worst['pl_pct']:.2f}%)")
    lines.append("")
    return lines


def section_allocation(enriched) -> list[str]:
    lines = ["## Posizioni", "", "| Ticker | Categoria | Prezzo | Valore | P&L | P&L % |", "|---|---|---|---|---|---|"]
    for _, row in enriched.iterrows():
        price = f"{row['price']:.2f}" if row["price"] is not None else "n/d"
        mv = f"{row['market_value']:,.2f}" if row["market_value"] is not None else "n/d"
        pl = f"{row['pl_abs']:,.2f}" if row["pl_abs"] is not None else "n/d"
        plp = f"{row['pl_pct']:.2f}%" if row["pl_pct"] is not None else "n/d"
        lines.append(f"| {row['ticker']} | {row.get('category', 'n/d')} | {price} | {mv} | {pl} | {plp} |")
    lines.append("")
    return lines


def section_rebalancing(enriched, settings: dict) -> list[str]:
    table = rb.compute_rebalancing(
        enriched, settings["target_allocation"], settings["rebalance_tolerance_pct"]
    )
    if table.empty:
        return []
    lines = ["## Ribilanciamento", "", "| Categoria | Target | Attuale | Scarto | Azione |", "|---|---|---|---|---|"]
    for _, row in table.iterrows():
        lines.append(
            f"| {row['category']} | {row['target_pct']:.1f}% | {row['actual_pct']:.1f}% | "
            f"{row['drift_pct']:+.1f}% | {row['action']} |"
        )
    lines.append("")
    return lines


def section_benchmark(raw, summary, settings: dict) -> list[str]:
    ticker = settings["benchmark_ticker"]
    name = settings.get("benchmark_name", ticker)
    since = bm.since_inception_comparison(raw, summary, ticker)
    lines = ["## Benchmark e Performance", ""]
    if since:
        lines.append(
            f"Da {since['start_date'].strftime('%d/%m/%Y')}: portafoglio "
            f"{since['portfolio_return_pct']:+.2f}% vs {name} {since['benchmark_return_pct']:+.2f}% "
            f"(differenza {since['difference_pct']:+.2f}%)."
        )
    else:
        lines.append("Dati insufficienti per il confronto con il benchmark questa settimana.")
    lines.append("")
    return lines


def section_opportunities(enriched) -> list[str]:
    scan = opp.scan_holdings(enriched)
    flagged = scan[scan["flags"] != "Nella norma"] if not scan.empty else scan
    lines = ["## Opportunità di Mercato", ""]
    if flagged.empty:
        lines.append("Nessun segnale particolare sui titoli in portafoglio questa settimana.")
    else:
        for _, row in flagged.iterrows():
            lines.append(f"- **{row['ticker']}**: {row['flags']}")
    lines.append("")
    return lines


def section_news(enriched) -> list[str]:
    lines = ["## News principali", ""]
    for _, row in enriched.iterrows():
        if row.get("category") == "Liquidità":
            continue
        ticker = row["ticker"]
        news = dp.get_news(ticker, limit=2)
        if news:
            lines.append(f"**{ticker}**")
            for n in news:
                title, link = n.get("title"), n.get("link")
                lines.append(f"- [{title}]({link})" if link else f"- {title}")
    lines.append("")
    return lines


def build_report(raw, enriched, summary, settings: dict, today: str) -> str:
    lines = [f"# Report portafoglio — {today}", ""]
    sections = settings.get("report_sections", [])

    if "overview" in sections:
        lines += section_overview(summary)
    if "allocation" in sections:
        lines += section_allocation(enriched)
    if "rebalancing" in sections:
        lines += section_rebalancing(enriched, settings)
    if "benchmark" in sections:
        lines += section_benchmark(raw, summary, settings)
    if "opportunities" in sections:
        lines += section_opportunities(enriched)
    if "news" in sections:
        lines += section_news(enriched)

    return "\n".join(lines)


def main():
    today = dt.date.today().isoformat()
    settings = cfg.load_settings(SETTINGS_PATH)
    raw = pf.load_portfolio(CSV_PATH)
    enriched = pf.enrich_with_prices(raw)
    summary = pf.portfolio_summary(enriched)

    os.makedirs(REPORTS_DIR, exist_ok=True)
    report_md = build_report(raw, enriched, summary, settings, today)

    with open(os.path.join(REPORTS_DIR, f"{today}.md"), "w") as f:
        f.write(report_md)
    with open(os.path.join(REPORTS_DIR, "latest.md"), "w") as f:
        f.write(report_md)

    append_history(summary, today)
    print(f"Report generato: reports/{today}.md")


if __name__ == "__main__":
    main()
