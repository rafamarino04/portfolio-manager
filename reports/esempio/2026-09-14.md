> **ATTENZIONE — REPORT SU DATI DI ESEMPIO, NON SU UN PORTAFOGLIO REALE.**
>
> Questo report e' stato generato automaticamente mentre
> `data/transactions.csv` conteneva ancora i movimenti di esempio
> distribuiti col progetto (AAPL, ENI.MI, SWDA.MI, un BTP segnaposto, un
> fondo e un conto deposito fittizi). Ogni cifra qui dentro - valore
> totale, P&L, XIRR, confronto col benchmark - si riferisce a un
> portafoglio che non esiste.
>
> Archiviato il 14/09/2026 in `reports/esempio/` per non lasciarlo
> indistinguibile dai report futuri. Da quella data lo script si rifiuta
> di generare report finche' i movimenti sono quelli di esempio
> (`src/example_data.py`).

# Report portafoglio — 2026-09-14

**Valore totale:** 173,489.65
**Costo totale:** 164,617.00
**P&L non realizzato:** 8,872.65 (5.39%)
**P&L realizzato:** 0.00
**Dividendi incassati:** 0.00
**Rendimento reale (XIRR):** 1.97%

**Miglior titolo:** AAPL (84.08%)
**Peggior titolo:** Conto Deposito ABC (0.00%)

## Posizioni

| Ticker | Categoria | Prezzo | Valore | P&L | P&L % |
|---|---|---|---|---|---|
| AAPL | Azione | 332.27 | 3,322.70 | 1,517.70 | 84.08% |
| ENI.MI | Azione | 24.15 | 3,621.75 | 1,641.75 | 82.92% |
| SWDA.MI | ETF | 126.19 | 10,095.20 | 3,263.20 | 47.76% |
| BTP-2030 | Obbligazione | 99.20 | 99,200.00 | 700.00 | 0.71% |
| Fondo Bilanciato XYZ | Fondo/SICAV | 108.50 | 54,250.00 | 1,750.00 | 3.33% |
| Conto Deposito ABC | Liquidità | 1.00 | 3,000.00 | 0.00 | 0.00% |

## Ribilanciamento

| Categoria | Target | Attuale | Scarto | Azione |
|---|---|---|---|---|
| Azione | 45.0% | 4.0% | -41.0% | Compra (sottopeso) |
| ETF | 30.0% | 5.8% | -24.2% | Compra (sottopeso) |
| Obbligazione | 15.0% | 57.2% | +42.2% | Vendi (sovrappeso) |
| Fondo/SICAV | 5.0% | 31.3% | +26.3% | Vendi (sovrappeso) |
| Liquidità | 5.0% | 1.7% | -3.3% | In linea |

## Benchmark e Performance

Da 10/06/2023: portafoglio +5.39% vs iShares Core MSCI World (proxy) +65.06% (differenza -59.67%).

## Opportunità di Mercato

- **ENI.MI**: Vicino ai massimi a 52 settimane

## News principali

**AAPL**
- [Apple vs. Microsoft: This Is the Magnificent Seven Stock I’d Buy Today](https://247wallst.com/investing/2026/09/14/apple-vs-microsoft-this-is-the-magnificent-seven-stock-id-buy-today/)
- [Apple Foldable iPhone Could Change Smartphones Forever](https://finance.yahoo.com/technology/articles/apple-foldable-iphone-could-change-121236187.html)
**ENI.MI**
- [Energy & Utilities Roundup: Market Talk](https://www.wsj.com/business/energy-utilities-roundup-market-talk-d53eec27?siteid=yhoof2&yptr=yahoo)
- [Eni, Vitol Pursue New Offshore Opportunities in Ghana's Tano Basin](https://finance.yahoo.com/energy/articles/eni-vitol-pursue-offshore-opportunities-162400434.html)
