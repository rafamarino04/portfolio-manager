"""
Export in Excel dell'analisi fondamentale: le stesse tabelle mostrate in
pagina, ma scaricabili e riutilizzabili fuori dall'app (per chi vuole
tenere traccia delle proprie analisi, incollarle in un modello più ampio,
o semplicemente rivederle offline).

I dati grezzi (ricavi, utile, debito, ecc.) sono valori storici presi da
Yahoo Finance: sono un input, non un calcolo, e vengono scritti come tali
(testo blu, per convenzione). I margini/ratio derivati sotto sono invece
vere formule Excel che leggono quei valori — così restano ricalcolabili
e verificabili anche fuori dall'app, non numeri congelati.
"""
from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

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
    ("operating_income", "Utile operativo"), ("net_income", "Utile netto"),
    ("free_cash_flow", "Free cash flow"), ("total_debt", "Debito totale"),
    ("cash", "Cassa"), ("total_equity", "Patrimonio netto"), ("eps", "EPS"),
]


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


def _period_labels(hist: dict) -> list[str]:
    for key, _ in _RAW_ROWS:
        s = hist.get(key)
        if s is not None and len(s) > 0:
            return [c.strftime("%Y-%m") if hasattr(c, "strftime") else str(c) for c in s.index]
    return []


def _write_raw_table(ws, start_row: int, hist: dict, title: str) -> tuple[int, dict]:
    """Scrive una tabella di dati grezzi (periodi in colonna) e ritorna la
    riga di fine tabella + una mappa {chiave_metrica: numero_riga} utile
    per costruire poi le formule dei margini."""
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
            aligned = s.reindex(s.index)  # already sorted
            for j, lbl in enumerate(labels):
                val = None
                if j < len(s):
                    val = float(s.iloc[j])
                cell = ws.cell(row=r, column=2 + j, value=val)
                cell.font = _input_font()
                cell.number_format = "$#,##0;($#,##0);-" if key != "eps" else "$#,##0.00;($#,##0.00);-"
        row_map[key] = r
        r += 1

    # Margini derivati come formule (dividono le righe di input sopra)
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

    ws.cell(row=r, column=1, value="Fonte: Yahoo Finance (yfinance), prospetti contabili storici. "
                                    "Le voci sopra sono dati storici (input); i margini % sotto sono formule.").font = Font(
        name=FONT_NAME, italic=True, size=9, color=GRAY
    )
    return r + 2, row_map


def _write_ratio_sheet(ws, symbol: str, sections: dict, breakdown: dict, currency: str | None):
    ws.cell(row=1, column=1, value=f"Ratio e punteggio fondamentale — {symbol}").font = _title_font(14)

    row = 3
    ws.cell(row=row, column=1, value="Sostenibilità: rendimento sul capitale e costo del capitale").font = _title_font(11)
    row += 1
    sus = sections.get("sustainability", {})
    pairs = [
        ("ROIC (%)", sus.get("roic")),
        ("WACC (%)", sus.get("wacc")),
        ("Spread ROIC - WACC (p.p.)",
         (sus.get("roic") - sus.get("wacc")) if sus.get("roic") is not None and sus.get("wacc") is not None else None),
    ]
    for label, val in pairs:
        ws.cell(row=row, column=1, value=label).font = _label_font()
        cell = ws.cell(row=row, column=2, value=val)
        cell.font = _input_font()
        cell.number_format = "0.0"
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="Sostenibilità: qualità degli utili").font = _title_font(11)
    row += 1
    quality = sus.get("quality", {}) or {}
    ratio_pairs = [
        ("FCF medio / Utile netto medio (%)", quality.get("avg_ratio")),
    ]
    for label, val in ratio_pairs:
        ws.cell(row=row, column=1, value=label).font = _label_font()
        cell = ws.cell(row=row, column=2, value=val)
        cell.font = _input_font()
        cell.number_format = "0.00"
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="Punteggio per domanda (scala -1 / +1)").font = _title_font(11)
    row += 1
    header_row = row
    for j, h in enumerate(["Domanda", "Punteggio", "Peso"]):
        ws.cell(row=header_row, column=1 + j, value=h)
    _style_header_row(ws, header_row, 3)
    row += 1
    axis_labels = {
        "profitability": "È profittevole?", "sustainability": "È sostenibile nel tempo?",
        "outlook": "Ha buone prospettive?",
    }
    first_score_row = row
    sub_scores = breakdown.get("sub_scores", {})
    weights_used = breakdown.get("weights_used", {})
    for key, label in axis_labels.items():
        ws.cell(row=row, column=1, value=label).font = _label_font()
        s_cell = ws.cell(row=row, column=2, value=sub_scores.get(key))
        s_cell.font = _input_font()
        s_cell.number_format = "0.00"
        w_cell = ws.cell(row=row, column=3, value=weights_used.get(key))
        w_cell.font = _input_font()
        w_cell.number_format = "0.0%"
        row += 1
    last_score_row = row - 1

    row += 1
    ws.cell(row=row, column=1, value="Punteggio composito totale").font = _label_font(bold=True)
    total_cell = ws.cell(
        row=row, column=2,
        value=f"=IFERROR(SUMPRODUCT(B{first_score_row}:B{last_score_row},C{first_score_row}:C{last_score_row})"
              f"/SUM(C{first_score_row}:C{last_score_row}),\"n/d\")",
    )
    total_cell.font = Font(name=FONT_NAME, bold=True, color=NAVY)
    total_cell.number_format = "0.00"
    row += 2
    ws.cell(row=row, column=1, value=(
        "Nota: i punteggi per domanda derivano dal modello di analisi dell'app (regole esplicite "
        "applicate a dati di bilancio/mercato reali, nessuna formula di fair value inventata), non da "
        "una formula Excel — il totale sopra è invece una vera media pesata, ricalcolabile se si "
        "modificano punteggio o peso di una domanda. È una lettura secondaria, non un rating."
    )).font = Font(name=FONT_NAME, italic=True, size=9, color=GRAY)

    _autosize(ws, {"A": 42, "B": 16, "C": 12})


def _write_peer_sheet(ws, peer_df, symbol: str):
    ws.cell(row=1, column=1, value=f"Confronto concorrenti — {symbol}").font = _title_font(14)
    if peer_df is None or peer_df.empty:
        ws.cell(row=3, column=1, value="Nessun concorrente impostato per questo titolo.").font = _label_font()
        return

    header_row = 3
    cols = list(peer_df.columns)
    for j, col in enumerate(cols):
        ws.cell(row=header_row, column=1 + j, value=col)
    _style_header_row(ws, header_row, len(cols))

    data_start = header_row + 1
    for i, (_, rec) in enumerate(peer_df.iterrows()):
        for j, col in enumerate(cols):
            val = rec[col]
            cell = ws.cell(row=data_start + i, column=1 + j, value=val)
            cell.font = _input_font() if col != "Ticker" else _label_font(bold=(i == 0))
            if col not in ("Ticker",):
                cell.number_format = "0.00"

    avg_row = data_start + len(peer_df)
    ws.cell(row=avg_row, column=1, value="Media concorrenti (esclude il titolo analizzato)").font = _label_font(bold=True)
    if len(peer_df) > 1:
        for j, col in enumerate(cols[1:], start=1):
            col_letter = get_column_letter(1 + j)
            formula = f"=IFERROR(AVERAGE({col_letter}{data_start + 1}:{col_letter}{data_start + len(peer_df) - 1}),\"n/d\")"
            cell = ws.cell(row=avg_row, column=1 + j, value=formula)
            cell.font = _formula_font()
            cell.number_format = "0.00"

    _autosize(ws, {get_column_letter(1 + j): 16 for j in range(len(cols))} | {"A": 14})


def _write_summary_sheet(ws, symbol: str, info: dict, price, sections: dict, breakdown: dict, synthesis: str):
    ws.cell(row=1, column=1, value=f"Analisi Fondamentale — {info.get('name', symbol)} ({symbol})").font = _title_font(16)
    ws.cell(row=2, column=1, value="Portfolio Manager · dati Yahoo Finance · solo a scopo informativo, non consulenza finanziaria").font = Font(
        name=FONT_NAME, italic=True, size=9, color=GRAY
    )

    row = 4
    facts = [
        ("Prezzo", price), ("Settore", info.get("sector")),
        ("Capitalizzazione", info.get("market_cap")), ("Valuta", info.get("currency")),
    ]
    for label, val in facts:
        ws.cell(row=row, column=1, value=label).font = _label_font(bold=True)
        cell = ws.cell(row=row, column=2, value=val)
        cell.font = _input_font()
        if label == "Capitalizzazione":
            cell.number_format = "$#,##0,,\"M\""
        row += 1

    target = info.get("target_mean_price")
    n_analysts = info.get("num_analyst_opinions")
    if target and price and n_analysts:
        row += 1
        ws.cell(row=row, column=1, value="Consensus reale degli analisti (dato di mercato, non una stima dell'app)").font = _title_font(11)
        row += 1
        ws.cell(row=row, column=1, value="Target price medio").font = _label_font()
        cell = ws.cell(row=row, column=2, value=target)
        cell.font = _input_font()
        cell.number_format = "$#,##0.00;($#,##0.00);-"
        row += 1
        ws.cell(row=row, column=1, value="Numero di analisti").font = _label_font()
        cell = ws.cell(row=row, column=2, value=n_analysts)
        cell.font = _input_font()
        row += 1
        ws.cell(row=row, column=1, value="Rendimento implicito vs prezzo attuale (%)").font = _label_font(bold=True)
        col_price_cell = None
        for r in range(4, row):
            if ws.cell(row=r, column=1).value == "Prezzo":
                col_price_cell = f"B{r}"
                break
        cell = ws.cell(
            row=row, column=2,
            value=f"=IFERROR(B{row-2}/{col_price_cell}-1,\"n/d\")" if col_price_cell else None,
        )
        cell.font = Font(name=FONT_NAME, bold=True, color=NAVY)
        cell.number_format = "+0.0%;-0.0%"
        row += 1
        ws.cell(row=row, column=1, value=(
            "Raccomandazione aggregata: " + str(info.get("recommendation_key") or "n/d")
        )).font = Font(name=FONT_NAME, italic=True, size=9, color=GRAY)
        row += 1

    row += 1
    total = breakdown.get("total")
    ws.cell(row=row, column=1, value="Punteggio composito").font = _label_font(bold=True)
    tcell = ws.cell(row=row, column=2, value=total)
    tcell.font = Font(name=FONT_NAME, bold=True, color=(GREEN if total and total > 0.15 else (RED if total and total < -0.15 else GRAY)))
    tcell.number_format = "+0.00;-0.00"
    row += 2

    ws.cell(row=row, column=1, value="Le tre domande, in chiaro").font = _title_font(11)
    row += 1
    axis_labels = {
        "profitability": "È profittevole?", "sustainability": "È sostenibile nel tempo?",
        "outlook": "Ha buone prospettive?",
    }
    for key, label in axis_labels.items():
        s = sections.get(key)
        if not s:
            continue
        ws.cell(row=row, column=1, value=label).font = _label_font()
        v = s.get("verdict", "neutro")
        color = {"positivo": GREEN, "negativo": RED, "neutro": GRAY}[v]
        vcell = ws.cell(row=row, column=2, value=v.capitalize())
        vcell.font = Font(name=FONT_NAME, bold=True, color=color)
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="Sintesi").font = _title_font(11)
    row += 1
    ws.cell(row=row, column=1, value=synthesis)
    ws.cell(row=row, column=1).alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=row, start_column=1, end_row=row + 6, end_column=6)
    ws.row_dimensions[row].height = 100

    _autosize(ws, {"A": 32, "B": 20, "C": 14, "D": 14, "E": 14, "F": 14})


def build_excel_report(symbol: str, info: dict, price, narrative: dict) -> bytes:
    """Costruisce il workbook completo dell'analisi fondamentale e lo
    ritorna come bytes, pronto per `st.download_button`."""
    sections = {s["key"]: s for s in narrative["sections"]}
    breakdown = narrative.get("score_breakdown", {})
    currency = info.get("currency")

    wb = Workbook()
    ws_summary = wb.active
    ws_summary.title = "Sintesi"
    _write_summary_sheet(ws_summary, symbol, info, price, sections, breakdown, narrative.get("synthesis", ""))

    ws_annual = wb.create_sheet("Bilancio annuale")
    annual_hist = sections.get("profitability", {}).get("annual", {})
    _write_raw_table(ws_annual, 1, annual_hist, f"Bilancio annuale — {symbol}")

    ws_ratio = wb.create_sheet("Ratio e punteggio")
    _write_ratio_sheet(ws_ratio, symbol, sections, breakdown, currency)

    peer_table = sections.get("outlook", {}).get("peer_table")
    ws_peer = wb.create_sheet("Concorrenti")
    _write_peer_sheet(ws_peer, peer_table, symbol)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
