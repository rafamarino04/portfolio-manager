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

- `app.py` — dashboard principale (valore, P&L, allocazione per titolo e categoria, rendimento reale XIRR)
- `pages/0_Registro_Transazioni.py` — registra acquisti, vendite e dividendi **direttamente dall'app**: posizioni, P&L realizzato e XIRR si calcolano da qui automaticamente
- `pages/1_Ribilanciamento.py` — confronta l'allocazione attuale con un target che imposti tu, con importi suggeriti da comprare/vendere
- `pages/2_Benchmark_e_Performance.py` — confronto con un indice di mercato (rendimento XIRR reale, non approssimato) + quali posizioni hanno contribuito di più al risultato
- `pages/3_Opportunita_di_Mercato.py` — segnali sui titoli in portafoglio (range 52 settimane, target price analisti, momentum)
- `pages/4_Analisi_Tecnica.py` — hub decisionale sui titoli: **Portafoglio** (i tuoi titoli, pronti da analizzare), **Preferiti** (watchlist con avvisi tecnici automatici) e **Cerca** (ricerca libera). Analisi tecnica completa per breve/medio/lungo termine — trend, medie mobili, Bollinger, oscillatori (RSI/Stocastico/MACD/Williams %R), pattern di candlestick e figure di prezzo — divisa per sezioni con una sintesi finale, contestualizzata sul tuo prezzo di carico/riferimento
- `pages/5_News.py` — news sui tuoi titoli + news di mercato generali
- `pages/6_Report_Settimanale.py` — ultimo report automatico + andamento storico
- `pages/7_Impostazioni_Report.py` — configura allocazione target, benchmark e sezioni del report, senza toccare codice
- `pages/8_Analisi_Fondamentale.py` — **Fundamental Score** (0-100) per un singolo titolo: **Portafoglio**, **Preferiti** e **Cerca**, come nell'Analisi Tecnica. Un nucleo di 8 metriche a bassa correlazione (creazione di valore, qualità degli utili, leva, valutazione, capital allocation) più i badge Piotroski F-Score e Altman Z-Score, sempre confrontati con un peer group curato per settore — non con soglie assolute
- `scripts/generate_weekly_report.py` — genera il report periodico (lanciato ogni lunedì da GitHub Actions)
- `data/transactions.csv` — **fonte di verità**: il registro di ogni movimento reale
- `data/portfolio.csv` — le posizioni attuali, calcolate automaticamente da `transactions.csv` (non modificarlo a mano)
- `data/watchlist.csv` — i tuoi titoli Preferiti, con un prezzo di riferimento opzionale (creato al primo utilizzo della pagina Analisi Tecnica)
- `data/fundamentals_cache.json` — cache dei fondamentali dei titoli peer usati per i percentili di settore del Fundamental Score, aggiornata al più ogni ~90 giorni (creato al primo utilizzo della pagina Analisi Fondamentale)
- `data/settings.json` — le tue impostazioni (target allocation, benchmark, sezioni report)
- `.github/workflows/weekly_report.yml` — l'automazione periodica, gratuita
- `.streamlit/config.toml` — tema grafico curato (navy/oro, coerente su tutte le pagine)

## Come funziona il registro transazioni

Il portafoglio non si inserisce più come "posizione attuale" — si registra
ogni movimento (acquisto, vendita, dividendo) e l'app calcola tutto il
resto: quantità posseduta e prezzo medio di carico con il metodo del costo
medio ponderato, il P&L realizzato ad ogni vendita (confrontato col costo
medio al momento della vendita, non con quello finale), i dividendi
incassati, e il rendimento reale (XIRR) — un rendimento annualizzato che
tiene conto di *quando* sono entrati e usciti i soldi, molto più accurato
di un semplice P&L% quando versi o prelevi nel tempo. `data/portfolio.csv`
resta per compatibilità con le altre pagine, ma è un file calcolato: si
rigenera automaticamente ogni volta che salvi un movimento.

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

### 3. Registra i tuoi movimenti reali
Una volta che l'app è online (punto 4), usa la pagina **Registro
Transazioni** dentro l'app — non serve toccare GitHub. Sostituisci le
righe di esempio con i tuoi acquisti/vendite/dividendi reali:

| colonna | significato |
|---|---|
| `date` | data del movimento |
| `ticker` | simbolo Yahoo Finance (`AAPL`, `ENI.MI` Borsa Italiana, `VWCE.DE` Xetra), o un'etichetta libera per liquidità/obbligazioni senza ticker |
| `type` | `Acquisto` / `Vendita` / `Dividendo` |
| `quantity`, `price` | quantità e prezzo per Acquisto/Vendita |
| `amount` | importo netto per i Dividendi |
| `fees` | commissioni (opzionale) |
| `category` | `Azione` / `ETF` / `Obbligazione` / `Fondo/SICAV` / `Liquidità` / `Altro` — basta impostarla al primo acquisto di un titolo |
| `manual_price` | forza un prezzo/NAV invece di quello live (necessario per obbligazioni/fondi senza ticker Yahoo Finance) |

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
Le pagine **Registro Transazioni** e **Impostazioni Report** salvano di
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
- **Analisi Tecnica**: scegli l'orizzonte (breve/medio/lungo termine) in
  base a come usi quel titolo — trading di breve o investimento — e leggi
  il "perché" sotto il grafico prima di decidere.

## Analisi Tecnica: come funziona

La pagina **Analisi Tecnica** applica in automatico le tecniche classiche
del libro di J. Murphy ai dati storici del ticker, organizzata in tre
sezioni — **Portafoglio**, **Preferiti**, **Cerca** — che condividono lo
stesso motore di analisi:

- **Portafoglio**: elenca automaticamente i titoli che hai già (dal
  Registro Transazioni) — nessuna ricerca necessaria. L'analisi è
  mostrata insieme al tuo prezzo medio di carico reale, con note che
  collegano il segnale tecnico alla tua posizione (es. "sei in guadagno e
  il titolo è in ipercomprato").
- **Preferiti**: una watchlist libera, anche su titoli che non possiedi.
  Puoi impostare un prezzo di riferimento/ingresso pianificato per avere
  la stessa lettura contestuale prima ancora di comprare. Il pulsante
  "Scansiona preferiti" applica un set di regole tecniche oggettive
  (incrocio RSI 70/30, incrocio MACD/segnale, rottura di supporto o
  resistenza, candela o figura di prezzo appena rilevata) e mostra solo i
  titoli con un evento reale. Va ricalcolato manualmente ogni volta che
  apri la pagina: non ci sono notifiche push in questa versione.
- **Cerca**: ricerca libera per qualsiasi altro titolo, con un pulsante
  rapido per aggiungerlo ai Preferiti.

In ognuna delle tre sezioni, l'analisi riconosce il trend
(massimi/minimi crescenti o decrescenti), disegna sul grafico supporti,
resistenze e trendlines calcolati dagli estremi locali, calcola medie
mobili e bande di Bollinger, i principali oscillatori (RSI 14, Stocastico
14/3/3, MACD 12/26/9, Williams %R) e segnala i pattern di candlestick e
le figure di prezzo (doppio massimo/minimo, triangoli) più recenti, con
l'obiettivo di prezzo calcolato secondo le tecniche di misurazione
standard (altezza della figura proiettata dal punto di rottura).

Sotto il grafico trovi prima una tabella con **tutti i valori numerici**
calcolati — supporti, resistenze, valore delle medie mobili, delle bande
di Bollinger, di RSI/Stocastico/MACD/Williams %R, dell'ATR e degli
eventuali obiettivi di prezzo delle figure — per chi vuole i dati grezzi
senza leggere il testo.

Poi l'analisi vera e propria: non un elenco di indicatori messi in fila,
ma sezioni separate — Trend e struttura del prezzo, Medie mobili e
volatilità, Momentum e oscillatori, Pattern grafici e candlestick —
ognuna con un paragrafo che spiega cosa significa, non solo il numero. In
fondo trovi una **Sintesi**: un paragrafo che ragiona su quanto le
sezioni concordano o si contraddicono tra loro (es. trend rialzista ma
momentum già in ipercomprato) e indica i livelli di prezzo da monitorare.
Ogni riga è generata da regole esplicite, non da un modello black-box:
puoi sempre risalire al perché di ogni frase.

Infine un **Piano operativo**: uno schema di ingresso/stop/target
pensato per chi usa l'analisi anche per il trading di breve periodo.
Usa il punteggio tecnico per stabilire un'impostazione (long/short/nessun
setup), lo stop è ancorato al supporto o resistenza più vicini (con un
margine dato dall'ATR, la volatilità media recente) o, se non c'è un
livello vicino, a un multiplo dell'ATR; il target è il livello opposto
più vicino o l'obiettivo di una figura di prezzo rilevata; viene mostrato
anche il rapporto rischio/rendimento. È uno schema costruito su regole
tecniche oggettive, non un ordine pronto da eseguire — il dimensionamento
della posizione resta una scelta tua.

I tre orizzonti temporali (breve/medio/lungo) usano parametri diversi —
oscillatori più corti e sensibili per il trading di breve, dati
settimanali per l'investimento di lungo periodo — così puoi cambiare la
profondità dell'analisi (grafico, sezioni e piano operativo insieme) in
base al tipo di decisione, senza lasciare la pagina.

## Analisi Fondamentale: come funziona il Fundamental Score

La pagina **Analisi Fondamentale** calcola un **Fundamental Score (0-100)**
per un singolo titolo, con la stessa struttura a tre sezioni delle altre
pagine di analisi: **Portafoglio**, **Preferiti** e **Cerca**. Non è un
modello di fair value — è uno strumento di screening comparativo, pensato
per un orizzonte di medio termine, costruito seguendo una specifica
tecnica (metriche, formule e pesi settoriali) fornita esplicitamente per
questo modulo. Le banche/assicurazioni restano escluse: EBITDA, ROIC, EV
e i coefficienti Piotroski/Altman non sono significativi per il loro
modello di business.

**Il principio guida è la parsimonia**: invece di un elenco lungo di
multipli slegati tra loro, un nucleo di **8 metriche a bassa correlazione
reciproca** (una per dimensione: creazione di valore, qualità degli
utili, leva, valutazione, capital allocation) più due **badge standalone**
con pedigree accademico (Piotroski F-Score, Altman Z-Score) — non
soglie assolute, ma **percentili contro un peer group curato per
settore** (15 titoli liquidi e rappresentativi per ciascuno degli 11
settori di Yahoo Finance, in `src/sector_universe.py`), perché una stessa
soglia di leva o di margine ha un significato diverso in settori diversi.

- **Le 8 metriche core**: ROIC (medie pluriennali di EBIT e capitale
  investito, per smorzare il rumore ciclico), gross-profits-to-assets
  (Novy-Marx), FCF conversion (FCF/utile netto), accruals ratio (Sloan —
  utili "di cassa" o solo contabili), debito netto/EBITDA, copertura
  interessi, EV/EBIT earnings yield, shareholder yield (dividendi +
  buyback netti su capitalizzazione) — più CAGR ricavi/EPS e volatilità
  della crescita per la categoria "Qualità della crescita".
- **Piotroski F-Score (0-9)**: 9 criteri binari su profittabilità, leva/
  liquidità ed efficienza operativa, confrontando l'anno corrente con il
  precedente (Piotroski, 2000) — mostrato come badge distinto, con il
  dettaglio dei singoli criteri in un pannello a parte.
- **Altman Z-Score / Z″**: predittore di distress finanziario, con la
  variante corretta in base al settore (manifatturiero vs
  non-manifatturiero). Se il titolo è in zona di distress, il punteggio
  composito viene **limitato a 40** indipendentemente dagli altri punti
  di forza — la difesa principale contro i "value trap".
- **Percentile sector-relative**: ogni metrica viene winsorizzata al
  5°/95° percentile del peer group e trasformata in un percentile 0-100
  (orientato così che un valore più alto sia sempre "meglio"), poi
  aggregata in 6 sub-score di categoria, sempre mostrati insieme al
  punteggio finale — mai solo il numero.
- **Pesi settore/cap-adjusted**: i 6 sub-score si combinano con pesi
  diversi per 6 profili settoriali (Growth/Tech, Value/Industrial,
  Utilities/Defensive, Consumer, Healthcare, Energy/Materials) e per
  dimensione (mega/large, mid, small/micro — il peso del Piotroski sale
  per le small cap, dove l'evidenza empirica è più forte). Se una
  metrica o un'intera categoria manca, il suo peso si ridistribuisce
  automaticamente sulle altre disponibili; sotto una copertura dati del
  60% lo score non viene mostrato ("dati insufficienti") invece di
  imputare un valore neutro che favorirebbe le aziende deboli.
- **Flag testuali automatici**: FCF conversion in calo, buyback dichiarati
  ma azioni in aumento (diluizione da SBC), P/E al 90° percentile della
  propria storia, ROIC sotto il costo del capitale stimato (CAPM/WACC),
  zona di distress Altman — spesso più utili del numero per decidere.
- **Peer group con caching**: i fondamentali dei ~15 peer per settore
  sono salvati in `data/fundamentals_cache.json` e riusati per ~90 giorni
  (i fondamentali cambiano su base trimestrale), per non richiamare
  Yahoo Finance su 15 titoli ad ogni singola analisi.

**Export Excel**: il bottone "Scarica Excel" in alto genera un workbook
con sintesi (punteggio, badge, tesi, punti di forza/attenzione), le 8
metriche core con percentile, categorie e pesi (con il punteggio
composito come vera formula Excel ricalcolabile), bilancio annuale e
l'intero peer group usato per i percentili — per verificare o archiviare
l'analisi fuori dall'app.

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
- Il confronto "da quando hai iniziato" con il benchmark è un'approssimazione
  solo se non hai ancora registrato transazioni; con il Registro Transazioni
  compilato usa l'XIRR, molto più accurato.
- Realizzato/XIRR usano il metodo del costo medio ponderato (average cost),
  non FIFO/LIFO — è lo standard più comune per investitori privati ma non
  coincide sempre col calcolo esatto del tuo broker o del fisco.
- Nessuna esecuzione di ordini: è uno strumento di sola consultazione e analisi.
- I pattern grafici e le candele in Analisi Tecnica sono rilevati con
  regole geometriche automatiche (non da un occhio umano): possono
  produrre falsi segnali, soprattutto su titoli poco liquidi o mercati
  laterali. Vanno letti come spunti da verificare, non certezze.
- Gli avvisi sui Preferiti sono solo in-app: nessuna email/notifica push in
  questa versione. Vanno controllati aprendo la pagina e premendo
  "Scansiona preferiti" — non è un servizio che gira in background.
- Il Piano operativo usa l'ATR (Average True Range), un indicatore
  standard di volatilità non presente nei capitoli del manuale di Murphy
  usati per il resto del modulo — è stato aggiunto perché necessario per
  calibrare stop e target in modo proporzionato alla volatilità reale del
  titolo. Stop e target sono un punto di partenza tecnico, non tengono
  conto di commissioni, slippage, orari di mercato o della tua gestione
  del rischio complessiva.
- Il **Fundamental Score** è un ranking **relativo** al peer group di
  settore: in un settore uniformemente debole, uno score alto significa
  "il migliore di un gruppo scarso", non un titolo oggettivamente solido
  — per questo la pagina mostra sempre gli anchor assoluti (ROIC vs WACC,
  bande di leva, zona Altman) accanto al percentile.
- Piotroski e Altman sono **backward-looking** (bilanci già pubblicati):
  sono filtri di rischio e sanity check, non segnali predittivi
  standalone. I coefficienti Altman sono tarati su manifatturieri USA del
  secolo scorso — per questo la pagina usa la variante Z″ per i settori
  non-manifatturieri. L'edge del Piotroski F-Score si è indebolito sui
  mega cap molto liquidi e coperti dagli analisti.
- I pesi settoriali (profilo Growth/Tech, Value/Industrial, ecc.) sono un
  **punto di partenza ragionato**, non calibrato con un backtest — la
  specifica stessa lo dichiara esplicitamente come primo passo da
  affinare nel tempo.
- Il peer group per settore (`src/sector_universe.py`) è una selezione
  curata di ~15 titoli liquidi per ciascuno degli 11 settori Yahoo
  Finance, non un campionamento esaustivo di mercato: un provider dati a
  pagamento con copertura completa per sotto-industria GICS darebbe
  percentili più precisi. La mappatura da 11 settori a 6 profili di peso
  ha due casi "misti" dichiarati (Communication Services e Real Estate).
- I REIT (settore Real Estate) userebbero un profilo dedicato con FFO/
  AFFO al posto di EPS/P/E: non ancora implementato, la pagina lo segnala
  esplicitamente e usa il profilo generico più vicino come approssimazione.
- I prospetti di bilancio dipendono dalla copertura Yahoo Finance: spesso
  incompleti o assenti per titoli non statunitensi o a bassa
  capitalizzazione. Sotto una copertura dati del 60% lo score non viene
  mostrato ("dati insufficienti") invece di essere stimato su dati
  incompleti.
- Il target price e la raccomandazione aggregata degli analisti (mostrati
  come contesto on-demand, non nello score) sono un consensus reale ma non
  infallibile: riflettono le stime di chi copre il titolo in quel momento,
  possono essere lente ad aggiornarsi, e con pochi analisti (l'app lo
  segnala) vanno pesate molto meno. Nessuna delle regole di punteggio di
  questa sezione è stata verificata con un backtest storico: sono regole
  costruite per ragionevolezza economica su dati reali, non un segnale
  operativo validato — vanno trattate come una diagnostica strutturata,
  non come un rating.
- Il sentiment sulle news è un filtro per parole chiave in inglese, non
  un modello linguistico: può classificare male titoli ambigui o ironici
  ed è pensato come primo orientamento, da verificare leggendo gli
  articoli.
