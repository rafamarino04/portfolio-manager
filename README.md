# Portfolio Manager

Dashboard indipendente di supporto alle decisioni per un portafoglio di
azioni, ETF, obbligazioni, fondi/SICAV e liquidità: non solo monitoraggio,
ma registro transazioni, ribilanciamento, confronto con un benchmark,
analisi tecnica e fondamentale sui singoli titoli, classificazione a
fattori, alert email sui segnali tecnici e un report periodico
configurabile. Gira fuori da Claude, come un sito vero, gratis, sul tuo
account GitHub + Streamlit Community Cloud.

**Cosa NON è**: non è collegato al tuo broker, non esegue ordini, non è
consulenza finanziaria personalizzata — ogni indicatore è statistico e
pubblico, da usare come spunto per approfondire, non come segnale
operativo. I prezzi arrivano da Yahoo Finance (via libreria `yfinance`)
con un delay tipico di 15-20 minuti — ottimo per decisioni ponderate, non
per trading attivo.

**Design**: tema scuro ispirato ai terminali finanziari (sfondo quasi
nero, card a bordo sottile, cifre in monospace, un solo colore d'accento)
invece della classica dashboard chiara da gestionale — pensato per
restare leggibile su tutte le pagine senza distrarre dal dato. Nessuna
emoji: gli unici indicatori visivi sono colore, tipografia e bordo.

## Cosa include

- `app.py` — bootstrap: password, poi la navigazione tra le 5 sezioni (nessun numero o emoji nel nome delle pagine, l'ordine è deciso qui)
- `pages/portafoglio_personale.py` — la vista su tutto ciò che riguarda le posizioni reali: **Registro Transazioni** a tendina in cima (aggiungi un movimento o apri lo storico completo per modificarlo), allocazione attuale a torta, confronto con il portafoglio ideale (target impostabile lì stesso) a tendina accanto al grafico, poi il dettaglio di rendimento per prodotto/portafoglio e il confronto con un benchmark di mercato (XIRR reale, non approssimato)
- `pages/analisi_tecnica.py` — hub decisionale sui titoli: **Portafoglio** (i tuoi titoli, pronti da analizzare), **Preferiti** (watchlist con avvisi tecnici automatici) e **Cerca** (ricerca libera). Analisi tecnica secondo il framework di J. Murphy per breve/medio/lungo termine — trend strutturale via swing highs/lows riconciliato con le medie mobili, supporti/resistenze e trendline validate, oscillatori letti nel contesto del trend, candlestick e figure di prezzo filtrati per affidabilità, volume/OBV — con una sintesi finale basata su un **Directional Score + Agreement Index** che distingue un quadro davvero neutro da segnali in conflitto tra loro
- `pages/analisi_fondamentale.py` — **Fundamental Score** (0-100) per un singolo titolo: **Portafoglio**, **Preferiti** e **Cerca**, come nell'Analisi Tecnica. Un nucleo di 8 metriche a bassa correlazione (creazione di valore, qualità degli utili, leva, valutazione, capital allocation) più i badge Piotroski F-Score e Altman Z-Score, sempre confrontati con un peer group curato per settore — non con soglie assolute
- `pages/fattori.py` — classifica i titoli in Portafoglio/Preferiti sui 5 **fattori** con premio storico documentato in letteratura — Value, Momentum, Quality, Low Volatility, Size — con percentile e radar a 5 assi contro un universo di confronto (portafoglio + preferiti + peer di settore), non contro il proprio grafico: è il ponte tra Fundamental Score (cosa comprare) e Analisi Tecnica (quando comprarlo)
- `pages/impostazioni_alert_report.py` — attiva/disattiva gli alert email sui segnali tecnici, l'indirizzo destinatario, quali tipi di evento notificare, più le istruzioni per configurare Gmail e i secrets GitHub Actions; e il contenuto/periodicità del report automatico
- `scripts/generate_weekly_report.py` — genera il report periodico in background (lanciato ogni lunedì da GitHub Actions); non ha più una pagina dedicata di visualizzazione in-app, resta un artefatto markdown nel repository
- `scripts/send_technical_alerts.py` — scansiona portafoglio + preferiti col motore di Analisi Tecnica (lanciato ogni giorno feriale da GitHub Actions) e invia un'email solo se compare un segnale nuovo rispetto all'ultima scansione (deduplica su `data/alert_state.json`)
- `src/email_alerts.py` — costruzione e invio dell'email di alert via Gmail SMTP
- `data/transactions.csv` — **fonte di verità**: il registro di ogni movimento reale
- `data/portfolio.csv` — le posizioni attuali, calcolate automaticamente da `transactions.csv` (non modificarlo a mano)
- `data/watchlist.csv` — i tuoi titoli Preferiti, con un prezzo di riferimento opzionale (creato al primo utilizzo della pagina Analisi Tecnica)
- `data/fundamentals_cache.json` — cache dei fondamentali dei titoli peer usati per i percentili di settore del Fundamental Score, aggiornata al più ogni ~90 giorni (creato al primo utilizzo della pagina Analisi Fondamentale)
- `data/factor_cache.json` — stessa logica di cache, file separato, per le metriche grezze usate dalla pagina Fattori (creato al primo utilizzo della pagina Fattori)
- `data/alert_state.json` — ultimo segnale tecnico visto per ogni titolo, usato per non rimandare la stessa email ogni giorno (creato al primo invio riuscito)
- `data/settings.json` — le tue impostazioni (allocazione ideale, benchmark, sezioni report, alert email)
- `.github/workflows/weekly_report.yml` — l'automazione del report periodico, gratuita
- `.github/workflows/technical_alerts.yml` — l'automazione degli alert email sui segnali tecnici, gratuita
- `.streamlit/config.toml` — tema scuro coerente su tutte le pagine

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
Una volta che l'app è online (punto 4), apri la tendina **Registro
Transazioni** in cima a **Portafoglio Personale** — non serve toccare
GitHub. Sostituisci le righe di esempio con i tuoi acquisti/vendite/
dividendi reali:

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
scelto in **Impostazioni Alert e Report**) e lo salva nel repository —
resta un file markdown nel repository, senza una pagina dedicata in-app
al momento. Lanciabile anche a mano: tab **Actions** → "Report
settimanale portafoglio" → **Run workflow**. Per cambiare giorno/orario,
modifica la riga `cron` in `.github/workflows/weekly_report.yml`.

### 6. (Opzionale) Attiva gli alert email sui segnali tecnici
Un secondo workflow, indipendente dal report, scansiona ogni giorno
feriale il portafoglio e i preferiti e ti scrive un'email solo quando
compare un segnale tecnico nuovo. Serve un account Gmail (anche quello
che usi già) con una **password per le app** dedicata — i passaggi
completi sono nella pagina **Impostazioni Alert e Report** dell'app
stessa (sezione "Come configurare l'invio"), in sintesi:

1. Attiva la Verifica in due passaggi sul tuo account Google, poi genera
   una password per le app su https://myaccount.google.com/apppasswords
2. GitHub → **Settings** (del repository) → **Secrets and variables** →
   **Actions**, aggiungi `GMAIL_ADDRESS` (il tuo indirizzo Gmail) e
   `GMAIL_APP_PASSWORD` (il codice generato al passo 1)
3. Nell'app, apri **Impostazioni Alert e Report**, attiva "Attiva alert
   email", scegli i tipi di evento e salva

Senza questi due secrets il workflow gira comunque (non fallisce) ma non
riesce a inviare l'email — lo stato della scansione viene comunque
salvato per non perdere la deduplica. Per cambiare giorno/orario, modifica
la riga `cron` in `.github/workflows/technical_alerts.yml`.

### 7. (Consigliato) Rendi permanenti le modifiche fatte dall'app
La pagina **Portafoglio Personale** (registro transazioni, allocazione
ideale, benchmark) e **Impostazioni Alert e Report** salvano di base solo
sul disco dell'app, che Streamlit Cloud può azzerare ad ogni redeploy
(succede anche quando il report automatico fa un commit). Per renderle
permanenti:

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

- **Portafoglio Personale**: registra ogni movimento reale nella tendina
  in cima (le posizioni si ricalcolano da sole), poi apri la tendina
  accanto alla torta per impostare una volta l'allocazione ideale e
  controllare periodicamente quanto ti sei discostato — la pagina ti dice
  l'importo indicativo da muovere per tornare in equilibrio. Più in basso,
  il rendimento per prodotto e il confronto col benchmark ti dicono se
  stai battendo o sottoperformando il mercato, non solo il valore assoluto
  del portafoglio.
- **Analisi Tecnica**: scegli l'orizzonte (breve/medio/lungo termine) in
  base a come usi quel titolo — trading di breve o investimento — e leggi
  il "perché" sotto il grafico prima di decidere.
- **Analisi Fondamentale**: guarda il Fundamental Score insieme agli
  anchor assoluti (ROIC vs WACC, bande di leva, zona Altman), non da solo
  — è un ranking relativo al peer group di settore, non un giudizio
  assoluto.
- **Fattori**: prima di comprare un titolo forte sui fondamentali, guarda
  dove si posiziona sui 5 fattori rispetto agli altri titoli che segui —
  un titolo di qualità ma caro (Value basso) o già corso molto (Momentum
  alto ma teso in Analisi Tecnica) merita un timing più attento.

## Analisi Tecnica: come funziona

La pagina **Analisi Tecnica** applica il framework di J. Murphy (Dow
Theory, supporti/resistenze, trendline, oscillatori in contesto, volume,
candlestick e figure di prezzo) ai dati storici del ticker, organizzata
in tre sezioni — **Portafoglio**, **Preferiti**, **Cerca** — che
condividono lo stesso motore (`src/technical.py`):

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

**Trend strutturale, non solo medie mobili**: il trend di fondo è
riconosciuto dalla sequenza di massimi/minimi locali (swing highs/lows
individuati con un algoritmo a frattali, scalato per orizzonte: più
sensibile a breve, più ampio a lungo) secondo la Dow Theory — massimi e
minimi crescenti (HH/HL) per un uptrend, decrescenti (LH/LL) per un
downtrend. Questo giudizio strutturale viene poi **riconciliato** in modo
esplicito con l'allineamento delle medie mobili: se le due letture
concordano il verdetto è "alta confidenza"; se il prezzo è in un pullback
temporaneo dentro un trend strutturale intatto, il verdetto lo dice
esplicitamente ("Rialzista con pullback in corso"), invece di produrre
output contraddittori tipo "trend ribassista" + "medie rialziste" sullo
stesso titolo.

**Supporti/resistenze e trendline**: i livelli vengono selezionati per
numero di tocchi, recency e volume sul livello, e quando si cerca il
livello "più vicino" il criterio è sempre la distanza dal prezzo attuale
nella direzione corretta (sotto per il supporto, sopra per la
resistenza) — non il livello più toccato in assoluto, che può essere
lontanissimo dal prezzo corrente. Le trendline vengono validate
geometricamente (tolleranza in ATR, verifica che non vengano attraversate
dal prezzo, minimo 3 punti di appoggio): una trendline che il prezzo ha
già superato non viene disegnata come se fosse ancora valida.

**Oscillatori in contesto, non come segnali standalone**: RSI, Stocastico
(dove previsto per l'orizzonte) e MACD vengono letti insieme al trend di
fondo — un RSI a 90 dentro un uptrend forte è raccontato come conferma di
forza del trend, non come segnale di vendita imminente (uno dei bug
esplicitamente corretti in questa revisione). Le divergenze prezzo/RSI
vengono rilevate a parte, come segnale distinto.

**Candlestick e figure di prezzo filtrati per affidabilità**: i pattern
di candele vengono pesati per affidabilità storica e filtrati per
contesto — due pattern contraddittori sullo stesso giorno (es. una
evening star ribassista e una piercing line rialzista mostrate entrambe
come valide) non vengono più presentati con pari peso; il più recente e
coerente col contesto prevale, con al massimo 3 pattern mostrati. Le
figure di prezzo (doppio massimo/minimo, triangoli) portano ora uno stato
esplicito — **in formazione**, **completata** (rottura confermata) o
**invalidata** — invece di essere segnalate come complete anche prima
della rottura.

**Volume/OBV**: l'On-Balance Volume conferma o mette in dubbio i
movimenti di prezzo (divergenze volume/prezzo), secondo il principio di
Murphy che il volume deve confermare il trend.

Sotto il grafico trovi prima una tabella con **tutti i valori numerici**
calcolati — supporti, resistenze, medie mobili, bande di Bollinger,
RSI/Stocastico/MACD, ATR ed eventuali obiettivi di prezzo delle figure —
poi l'analisi per sezioni (Trend e struttura, Medie mobili e volatilità,
Momentum e oscillatori, Volume, Pattern grafici e candlestick), ognuna
con un paragrafo che spiega cosa significa, non solo il numero.

**Sintesi con Directional Score + Agreement Index**: invece di una media
semplice dei segnali, ogni famiglia di segnali (trend, medie, momentum,
volume, pattern, candlestick, volatilità) vota con un valore direzionale
`d` in [-1,+1] e un peso di affidabilità `c`; la sintesi calcola un
**Directional Score** `D` (la direzione media pesata) e un **Agreement
Index** `A` (quanto i segnali sono d'accordo *sul segno*, non solo sulla
media). Questo distingue due situazioni che una media semplice
confonderebbe: **"Neutro"** (`|D|` piccolo perché i segnali sono
davvero deboli/laterali, `A` alto) da **"Conflitto tra segnali"** (`|D|`
piccolo perché segnali forti ma di segno opposto si cancellano a
vicenda, `A` basso) — nel secondo caso il quadro non è decidibile, e la
pagina lo dice esplicitamente invece di appiattirlo su "neutro". Sotto la
sintesi trovi anche i **flag tematici** (badge testuali su condizioni
particolari: ipercomprato/ipervenduto in trend, rottura recente,
divergenza attiva, ecc.).

**Piano operativo**: uno schema di ingresso/stop/target per chi usa
l'analisi anche per il trading di breve periodo, costruito sul motore
D/A — se `|D|` è troppo piccolo o `A` è troppo basso (quadro neutro o in
conflitto), il piano viene **rifiutato esplicitamente** invece di
proporre un'operazione senza base. Quando c'è un'impostazione (long/
short), lo stop è ancorato al supporto/resistenza più vicino (con
margine ATR) o a un multiplo dell'ATR se non c'è un livello vicino; il
target è il livello opposto più vicino o l'obiettivo di una figura di
prezzo rilevata; viene mostrato il rapporto rischio/rendimento, con un
avviso esplicito se è sfavorevole (sotto 1.5). È uno schema costruito su
regole tecniche oggettive, non un ordine pronto da eseguire — il
dimensionamento della posizione resta una scelta tua.

I tre orizzonti temporali (breve/medio/lungo) usano parametri diversi —
ordine dello swing detector, RSI/Stocastico più corti e sensibili per il
trading di breve (lo Stocastico non è previsto sul lungo termine, dove i
dati sono settimanali), medie mobili più lunghe per l'investimento di
lungo periodo — così puoi cambiare la profondità dell'analisi (grafico,
sezioni, sintesi e piano operativo insieme) in base al tipo di decisione,
senza lasciare la pagina.

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

## Fattori: come funziona

La pagina **Fattori** classifica i titoli in Portafoglio e Preferiti su
**5 fattori** con un premio storico documentato in letteratura accademica
(Fama-French, Novy-Marx, Asness/AQR, Jegadeesh-Titman): **Value**,
**Momentum**, **Quality**, **Low Volatility**, **Size**. A differenza
delle altre due pagine di analisi, qui il confronto non è mai col
passato del titolo stesso, ma con un **universo** di altri titoli
(portafoglio + preferiti + peer di settore, opzionali): il percentile
dice "dove sei rispetto agli altri", non "sei a buon mercato in
assoluto".

- **Value**: earnings yield (E/P), FCF yield, EV/EBIT earnings yield
  (riusato dal Fundamental Score), book-to-price — quattro angolazioni
  diverse sulla stessa idea, per non dipendere da un solo multiplo.
- **Momentum**: total return a 12 mesi **escludendo l'ultimo mese**
  (12-1) — la convenzione standard in letteratura, perché il mese più
  recente tende a mostrare un effetto di reversione di breve termine che
  contaminerebbe il segnale di momentum vero e proprio.
- **Quality**: collegato direttamente alle metriche core del Fundamental
  Score — ROIC, gross-profits-to-assets, accruals ratio — cosi' i due
  moduli restano coerenti tra loro invece di avere due definizioni
  diverse di "qualità".
- **Low Volatility**: volatilità storica a 12 mesi e beta — storicamente,
  i titoli meno volatili non hanno reso peggio di quelli più volatili a
  parità di rischio atteso, il cosiddetto "low-volatility anomaly".
- **Size**: capitalizzazione di mercato, con percentile più alto per
  cap **più piccola** — il premio storico delle small cap, per quanto
  meno robusto negli ultimi decenni rispetto agli anni '80-'90.

Ogni fattore diventa un **percentile 0-100** (winsorizzato al 5°/95°,
stesso metodo del Fundamental Score) contro l'universo scelto, poi
aggregato in un **composite** con un profilo di peso a scelta —
Equal-weight di default, o un tilt dichiarato verso Value/Momentum/
Quality. Per ogni titolo trovi un **radar a 5 assi** e le metriche
grezze in un pannello a parte, per verificare da dove viene ogni
percentile.

**Distinzione cruciale, ribadita anche nell'interfaccia**: il Momentum-
fattore qui è **cross-sezionale e di medio termine** (quali titoli
comprare, confrontando total return a 12-1 mesi tra titoli diversi) — un
concetto diverso dagli **oscillatori di momentum** dell'Analisi Tecnica
(RSI, Stocastico, MACD: quando entrare su un singolo titolo, nel breve
termine). Un titolo forte su Fundamental Score e Fattori ma teso
sull'Analisi Tecnica (ipercomprato, resistenza vicina) è un caso da
"aspetta il pullback", non da comprare subito; forte su tutti e tre i
moduli è un setup più pulito.

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
- Le pagine Opportunità di Mercato, News e Report Settimanale sono state
  rimosse dalla navigazione nella revisione grafica/strutturale
  dell'app: il report periodico continua a generarsi in background
  (GitHub Actions) e resta un file markdown nel repository, ma non ha
  più una vista dedicata in-app finché non verrà ripreso dal lavoro
  sugli alert.
- I pattern grafici e le candele in Analisi Tecnica sono rilevati con
  regole geometriche automatiche (non da un occhio umano): possono
  produrre falsi segnali, soprattutto su titoli poco liquidi o mercati
  laterali. Anche col filtro di affidabilità/contesto, vanno letti come
  spunti da verificare, non certezze — lo stato "in formazione" di una
  figura può non completarsi mai.
- Il Directional Score e l'Agreement Index sono pesi/soglie costruiti
  per ragionevolezza (coerenti con la logica di `ta_core.py` preso come
  riferimento), non calibrati con un backtest storico: la soglia
  "Conflitto tra segnali" (`|D|` piccolo, `A` basso) può classificare
  come conflitto anche casi limite dove i segnali sono semplicemente
  entrambi deboli di segno opposto — un giudizio tecnicamente corretto
  ma da leggere col buon senso, non come oracolo.
- Il pulsante "Scansiona preferiti" in Analisi Tecnica resta solo in-app
  (calcolato al momento in cui apri la pagina). Gli **alert email**
  (sezione Impostazioni Alert e Report) sono invece un servizio separato
  che gira in background ogni giorno feriale via GitHub Actions e usa lo
  stesso motore di scansione, ma richiede la configurazione una tantum di
  Gmail + secrets descritta nel README/nella pagina stessa: finché non è
  configurato, resta disattivato di default e nessuna email parte.
- Il Piano operativo usa l'ATR (Average True Range), un indicatore
  standard di volatilità non presente nei capitoli del manuale di Murphy
  usati per il resto del modulo — è stato aggiunto perché necessario per
  calibrare stop e target in modo proporzionato alla volatilità reale del
  titolo. Viene rifiutato esplicitamente se il quadro D/A non lo
  giustifica, ma quando è mostrato resta un punto di partenza tecnico:
  non tiene conto di commissioni, slippage, orari di mercato o della tua
  gestione del rischio complessiva.
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
- Gli **alert email** girano su GitHub Actions gratuito: l'orario non è
  al secondo (può slittare di qualche minuto nelle ore di punta) e i
  workflow programmati possono essere disattivati automaticamente da
  GitHub se il repository resta inattivo a lungo (si riattivano da soli
  al primo commit o si possono riabilitare a mano dal tab Actions). La
  deduplica confronta il testo del messaggio, quindi un segnale che
  scompare e ricompare identico (es. RSI che rientra sotto 70 e poi lo
  risupera) genera una nuova email, correttamente.
- I **Fattori** sono premi statistici di lungo periodo, non garanzie:
  possono sottoperformare per anni interi (il value 2010-2020 è
  l'esempio classico) — un percentile alto oggi non è una promessa di
  rendimento futuro. Il percentile dipende sempre dall'universo di
  confronto scelto: con pochi titoli in Portafoglio/Preferiti e i peer
  di settore disattivati, l'universo può essere troppo piccolo per un
  percentile robusto. Il composite ridistribuisce i pesi sui fattori
  disponibili se qualcuno manca per dati insufficienti, invece di
  imputare un valore neutro.
