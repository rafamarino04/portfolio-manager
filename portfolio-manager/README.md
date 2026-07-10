# Portfolio Manager

Dashboard indipendente per tenere sotto controllo un portafoglio azionario/ETF:
valore, P&L, allocazione, analisi per singolo titolo, news e un report
settimanale generato in automatico. Gira fuori da Claude, come un sito vero,
gratis, sul tuo account GitHub + Streamlit Community Cloud.

**Cosa NON è**: non è collegato al tuo broker, non esegue ordini, non è
consulenza finanziaria. I prezzi arrivano da Yahoo Finance (via libreria
`yfinance`) con un delay tipico di 15-20 minuti — ottimo per un report
periodico, non per trading attivo.

## Cosa include

- `app.py` — dashboard principale (valore totale, P&L, allocazione, tabella posizioni)
- `pages/1_Analisi_Titoli.py` — grafico prezzo, statistiche e news per un singolo ticker
- `pages/2_News.py` — news sui tuoi titoli + news di mercato generali
- `pages/3_Report_Settimanale.py` — ultimo report automatico + andamento storico
- `scripts/generate_weekly_report.py` — genera il report (lanciato ogni lunedì da GitHub Actions)
- `data/portfolio.csv` — le tue posizioni (da modificare con i tuoi dati)
- `.github/workflows/weekly_report.yml` — l'automazione settimanale, gratuita

## Setup (circa 15 minuti, tutto gratuito)

### 1. Crea un account GitHub (se non ce l'hai)
https://github.com/signup

### 2. Crea un nuovo repository
Su GitHub: **New repository** → nome a piacere (es. `portfolio-manager`) →
**Private** (consigliato, così i tuoi dati restano privati) → Create.

### 3. Carica questi file nel repository
Il modo più semplice senza usare la riga di comando: nel repository appena
creato clicca **Add file → Upload files** e trascina l'intera cartella
`portfolio-manager` (tutti i file e le sottocartelle inclusi `.github/`).

In alternativa, da terminale:
```bash
cd portfolio-manager
git init
git add .
git commit -m "Prima versione"
git branch -M main
git remote add origin https://github.com/TUO-USERNAME/portfolio-manager.git
git push -u origin main
```

### 4. Personalizza il tuo portafoglio
Apri `data/portfolio.csv` su GitHub (matita in alto a destra per modificarlo)
e sostituisci le righe di esempio con i tuoi titoli reali:

| colonna | significato |
|---|---|
| `ticker` | simbolo Yahoo Finance (es. `AAPL`, `ENI.MI` per Borsa Italiana, `VWCE.DE` per Xetra) |
| `quantity` | quantità posseduta |
| `buy_price` | prezzo medio di carico |
| `buy_date` | data di acquisto (opzionale, solo informativa) |
| `currency` | valuta (opzionale, solo informativa) |
| `category` | es. Azione / ETF, usata per il grafico di allocazione |

Per trovare il ticker giusto: cerca il titolo su finance.yahoo.com, il
simbolo mostrato è quello da usare (per i mercati europei ha spesso un
suffisso: `.MI` Milano, `.DE` Xetra, `.PA` Parigi, `.L` Londra).

### 5. Metti online la dashboard su Streamlit Community Cloud (gratis)
1. Vai su https://share.streamlit.io e accedi con GitHub
2. **New app** → seleziona il tuo repository `portfolio-manager`
3. Main file path: `app.py`
4. Prima di avviare, vai su **Advanced settings → Secrets** e incolla:
   ```
   APP_PASSWORD = "scegli-una-password-tua"
   ```
   (questo protegge la dashboard con una password, dato che mostra dati
   finanziari personali — il file non va mai messo nel repository)
5. **Deploy**. Dopo un paio di minuti ottieni un link pubblico tipo
   `https://tuo-nome-app.streamlit.app` che puoi aprire da qualsiasi
   browser, fuori da Claude, sul telefono incluso.

### 6. L'automazione settimanale è già pronta
GitHub Actions è abilitato di default sui repository. Ogni lunedì alle 7:00
UTC il workflow genera automaticamente un nuovo report in `reports/` e lo
salva nel repository — lo trovi nella pagina "Report Settimanale" della
dashboard. Puoi anche lanciarlo a mano da GitHub: tab **Actions** → "Report
settimanale portafoglio" → **Run workflow**.

Per cambiare giorno/orario, modifica la riga `cron` in
`.github/workflows/weekly_report.yml` (formato standard cron, orario UTC).

## Aggiornare il portafoglio nel tempo

Basta modificare `data/portfolio.csv` su GitHub quando compri/vendi qualcosa
— la dashboard e il prossimo report leggono sempre l'ultima versione. Non
serve toccare altro codice.

## Sviluppo/test in locale (opzionale)

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # poi modifica la password
streamlit run app.py
```

## Limiti da tenere presente

- Dati di mercato non in tempo reale (delay Yahoo Finance).
- `yfinance` non è un'API ufficiale: in rari casi Yahoo può cambiare
  qualcosa e rompere temporaneamente una funzione — il codice è scritto per
  degradare senza crashare (mostra "n/d" invece di errore).
- Le news sono headline pubbliche via Yahoo Finance/RSS, non un servizio a
  pagamento — copertura buona su titoli grandi, più scarsa su small cap.
- Nessuna esecuzione di ordini: è uno strumento di sola consultazione.
