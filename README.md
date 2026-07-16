# Portfolio Manager

Dashboard indipendente di supporto alle decisioni per un portafoglio di
azioni, ETF, obbligazioni, fondi/SICAV e liquidità: non solo monitoraggio,
ma ribilanciamento, confronto con un benchmark, segnali di opportunità sui
titoli e un report periodico configurabile. Gira fuori da Claude, come un
sito vero, gratis, sul tuo account GitHub + Streamlit Community Cloud.

**Cosa NON è**: non è collegato al tuo broker, non esegue ordini, non è
consulenza finanziaria personalizzata — i segnali di opportunità sono
indicatori statistici pubblici, da usare come spunto per approfondire. I
prezzi arrivano da Yahoo Finance (via libreria `yfinance`) con un delay
tipico di 15-20 minuti — ottimo per decisioni ponderate, non per trading
attivo.

## Cosa include

- `app.py` — dashboard principale (valore, P&L, allocazione per titolo e categoria)
- `pages/0_Gestisci_Portafoglio.py` — aggiungi/modifica/elimina azioni, ETF, obbligazioni, fondi e liquidità **direttamente dall'app**
- `pages/1_Ribilanciamento.py` — confronta l'allocazione attuale con un target che imposti tu, con importi suggeriti da comprare/vendere
- `pages/2_Benchmark_e_Performance.py` — confronto con un indice di mercato + quali posizioni hanno contribuito di più al risultato
- `pages/3_Opportunita_di_Mercato.py` — segnali sui titoli in portafoglio (range 52 settimane, target price analisti, momentum)
- `pages/4_Analisi_Titoli.py` — grafico prezzo, statistiche e news per un singolo ticker
- `pages/5_News.py` — news sui tuoi titoli + news di mercato generali
- `pages/6_Report_Settimanale.py` — ultimo report automatico + andamento storico
- `pages/7_Impostazioni_Report.py` — configura allocazione target, benchmark e sezioni del report, senza toccare codice
- `scripts/generate_weekly_report.py` — genera il report periodico (lanciato ogni lunedì da GitHub Actions)
- `data/portfolio.csv` — le tue posizioni
- `data/settings.json` — le tue impostazioni (target allocation, benchmark, sezioni report)
- `.github/workflows/weekly_report.yml` — l'automazione periodica, gratuita
- `.streamlit/config.toml` — tema grafico curato (navy/oro, coerente su tutte le pagine)

## Setup

### 1. Account GitHub e Streamlit
Se non li hai già: https://github.com/signup e poi https://share.streamlit.io
(accedi con lo stesso account GitHub).

### 2. Carica i file nel repository
Il modo più affidabile è da terminale con `git`, che evita gli errori tipici
del trascinamento manuale di cartelle nel browser (cartelle annidate per
sbaglio, file nascosti come `.github` scartati):

```bash
cd portfolio-manager
git init
git add .
git commit -m "Prima versione"
git branch -M main
git remote add origin https://github.com/TUO-USERNAME/portfolio-manager.git
git push -u origin main
```

Se il repository esiste già e contiene versioni precedenti disordinate, usa
`git push --force` dopo il remote add per sostituire completamente il
contenuto con questa versione pulita.

### 3. Personalizza il tuo portafoglio
Una volta che l'app è online (punto 5), usa la pagina **Gestisci
Portafoglio** dentro l'app — non serve toccare GitHub. Se preferisci
partire subito, modifica `data/portfolio.csv`:

| colonna | significato |
|---|---|
| `ticker` | simbolo Yahoo Finance (`AAPL`, `ENI.MI` Borsa Italiana, `VWCE.DE` Xetra), o un'etichetta libera per liquidità/obbligazioni senza ticker |
| `quantity` | quantità posseduta (nominale per obbligazioni, importo in euro per liquidità) |
| `buy_price` | prezzo medio di carico (non serve per liquidità) |
| `buy_date` | data di acquisto (usata anche per il confronto con il benchmark) |
| `currency` | valuta (informativa) |
| `category` | `Azione` / `ETF` / `Obbligazione` / `Fondo/SICAV` / `Liquidità` / `Altro` — usata per allocazione e ribilanciamento |
| `manual_price` | forza un prezzo/NAV invece di quello live (obbligatorio per obbligazioni/fondi senza ticker Yahoo Finance) |

Per i ticker europei: cerca il titolo su finance.yahoo.com, il simbolo
mostrato è quello giusto (suffissi comuni: `.MI` Milano, `.DE` Xetra, `.PA`
Parigi, `.L` Londra).

### 4. Metti online la dashboard su Streamlit Community Cloud
1. Su https://share.streamlit.io → **New app** → seleziona il repository
2. Branch: `main` — Main file path: `app.py`
3. **Advanced settings → Secrets**, incolla:
   ```
   APP_PASSWORD = "scegli-una-password-tua"
   ```
4. **Deploy**. Dopo un paio di minuti hai un link pubblico tipo
   `https://tuo-nome-app.streamlit.app`, apribile da qualsiasi browser o
   telefono, fuori da Claude.

### 5. L'automazione periodica è già pronta
GitHub Actions è abilitato di default. Ogni lunedì alle 7:00 UTC il
workflow genera un nuovo report (le sezioni incluse dipendono da cosa hai
scelto in **Impostazioni Report**) e lo salva nel repository. Lanciabile
anche a mano: tab **Actions** → "Report settimanale portafoglio" → **Run
workflow**. Per cambiare giorno/orario, modifica la riga `cron` in
`.github/workflows/weekly_report.yml`.

### 6. (Consigliato) Rendi permanenti le modifiche fatte dall'app
Le pagine **Gestisci Portafoglio** e **Impostazioni Report** salvano di
base solo sul disco dell'app, che Streamlit Cloud può azzerare ad ogni
redeploy (succede anche quando il report automatico fa un commit). Per
renderle permanenti:

1. GitHub → **Settings** (profilo) → **Developer settings** → **Personal
   access tokens** → **Fine-grained tokens** → **Generate new token**
2. Repository access: **Only select repositories** → il tuo repository
3. Permissions → **Contents** → **Read and write**
4. Copia il token (`github_pat_...`, mostrato una sola volta)
5. Su Streamlit Cloud: **App → Settings → Secrets**, aggiungi:
   ```
   GITHUB_TOKEN = "github_pat_..."
   GITHUB_REPO = "TUO-USERNAME/portfolio-manager"
   ```
6. Salva: da ora ogni "Salva modifiche" fa anche un commit automatico su
   GitHub. Senza questo passaggio l'app funziona comunque, ma te lo
   segnala ogni volta.

## Come usarla per decidere, non solo per guardare

- **Ribilanciamento**: imposta la tua allocazione ideale una volta in
  Impostazioni Report, poi controlla periodicamente quanto ti sei
  discostato e di quanto — la pagina ti dice l'importo indicativo da
  muovere per tornare in equilibrio.
- **Benchmark**: capire se stai battendo o sottoperformando il mercato è
  più utile del solo valore assoluto del portafoglio.
- **Opportunità**: non sono segnali di acquisto/vendita, ma flag su cosa
  merita un controllo più attento questa settimana.

## Sviluppo/test in locale (opzionale)

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # poi modifica la password
streamlit run app.py
```

## Limiti da tenere presente

- Dati di mercato non in tempo reale (delay Yahoo Finance).
- `yfinance` non è un'API ufficiale: il codice è scritto per degradare
  senza crashare (mostra "n/d" invece di errore) se qualcosa non è disponibile.
- Le news sono headline pubbliche via Yahoo Finance/RSS — copertura buona
  su titoli grandi, più scarsa su small cap.
- Target price e raccomandazioni degli analisti sono disponibili
  soprattutto per titoli USA/large cap, spesso assenti per titoli europei
  più piccoli.
- Il confronto "da quando hai iniziato" con il benchmark è un'approssimazione:
  non tiene conto della tempistica esatta di ogni versamento.
- Nessuna esecuzione di ordini: è uno strumento di sola consultazione e analisi.
