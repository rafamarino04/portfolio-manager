# Report generati su dati di esempio

Contenuto: i nove report settimanali prodotti automaticamente fra il
20 luglio e il 14 settembre 2026, piu' lo storico `history.csv` che li
alimentava.

Non descrivono nessun portafoglio reale. Sono stati generati mentre
`data/transactions.csv` conteneva ancora i movimenti di esempio
distribuiti col progetto, e riportano un patrimonio inventato di circa
173.000 EUR con un confronto a benchmark fra due finzioni.

Sono conservati invece che cancellati perche' documentano un difetto di
processo che vale la pena ricordare: l'automazione girava correttamente,
produceva output ben formattati, e per questo nessuno si accorgeva che
non significavano niente. Un output falso ma indistinguibile da uno vero
e' peggio di un output mancante.

Dal 14/09/2026 `scripts/generate_weekly_report.py` si rifiuta di
generare finche' il registro contiene solo movimenti di esempio
(`src/example_data.py`). Quando caricherai i movimenti reali, lo storico
ripartira' da zero in `reports/history.csv`.
