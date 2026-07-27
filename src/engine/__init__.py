"""
Motore event-driven per backtest e forward paper trading.

Costruito secondo BACKTEST AND FORWARD.pdf (Stage 0 della specifica). Il
principio architetturale che regge tutto il resto: **un solo motore**, di
cui backtest e paper trader sono due wrapper sottili. Se il forward
trader usasse un codice diverso dal backtest, qualunque divergenza tra i
due risultati sarebbe inattribuibile — non sapresti se è attrito reale
del mercato o una differenza di implementazione.

Moduli (separazione richiesta dalla spec):
  costs.py     — modello di costo (commissioni Trade Republic, FX, spread)
  risk.py      — sizing a frazione fissa del rischio, ATR, confidenza→leva
  execution.py — simulatore di esecuzione: fill al next-bar-open, regola
                 stop-first intrabar, gestione dei gap
  ledger.py    — posizioni aperte, equity, trade chiusi in EUR e in R
  signals.py   — generatore di segnali (wrapper point-in-time su trade_plan)
  core.py      — il bar loop cronologico che orchestra i moduli sopra
  metrics.py   — metriche di performance con intervalli di Wilson
  benchmarks.py— buy-and-hold e random-entry Monte Carlo

Le tre regole di esecuzione da cui dipende l'onestà di tutto il motore,
enunciate qui una volta sola perché sono il punto in cui un backtest
mente a se stesso:

  1. **Segnale sul close del bar t, fill all'open del bar t+1.** Eseguire
     sullo stesso close usato per generare il segnale è il classico bug
     di look-ahead che fabbrica profitti inesistenti.
  2. **Ambiguità intrabar risolta in modo conservativo (stop-first).** Con
     barre daily non si può sapere se il massimo o il minimo sia arrivato
     prima: se il range di un bar contiene sia lo stop sia il target, si
     assume che sia stato colpito lo stop (l'esito peggiore).
  3. **I gap si pagano.** Se il bar apre oltre lo stop (o il target), il
     fill avviene all'open, non al livello teorico: quel gap è slippage
     reale e non va "riempito" silenziosamente al prezzo che avresti
     voluto.
"""
