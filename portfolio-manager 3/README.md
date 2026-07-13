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
- `pages/0_Gestisci_Portafoglio.py` — aggiungi/modifica/elimina azioni, ETF e obbligazioni **direttamente dall'app**, senza toccare file
- `pages/1_Analisi_Titoli.py` — grafico prezzo, statistiche e news per un singolo ticker
- `pages/2_News.py` — news sui tuoi titoli + news di mercato generali
- `pages/3_Report_Settimanale.py` — ultimo report automatico + andamento storico
- `scripts/generate_weekly_report.py` — genera il report (lanciato ogni lunedì da GitHub Actions)
- `data/portfolio.csv` — le tue posizioni (puoi modificarle da GitHub oppure, più comodo, dalla pagina "Gestisci Portafoglio" dentro l'app)
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
Il file `data/portfolio.csv` che carichi ora contiene solo righe di esempio.
Una volta che l'app è online (punto 5), il modo comodo per sostituirle con i
tuoi titoli reali è la pagina **Gestisci Portafoglio** dentro l'app stessa —
non serve toccare GitHub. Se preferisci farlo subito prima del deploy, puoi
comunque modificare `data/portfolio.csv` direttamente su GitHub (matita in
alto a destra):

| colonna | significato |
|---|---|
| `ticker` | simbolo Yahoo Finance (es. `AAPL`, `ENI.MI` per Borsa Italiana, `VWCE.DE` per Xetra) |
| `quantity` | quantità posseduta (o nominale, per le obbligazioni) |
| `buy_price` | prezzo medio di carico |
| `buy_date` | data di acquisto (opzionale, solo informativa) |
| `currency` | valuta (opzionale, solo informativa) |
| `category` | `Azione` / `ETF` / `Obbligazione` / `Altro`, usata per il grafico di allocazione |
| `manual_price` | opzionale — forza un prezzo invece di quello live (vedi sotto per le obbligazioni) |

Per trovare il ticker giusto: cerca il titolo su finance.yahoo.com, il
simbolo mostrato è quello da usare (per i mercati europei ha spesso un
suffisso: `.MI` Milano, `.DE` Xetra, `.PA` Parigi, `.L` Londra).

**Obbligazioni**: Yahoo Finance copre bene ETF obbligazionari, molto meno i
singoli titoli di stato per ISIN (es. un BTP specifico). Se il ticker non
viene trovato, scrivi una sigla a tua scelta in `ticker` e il prezzo attuale
in `manual_price` — la dashboard lo userà al posto del prezzo live, e dovrai
aggiornarlo tu manualmente ogni tanto dalla pagina "Gestisci Portafoglio".

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

### 7. (Consigliato) Rendi permanenti le modifiche fatte dall'app
La pagina **Gestisci Portafoglio** ti permette di aggiungere/modificare/
eliminare titoli con una tabella, senza toccare file. Di base salva solo
sul disco dell'app, che Streamlit Cloud può azzerare a ogni redeploy
(succede anche ogni volta che il report automatico del lunedì fa un commit).
Per rendere le modifiche permanenti, collega l'app al repository:

1. Su GitHub vai su **Settings** (del tuo profilo, non del repository) →
   **Developer settings** → **Personal access tokens** → **Fine-grained tokens**
   → **Generate new token**
2. Repository access: **Only select repositories** → scegli solo
   `portfolio-manager`
3. Permissions → **Repository permissions** → **Contents** → **Read and write**
4. Genera il token e copialo (inizia con `github_pat_...`, mostrato una sola volta)
5. Su Streamlit Cloud: **App → Settings → Secrets**, aggiungi due righe alle
   secrets che avevi già messo:
   ```
   GITHUB_TOKEN = "github_pat_..."
   GITHUB_REPO = "rafamarino04/portfolio-manager"
   ```
6. Salva: l'app si riavvia da sola. Da ora, ogni volta che premi "Salva
   modifiche" nella pagina Gestisci Portafoglio, l'app fa anche un commit
   automatico su GitHub — le modifiche non si perdono più.

Se salti questo passaggio l'app funziona lo stesso, ma te lo segnala ogni
volta con un avviso quando salvi.

## Aggiornare il portafoglio nel tempo

Il modo comodo: apri l'app, vai su **Gestisci Portafoglio**, modifica la
tabella e premi "Salva modifiche" — non serve toccare file né codice. In
alternativa resta sempre possibile modificare `data/portfolio.csv`
direttamente su GitHub.

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
