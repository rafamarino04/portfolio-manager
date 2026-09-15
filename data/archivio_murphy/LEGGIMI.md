# Forward paper trading sul segnale Murphy (28/07 - 14/09/2026)

Stato finale del forward prima della rimozione di tutte le strategie:
22 trade chiusi, 4 posizioni ancora aperte, equity da 10.000 a 9.145 EUR.

## Perche' e' archiviato e non proseguito

La strategia che ha prodotto questi trade non esiste piu'. Continuare ad
accumulare operazioni sulla nuova strategia dentro lo stesso registro
mescolerebbe due sistemi diversi in un'unica statistica, e renderebbe
impossibile dire a quale dei due si riferisca un'expectancy.

Le 4 posizioni aperte sono abbandonate insieme al resto. Tre erano short
su titoli americani: operazioni che su Trade Republic, spot-only, non
sarebbero state eseguibili in primo luogo.

## Cosa dicono questi numeri

E' il materiale su cui e' stata fatta la diagnosi, e vale la pena
conservarlo:

- somma dei risultati **lordi +2,94R**, somma dei **netti -8,79R** (sui
  primi 21 trade). Il segnale non era la voce dominante: lo erano i costi;
- costo mediano **0,19R per trade**, medio 0,56R;
- durata mediana di un trade: **3 sedute**; stop mediano all'**1,6%** dal
  prezzo. Con `costo_in_R = costo% / stop%`, quelle due cifre insieme
  rendono il sistema non finanziabile a prescindere dalla qualita' del
  segnale;
- 11 trade in dollari hanno pagato 222 EUR di costi su 289 EUR totali;
- tre trade aperti con un rischio residuo di 0,59 / 1,65 / 2,05 EUR contro
  i ~70 EUR nominali, per il difetto di troncamento della size corretto il
  14/09/2026. Uno di questi ha trasformato un -1,0R lordo in -5,09R netto.

## Difetto di processo, non solo di strategia

Fino al 15/09/2026 `src/engine/paper.py` chiamava il generatore di segnali
direttamente, senza passare dal registro delle strategie. Il forward ha
quindi girato su Murphy per sei settimane mentre la pagina di backtest
confrontava quattro strategie diverse, e la strategia in uso non era
scritta da nessuna parte nell'interfaccia. Ora compare fra i parametri
congelati, proprio perche' una cosa del genere non passi inosservata.
