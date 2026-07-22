"""
Universo di peer per settore e mappatura ai profili di peso del
Fundamental Score (vedi Specifica_Fundamental_Score_yfinance.md, §7).

Yahoo Finance/yfinance non espone un modo diretto per "prendere tutti i
titoli di un settore": per calcolare percentili sector-relative con dati
gratuiti serve un universo di confronto costruito a mano. Le liste qui
sotto sono una selezione ragionata di titoli liquidi e rappresentativi
per ciascuno degli 11 settori restituiti da `info['sector']` — pensate
per dare una distribuzione sensata su cui calcolare percentili, non un
campionamento esaustivo di mercato (richiederebbe un provider dati a
pagamento con copertura completa per sotto-industria GICS). Vanno
considerate un punto di partenza ragionevole, calibrabile nel tempo.

La specifica organizza i pesi di categoria su 6 profili invece che sugli
11 settori grezzi di Yahoo Finance: la mappatura sotto è la mia proposta
esplicita, con due casi "misti" dichiarati (Communication Services e
Real Estate) dove il settore Yahoo non ha un corrispettivo netto in uno
dei 6 profili.
"""
from __future__ import annotations

# Settori esclusi dallo scoring per esplicita indicazione della
# specifica (§0.5): per banche/assicurazioni EBITDA, ROIC, EV e i
# coefficienti Altman/Piotroski non sono metriche significative — il loro
# modello di business (leva finanziaria intrinseca, bilancio fatto di
# attività/passività finanziarie) rende questi ratio fuorvianti.
EXCLUDED_SECTORS = {"Financial Services"}

# Settori con un modello di business sufficientemente diverso da
# richiedere un profilo dedicato non ancora implementato (REIT: FFO/AFFO
# al posto di EPS/P/E, vedi specifica §7) — per ora usano il profilo
# generico più vicino (Utilities/Defensive) e lo score mostra un avviso
# esplicito di copertura parziale invece di fingere un dettaglio che non
# abbiamo ancora costruito.
SECTORS_NEEDING_OVERRIDE = {"Real Estate"}

SECTOR_PEERS: dict[str, list[str]] = {
    "Technology": [
        "AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "ADBE", "CSCO",
        "ACN", "IBM", "INTU", "AMD", "QCOM", "TXN", "NOW",
    ],
    "Communication Services": [
        "GOOGL", "META", "NFLX", "DIS", "CMCSA", "VZ", "T", "TMUS",
        "CHTR", "EA", "TTWO", "WBD", "OMC", "MTCH", "LYV",
    ],
    "Healthcare": [
        "UNH", "JNJ", "LLY", "ABBV", "MRK", "PFE", "TMO", "ABT",
        "DHR", "BMY", "AMGN", "GILD", "ISRG", "CVS", "MDT",
    ],
    "Consumer Cyclical": [
        "AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "SBUX", "TJX",
        "BKNG", "CMG", "MAR", "GM", "F", "RCL", "YUM",
    ],
    "Consumer Defensive": [
        "PG", "KO", "PEP", "WMT", "COST", "PM", "MO", "CL",
        "KMB", "GIS", "KHC", "STZ", "EL", "SYY", "KR",
    ],
    "Industrials": [
        "HON", "UNP", "UPS", "CAT", "DE", "LMT", "RTX", "BA",
        "GE", "MMM", "ITW", "EMR", "ETN", "NSC", "WM",
    ],
    "Energy": [
        "XOM", "CVX", "COP", "SLB", "EOG", "PSX", "MPC", "VLO",
        "OXY", "WMB", "KMI", "HAL", "BKR", "DVN", "FANG",
    ],
    "Basic Materials": [
        "LIN", "SHW", "APD", "ECL", "FCX", "NEM", "DOW", "NUE",
        "VMC", "MLM", "ALB", "CTVA", "IFF", "PPG", "CE",
    ],
    "Utilities": [
        "NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE", "XEL",
        "ED", "WEC", "ES", "PEG", "EIX", "FE", "AWK",
    ],
    "Real Estate": [
        "PLD", "AMT", "EQIX", "CCI", "PSA", "O", "SPG", "WELL",
        "DLR", "AVB", "EQR", "VTR", "ARE", "MAA", "EXR",
    ],
    "Financial Services": [],  # fuori scope, vedi EXCLUDED_SECTORS
}

# Mappatura settore Yahoo Finance -> profilo di peso a 6 categorie
# (specifica §7). Comunicazione e Real Estate sono i due casi dichiarati
# come approssimazioni: Communication Services include sia titoli
# growth/tech (Google, Meta, Netflix) sia telecom maturi (Verizon, AT&T) —
# la maggioranza dei nomi grandi nel settore è growth-oriented, quindi
# usa quel profilo; Real Estate userebbe un profilo REIT dedicato
# (FFO/AFFO) non ancora implementato, per ora si appoggia a
# Utilities/Defensive (entrambi yield-oriented, a bassa crescita).
SECTOR_TO_WEIGHT_PROFILE: dict[str, str] = {
    "Technology": "Growth/Tech",
    "Communication Services": "Growth/Tech",
    "Industrials": "Value/Industrial",
    "Energy": "Energy/Materials",
    "Basic Materials": "Energy/Materials",
    "Utilities": "Utilities/Defensive",
    "Real Estate": "Utilities/Defensive",
    "Consumer Cyclical": "Consumer",
    "Consumer Defensive": "Consumer",
    "Healthcare": "Healthcare",
}


def is_excluded_sector(sector: str | None) -> bool:
    return sector in EXCLUDED_SECTORS


def needs_unimplemented_override(sector: str | None) -> bool:
    return sector in SECTORS_NEEDING_OVERRIDE


def peers_for_sector(sector: str | None) -> list[str]:
    if not sector:
        return []
    return SECTOR_PEERS.get(sector, [])


def weight_profile_for_sector(sector: str | None) -> str | None:
    if not sector:
        return None
    return SECTOR_TO_WEIGHT_PROFILE.get(sector)


def market_cap_bucket(market_cap: float | None) -> str:
    """mega_large (>=10 Mld $) · mid (2-10 Mld $) · small_micro (<2 Mld $),
    come da specifica §7 ("Aggiustamenti per market cap")."""
    if not market_cap:
        return "unknown"
    if market_cap >= 10e9:
        return "mega_large"
    if market_cap >= 2e9:
        return "mid"
    return "small_micro"
