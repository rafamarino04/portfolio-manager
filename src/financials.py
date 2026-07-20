"""
Numeri di bilancio: storico multi-periodo di ricavi, EBITDA, utile netto,
margini, free cash flow, debito/cassa e patrimonio netto, dai prospetti
contabili di Yahoo Finance (conto economico, bilancio, flussi di cassa,
via yfinance) — più i ratio derivati (leva, liquidità, copertura interessi,
ROIC) e gli strumenti di formattazione numerica usati in tutta la sezione
di Analisi Fondamentale.

Le etichette delle righe dei prospetti non sono rigidamente standardizzate
da Yahoo Finance (variano leggermente per settore e nel tempo): ogni
metrica viene quindi cercata provando più varianti, con fallback a None
se non disponibile per quel titolo — tipico per società finanziarie
(niente "Gross Profit", niente EBITDA operativo comparabile) o per titoli
a copertura Yahoo Finance più scarsa (spesso i titoli non statunitensi).
"""
from __future__ import annotations

import pandas as pd

from src import data_provider as dp

# ---------------------------------------------------------------------------
# Etichette righe prospetti (conto economico / bilancio / flussi di cassa)
# ---------------------------------------------------------------------------
_REVENUE_LABELS = ["Total Revenue", "TotalRevenue", "Revenue"]
_NET_INCOME_LABELS = ["Net Income", "Net Income Common Stockholders", "NetIncome"]
_GROSS_PROFIT_LABELS = ["Gross Profit"]
_OPERATING_INCOME_LABELS = ["Operating Income", "Total Operating Income As Reported"]
_EBITDA_LABELS = ["EBITDA", "Normalized EBITDA"]
_DA_LABELS = [
    "Reconciled Depreciation", "Depreciation And Amortization",
    "Depreciation Amortization Depletion", "Depreciation",
]
_OPERATING_CASHFLOW_LABELS = [
    "Operating Cash Flow", "Cash Flow From Continuing Operating Activities",
    "Total Cash From Operating Activities",
]
_CAPEX_LABELS = ["Capital Expenditure", "Capital Expenditures", "Purchase Of PPE"]
_FREE_CASHFLOW_LABELS = ["Free Cash Flow"]
_TOTAL_DEBT_LABELS = ["Total Debt"]
_CASH_LABELS = [
    "Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments",
    "Cash Financial",
]
_EQUITY_LABELS = ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"]
_EPS_LABELS = ["Diluted EPS", "Basic EPS"]
_CURRENT_ASSETS_LABELS = ["Current Assets", "Total Current Assets"]
_CURRENT_LIABILITIES_LABELS = ["Current Liabilities", "Total Current Liabilities"]
_INTEREST_EXPENSE_LABELS = [
    "Interest Expense", "Interest Expense Non Operating",
    "Net Non Operating Interest Income Expense",
]
_PRETAX_INCOME_LABELS = ["Pretax Income"]
_TAX_PROVISION_LABELS = ["Tax Provision"]
_DILUTED_SHARES_LABELS = ["Diluted Average Shares", "Basic Average Shares"]

METRIC_KEYS = [
    "revenue", "net_income", "gross_profit", "operating_income", "ebitda",
    "depreciation_amortization", "operating_cash_flow", "capex", "free_cash_flow",
    "total_debt", "cash", "total_equity", "eps", "current_assets",
    "current_liabilities", "interest_expense", "pretax_income", "tax_provision",
    "diluted_shares",
]

CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "CHF": "CHF ", "JPY": "¥"}


# ---------------------------------------------------------------------------
# Helpers di estrazione/pulizia
# ---------------------------------------------------------------------------

def _find_row(df: pd.DataFrame, candidates: list[str]) -> pd.Series | None:
    if df is None or df.empty:
        return None
    idx_lower = {str(i).strip().lower(): i for i in df.index}
    for cand in candidates:
        key = cand.strip().lower()
        if key in idx_lower:
            return df.loc[idx_lower[key]]
    for cand in candidates:
        key = cand.strip().lower()
        for lower_name, orig in idx_lower.items():
            if key in lower_name:
                return df.loc[orig]
    return None


def _clean(s: pd.Series | None) -> pd.Series | None:
    if s is None:
        return None
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty:
        return None
    return s.sort_index()


def _ratio_series(num: pd.Series | None, den: pd.Series | None, multiplier: float = 1.0) -> pd.Series | None:
    """Divide due serie allineandole sui periodi in comune. Usato per
    tutti i margini/ratio derivati (percentuali o multipli)."""
    if num is None or den is None:
        return None
    n, d = num.align(den, join="inner")
    if n.empty:
        return None
    d = d.replace(0, pd.NA)
    r = (n / d * multiplier).replace([float("inf"), float("-inf")], pd.NA).dropna()
    return r if not r.empty else None


def _diff_series(a: pd.Series | None, b: pd.Series | None) -> pd.Series | None:
    """a - b sui periodi in comune (es. debito netto = debito - cassa)."""
    if a is None or b is None:
        return None
    x, y = a.align(b, join="inner")
    if x.empty:
        return None
    return (x - y).dropna()


def _last(series: pd.Series | None) -> float | None:
    if series is None or series.empty:
        return None
    return float(series.iloc[-1])


# ---------------------------------------------------------------------------
# Estrazione storico
# ---------------------------------------------------------------------------

def get_financial_history(symbol: str, freq: str = "annual") -> dict:
    """Serie temporali (dalla più vecchia alla più recente) per le
    metriche principali. `freq`: 'annual' o 'quarterly'."""
    out: dict = {k: None for k in METRIC_KEYS}
    try:
        t = dp.get_ticker(symbol)
        if freq == "quarterly":
            income, balance, cash = t.quarterly_income_stmt, t.quarterly_balance_sheet, t.quarterly_cashflow
        else:
            income, balance, cash = t.income_stmt, t.balance_sheet, t.cashflow

        out["revenue"] = _clean(_find_row(income, _REVENUE_LABELS))
        out["net_income"] = _clean(_find_row(income, _NET_INCOME_LABELS))
        out["gross_profit"] = _clean(_find_row(income, _GROSS_PROFIT_LABELS))
        out["operating_income"] = _clean(_find_row(income, _OPERATING_INCOME_LABELS))
        out["depreciation_amortization"] = _clean(_find_row(cash, _DA_LABELS))
        out["pretax_income"] = _clean(_find_row(income, _PRETAX_INCOME_LABELS))
        out["tax_provision"] = _clean(_find_row(income, _TAX_PROVISION_LABELS))
        out["interest_expense"] = _clean(_find_row(income, _INTEREST_EXPENSE_LABELS))
        out["diluted_shares"] = _clean(_find_row(income, _DILUTED_SHARES_LABELS))

        ebitda = _clean(_find_row(income, _EBITDA_LABELS))
        if ebitda is None and out["operating_income"] is not None and out["depreciation_amortization"] is not None:
            oi, da = out["operating_income"].align(out["depreciation_amortization"], join="inner")
            if not oi.empty:
                ebitda = (oi + da.abs()).dropna()
        out["ebitda"] = ebitda

        out["operating_cash_flow"] = _clean(_find_row(cash, _OPERATING_CASHFLOW_LABELS))
        out["capex"] = _clean(_find_row(cash, _CAPEX_LABELS))

        fcf = _clean(_find_row(cash, _FREE_CASHFLOW_LABELS))
        if fcf is None and out["operating_cash_flow"] is not None and out["capex"] is not None:
            ocf, capex = out["operating_cash_flow"].align(out["capex"], join="inner")
            if not ocf.empty:
                fcf = ocf + capex  # capex e' tipicamente negativo nei prospetti
        out["free_cash_flow"] = fcf

        out["total_debt"] = _clean(_find_row(balance, _TOTAL_DEBT_LABELS))
        out["cash"] = _clean(_find_row(balance, _CASH_LABELS))
        out["total_equity"] = _clean(_find_row(balance, _EQUITY_LABELS))
        out["eps"] = _clean(_find_row(income, _EPS_LABELS))
        out["current_assets"] = _clean(_find_row(balance, _CURRENT_ASSETS_LABELS))
        out["current_liabilities"] = _clean(_find_row(balance, _CURRENT_LIABILITIES_LABELS))
    except Exception:
        pass
    return out


def compute_margins(hist: dict) -> dict:
    """Margini derivati (lordo/operativo/EBITDA/netto) dalle serie di
    bilancio, quando ricavi e la relativa voce sono entrambi disponibili."""
    out = {"gross_margin": None, "operating_margin": None, "ebitda_margin": None, "net_margin": None}
    rev = hist.get("revenue")
    if rev is None:
        return out
    for key, out_key in (
        ("gross_profit", "gross_margin"), ("operating_income", "operating_margin"),
        ("ebitda", "ebitda_margin"), ("net_income", "net_margin"),
    ):
        margin = _ratio_series(hist.get(key), rev, 100)
        if margin is not None:
            out[out_key] = margin
    return out


def compute_ratios(hist: dict) -> dict:
    """Ratio di leva, liquidità e qualità degli utili derivati dalle serie
    di bilancio. Ogni voce è una Series (storico) quando i dati lo
    permettono, per poter leggere anche il *trend* e non solo il livello
    più recente."""
    out = {
        "net_debt": None, "net_debt_to_ebitda": None, "current_ratio": None,
        "interest_coverage": None, "effective_tax_rate": None,
        "fcf_margin": None, "fcf_conversion": None,
    }
    debt, cash = hist.get("total_debt"), hist.get("cash")
    if debt is not None and cash is not None:
        out["net_debt"] = _diff_series(debt, cash)
    elif debt is not None:
        out["net_debt"] = debt

    if out["net_debt"] is not None and hist.get("ebitda") is not None:
        out["net_debt_to_ebitda"] = _ratio_series(out["net_debt"], hist["ebitda"], 1.0)

    if hist.get("current_assets") is not None and hist.get("current_liabilities") is not None:
        out["current_ratio"] = _ratio_series(hist["current_assets"], hist["current_liabilities"], 1.0)

    if hist.get("operating_income") is not None and hist.get("interest_expense") is not None:
        interest_abs = hist["interest_expense"].abs()
        out["interest_coverage"] = _ratio_series(hist["operating_income"], interest_abs, 1.0)

    if hist.get("tax_provision") is not None and hist.get("pretax_income") is not None:
        out["effective_tax_rate"] = _ratio_series(hist["tax_provision"], hist["pretax_income"], 100)

    if hist.get("free_cash_flow") is not None and hist.get("revenue") is not None:
        out["fcf_margin"] = _ratio_series(hist["free_cash_flow"], hist["revenue"], 100)

    if hist.get("free_cash_flow") is not None and hist.get("net_income") is not None:
        out["fcf_conversion"] = _ratio_series(hist["free_cash_flow"], hist["net_income"], 100)

    return out


def latest_ratios(hist: dict, ratios: dict, market_cap: float | None = None) -> dict:
    """Livelli più recenti dei ratio (per le metriche "puntuali" come
    ROIC, dove ha senso guardare l'ultimo periodo disponibile, come si fa
    già con ROE) più NOPAT/capitale investito/ROIC, che richiedono di
    combinare più voci nello stesso periodo."""
    out = {
        "ebitda": _last(hist.get("ebitda")),
        "net_debt": _last(ratios.get("net_debt")),
        "net_debt_to_ebitda": _last(ratios.get("net_debt_to_ebitda")),
        "current_ratio": _last(ratios.get("current_ratio")),
        "interest_coverage": _last(ratios.get("interest_coverage")),
        "effective_tax_rate": _last(ratios.get("effective_tax_rate")),
        "fcf_margin": _last(ratios.get("fcf_margin")),
        "fcf_conversion": _last(ratios.get("fcf_conversion")),
        "nopat": None, "invested_capital": None, "roic": None,
        "fcf_yield": None,
    }

    oi = _last(hist.get("operating_income"))
    tax_rate = out["effective_tax_rate"]
    if oi is not None:
        rate = (tax_rate / 100) if tax_rate is not None and 0 <= tax_rate <= 100 else 0.21
        out["nopat"] = oi * (1 - rate)

    debt = _last(hist.get("total_debt"))
    equity = _last(hist.get("total_equity"))
    cash = _last(hist.get("cash"))
    if debt is not None and equity is not None:
        invested_capital = debt + equity - (cash or 0)
        if invested_capital > 0:
            out["invested_capital"] = invested_capital
            if out["nopat"] is not None:
                out["roic"] = out["nopat"] / invested_capital * 100

    fcf = _last(hist.get("free_cash_flow"))
    if fcf is not None and market_cap:
        out["fcf_yield"] = fcf / market_cap * 100

    return out


def earnings_quality_flag(hist: dict) -> dict:
    """Confronta utile netto e free cash flow sul periodo disponibile:
    se l'FCF resta sistematicamente e nettamente sotto l'utile netto,
    è un segnale classico (non definitivo) di qualità degli utili da
    verificare — l'utile "contabile" non si sta traducendo in cassa."""
    ni, fcf = hist.get("net_income"), hist.get("free_cash_flow")
    out = {"avg_ratio": None, "flag": False, "n_periods": 0}
    if ni is None or fcf is None:
        return out
    n, f = ni.align(fcf, join="inner")
    if n.empty or (n <= 0).all():
        return out
    valid = n[n > 0]
    f_valid = f.loc[valid.index]
    if valid.empty:
        return out
    ratio = (f_valid / valid).mean() * 100
    out["avg_ratio"] = ratio
    out["n_periods"] = len(valid)
    out["flag"] = ratio < 60 and len(valid) >= 2
    return out


def growth_trend(series: pd.Series | None) -> str | None:
    """Classifica la crescita sull'intero storico disponibile confrontando
    la crescita media dei periodi più vecchi con quella dei periodi più
    recenti — non solo l'ultimo dato vs il precedente."""
    if series is None or len(series) < 3:
        return None
    yoy = series.pct_change().dropna() * 100
    if len(yoy) < 2:
        return None
    mid = len(yoy) // 2
    first_half, second_half = yoy.iloc[:mid].mean(), yoy.iloc[mid:].mean()
    if second_half - first_half > 3:
        return "in accelerazione"
    if first_half - second_half > 3:
        return "in decelerazione"
    return "stabile"


def margin_trend(series: pd.Series | None) -> str | None:
    """Espansione/contrazione del margine confrontando inizio e fine
    dello storico disponibile (in punti percentuali)."""
    if series is None or len(series) < 3:
        return None
    diff = float(series.iloc[-1]) - float(series.iloc[0])
    if diff > 1.5:
        return "in espansione"
    if diff < -1.5:
        return "in contrazione"
    return "stabile"


def growth_rate(series: pd.Series | None) -> float | None:
    """CAGR% tra il primo e l'ultimo periodo disponibile (variazione
    totale se solo due periodi o se i valori non sono entrambi positivi)."""
    if series is None or len(series) < 2:
        return None
    first, last = float(series.iloc[0]), float(series.iloc[-1])
    if pd.isna(first) or pd.isna(last) or first == 0:
        return None
    periods = len(series) - 1
    if periods <= 1 or first <= 0 or last <= 0:
        return (last - first) / abs(first) * 100
    return ((last / first) ** (1 / periods) - 1) * 100


def latest_and_yoy(series: pd.Series | None) -> dict:
    """Ultimo valore, precedente, e variazione percentuale tra i due."""
    if series is None or series.empty:
        return {"latest": None, "prev": None, "yoy_pct": None}
    latest = float(series.iloc[-1])
    prev = float(series.iloc[-2]) if len(series) >= 2 else None
    yoy = ((latest - prev) / abs(prev) * 100) if prev not in (None, 0) else None
    return {"latest": latest, "prev": prev, "yoy_pct": yoy}


def historical_multiple_band(symbol: str, years: int = 3) -> dict | None:
    """P/E "vero" storico dell'azienda: prezzo settimanale diviso per
    l'EPS diluito trailing-12-mesi (somma degli ultimi 4 trimestri),
    sugli ultimi N anni. Permette di dire se il multiplo attuale è caro o
    a buon mercato *rispetto alla storia del titolo stesso* — non solo
    guardare il P/E di oggi in isolamento, come faceva la versione
    precedente di questo modulo nonostante lo promettesse."""
    try:
        price_hist = dp.get_history(symbol, period=f"{years}y", interval="1wk")
        if price_hist is None or price_hist.empty or len(price_hist) < 20:
            return None
        t = dp.get_ticker(symbol)
        eps_q = _clean(_find_row(t.quarterly_income_stmt, _EPS_LABELS))
        if eps_q is None or len(eps_q) < 4:
            return None
        eps_q.index = pd.to_datetime(eps_q.index)
        ttm_eps = eps_q.rolling(4).sum().dropna()
        if ttm_eps.empty:
            return None

        close = price_hist["Close"].dropna()
        close.index = pd.to_datetime(close.index).tz_localize(None)
        ttm_eps.index = ttm_eps.index.tz_localize(None) if ttm_eps.index.tz else ttm_eps.index
        eps_aligned = ttm_eps.reindex(close.index.union(ttm_eps.index)).sort_index().ffill().reindex(close.index)

        pe_series = (close / eps_aligned).replace([float("inf"), float("-inf")], pd.NA).dropna()
        pe_series = pe_series[pe_series > 0]
        if len(pe_series) < 15:
            return None

        current_pe = float(pe_series.iloc[-1])
        percentile = float((pe_series < current_pe).mean() * 100)
        return {
            "current": current_pe, "min": float(pe_series.min()), "median": float(pe_series.median()),
            "max": float(pe_series.max()), "percentile": percentile, "n_points": len(pe_series),
            "years": years,
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Ancora di prezzo — due cross-check di prezzo "implicito", non una stima
# di fair value rigorosa (richiederebbe un vero DCF con dati a pagamento).
# Servono a rispondere alla domanda che conta davvero per decidere: "a
# questo prezzo, quale rendimento sto implicitamente scontando?"
# ---------------------------------------------------------------------------

def implied_price_multiple_reversion(historical_median_multiple: float | None, eps: float | None) -> float | None:
    """Prezzo implicito se il multiplo (P/E) tornasse alla propria mediana
    storica, applicato all'EPS forward (o trailing se il forward non è
    disponibile). Non è una previsione: è "cosa dovrebbe fare il prezzo
    perché il multiplo torni nella norma della sua storia recente"."""
    if historical_median_multiple is None or eps is None or eps <= 0:
        return None
    return historical_median_multiple * eps


def graham_intrinsic_value(eps: float | None, growth_pct: float | None, bond_yield_pct: float | None) -> float | None:
    """Formula di Graham (The Intelligent Investor, versione rivista):
    V = EPS x (8.5 + 2g) x 4.4 / Y, dove g è la crescita attesa (%) e Y il
    rendimento di un'obbligazione di alta qualità (qui: Treasury 10 anni
    live, in assenza di un rendimento corporate AAA gratuito — un'
    approssimazione dichiarata). g è limitata a un intervallo 0-15% per
    evitare risultati assurdi quando si estrapola la crescita storica di
    un titolo ad altissima crescita. È un euristica di controllo rapido,
    non una valutazione rigorosa: molto sensibile all'assunzione di g."""
    if eps is None or eps <= 0 or growth_pct is None or bond_yield_pct is None or bond_yield_pct <= 0:
        return None
    g = max(0.0, min(growth_pct, 15.0))
    return eps * (8.5 + 2 * g) * 4.4 / bond_yield_pct


# ---------------------------------------------------------------------------
# Formattazione numerica — il problema segnalato: numeri grezzi senza
# punti/unità di misura non si leggono. Tutta la UI passa da qui.
# ---------------------------------------------------------------------------

def format_money(value, currency: str | None = None, decimals: int = 1) -> str:
    """Es. 1_400_000_000 -> '$1,4 Mld'. Scala automaticamente in
    mila/milioni/miliardi con simbolo di valuta quando disponibile."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "n/d"
    sym = CURRENCY_SYMBOLS.get(currency, f"{currency} " if currency else "")
    sign = "-" if value < 0 else ""
    v = abs(float(value))
    if v >= 1e9:
        return f"{sign}{sym}{v/1e9:,.{decimals}f} Mld"
    if v >= 1e6:
        return f"{sign}{sym}{v/1e6:,.{decimals}f} Mln"
    if v >= 1e3:
        return f"{sign}{sym}{v/1e3:,.{decimals}f} mila"
    return f"{sign}{sym}{v:,.0f}"


def format_pct(value, decimals: int = 1, signed: bool = False) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "n/d"
    fmt = f"{{:+.{decimals}f}}%" if signed else f"{{:.{decimals}f}}%"
    return fmt.format(float(value))


def format_ratio(value, decimals: int = 2, suffix: str = "x") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "n/d"
    return f"{float(value):,.{decimals}f}{suffix}"


def format_number(value, decimals: int = 2) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "n/d"
    return f"{float(value):,.{decimals}f}"


# Tipo di formattazione per riga, usato sia dalla tabella grezza (Excel)
# sia da quella "leggibile" mostrata in pagina.
_ROW_TYPES = {
    "Ricavi": "money", "EBITDA": "money", "Utile lordo": "money", "Utile operativo": "money",
    "Utile netto": "money", "Free cash flow": "money", "Debito totale": "money",
    "Cassa": "money", "Debito netto": "money", "Patrimonio netto": "money",
    "EPS": "eps",
    "Margine lordo %": "pct", "Margine operativo %": "pct", "Margine EBITDA %": "pct",
    "Margine netto %": "pct", "Margine FCF %": "pct",
    "Debito netto/EBITDA": "ratio_x", "Current ratio": "ratio_x", "Copertura interessi": "ratio_x",
}


def to_raw_table(hist: dict, margins: dict, ratios: dict | None = None) -> pd.DataFrame:
    """Tabella metriche (righe) x periodi (colonne) con valori NUMERICI
    grezzi — usata per i grafici e per l'export Excel."""
    rows = {}
    label_map = [
        ("revenue", "Ricavi"), ("ebitda", "EBITDA"), ("net_income", "Utile netto"),
        ("gross_profit", "Utile lordo"), ("operating_income", "Utile operativo"),
        ("free_cash_flow", "Free cash flow"), ("total_debt", "Debito totale"),
        ("cash", "Cassa"), ("total_equity", "Patrimonio netto"), ("eps", "EPS"),
    ]
    for key, label in label_map:
        s = hist.get(key)
        if s is not None:
            rows[label] = s

    ratios = ratios or {}
    if ratios.get("net_debt") is not None:
        rows["Debito netto"] = ratios["net_debt"]
    if ratios.get("net_debt_to_ebitda") is not None:
        rows["Debito netto/EBITDA"] = ratios["net_debt_to_ebitda"]
    if ratios.get("current_ratio") is not None:
        rows["Current ratio"] = ratios["current_ratio"]
    if ratios.get("interest_coverage") is not None:
        rows["Copertura interessi"] = ratios["interest_coverage"]

    margin_map = [
        ("gross_margin", "Margine lordo %"), ("operating_margin", "Margine operativo %"),
        ("ebitda_margin", "Margine EBITDA %"), ("net_margin", "Margine netto %"),
    ]
    for key, label in margin_map:
        s = margins.get(key)
        if s is not None:
            rows[label] = s
    if ratios.get("fcf_margin") is not None:
        rows["Margine FCF %"] = ratios["fcf_margin"]

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).T
    df.columns = [pd.Timestamp(c).strftime("%Y-%m") if not isinstance(c, str) else c for c in df.columns]
    return df


def to_display_table(hist: dict, margins: dict, ratios: dict | None = None, currency: str | None = None) -> pd.DataFrame:
    """Stessa tabella di `to_raw_table`, ma con celle formattate come
    stringhe leggibili (unità di misura, valuta, punti percentuali,
    multipli "x") invece di float grezzi — questo è il fix diretto al
    problema "tutti sti 0 senza punti e unità di misura"."""
    raw = to_raw_table(hist, margins, ratios)
    if raw.empty:
        return raw

    def fmt_row(label, values):
        kind = _ROW_TYPES.get(label, "money")
        if kind == "money":
            return [format_money(v, currency) for v in values]
        if kind == "pct":
            return [format_pct(v) for v in values]
        if kind == "ratio_x":
            return [format_ratio(v) for v in values]
        if kind == "eps":
            return [f"{sym}{v:,.2f}" if v is not None and not pd.isna(v) else "n/d"
                    for v, sym in zip(values, [CURRENCY_SYMBOLS.get(currency, currency + " " if currency else "")] * len(values))]
        return [format_number(v) for v in values]

    out = pd.DataFrame(index=raw.index, columns=raw.columns, dtype=object)
    for label in raw.index:
        out.loc[label] = fmt_row(label, raw.loc[label].tolist())
    return out
