"""
Export in Excel del Fundamental Score (src/fundamental_score.py): le
stesse informazioni mostrate in pagina — le 8 metriche core + crescita,
i sub-score di categoria, i badge Piotroski/Altman, il peer group usato
per i percentili — ma scaricabili e riutilizzabili fuori dall'app.

Convenzione (invariata dalle versioni precedenti di questo modulo): i
valori calcolati dal motore Python (metriche derivate, percentili,
sub-score) sono scritti come dati storici/di input (testo blu), perché
non sono ricavabili da una semplice formula tra celle adiacenti nel
foglio; il punteggio composito totale nel foglio "Categorie e pesi" resta
invece una vera formula Excel (somma pesata di sub-score e Piotroski),
cosi' è ricalcolabile se si modifica un peso o un sub-score a mano.
"""
from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from src import financials as finmod
from src import fundamental_score as fscore

NAVY = "1B2A4A"
GOLD = "C9A227"
GREEN = "1E8E5A"
RED = "C0392B"
GRAY = "6B7280"
INPUT_BLUE = "0000FF"
LIGHT_FILL = "F4F6F9"
HEADER_FILL = "1B2A4A"

FONT_NAME = "Arial"

_RAW_ROWS = [
    ("revenue", "Ricavi"), ("ebitda", "EBITDA"), ("gross_profit", "Utile lordo"),
    ("operating_income", "Utile operativo (EBIT)"), ("net_income", "Utile netto"),
    ("free_cash_flow", "Free cash flow"), ("total_debt", "Debito totale"),
    ("cash", "Cassa"), ("total_equity", "Patrimonio netto"), ("total_assets", "Attivo totale"),
    ("retained_earnings", "Utili non distribuiti"), ("eps", "EPS"),
]

_METRIC_UNIT = {
    "roic": "pct", "gross_profits_to_assets": "pct", "fcf_conversion": "pct",
    "accruals_ratio": "pct", "net_debt_to_ebitda": "ratio", "interest_coverage": "ratio",
    "ev_ebit_yield": "pct", "shareholder_yield": "pct", "revenue_cagr": "pct",
    "eps_cagr": "pct", "growth_volatility": "pct",
}
_METRIC_LABELS_IT = {
    "roic": "ROIC", "gross_profits_to_assets": "Gross profit / Attivo",
    "fcf_conversion": "FCF conversion (FCF/Utile netto)", "accruals_ratio": "Accruals ratio (Sloan)",
    "net_debt_to_ebitda": "Debito netto / EBITDA", "interest_coverage": "Copertura interessi (EBIT/int.)",
    "ev_ebit_yield": "EV/EBIT earnings yield", "shareholder_yield": "Shareholder yield",
    "revenue_cagr": "CAGR ricavi", "eps_cagr": "CAGR EPS", "growth_volatility": "Volatilità crescita ricavi",
}


def _header_font():
    return Font(name=FONT_NAME, bold=True, color="FFFFFF")


def _title_font(size=14):
    return Font(name=FONT_NAME, bold=True, size=size, color=NAVY)


def _label_font(bold=False):
    return Font(name=FONT_NAME, bold=bold, color=NAVY)


def _input_font():
    return Font(name=FONT_NAME, color=INPUT_BLUE)


def _formula_font():
    return Font(name=FONT_NAME, color="000000")


def _style_header_row(ws, row, n_cols, start_col=1):
    for c in range(start_col, start_col + n_cols):
        cell = ws.cell(row=row, column=c)
        cell.font = _header_font()
        cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
        cell.alignment = Alignment(horizontal="center")


def _autosize(ws, widths: dict):
    for col, width in widths.items():
        ws.column_dimensions[col].width = width


def _band_color(band: str) -> str:
    return {"Eccellente": GREEN, "Solido": GREEN, "Nella media": GOLD, "Debole": RED, "Scarso": RED}.get(band, GRAY)


# ---------------------------------------------------------------------------
# Foglio 1 — Sintesi
# ---------------------------------------------------------------------------

def _write_summary_sheet(ws, symbol: str, info: dict, price, result: dict):
    ws.cell(row=1, column=1, value=f"Fundamental Score — {info.get('name', symbol)} ({symbol})").font = _title_font(16)
    ws.cell(row=2, column=1, value=(
        "Portfolio Manager · dati Yahoo Finance (yfinance) · screening comparativo su peer group di "
        "settore, non un fair value · solo a scopo informativo, non consulenza finanziaria"
    )).font = Font(name=FONT_NAME, italic=True, size=9, color=GRAY)

    row = 4
    currency = info.get("currency")
    facts = [
        ("Prezzo", price, "$#,##0.00;($#,##0.00);-"),
        ("Settore", info.get("sector"), None),
        ("Profilo di peso", result.get("weight_profile"), None),
        ("Cap bucket", result.get("cap_bucket"), None),
        ("Numero peer di confronto", result.get("n_peers"), None),
        ("Capitalizzazione", info.get("market_cap"), "$#,##0,,\"M\""),
        ("Valuta", currency, None),
    ]
    for label, val, fmt in facts:
        ws.cell(row=row, column=1, value=label).font = _label_font(bold=True)
        cell = ws.cell(row=row, column=2, value=val)
        cell.font = _input_font()
        if fmt:
            cell.number_format = fmt
        row += 1

    row += 1
    composite = result["composite"]
    ws.cell(row=row, column=1, value="Fundamental Score composito").font = _title_font(12)
    row += 1
    ws.cell(row=row, column=1, value="Punteggio (0-100)").font = _label_font()
    score = composite.get("score")
    cell = ws.cell(row=row, column=2, value=score)
    cell.font = Font(name=FONT_NAME, bold=True, color=_band_color(composite.get("band", "n/d")))
    cell.number_format = "0"
    row += 1
    ws.cell(row=row, column=1, value="Banda").font = _label_font()
    band_cell = ws.cell(row=row, column=2, value=composite.get("band", "n/d"))
    band_cell.font = Font(name=FONT_NAME, bold=True, color=_band_color(composite.get("band", "n/d")))
    row += 1
    if composite.get("insufficient_data"):
        ws.cell(row=row, column=1, value=composite.get("reason", "Copertura dati insufficiente.")).font = Font(
            name=FONT_NAME, italic=True, size=9, color=RED
        )
        row += 1
    if composite.get("altman_capped"):
        ws.cell(row=row, column=1, value="Punteggio limitato a 40 per zona di distress secondo Altman Z.").font = Font(
            name=FONT_NAME, italic=True, size=9, color=RED
        )
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="Badge").font = _title_font(11)
    row += 1
    piotroski = result["piotroski"]
    ws.cell(row=row, column=1, value="Piotroski F-Score (0-9)").font = _label_font()
    p_cell = ws.cell(row=row, column=2, value=piotroski.get("score"))
    p_cell.font = _input_font()
    row += 1
    altman = result["altman"]
    ws.cell(row=row, column=1, value=f"Altman {altman.get('variant') or 'Z'}").font = _label_font()
    a_cell = ws.cell(row=row, column=2, value=altman.get("z"))
    a_cell.font = _input_font()
    a_cell.number_format = "0.00"
    row += 1
    ws.cell(row=row, column=1, value="Zona Altman").font = _label_font()
    zone_it = {"safe": "Sicura", "grey": "Grigia", "distress": "Distress"}.get(altman.get("zone"), "n/d")
    z_cell = ws.cell(row=row, column=2, value=zone_it)
    z_cell.font = Font(name=FONT_NAME, bold=True, color={"Sicura": GREEN, "Grigia": GOLD, "Distress": RED}.get(zone_it, GRAY))
    row += 2

    ws.cell(row=row, column=1, value="Tesi in una riga").font = _title_font(11)
    row += 1
    ws.cell(row=row, column=1, value=fscore.build_thesis_text(result, info))
    ws.cell(row=row, column=1).alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=row, start_column=1, end_row=row + 2, end_column=6)
    ws.row_dimensions[row].height = 50
    row += 4

    bulls, bears = fscore.build_bull_bear(result)
    ws.cell(row=row, column=1, value="Punti di forza").font = Font(name=FONT_NAME, bold=True, color=GREEN)
    row += 1
    if bulls:
        for b in bulls:
            ws.cell(row=row, column=1, value=f"+ {b}")
            row += 1
    else:
        ws.cell(row=row, column=1, value="Nessun punto di forza netto rispetto al peer group.").font = Font(
            name=FONT_NAME, italic=True, size=9, color=GRAY
        )
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="Punti di attenzione").font = Font(name=FONT_NAME, bold=True, color=RED)
    row += 1
    if bears:
        for b in bears:
            ws.cell(row=row, column=1, value=f"- {b}")
            row += 1
    else:
        ws.cell(row=row, column=1, value="Nessun segnale di attenzione rilevato.").font = Font(
            name=FONT_NAME, italic=True, size=9, color=GRAY
        )
        row += 1

    _autosize(ws, {"A": 46, "B": 18, "C": 14, "D": 14, "E": 14, "F": 14})


# ---------------------------------------------------------------------------
# Foglio 2 — Metriche core (le 8 + crescita, con percentile settoriale)
# ---------------------------------------------------------------------------

def _write_metrics_sheet(ws, symbol: str, result: dict):
    ws.cell(row=1, column=1, value=f"Metriche core del Fundamental Score — {symbol}").font = _title_font(14)
    ws.cell(row=2, column=1, value=(
        "Percentile rispetto al peer group di settore (winsorizzato al 5°/95°), orientato cosi' che "
        "un valore più alto sia sempre 'meglio' — non una soglia assoluta."
    )).font = Font(name=FONT_NAME, italic=True, size=9, color=GRAY)

    header_row = 4
    for j, h in enumerate(["Metrica", "Valore", "Percentile settoriale"]):
        ws.cell(row=header_row, column=1 + j, value=h)
    _style_header_row(ws, header_row, 3)

    metrics = result.get("metrics", {})
    percentiles = result.get("metric_percentiles", {})
    row = header_row + 1
    for key, label in _METRIC_LABELS_IT.items():
        ws.cell(row=row, column=1, value=label).font = _label_font()
        val_cell = ws.cell(row=row, column=2, value=metrics.get(key))
        val_cell.font = _input_font()
        val_cell.number_format = "0.00%" if _METRIC_UNIT.get(key) == "pct" else "0.00\"x\""
        # i valori "pct" qui sono già in scala 0-100 (es. 12.3 = 12.3%): usare
        # un formato percentuale diretto richiederebbe /100, quindi si usa
        # un formato numerico con simbolo % applicato al numero cosi' com'è
        if _METRIC_UNIT.get(key) == "pct":
            val_cell.number_format = '0.00"%"'
        pct_cell = ws.cell(row=row, column=3, value=percentiles.get(key))
        pct_cell.font = _input_font()
        pct_cell.number_format = '0"° percentile"'
        row += 1

    ws.cell(row=row + 1, column=1, value=(
        "Fonte: calcolato da src/fundamental_score.py sui bilanci storici (Yahoo Finance) e sul peer "
        "group curato per settore (src/sector_universe.py)."
    )).font = Font(name=FONT_NAME, italic=True, size=9, color=GRAY)

    _autosize(ws, {"A": 38, "B": 14, "C": 20})


# ---------------------------------------------------------------------------
# Foglio 3 — Categorie e pesi (composito ricalcolabile)
# ---------------------------------------------------------------------------

def _write_categories_sheet(ws, symbol: str, result: dict):
    ws.cell(row=1, column=1, value=f"Categorie, pesi e punteggio composito — {symbol}").font = _title_font(14)

    header_row = 3
    for j, h in enumerate(["Categoria", "Sub-score (0-100)", "Peso nel composito (%)"]):
        ws.cell(row=header_row, column=1 + j, value=h)
    _style_header_row(ws, header_row, 3)

    subscores = result.get("subscores", {})
    weights_used = result.get("composite", {}).get("category_weights_used", {})
    row = header_row + 1
    first_cat_row = row
    for cat in fscore.CATEGORIES:
        ws.cell(row=row, column=1, value=fscore.CATEGORY_LABELS_IT[cat]).font = _label_font()
        s_cell = ws.cell(row=row, column=2, value=subscores.get(cat))
        s_cell.font = _input_font()
        s_cell.number_format = "0.0"
        w_cell = ws.cell(row=row, column=3, value=weights_used.get(cat))
        w_cell.font = _input_font()
        w_cell.number_format = "0.0"
        row += 1
    last_cat_row = row - 1

    piotroski = result.get("piotroski", {})
    piotroski_weight = result.get("composite", {}).get("piotroski_weight_used")
    ws.cell(row=row, column=1, value="Piotroski F-Score (scalato 0-100)").font = _label_font()
    piotroski_scaled = (piotroski["score"] / 9 * 100) if piotroski.get("score") is not None else None
    p_cell = ws.cell(row=row, column=2, value=piotroski_scaled)
    p_cell.font = _input_font()
    p_cell.number_format = "0.0"
    pw_cell = ws.cell(row=row, column=3, value=piotroski_weight)
    pw_cell.font = _input_font()
    pw_cell.number_format = "0.0"
    piotroski_row = row
    row += 2

    ws.cell(row=row, column=1, value="Punteggio composito (formula ricalcolabile)").font = _label_font(bold=True)
    total_cell = ws.cell(
        row=row, column=2,
        value=f"=IFERROR(SUMPRODUCT(B{first_cat_row}:B{last_cat_row},C{first_cat_row}:C{last_cat_row})/100"
              f"+IF(B{piotroski_row}=\"\",0,B{piotroski_row}*C{piotroski_row}/100),\"n/d\")",
    )
    total_cell.font = Font(name=FONT_NAME, bold=True, color=NAVY)
    total_cell.number_format = "0.0"
    row += 1
    if result.get("composite", {}).get("altman_capped"):
        ws.cell(row=row, column=1, value=(
            "Nota: il punteggio mostrato in pagina è limitato a 40 per zona di distress Altman Z — la "
            "formula sopra ricalcola il composito 'grezzo' pre-override, utile per capire quanto la "
            "qualità operativa sarebbe alta se non fosse per il rischio di solvibilità."
        )).font = Font(name=FONT_NAME, italic=True, size=9, color=RED)
        row += 1

    row += 1
    ws.cell(row=row, column=1, value=(
        "I pesi di categoria sono già cap/settore-adjusted e ridistribuiti sulle categorie disponibili "
        "in caso di dati mancanti (specifica §6-7): modificarli manualmente sopra rompe questa coerenza "
        "— utile solo per simulazioni 'what-if'."
    )).font = Font(name=FONT_NAME, italic=True, size=9, color=GRAY)

    _autosize(ws, {"A": 44, "B": 18, "C": 20})


# ---------------------------------------------------------------------------
# Foglio 4 — Bilancio annuale (dati grezzi + margini calcolati)
# ---------------------------------------------------------------------------

def _period_labels(hist: dict) -> list[str]:
    for key, _ in _RAW_ROWS:
        s = hist.get(key)
        if s is not None and len(s) > 0:
            return [c.strftime("%Y-%m") if hasattr(c, "strftime") else str(c) for c in s.index]
    return []


def _write_raw_table(ws, start_row: int, hist: dict, title: str) -> int:
    labels = _period_labels(hist)
    ws.cell(row=start_row, column=1, value=title).font = _title_font(12)
    header_row = start_row + 1
    ws.cell(row=header_row, column=1, value="Voce (dati storici Yahoo Finance)").font = _header_font()
    for j, lbl in enumerate(labels):
        ws.cell(row=header_row, column=2 + j, value=lbl)
    _style_header_row(ws, header_row, 1 + len(labels))

    row_map = {}
    r = header_row + 1
    for key, label in _RAW_ROWS:
        s = hist.get(key)
        ws.cell(row=r, column=1, value=label).font = _label_font()
        if s is not None:
            for j in range(len(labels)):
                val = float(s.iloc[j]) if j < len(s) else None
                cell = ws.cell(row=r, column=2 + j, value=val)
                cell.font = _input_font()
                cell.number_format = "$#,##0;($#,##0);-" if key != "eps" else "$#,##0.00;($#,##0.00);-"
        row_map[key] = r
        r += 1

    margin_defs = [
        ("gross_profit", "Margine lordo %"), ("operating_income", "Margine operativo %"),
        ("ebitda", "Margine EBITDA %"), ("net_income", "Margine netto %"),
    ]
    for num_key, label in margin_defs:
        if num_key not in row_map or "revenue" not in row_map:
            continue
        ws.cell(row=r, column=1, value=label).font = _label_font()
        num_row, rev_row = row_map[num_key], row_map["revenue"]
        for j in range(len(labels)):
            col = get_column_letter(2 + j)
            formula = f"=IFERROR({col}{num_row}/{col}{rev_row},\"n/d\")"
            cell = ws.cell(row=r, column=2 + j, value=formula)
            cell.font = _formula_font()
            cell.number_format = "0.0%"
        r += 1

    ws.cell(row=r, column=1, value=(
        "Fonte: Yahoo Finance (yfinance), prospetti contabili annuali. Le voci sopra sono dati storici "
        "(input, testo blu); i margini % sotto sono formule (testo nero)."
    )).font = Font(name=FONT_NAME, italic=True, size=9, color=GRAY)

    widths = {"A": 30}
    for j in range(len(labels)):
        widths[get_column_letter(2 + j)] = 13
    _autosize(ws, widths)
    return r + 2


# ---------------------------------------------------------------------------
# Foglio 5 — Peer group (trasparenza sulla distribuzione usata per i percentili)
# ---------------------------------------------------------------------------

def _write_peer_group_sheet(ws, symbol: str, result: dict):
    ws.cell(row=1, column=1, value=f"Peer group di settore usato per i percentili — {symbol}").font = _title_font(14)
    peer_metrics = result.get("peer_metrics", {})
    if not peer_metrics:
        ws.cell(row=3, column=1, value="Nessun peer disponibile (peer group non caricato o settore senza lista curata).").font = _label_font()
        return

    metric_keys = list(_METRIC_LABELS_IT.keys())
    header_row = 3
    ws.cell(row=header_row, column=1, value="Ticker")
    for j, key in enumerate(metric_keys):
        ws.cell(row=header_row, column=2 + j, value=_METRIC_LABELS_IT[key])
    _style_header_row(ws, header_row, 1 + len(metric_keys))

    row = header_row + 1
    for ticker in sorted(peer_metrics.keys()):
        m = peer_metrics[ticker]
        ws.cell(row=row, column=1, value=ticker).font = _label_font(bold=True)
        for j, key in enumerate(metric_keys):
            cell = ws.cell(row=row, column=2 + j, value=m.get(key))
            cell.font = _input_font()
            cell.number_format = "0.00"
        row += 1

    ws.cell(row=row + 1, column=1, value=(
        "Fonte: cache locale (src/fundamental_cache.py), aggiornata al più ogni 90 giorni dai bilanci "
        "Yahoo Finance dei ticker del peer group curato (src/sector_universe.py). Serve a rendere "
        "verificabile il percentile mostrato in pagina, non è una raccomandazione sui peer stessi."
    )).font = Font(name=FONT_NAME, italic=True, size=9, color=GRAY)

    widths = {"A": 12}
    for j in range(len(metric_keys)):
        widths[get_column_letter(2 + j)] = 16
    _autosize(ws, widths)


# ---------------------------------------------------------------------------
# Orchestrazione
# ---------------------------------------------------------------------------

def build_excel_report(symbol: str, info: dict, price, result: dict) -> bytes:
    """Costruisce il workbook completo del Fundamental Score e lo ritorna
    come bytes, pronto per `st.download_button`. `result` è l'output di
    `fundamental_score.build_fundamental_score()`."""
    wb = Workbook()
    ws_summary = wb.active
    ws_summary.title = "Sintesi"
    _write_summary_sheet(ws_summary, symbol, info, price, result)

    ws_metrics = wb.create_sheet("Metriche core")
    _write_metrics_sheet(ws_metrics, symbol, result)

    ws_cat = wb.create_sheet("Categorie e pesi")
    _write_categories_sheet(ws_cat, symbol, result)

    ws_annual = wb.create_sheet("Bilancio annuale")
    hist = finmod.get_financial_history(symbol, freq="annual")
    _write_raw_table(ws_annual, 1, hist, f"Bilancio annuale — {symbol}")

    ws_peers = wb.create_sheet("Peer group")
    _write_peer_group_sheet(ws_peers, symbol, result)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
