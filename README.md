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

- `app.py` — bootstrap: password, poi la navigazione tra le 7 sezioni (nessun numero o emoji nel nome delle pagine, l'ordine è deciso qui)
- `pages/portafoglio_personale.py` — la vista su tutto ciò che riguarda le posizioni reali: **Registro Transazioni** a tendina in cima (aggiungi un movimento o apri lo storico completo per modificarlo), allocazione attuale a torta, confronto con il portafoglio ideale (target impostabile lì stesso) a tendina accanto al grafico, poi il dettaglio di rendimento per prodotto/portafoglio e il confronto con un benchmark di mercato (XIRR reale, non approssimato)
- `pages/analisi_tecnica.py` — hub decisionale sui titoli: **Portafoglio** (i tuoi titoli, pronti da analizzare), **Preferiti** (watchlist con avvisi tecnici automatici), **Cerca** (ricerca libera), **Idoneità al Trading** (Technical Tradeability Score, con ambito dello screening selezionabile) e **Universo Trading** (la short-list selezionata per il trading). Analisi tecnica secondo il framework di J. Murphy per breve/medio/lungo termine — trend strutturale via swing highs/lows riconciliato con le medie mobili, supporti/resistenze e trendline validate, oscillatori letti nel contesto del trend, candlestick e figure di prezzo filtrati per affidabilità, volume/OBV — con una sintesi finale basata su un **Directional Score + Agreement Index** che distingue un quadro davvero neutro da segnali in conflitto tra loro
- `src/tradeability.py` — **Technical Tradeability Score** (0-100): quanto uno strumento è strutturalmente adatto a un sistema di trading tecnico trend-following (liquidità, volatilità ATR%, trendiness via Efficiency Ratio/ADX/Hurst, frequenza dei gap, sensibilità earnings, autocorrelazione) — non un segnale operativo, ma un filtro sull'universo di trading
- `pages/backtest.py` — **Backtest** del piano operativo dell'Analisi Tecnica sull'Universo Trading: motore event-driven bar-by-bar (`src/engine/`), esecuzione al next-bar-open, regola stop-first sull'ambiguità intrabar, gap pagati al prezzo reale, costi Trade Republic + FX, sizing a frazione fissa del rischio, metriche in EUR e in R con intervalli di Wilson, benchmark buy-and-hold ed entrata casuale, verdetto in linguaggio piano
- `pages/forward_paper.py` — **Forward Paper Trading**: il segnale messo alla prova in tempo reale con capitale virtuale, avanzato da un job schedulato a mercato aperto. Confronto backtest vs forward, costo del ritardo di esecuzione e curva di calibrazione della confidenza
- `src/engine/` — il motore condiviso da backtest e forward paper trading: `costs.py`, `risk.py`, `execution.py`, `ledger.py`, `signals.py`, `core.py` (bar loop), `metrics.py`, `benchmarks.py`, `runner.py`, `paper.py`, `calibration.py`
- `src/paper_store.py` — persistenza dello stato del paper trading (posizioni aperte, trade chiusi, parametri congelati), committata nel repository dal job schedulato
- `src/trading_universe.py` — **Universo Trading**: la short-list dei titoli selezionati per il trading tecnico, distinta dai Preferiti, con nota libera e TTS congelato all'inserimento (più la data) per accorgersi quando uno strumento diventa meno tradabile di quando l'avevi scelto
- `pages/analisi_fondamentale.py` — **Quality** e **Valuation** (0-100 ciascuno, assi separati) per un singolo titolo: **Portafoglio**, **Preferiti** e **Cerca**, come nell'Analisi Tecnica. Scoring assoluto calibrato per settore/archetipo operativo (nessun peer group a runtime), matrice 2x2 Quality x Valuation, archetipo Dickinson, Piotroski/Altman/Beneish, Note Critiche selettive e un modello di confidenza esplicito
- `pages/fattori.py` — valuta i titoli in Portafoglio/Preferiti sui 5 **fattori** con premio storico documentato in letteratura — Value, Momentum, Quality, Low Volatility, Size — con un punteggio **assoluto** 0-100 (scala fissa, non un confronto con altri titoli) e radar a 5 assi: è il ponte tra Analisi Fondamentale (cosa comprare) e Analisi Tecnica (quando comprarlo)
- `pages/impostazioni_alert_report.py` — attiva/disattiva gli alert email sui segnali tecnici, l'indirizzo destinatario, quali tipi di evento notificare, più le istruzioni per configurare Gmail e i secrets GitHub Actions; e il contenuto/periodicità del report automatico
- `scripts/generate_weekly_report.py` — genera il report periodico in background (lanciato ogni lunedì da GitHub Actions); non ha più una pagina dedicata di visualizzazione in-app, resta un artefatto markdown nel repository
- `scripts/run_paper_trading.py` — avanza il forward paper trading di un passo (lanciato ogni giorno feriale alle 15:00 UTC da GitHub Actions, a mercato aperto) e ricommitta lo stato nel repository
- `scripts/send_technical_alerts.py` — scansiona portafoglio + preferiti col motore di Analisi Tecnica (lanciato ogni giorno feriale da GitHub Actions) e invia un'email solo se compare un segnale nuovo rispetto all'ultima scansione (deduplica su `data/alert_state.json`)
- `scripts/verify_axis_distribution.py` — script di verifica manuale (non automatizzato da GitHub Actions): calcola la distribuzione di Quality/Valuation su un campione diversificato di titoli, per giudicare se l'asse Valuation discrimina abbastanza o si comprime in un mercato mediamente caro (v2.1, va eseguito con `PYTHONPATH=.` e accesso di rete reale)
- `scripts/verify_horizon_scaling.py` — script di verifica manuale (non automatizzato): calcola su un campione diversificato di titoli la distanza percentuale di stop/target dal prezzo per ciascun orizzonte (breve/medio/lungo), per verificare che l'ampiezza del piano operativo cresca in modo marcato e monotono passando da un orizzonte all'altro (va eseguito con `PYTHONPATH=.` e accesso di rete reale)
- `tests/` — test automatici (pytest): logica di gerarchia tra orizzonti e piano operativo su fixture sintetiche (nessuna rete richiesta), i sei criteri del Technical Tradeability Score, la persistenza dell'Universo Trading, il fatto che un salvataggio non permanente non sia mai silenzioso, il forward paper trading (barra parziale mai usata, fill al prezzo corrente, riesame della seduta di ingresso) e la calibrazione, le regole di esecuzione del motore di backtest (next-bar-open, stop-first, gap), sizing e metriche, più AppTest sulle pagine Analisi Tecnica e Backtest
- `src/persistence.py` — **persistenza dichiarata**: ogni salvataggio restituisce un esito esplicito (permanente su GitHub / solo sessione / sincronizzazione fallita) e non esiste un percorso in cui il caso non permanente sia silenzioso. Streamlit Cloud non ha disco permanente: senza il collegamento a GitHub i dati si perdono al riavvio
- `src/email_alerts.py` — costruzione e invio dell'email di alert via Gmail SMTP
- `data/transactions.csv` — **fonte di verità**: il registro di ogni movimento reale
- `data/portfolio.csv` — le posizioni attuali, calcolate automaticamente da `transactions.csv` (non modificarlo a mano)
- `data/watchlist.csv` — i tuoi titoli Preferiti, con un prezzo di riferimento opzionale (creato al primo utilizzo della pagina Analisi Tecnica; esiste nel repository solo se il collegamento a GitHub è attivo — vedi punto 7 del Setup)
- `data/trading_universe.csv` — il tuo Universo Trading: ticker, nota e TTS congelato all'inserimento (creato al primo inserimento)
- `data/paper_open_positions.csv`, `data/paper_closed_trades.csv`, `data/paper_meta.json` — lo stato del forward paper trading: posizioni virtuali aperte, registro dei trade chiusi e parametri congelati con la loro data
- `data/alert_state.json` — ultimo segnale tecnico visto per ogni titolo, usato per non rimandare la stessa email ogni giorno (creato al primo invio riuscito)
- `data/settings.json` — le tue impostazioni (allocazione ideale, benchmark, sezioni report, alert email)
- `.github/workflows/weekly_report.yml` — l'automazione del report periodico, gratuita
- `.github/workflows/technical_alerts.yml` — l'automazione degli alert email sui segnali tecnici, gratuita
- `.github/workflows/paper_trading.yml` — l'automazione del forward paper trading, gratuita
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

### 7. (NECESSARIO) Rendi permanenti le modifiche fatte dall'app

**Senza questo passaggio perdi i dati al primo riavvio dell'app.** Non è
un'ipotesi: è già successo.

Streamlit Community Cloud non ha un disco permanente. Ad ogni riavvio o
redeploy ricostruisce l'app da GitHub, e conserva **solo ciò che è nel
repository**. Tutto quello che l'app scrive mentre gira — preferiti,
universo trading, transazioni, impostazioni — vive nel container in
esecuzione e sparisce quando il container viene ricreato.

Il collegamento a GitHub è ciò che trasforma un salvataggio temporaneo in
un commit permanente. Finché non è configurato, l'app mostra un avviso
rosso in cima a ogni pagina e ogni singolo salvataggio dichiara
esplicitamente di non essere permanente. Nel frattempo, usa i pulsanti
**Backup** nelle sezioni Preferiti e Universo Trading per scaricare una
copia dei dati.

Per configurarlo: 

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
6. Salva: da ora ogni salvataggio fa anche un commit automatico su GitHub,
   e l'app te lo conferma esplicitamente ("la modifica è permanente").

Per verificare che funzioni: aggiungi un titolo ai Preferiti e controlla
che compaia `data/watchlist.csv` nel repository su GitHub. Se non compare,
il collegamento non è attivo e i dati sono ancora a rischio.

**Perché è successo (nota storica).** Fino alla versione precedente il
salvataggio verso GitHub era agganciato come `if is_configured(): push()`:
quando i secrets non erano impostati, il ramo era **vuoto e silenzioso**.
L'utente vedeva la conferma verde "aggiunto ai preferiti" e non aveva modo
di sapere che il dato sarebbe sparito al primo riavvio. Ora ogni
salvataggio passa da `src/persistence.py`, che restituisce sempre un esito
esplicito — permanente, solo-sessione o sincronizzazione fallita — e non
esiste più un percorso in cui il caso non permanente sia muto.

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
short), lo stop è ancorato al supporto/resistenza più vicino con un
buffer di 0,5×ATR, oppure a 1,5×ATR dal prezzo se non c'è un livello
abbastanza vicino; il target è il livello opposto più vicino (o
l'obiettivo di una figura di prezzo rilevata, se più vicino) oppure
2×ATR dal prezzo. La spiegazione mostrata sotto il piano (**"Stop basato
su... / Target basato su..."**) dichiara sempre il tipo di livello usato,
il suo valore numerico e l'eventuale buffer ATR applicato — mai un
aggettivo generico come "leggermente sopra/sotto" che potrebbe
contraddire la distanza reale quando include un buffer non dichiarato.
Viene mostrato anche il rapporto rischio/rendimento, con un avviso
esplicito se è sfavorevole (sotto 1,5). È uno schema costruito su regole
tecniche oggettive, non un ordine pronto da eseguire — il
dimensionamento della posizione resta una scelta tua.

I tre orizzonti temporali (breve/medio/lungo) usano parametri diversi —
ordine dello swing detector, RSI/Stocastico più corti e sensibili per il
trading di breve (lo Stocastico non è previsto sul lungo termine, dove i
dati sono settimanali), medie mobili più lunghe per l'investimento di
lungo periodo — così puoi cambiare la profondità dell'analisi (grafico,
sezioni, sintesi e piano operativo insieme) in base al tipo di decisione,
senza lasciare la pagina.

**Gerarchia dei timeframe**: fino a questa revisione i tre orizzonti
venivano calcolati **in isolamento** — l'app poteva mostrare un piano
LONG su breve e uno SHORT su medio per lo stesso titolo senza segnalare
che sono in conflitto. Ora, qualunque orizzonte tu scelga, l'app calcola
sempre anche il verdetto di trend dell'orizzonte **immediatamente
superiore** (breve → medio → lungo; sul lungo termine non esiste un
superiore) e li confronta in un nuovo indicatore, **Allineamento tra
orizzonti**, mostrato con pari evidenza accanto al Verdetto:

- **CONCORDE** — la direzione dell'orizzonte scelto coincide con quella del superiore.
- **DISCORDE** — le due direzioni sono opposte: un segnale di breve contro il trend di fondo è un *pullback/rimbalzo*, non un'inversione, finché l'orizzonte superiore non lo conferma (principio di Murphy, §0.2 della spec).
- **NEUTRO** — l'orizzonte superiore è laterale o non abbastanza direzionale da poter essere confermato o contraddetto: nessun conflitto segnalato, ma l'app chiarisce sempre che l'assenza di conflitto non equivale a una conferma.
- **N/D** — sei già sull'orizzonte più alto della catena (lungo termine): nessuna gerarchia da applicare.

Una **sintesi compatta multi-orizzonte**, sempre visibile in cima
all'analisi di ogni titolo, mostra verdetto, Directional Score e
direzione del piano operativo per tutti e tre gli orizzonti insieme, con
una riga di lettura generata dai valori reali (es. "Rimbalzo di breve
dentro un trend ribassista di medio termine"), prima ancora di scegliere
quale orizzonte approfondire nel dettaglio sotto.

Quando il piano operativo dell'orizzonte scelto va nella direzione
opposta al trend dell'orizzonte superiore, viene etichettato
**CONTRO-TREND** con un avviso esplicito sopra il piano — **il piano non
viene mai soppresso**: resta il diritto dell'utente di vederlo, dato che
ha scelto quell'orizzonte. L'avviso dichiara la natura del movimento
(rimbalzo, non inversione), il verdetto dell'orizzonte superiore
contraddetto, e — se il rapporto rischio/rendimento è anche sfavorevole —
collega esplicitamente i due segnali: uno spazio ridotto prima del
livello dominante non è una coincidenza quando si opera contro-trend.

L'**Agreement Index** resta, per costruzione, una misura di **coerenza
interna al singolo orizzonte** (accordo tra le famiglie di indicatori di
*quell'orizzonte*), mai una misura di affidabilità assoluta del segnale:
un rimbalzo contro-trend può avere Agreement alto (tutti gli indicatori
di breve concordano sul rimbalzo) senza che questo lo renda un segnale
solido nel quadro complessivo. Per questo, quando l'allineamento è
DISCORDE, la pagina affianca sempre all'Agreement Index un avviso che ne
limita la portata, e mostra una **confidenza complessiva** distinta
(Agreement Index corretto per l'allineamento tra orizzonti — stima
editoriale dichiarata, non backtestata) accanto ai due numeri originali.

## Technical Tradeability Score: come funziona

Quarta sezione della pagina **Analisi Tecnica** ("Idoneità al Trading"),
motore in `src/tradeability.py`. Non è l'analisi del singolo titolo per
decidere *quando* entrare (quello resta il compito di Directional Score +
Agreement Index nelle altre tre sezioni): è un punteggio **assoluto
0-100** che misura quanto uno strumento è **strutturalmente** adatto a un
sistema di trading tecnico trend-following — serve a decidere **cosa
mettere nell'universo di trading** e cosa testare per primo in
backtest/forward test, non se comprarlo o venderlo oggi. Si applica
all'universo Portafoglio + Preferiti, esattamente come la pagina Fattori,
e va **ricalcolato periodicamente** (il pulsante "Calcola idoneità al
trading" non gira automaticamente ad ogni apertura pagina, perché
richiede fino a 2 anni di storico per titolo).

Sei criteri, ciascuno un sub-score assoluto su scala fissa (ancore
dichiarate nel codice, mai calibrate con un backtest), combinati in una
media pesata su una finestra rolling di 252 barre daily (~1 anno di
borsa):

- **Liquidità (20%)**: controvalore medio scambiato negli ultimi 20
  giorni (ADV), convertito in EUR. Ancore: sotto 1 Mln€ = punteggio 0
  (illiquido), 10 Mln€ = 40, 100 Mln€ = 70, 1 Mld€ o oltre = 100. Per FX e
  crypto, dove il campo Volume di yfinance è spesso inaffidabile o zero,
  lo score è un valore fisso dichiarato come override (90 per le coppie
  FX, 85 per BTC/ETH, 60 per le altre crypto) — mai calcolato in silenzio
  da un volume comunque inattendibile.
- **Volatilità ATR% (15%)**: ATR di Wilder (stessa formula di
  `src/technical.py`) diviso il prezzo, su una curva **a campana**: sweet
  spot 2,5% (punteggio 100), penalizzata sia troppo poca volatilità
  (sotto 0,8%, i costi non si coprono) sia troppa (sopra il 10%, gli stop
  diventano casuali). Per le crypto la curva è spostata a destra (sweet
  spot 4-5%, nessuna penalizzazione forte fino all'8%), coerentemente con
  la loro volatilità strutturalmente più alta.
- **Trendiness (30%, il criterio più pesante)**: media di tre
  sotto-metriche indipendenti — Kaufman Efficiency Ratio (rettilineità del
  movimento), ADX medio di Wilder (forza della direzionalità) ed
  esponente di Hurst (persistenza vs mean-reversion dei rendimenti,
  stimato via la pendenza di log(deviazione standard) su log(lag), lag da
  2 a 64 barre). Un titolo strutturalmente mean-reverting (l'esponente di
  Hurst misura la persistenza dei *rendimenti*, non la semplice presenza
  di un drift: un prezzo può salire costantemente e restare comunque un
  random walk se i rendimenti non sono autocorrelati) ottiene qui un
  punteggio basso su tutte e tre le sotto-metriche.
- **Frequenza dei gap (15%)**: quota di sedute negli ultimi 60 giorni con
  un gap di apertura superiore all'ATR — i gap saltano gli stop, rendendo
  il risk management solo teorico. Nessun gap = 100, gap quasi ogni
  giorno (≥30%) = 10. Per le crypto (mercato 24/7) i gap del lunedì sono
  contati a parte come rischio weekend: lo score non può salire fino a
  100 se il lunedì gappa spesso, anche con una frequenza giornaliera
  complessiva bassa.
- **Sensibilità earnings (10%)**: ETF, indici, FX, crypto e future
  ottengono 100 per esenzione strutturale (nessuna pubblicazione utili).
  Per le azioni singole, il movimento medio assoluto di prezzo sulle
  ultime pubblicazioni (fino a 2 anni indietro, coerente con la finestra
  storica scaricata): sotto il 2% = punteggio 80, 12% o oltre = 10. La
  pagina mostra sempre la prossima data earnings nota — il **blocco
  operativo dei segnali nella finestra earnings resta una regola
  separata**, non ancora automatizzata nel modulo di paper trading.
- **Autocorrelazione (10%)**: calcolata sui rendimenti aggregati
  all'orizzonte di posizionamento (5 giorni di borsa = settimanale, non
  overlapping) invece che sui rendimenti daily grezzi, dove molti
  strumenti mostrano una leggera autocorrelazione negativa (short-term
  reversal) che sull'orizzonte settimanale spesso si inverte. Positiva e
  marcata (≥0,20) = momentum forte, punteggio 100; negativa e marcata
  (≤-0,15) = mean-reversion ostile al trend-following, punteggio 10.

**Regola di esclusione hard**: se Liquidità < 20 oppure Trendiness < 25,
lo strumento è marcato "inadatto al trading tecnico" **indipendentemente
dal totale pesato** — un buon punteggio sugli altri quattro criteri non
compensa illiquidità o assenza di trend, entrambi requisiti strutturali
per un sistema trend-following, non compensabili a livello di media.

**Bande di lettura**: 80-100 Eccellente, 65-79 Buono, 50-64 Discreto,
35-49 Debole, 0-34 Inadatto. Ogni titolo mostra la **scomposizione
completa** (i sei sub-score, mai solo il totale) e i **valori grezzi**
dietro ciascuno (ADV in EUR, ATR% medio, ER, ADX medio, esponente di
Hurst, frequenza dei gap, movimento medio su earnings, autocorrelazione)
in un pannello dedicato, per poter verificare da dove viene ogni
punteggio. Un **indicatore di confidenza** si riduce (mai in silenzio)
quando una o più metriche non sono calcolabili — ad esempio earnings non
disponibili da yfinance, o volume nullo — senza mai sostituire il dato
mancante con un valore neutro che gonfierebbe il totale.

La classe di strumento (Azione/ETF/Indice/Fondo/FX/Crypto/Future) si
rileva sempre da `quoteType` di yfinance, **mai da un elenco di ticker
scritto a mano**. La pagina distingue anche tra strumenti **tradabili su
Trade Republic** e **solo backtestabili su yfinance** (FX, future,
crypto): è una mappa indicativa dichiarata nel codice
(`BROKER_TRADABLE_ASSET_CLASSES`), non un dato ufficiale integrato via
API — da correggere se l'offerta reale del broker diverge.

L'**ambito dello screening è selezionabile** — Portafoglio, Preferiti o
Universo Trading — perché le tre liste servono a domande diverse: vagliare
quello che già possiedi, vagliare i candidati che stai seguendo, o
monitorare la short-list che hai già selezionato. Il risultato è
memorizzato **per ambito**, così cambiare lista non mostra mai la
classifica di un'altra come se fosse quella scelta.

Il Technical Tradeability Score compare anche come **badge compatto**
(punteggio, banda, eventuale esclusione hard) accanto all'analisi tecnica
del singolo titolo nelle sezioni **Preferiti** e **Universo Trading** — le
due orientate al trading. È volutamente assente in Portafoglio e Cerca,
dove aggiungerebbe il download di 2 anni di storico ad ogni apertura senza
essere il motivo per cui stai guardando quel titolo.

## Forward Paper Trading: come funziona

Stage 3 (più l'impianto dello Stage 4) di `BACKTEST AND FORWARD.pdf`.
Motore in `src/engine/paper.py`, pagina **Forward Paper Trading**.

Il backtest dice come il segnale si sarebbe comportato sul passato; il
forward lo verifica su dati che si srotolano in tempo reale, dove non
esistono senno di poi né selezione a posteriori. È la validazione più
onesta possibile senza rischiare denaro — e anche la più lenta: un sistema
daily accumula trade con lentezza, e servono settimane o mesi per un
campione utile. Due anni di forward valgono però più di un backtest
ventennale, proprio perché quel record non può essere stato contaminato.

**Non è una riscrittura.** Il modulo importa `signals`, `risk`, `costs` ed
`execution` dal motore di backtest. È l'intero motivo per cui il motore è
event-driven: se il forward avesse un codice suo, una differenza di
risultato tra i due non sarebbe attribuibile.

### Come gira

Un job di GitHub Actions (`.github/workflows/paper_trading.yml`) parte
ogni giorno feriale alle **15:00 UTC**, a mercato aperto, e ricommitta lo
stato nel repository. Avanza quindi anche quando l'app è chiusa, e lo
stato sopravvive ai riavvii di Streamlit Cloud. L'orario è scelto per
cadere dentro la seduta tutto l'anno (le 11:00 a New York con l'ora
legale, le 10:00 con quella solare) senza dover inseguire i cambi d'ora,
che il cron non sa gestire.

A differenza degli alert, che girano a mercato chiuso, qui il mercato
**deve** essere aperto: il fill avviene al prezzo corrente, e un job
serale registrerebbe entrate a prezzi ai quali non si sarebbe potuto
operare.

Opera sull'unione di **Universo Trading e Preferiti** — una lista più
ampia di quella del backtest, scelta per accumulare trade più in fretta,
al prezzo di rendere il confronto tra i due un po' meno pulito.

### Esecuzione al prezzo corrente (scelta dichiarata)

Il backtest riempie all'apertura della seduta successiva; il paper trader
riempie al **prezzo corrente** nel momento in cui il segnale scatta. È la
regola che corrisponde a come si opera davvero guardando un segnale a
mercato aperto, ma ha una conseguenza da tenere presente: una differenza
di expectancy tra backtest e paper non è più attribuibile al solo attrito
del mercato, perché cambia anche la regola di esecuzione.

Per non perdere del tutto l'attribuzione, ogni trade registra anche
**l'apertura della seduta** in cui si è entrati — il prezzo a cui il
backtest sarebbe entrato — e la pagina mostra la differenza come *costo
del ritardo di esecuzione*, in multipli di rischio. Non è un secondo
registro parallelo: è una colonna diagnostica sullo stesso trade.

### Due dettagli che decidono la correttezza

- **Il segnale usa solo barre complete.** A mercato aperto yfinance
  include la seduta in corso, il cui "close" è solo il prezzo
  dell'istante. Calcolare il segnale su quella barra darebbe un valore che
  cambia di minuto in minuto e che non corrisponde a nulla di ciò che il
  backtest ha testato. La seduta corrente viene quindi sempre esclusa.
- **La seduta di ingresso viene riesaminata quando è completa.** Entrando
  a metà giornata, quella barra non è ancora chiusa: segnarla subito come
  processata farebbe sfuggire uno stop toccato nel resto della stessa
  seduta, lasciando la posizione aperta con una perdita mai registrata.
  Quando la barra si chiude viene riesaminata con la regola conservativa
  dello stop-first — che può registrare una perdita legata a un minimo
  toccato *prima* del nostro ingresso, un eccesso di prudenza coerente col
  resto del motore.

Le uscite usano le stesse funzioni del backtest (stop-first sull'ambiguità
intrabar, gap pagati al prezzo reale) sulle barre complete, più un
controllo del prezzo corrente a ogni esecuzione per il tocco intraday.

### Calibrazione della confidenza (Stage 4)

`src/engine/calibration.py` raggruppa i trade chiusi per banda di
confidenza — le stesse bande della mappa confidenza→leva, perché calibrare
su intervalli diversi da quelli su cui si deciderebbe la leva non direbbe
nulla — e confronta la confidenza predetta col win rate realizzato. Un
sistema calibrato sta vicino alla diagonale a 45°: se i segnali "70"
vincono davvero circa il 70% delle volte, il punteggio significa qualcosa;
se vincono il 40%, è decorazione.

Ogni banda porta il proprio **intervallo di Wilson**, e una banda è
dichiarata calibrata solo se la confidenza predetta ci cade dentro. Sotto
i 20 trade una banda è marcata non interpretabile: con pochi dati
l'intervallo è così largo che quasi tutto risulterebbe calibrato, ed è il
punto in cui un diagramma di affidabilità inganna più facilmente.

Il **cancello per la leva** si apre solo con tutte e tre le condizioni:
almeno 50 trade chiusi con confidenza registrata, almeno una banda
interpretabile, e nessuna banda interpretabile fuori calibrazione. Finché
non si apre, la leva resta a 1,0× — che è anche il default del forward,
coerentemente con lo Stage 3 della specifica.

### Limiti dichiarati

Capitale virtuale e prezzi con delay tipico di 15-20 minuti: il prezzo di
ingresso registrato non è quello che avresti ottenuto al millisecondo. I
parametri vengono **congelati alla prima esecuzione** e la data resta in
`data/paper_meta.json`: ritoccarli mentre il forward gira lo
trasformerebbe nell'ennesimo backtest ottimizzato, e la data di
congelamento è ciò che permette di accorgersene a posteriori.

## Universo Trading: come funziona

Quinta sezione della pagina **Analisi Tecnica**, persistenza in
`src/trading_universe.py` (`data/trading_universe.csv`). È la
**short-list dei titoli selezionati per il trading tecnico**, ed è una
lista **distinta dai Preferiti** — non un flag sulla stessa. La
distinzione non è cosmetica:

- I **Preferiti** sono i titoli che segui per qualunque ragione:
  interesse, valutazione fondamentale, attesa di un prezzo d'ingresso.
- L'**Universo Trading** è il sottoinsieme che hai giudicato
  strutturalmente adatto a un sistema di trading tecnico, tipicamente
  dopo averlo vagliato col Technical Tradeability Score.

Un titolo può stare in una lista, nell'altra, in entrambe o in nessuna:
un'azienda eccellente che gappa di continuo resta un buon Preferito e un
pessimo candidato di trading; un ETF noioso da seguire ma liquidissimo e
pulito nei trend merita l'Universo Trading senza essere un Preferito.

Il flusso previsto è: **vagli** i candidati nella tab Idoneità al Trading
(ambito Portafoglio o Preferiti), **promuovi** i migliori con il pulsante
di inserimento nel dettaglio, poi **rilanci** la classifica sull'ambito
Universo Trading per monitorarla nel tempo. Puoi anche inserire un titolo
direttamente dalla tab Universo Trading: il punteggio viene calcolato e
congelato in quel momento.

Ogni riga conserva una **nota libera** (perché l'hai inserito) e il
**TTS congelato all'inserimento con la data in cui è stato congelato**.
La data è indispensabile perché il punteggio storico sia interpretabile:
senza sapere a quando risale, confrontarlo con quello attuale non
direbbe nulla. Quando analizzi un titolo dell'universo, la pagina mostra
punteggio congelato e punteggio attuale affiancati con la differenza, e
**avvisa esplicitamente se la tradabilità è peggiorata di 10 punti o
più** dall'inserimento — il caso che questo confronto esiste per far
emergere, dato che la tradabilità di uno strumento cambia nel tempo.
Aggiornare la nota di un titolo **non** azzera il punteggio congelato:
si sovrascrive solo ricalcolandolo esplicitamente.

## Backtest: come funziona

La pagina **Backtest** risponde a una sola domanda: *il piano operativo
che l'Analisi Tecnica mi mostra ha un edge reale?* Motore in
`src/engine/`, costruito secondo `BACKTEST AND FORWARD.pdf` (Stage 0
architettura + Stage 1 backtest in-sample). Non testa una versione
semplificata del segnale: chiama `technical_snapshot` + `trade_plan`,
cioè **esattamente** ciò che vedi a schermo. Gira sull'**Universo
Trading**, la lista che hai selezionato per il trading.

Il suo compito non è produrre una bella curva di equity, ma dirti la
verità su se il segnale abbia un edge che sopravvive ai costi ed è
statisticamente sostenuto. È progettato per **smentire** il segnale.

### Architettura event-driven (e perché non vettoriale)

Un backtest vettoriale calcola i segnali su tutto l'array di prezzi in una
passata: è veloce, ma non modella stop/target, path-dependence ed
esecuzione, e invita il look-ahead bias. Il motore qui è **event-driven**:
processa una barra alla volta come se arrivasse dal vivo. Il vantaggio
decisivo è il **riuso del codice** — lo stesso motore guiderà il forward
paper trader, ed è l'unico modo perché una divergenza tra backtest e
paper sia attribuibile all'attrito reale del mercato invece che a
differenze di implementazione.

Ogni barra esegue sempre gli stessi passi nello stesso ordine: esegue gli
ordini accodati ieri all'apertura di oggi, aggiorna le posizioni aperte e
verifica stop/target, valuta il segnale sul close, accoda un ordine per
domani, valorizza l'equity.

### Le tre regole da cui dipende l'onestà del risultato

- **Segnale sul close del bar t, esecuzione all'apertura del bar t+1.**
  Eseguire sullo stesso close usato per generare il segnale è il bug di
  look-ahead classico, quello che fabbrica profitti inesistenti. Il
  rischio iniziale (1R) si ricalcola sull'ingresso **effettivo**, non su
  quello pianificato.
- **Ambiguità intrabar risolta con stop-first.** Con barre daily non si
  può sapere se sia arrivato prima il massimo o il minimo: se il range di
  una barra contiene sia lo stop sia il target, si assume che sia stato
  colpito lo **stop**, l'esito peggiore.
- **I gap si pagano al prezzo reale.** Se la barra apre già oltre lo stop,
  il fill avviene all'apertura — peggiore dello stop teorico — perché quel
  gap è slippage vero. Il risultato è che un trade può chiudere a −2R
  invece che a −1R: è la coda sinistra reale, ed è precisamente ciò che la
  leva amplificherebbe.

### Costi

Applicati a livello di singolo trade, con curva lorda e netta sempre
affiancate. Tre componenti: commissione Trade Republic (1 EUR per ordine
Best Price, 2 EUR Direct Price), costo di conversione valutaria sugli
strumenti non in EUR, e spread/slippage.

Il costo FX è la voce genuinamente opaca: dopo il divieto UE di Payment
for Order Flow (30 giugno 2026) Trade Republic esegue sulla propria
infrastruttura e il costo è **incorporato nello spread**, non pubblicato.
Le stime indipendenti sono in conflitto tra loro. Il default qui è
**0,5% per gamba** (≈1% sul round trip): una stima prudenziale dichiarata,
non un dato ufficiale, ed è un parametro modificabile in pagina. Non si
applica agli ETF UCITS che quotano in EUR. Se la valuta di uno strumento
è ignota si assume il caso peggiore (costo applicato): un costo
dimenticato è il modo classico in cui un backtest si lusinga da solo.

### Dimensionamento e leva

Sizing a **frazione fissa del rischio**: `size = (equity × risk%) /
(entry − stop)`, con default 0,75% e tetto all'1%. Ogni perdita piena vale
quindi sempre la stessa frazione dell'equity, e la size si adatta
automaticamente alla volatilità. Tre cap rigidi: rischio per trade ≤1,5%,
esposizione lorda aggregata ≤1,5× equity, somma dei rischi aperti ≤5%
dell'equity — perché un sistema che rispetta l'1% per trade ma tiene dieci
posizioni aperte sta rischiando il 10%, non l'1%.

La **leva da confidenza nasce disattivata** e tutto gira a 1,0×. La mappa
esiste (sotto 50 non si opera, 50-69 → 1,0×, 70-84 → 1,25×, 85-100 →
1,5× con tetto rigido) ma si sblocca solo dopo che la calibrazione
empirica avrà mostrato che i segnali "85 di confidenza" vincono davvero
circa l'85% delle volte. Il motivo è che la confidenza è una *stima*, e
l'errore di stima è esattamente ciò che la leva magnifica; per giunta i
segnali ad alta confidenza, quando falliscono, tendono a farlo nei gap e
nei cambi di regime, cioè proprio dove vive la coda sinistra. Nota che
Trade Republic è spot-only: qui la "leva" è un costrutto di modello che
nel reale mappa sulla concentrazione di capitale, che amplifica i
drawdown allo stesso modo.

### Metriche e benchmark

Ogni trade è tracciato **sia in euro sia in R** (multipli del rischio
iniziale): gli R dicono se il *segnale* ha un edge, gli euro dicono cosa
gli hanno fatto sizing e leva. Metriche calcolate: expectancy in R e in
EUR, win rate con **intervallo di Wilson al 95%**, profit factor, Sharpe,
Sortino, max drawdown, Calmar, durata media, MAE/MFE.

Due benchmark **obbligatori**, mostrati accanto a ogni curva:

- **Buy-and-hold** degli stessi strumenti: il timing ha aggiunto qualcosa
  rispetto a restare semplicemente investito?
- **Entrata casuale** in Monte Carlo, con la stessa frequenza di trade e
  identiche regole di stop/target/sizing: l'edge viene dal *segnale* o
  soltanto dalle uscite e dal money management? Nell'esperimento di Tom
  Basso riportato da Van Tharp, entrate a testa o croce con uno stop a
  3×ATR e rischio all'1% hanno fatto soldi il 100% delle volte con un win
  rate del 38%. Un segnale si guadagna il posto solo se batte il caso a
  parità di tutto il resto.

### Guardrail anti-autoinganno cablati nella pagina

Non sono opzioni: sono il motivo per cui la pagina esiste.

1. Rendimento lordo sempre accanto al netto, con il costo esplicitato.
2. In-sample e out-of-sample affiancati, con la percentuale di expectancy
   trattenuta fuori campione.
3. Nessun win rate senza il suo intervallo di Wilson e il numero di trade.
4. Metriche marcate come non interpretabili sotto i 50 trade, e come non
   ancora affidabili sotto i 100 (idealmente ne servono 200+).
5. Entrambi i benchmark accanto alla curva di equity.
6. Conteggio delle configurazioni provate in sessione, con avviso oltre
   le 3: ogni tentativo in più gonfia per caso il risultato migliore.
7. Expectancy in R in evidenza, perché è la metrica che la leva non può
   mascherare.
8. **Verdetto in linguaggio piano**: edge *stabilito*, *marginale*, *non
   provato* o *assente*, con la motivazione esplicita.

L'out-of-sample è **disattivato di default**, coerentemente con lo Stage 1
della specifica: va guardato una volta sola, dopo aver congelato i
parametri. Rieseguire il backtest cambiando parametri finché l'OOS non
migliora lo converte silenziosamente in in-sample e garantisce
overfitting. Se l'out-of-sample risulta **migliore** dell'in-sample la
pagina lo segnala come sospetto di contaminazione, non come trionfo: il
decadimento fuori campione è la norma (i rendimenti calano tipicamente di
un quarto, lo Sharpe di circa un terzo).

### Limiti dichiarati

Orizzonti supportati: solo quelli su barre daily (`breve`, `medio`). Il
lungo termine usa barre settimanali e richiederebbe un ricampionamento
dedicato: è escluso invece di essere approssimato con dati daily, che
darebbe risultati diversi da quelli mostrati nell'app. I dati vengono da
yfinance, di qualità retail (attenzione a rettifiche per split/dividendi e
barre mancanti). Le posizioni ancora aperte all'ultimo bar vengono chiuse
al close: escluderle renderebbe i risultati sistematicamente migliori del
reale, perché le posizioni in perdita tendono a restare aperte più a lungo.

Il **forward paper trading** (Stage 3) e la **calibrazione della
confidenza** (Stage 4) non sono ancora implementati: il motore è però già
strutturato perché il paper trader sia un secondo wrapper sottile sopra
gli stessi moduli.

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

### Test automatici

```bash
pip install pytest
PYTHONPATH=. python -m pytest tests/
```

`tests/test_technical_hierarchy.py` copre la logica di gerarchia tra
orizzonti (`classify_horizon_alignment`, `plan_alignment_warning`,
`multi_horizon_summary`) e il piano operativo (`trade_plan`) su
dizionari/serie storiche sintetiche — nessun accesso di rete richiesto.
`tests/test_analisi_tecnica_page.py` esegue un AppTest sulla pagina
Streamlit con dati storici sintetici (via monkeypatch di
`src/data_provider.py`) per escludere eccezioni a runtime, incluso il
calcolo del Technical Tradeability Score nella tab "Idoneità al Trading".
`tests/test_tradeability.py` copre i sei criteri del Technical
Tradeability Score in isolamento (liquidità, volatilità, trendiness,
gap, earnings, autocorrelazione) su serie storiche sintetiche con
proprietà statistiche note — un processo Ornstein-Uhlenbeck
mean-reverting per verificare che Trendiness sia basso (Hurst < 0,5),
rendimenti AR(1) con autocorrelazione positiva per verificare che
Trendiness e Autocorrelazione siano alti — oltre alla regola di
esclusione hard, agli override FX/crypto e alla robustezza del report
quando un titolo nell'universo fallisce.
`tests/test_trading_universe.py` copre la persistenza dell'Universo
Trading, in particolare che aggiornare la nota di un titolo non cancelli
il TTS congelato e che un CSV scritto da una versione precedente (solo
`ticker`) si carichi senza errori.
`tests/test_engine_execution.py` copre le tre regole di esecuzione da cui
dipende l'onestà del backtest (fill al next-bar-open, stop-first
sull'ambiguità intrabar, gap pagati al prezzo reale) su barre costruite a
mano con esito calcolabile a mente. `tests/test_engine_risk_metrics.py`
copre sizing, cap di rischio aggregati, modello di costo, intervalli di
Wilson e verdetto. `tests/test_engine_integration.py` esegue la pipeline
completa con il segnale REALE (`trade_plan`) su serie sintetiche a tre
regimi, senza rete. `tests/test_backtest_page.py` verifica che i guardrail
anti-autoinganno siano effettivamente presenti in pagina, non solo che la
pagina non vada in eccezione.
`tests/test_paper_trading.py` copre il forward: che la barra parziale
della seduta in corso non venga mai usata per il segnale, il fill al
prezzo corrente con registrazione dell'apertura di riferimento, e la
regressione del bug per cui la seduta di ingresso non veniva riesaminata
una volta completa. `tests/test_calibration.py` verifica soprattutto che
il cancello della leva NON si apra quando non deve (campione sottile,
bande sotto soglia, confidenza che non corrisponde al risultato).

I test non scrivono mai dentro `data/`, che è versionata: l'Universo
Trading viene rediretto su una cartella temporanea, perché un file di
test lasciato lì finirebbe in un commit e comparirebbe come voce
fantasma nell'app.

Gli script `scripts/verify_axis_distribution.py` e
`scripts/verify_horizon_scaling.py` sono verifiche manuali distinte, non
automatizzate da GitHub Actions: richiedono accesso di rete reale a
Yahoo Finance (yfinance) e vanno eseguiti a mano quando serve verificare
la calibrazione su dati di mercato veri.

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
- Allo stesso modo, la soglia di direzionalità usata per l'Allineamento
  tra orizzonti (`|D| < 0,20` sull'orizzonte superiore), i pesi della
  confidenza complessiva (CONCORDE 1,0 / NEUTRO 0,7 / DISCORDE 0,4) e i
  moltiplicatori ATR del piano operativo (buffer 0,5×, stop 1,5×, target
  2×, "livello vicino" entro 3×ATR) sono costanti editoriali dichiarate
  esplicitamente nel codice (`src/technical.py`), non backtestate: buoni
  punti di partenza ragionevoli, non soglie ottimizzate su dati storici.
  `scripts/verify_horizon_scaling.py` verifica solo che lo *scaling* per
  orizzonte funzioni (le ampiezze crescono da breve a lungo), non che i
  valori assoluti siano ottimali.
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
