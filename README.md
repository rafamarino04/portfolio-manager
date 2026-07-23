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
- `pages/analisi_fondamentale.py` — **Quality** e **Valuation** (0-100 ciascuno, assi separati) per un singolo titolo: **Portafoglio**, **Preferiti** e **Cerca**, come nell'Analisi Tecnica. Scoring assoluto calibrato per settore/archetipo operativo (nessun peer group a runtime), matrice 2x2 Quality x Valuation, archetipo Dickinson, Piotroski/Altman/Beneish, Note Critiche selettive e un modello di confidenza esplicito
- `pages/fattori.py` — valuta i titoli in Portafoglio/Preferiti sui 5 **fattori** con premio storico documentato in letteratura — Value, Momentum, Quality, Low Volatility, Size — con un punteggio **assoluto** 0-100 (scala fissa, non un confronto con altri titoli) e radar a 5 assi: è il ponte tra Analisi Fondamentale (cosa comprare) e Analisi Tecnica (quando comprarlo)
- `pages/impostazioni_alert_report.py` — attiva/disattiva gli alert email sui segnali tecnici, l'indirizzo destinatario, quali tipi di evento notificare, più le istruzioni per configurare Gmail e i secrets GitHub Actions; e il contenuto/periodicità del report automatico
- `scripts/generate_weekly_report.py` — genera il report periodico in background (lanciato ogni lunedì da GitHub Actions); non ha più una pagina dedicata di visualizzazione in-app, resta un artefatto markdown nel repository
- `scripts/send_technical_alerts.py` — scansiona portafoglio + preferiti col motore di Analisi Tecnica (lanciato ogni giorno feriale da GitHub Actions) e invia un'email solo se compare un segnale nuovo rispetto all'ultima scansione (deduplica su `data/alert_state.json`)
- `scripts/verify_axis_distribution.py` — script di verifica manuale (non automatizzato da GitHub Actions): calcola la distribuzione di Quality/Valuation su un campione diversificato di titoli, per giudicare se l'asse Valuation discrimina abbastanza o si comprime in un mercato mediamente caro (v2.1, va eseguito con `PYTHONPATH=.` e accesso di rete reale)
- `src/email_alerts.py` — costruzione e invio dell'email di alert via Gmail SMTP
- `data/transactions.csv` — **fonte di verità**: il registro di ogni movimento reale
- `data/portfolio.csv` — le posizioni attuali, calcolate automaticamente da `transactions.csv` (non modificarlo a mano)
- `data/watchlist.csv` — i tuoi titoli Preferiti, con un prezzo di riferimento opzionale (creato al primo utilizzo della pagina Analisi Tecnica)
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
- **Analisi Fondamentale**: guarda Quality e Valuation come due domande
  separate — "è un buon business?" e "è a un prezzo interessante?" — e
  usa la matrice 2x2 per capire il quadrante (wonderful company, quality
  a caro prezzo, value trap, da evitare) prima di guardare il numero
  unico secondario. Leggi sempre le eventuali Note Critiche: segnalano
  quando una metrica standard rischia di ingannare su quel titolo
  specifico.
- **Fattori**: prima di comprare un titolo forte sui fondamentali, guarda
  il suo punteggio assoluto sui 5 fattori — un titolo di qualità ma caro
  (Value basso) o già corso molto (Momentum alto ma teso in Analisi
  Tecnica) merita un timing più attento.

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

## Analisi Fondamentale v2.1: come funziona

La pagina **Analisi Fondamentale** calcola due punteggi **assoluti 0-100
separati** — **Quality** e **Valuation** — per un singolo titolo, con la
stessa struttura a tre sezioni delle altre pagine di analisi:
**Portafoglio**, **Preferiti** e **Cerca**. Non è un modello di fair
value — è uno strumento di screening, costruito seguendo una specifica
tecnica v2.0 fornita esplicitamente per questo modulo ("Absolute
Sector-Calibrated Scoring with Quality-Valuation Matrix and Critical
Notes Layer"). Le banche/assicurazioni restano escluse: EBITDA, ROIC, EV
e i coefficienti Piotroski/Altman non sono significativi per il loro
modello di business.

**Perché due assi separati invece di un numero solo**: la letteratura
accademica (Novy-Marx 2013 sul premio di profittabilità; Asness/Frazzini/
Pedersen 2019 sul quality factor; la Magic Formula di Greenblatt, che usa
esplicitamente due segnali ortogonali — ROIC per la qualità, EBIT/EV per
il prezzo) tratta qualità e convenienza come **assi ortogonali**:
fonderli in un solo numero distrugge l'informazione più utile per
decidere ("buon business ma caro" è una situazione diversa da "business
scadente ma a buon mercato", anche se il loro numero medio fosse
identico). Il **blended number** (media dei due assi) resta visibile
solo come dettaglio secondario, mai come segnale primario.

**Perché "assoluto" qui significa "calibrato per settore", non "soglia
universale"**: un ROIC del 12% è eccellente per una utility (il cui costo
del capitale tipico è ~5-6%) e mediocre per un software (~9-10%) — le
soglie sono tabelle di lookup pre-calcolate per **8 bucket di settore**
(`src/sector_thresholds.py`, ispirate al dataset Damodaran NYU Stern e
alle convenzioni di rating S&P/Moody's per la leva), **non un peer group
costruito a runtime**: a differenza della versione precedente di questo
modulo, il punteggio di un titolo non cambia in base a quali altri titoli
segui, ed è quindi utilizzabile anche per un singolo titolo isolato.

- **Archetipo operativo, non settore GICS grezzo** (`src/lifecycle.py`):
  il ciclo di vita si deriva dai segni dei tre flussi di cassa (modello
  Dickinson 2011: 8 combinazioni di OCF/CFI/CFF → Introduzione/Crescita/
  Maturità/Declino/Shake-out) combinati con crescita ricavi, margini,
  capex/ricavi, R&D/ricavi, payout e ROIC — non dal solo settore Yahoo
  Finance. Sette archetipi (Hyper-growth, Growth, Mature compounder,
  Mature cash cow, Cyclical, Turnaround, Capital-intensive/utility-like),
  ciascuno con pesi diversi per le 4 categorie Quality: così un'azienda a
  crescita lenta in un settore "Tech" non viene più penalizzata sul peso
  crescita solo per l'etichetta di settore (bug-fix esplicito rispetto a
  v1).
- **Asse Quality (0-100)**: 4 categorie — Redditività e creazione di
  valore (ROIC, gross-profits-to-assets, margine operativo, shareholder
  yield), Qualità degli utili e cash flow (FCF conversion, accruals
  ratio secondo Sloan), Solidità finanziaria (debito netto/EBITDA,
  copertura interessi), Qualità della crescita (CAGR ricavi/EPS,
  volatilità della crescita) — più Piotroski F-Score (0-9) a parte, con
  peso più alto per le small cap. Ogni metrica si legge su una scala
  fissa a 6 bande (Scarso/Debole/Sufficiente/Discreto/Buono/Eccellente),
  mai relativa ad altri titoli.
- **Asse Valuation (0-100, punteggio alto = economico)**: 4 componenti —
  multipli assoluti calibrati per settore (EV/EBITDA, EV/Sales, P/E vs
  bande di fair value), storia propria (percentile del P/E su una
  finestra storica, idealmente 8 anni con fallback a 5), EV/EBIT earnings
  yield (Greenblatt) confrontato col rendimento del Treasury 10 anni,
  growth-adjusted (PEG dove il P/E è definito, altrimenti Rule of 40 per
  le aziende hyper-growth in perdita).
- **Matrice 2x2 Quality x Valuation**: quattro quadranti interpretativi —
  *Wonderful company at a fair price* (quality alta, economico: candidato
  forte), *Quality-at-a-price* (quality alta, caro: watchlist/pullback),
  *Value trap potenziale* (quality bassa, economico: serve una tesi
  specifica su un catalizzatore), *Evitare* (quality bassa, caro) — il
  quadrante conta più del numero, per costruzione.
- **Piotroski F-Score, Altman Z/Z″, Beneish M-Score**: Piotroski (9
  criteri binari, 2000) con guard rail — il criterio sul current ratio si
  neutralizza per modelli a working capital negativo (subscription),
  i criteri variazionali si sospendono in presenza di one-off o M&A.
  Altman Z (manifatturieri) o Z″ (tutti gli altri) per il rischio di
  distress, soggetto anch'esso a un guard rail (buyback che erodono i
  retained earnings possono generare un falso segnale di distress).
  Beneish M-Score (1999, 8 variabili o versione ridotta a 5 se i dati
  Yahoo Finance non bastano): un "early warning" statistico su possibili
  manipolazioni contabili, non una prova di frode.
- **Layer di Note Critiche selettivo** (`src/critical_notes.py`, 19
  situazioni diagnosticabili — NC-01…NC-19): emettono un avviso testuale
  SOLO quando un trigger preciso scatta sui dati del titolo — buyback che
  distorce l'Altman Z, patrimonio netto negativo, ROE gonfiato dalla leva
  (DuPont), goodwill che distorce il ROIC, R&D non capitalizzato,
  leasing operativi, stock-based compensation, ciclicità al picco/
  minimo, utili distorti da voci non ricorrenti, working capital
  negativo come punto di forza (non debolezza) per i modelli subscription,
  cassa netta, M&A recenti, azienda in perdita, settori REIT/Utility a
  leva strutturale diversa, dati di bilancio non aggiornati, divergenza
  tra utile operativo e free cash flow, effetti valutari, base di asset
  molto ammortizzata, e (NC-19, v2.1) cash flow da investimento distorto
  dal portafoglio di marketable securities. Selettivo per scelta: una
  nota su ogni metrica distruggerebbe la fiducia nello strumento. Ogni
  nota dichiara ora anche un **tipo di aggiustamento** (penalità reale su
  un sub-score, soppressione di una metrica/criterio, riclassificazione,
  o solo informativa): solo le note di tipo "penalità" possono impedire a
  una categoria di comparire fra i Punti di forza, per evitare che la
  stessa dimensione compaia contemporaneamente come forza e come
  attenzione.
- **Modello di Confidenza/Incertezza**: un punteggio 0-100 (Alta ≥75,
  Media 50-74, Bassa <50) da completezza dati, freschezza dell'ultimo
  bilancio (anche per singola metrica, non solo per l'intero bilancio),
  stabilità del segnale Dickinson su più anni e chiarezza dell'archetipo
  assegnato — mostrato sempre accanto agli score, col valore numerico
  esplicito e con la spiegazione testuale di cosa l'ha abbassato. Se sono
  presenti fattori di riduzione, l'etichetta non può dichiararsi "Alta"
  anche se il punteggio numerico lo sarebbe (vincolo di coerenza v2.1):
  in quel caso viene declassata a "Media" e la pagina lo segnala
  esplicitamente, per non mostrare un badge che contraddice le sue stesse
  spiegazioni.

**Correzioni v2.1** (rispetto alla prima versione di questo modulo):
rendering della matrice 2x2 corretto (l'HTML dei quadranti veniva
mostrato come testo grezzo invece che renderizzato, e il quadrante attivo
mostrava un segnaposto statico invece del ticker analizzato); badge di
affidabilità reso coerente coi fattori di riduzione elencati; note
critiche NC-07/NC-16 ora applicano una penalità reale al sub-score
qualità utili invece di essere solo segnalate a testo; le metriche
derivate da un esercizio più vecchio delle altre della stessa categoria
sono ora etichettate con l'anno di riferimento, pesate a metà nel
sub-score e riducono la confidenza in proporzione (non solo quando
l'intero bilancio è vecchio); i Punti di attenzione ora includono anche
le categorie/assi in banda Debole o Scarso anche senza una nota critica
specifica; la tabella "Prospettive per categoria" include ora la riga
Piotroski F-Score col suo peso effettivo, e i pesi sommano visibilmente
a 100%; aggiunta la nota critica NC-19.

**Export Excel**: il bottone "Scarica Excel" in alto genera un workbook
con sintesi (Quality, Valuation, quadrante, badge, tesi, punti di forza/
attenzione), le metriche core per categoria, i pesi Quality (con il
punteggio come vera formula Excel ricalcolabile), i 4 componenti
Valuation, le Note Critiche scattate e il bilancio annuale — per
verificare o archiviare l'analisi fuori dall'app.

## Fattori: come funziona

La pagina **Fattori** valuta i titoli in Portafoglio e Preferiti su **5
fattori** con un premio storico documentato in letteratura accademica
(Fama-French, Novy-Marx, Asness/AQR, Jegadeesh-Titman): **Value**,
**Momentum**, **Quality**, **Low Volatility**, **Size**. A differenza di
una prima versione (percentile contro un universo di portafoglio +
preferiti + peer di settore), ogni fattore è ora un punteggio
**assoluto 0-100 su una scala fissa**: la metrica grezza si confronta
con tre ancore economicamente ragionevoli (0 = scarso, 50 = nella
media, 100 = eccellente), non con gli altri titoli che segui — il
punteggio di un titolo non cambia se aggiungi o togli altri titoli dal
portafoglio o dai preferiti, ed è quindi un valore su cui puoi basarti
da solo, anche per un singolo titolo isolato.

- **Value**: earnings yield (E/P), FCF yield, EV/EBIT earnings yield
  (riusato dall'Analisi Fondamentale), book-to-price — quattro angolazioni
  diverse sulla stessa idea, per non dipendere da un solo multiplo.
  Ancore attorno ai multipli medi storici di lungo periodo del mercato
  azionario USA (es. earnings yield: 2% = punteggio 0, 6,5% ~ P/E 15 =
  punteggio 50, 12% = punteggio 100).
- **Momentum**: total return a 12 mesi **escludendo l'ultimo mese**
  (12-1) — la convenzione standard in letteratura, perché il mese più
  recente tende a mostrare un effetto di reversione di breve termine che
  contaminerebbe il segnale di momentum vero e proprio. Ancore: -30% =
  punteggio 0, 0% (piatto) = punteggio 50, +40% = punteggio 100.
- **Quality**: collegato direttamente alle metriche core dell'Analisi
  Fondamentale — ROIC, gross-profits-to-assets, accruals ratio — cosi' i
  due moduli restano coerenti tra loro invece di avere due definizioni
  diverse di "qualità". Ancore: ROIC 0%/10%/25% (0/50/100).
- **Low Volatility**: volatilità storica a 12 mesi e beta — storicamente,
  i titoli meno volatili non hanno reso peggio di quelli più volatili a
  parità di rischio atteso, il cosiddetto "low-volatility anomaly".
  Ancore: volatilità 55%/30%/12% e beta 2,0/1,0/0,4 (0/50/100).
- **Size**: capitalizzazione di mercato su scala logaritmica, con
  punteggio più alto per cap **più piccola** — il premio storico delle
  small cap, per quanto meno robusto negli ultimi decenni rispetto agli
  anni '80-'90. Ancore: 200 Mld $ = punteggio 0, 10 Mld $ = punteggio
  50, 0,5 Mld $ = punteggio 100.

I punteggi si aggregano in un **composite** con un profilo di peso a
scelta — Equal-weight di default, o un tilt dichiarato verso
Value/Momentum/Quality (il peso si ridistribuisce sui fattori
disponibili se qualcuno manca per dati insufficienti). Per ogni titolo
trovi un **radar a 5 assi** e le metriche grezze in un pannello a
parte, per verificare da dove viene ogni punteggio.

**Distinzione cruciale, ribadita anche nell'interfaccia**: il Momentum-
fattore qui è **cross-sezionale e di medio termine** (quali titoli
comprare, confrontando total return a 12-1 mesi tra titoli diversi) — un
concetto diverso dagli **oscillatori di momentum** dell'Analisi Tecnica
(RSI, Stocastico, MACD: quando entrare su un singolo titolo, nel breve
termine). Un titolo forte su Analisi Fondamentale e Fattori ma teso
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
- Le soglie assolute per settore/archetipo di **Quality/Valuation**
  (`src/sector_thresholds.py`) sono una mia calibrazione ragionata,
  ispirata alle cifre citate nella specifica (dataset Damodaran, gennaio
  2026) ma non l'esatto dataset — soprattutto per i settori non
  esplicitamente coperti dalla specifica (Energy/Materials, Consumer
  Cyclical, Communication Services), dove ho esteso gli ordini di
  grandezza dei bucket vicini. Da versionare/aggiornare manualmente,
  idealmente ogni gennaio quando Damodaran pubblica l'aggiornamento.
- L'**archetipo operativo** (Dickinson + caratteristiche osservabili) è
  un classificatore a regole con un ordine di priorità esplicito, mio,
  per risolvere i casi in cui più trigger si sovrappongono — non
  un'assegnazione garantita "corretta": la pagina mostra sempre il
  motivo (quali trigger hanno determinato l'archetipo) per poterlo
  verificare.
- Piotroski, Altman e Beneish sono **backward-looking/forensic-
  statistici** (bilanci già pubblicati): sono filtri di rischio e sanity
  check, non segnali predittivi standalone né prove di frode. I
  coefficienti Altman sono tarati su manifatturieri USA del secolo
  scorso — per questo la pagina usa la variante Z″ per i settori
  non-manifatturieri. Il Beneish M-Score richiede diverse voci di
  bilancio (crediti, SG&A, PP&E lordo/netto, aliquota di ammortamento)
  spesso incomplete su Yahoo Finance: se mancano, passa alla versione a
  5 variabili o si sopprime del tutto, mai mostrato a metà.
- I fattori quality/value pubblicati in letteratura accademica si sono
  **indeboliti nel tempo** (McLean & Pontiff 2016: rendimenti fuori
  campione il 26% più bassi, post-pubblicazione il 58% più bassi;
  l'accruals anomaly di Sloan in particolare è documentata in declino) —
  trattare Quality e Valuation come indicatori di robustezza
  fondamentale, non come previsioni di rendimento.
- I REIT e le Utility (settore Real Estate/Utilities) hanno una leva
  strutturalmente diversa dagli altri settori: la Nota Critica NC-14 lo
  segnala esplicitamente, ma un profilo dedicato con FFO/AFFO al posto di
  EPS/P/E per i REIT non è ancora implementato — usa il bucket di soglie
  Utility/capital-intensive come approssimazione.
- Il **layer di Note Critiche** è selettivo per scelta (19 situazioni
  diagnosticabili, non un controllo su ogni metrica): può quindi non
  coprire situazioni reali non incluse nelle 19 regole — resta un
  supplemento al giudizio, non un sostituto.
- Le **soglie assolute dell'asse Valuation** sono calibrate sul valore
  intrinseco per settore/archetipo, non sul livello generale del mercato:
  in una fase di mercato mediamente caro, l'asse potrebbe comprimersi
  verso punteggi bassi per la maggior parte dei titoli analizzati,
  restando "onesto" ma perdendo potere discriminante fra i candidati
  seguiti. `scripts/verify_axis_distribution.py` calcola la distribuzione
  di Quality e Valuation su un campione diversificato di titoli per
  verificarlo (va eseguito con accesso di rete reale, non nella sandbox
  di sviluppo): se la distribuzione risulta compressa, la correzione
  corretta NON è ammorbidire le soglie assolute, ma affiancare un secondo
  livello di lettura — la posizione relativa del titolo nell'universo
  portafoglio+preferiti dell'utente, etichettata distintamente dal
  punteggio assoluto — non ancora implementato in attesa del risultato
  della verifica.
- I prospetti di bilancio dipendono dalla copertura Yahoo Finance:
  tipicamente **4 anni** di bilanci annuali gratuiti, non gli 8 idealmente
  usati da alcune metriche (percentile storico di valutazione,
  normalizzazione mid-cycle per i titoli ciclici) — dove i dati non
  bastano lo score/percentile viene soppresso, mai stimato su dati
  insufficienti, e il modello di confidenza segnala la riduzione. Sotto
  una copertura dati del 60% lo score Quality o Valuation non viene
  mostrato ("dati insufficienti").
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
  l'esempio classico) — un punteggio alto oggi non è una promessa di
  rendimento futuro. Il punteggio è assoluto (ancore fisse scelte da
  me su basi economiche/statistiche ragionevoli, non calibrate con un
  backtest, dichiarate nel disclaimer della pagina), non relativo a un
  universo di confronto: è stabile nel tempo, ma le ancore restano una
  scelta soggettiva — un multiplo "medio" ragionevole oggi potrebbe non
  esserlo tra qualche anno se il mercato si rivaluta strutturalmente. Il
  composite ridistribuisce i pesi sui fattori disponibili se qualcuno
  manca per dati insufficienti, invece di imputare un valore neutro.
