"""
Riconoscimento dei dati di esempio — src/example_data.py

**Perché questo modulo esiste.** Il progetto è stato distribuito con un
portafoglio di esempio (AAPL, ENI.MI, SWDA.MI, un BTP segnaposto, un
fondo e un conto deposito fittizi) perché l'app fosse navigabile al primo
avvio. Quelle righe non sono mai state sostituite, ma le automazioni sono
partite lo stesso: fra il 20 luglio e il 7 settembre 2026 il job
settimanale ha prodotto otto report su un patrimonio inventato di
173.336 €, compresa la frase "portafoglio +5,30% vs iShares Core MSCI
World +66,59%" — il confronto fra due finzioni, presentato con la stessa
autorevolezza grafica che avrebbe un dato vero.

Un report sbagliato è meno dannoso di un report **indistinguibile da uno
giusto**. Da qui la regola: nessun artefatto automatico (report, alert,
paper trading) viene prodotto finché i dati sono ancora quelli di
esempio. Non è un avviso da leggere, è un blocco.

**Come si riconosce.** Per impronta dei movimenti, non per il testo della
nota: la nota si può cancellare lasciando intatti i dati finti. Se ogni
movimento presente è uno di quelli distribuiti col progetto, il file è
ancora quello di esempio. Basta aggiungere o modificare un movimento vero
perché il blocco cada da solo, senza dover toccare nessuna impostazione.
"""
from __future__ import annotations

import csv
import os

# Impronta dei movimenti distribuiti col progetto: (data, ticker, tipo).
# Non si confronta il file intero perché prezzi e quantità potrebbero
# essere stati ritoccati senza che il portafoglio diventi reale.
EXAMPLE_MOVEMENTS = {
    ("2024-03-15", "AAPL", "Acquisto"),
    ("2023-11-02", "ENI.MI", "Acquisto"),
    ("2023-06-10", "SWDA.MI", "Acquisto"),
    ("2024-01-10", "BTP-2030", "Acquisto"),
    ("2024-02-01", "FONDO BILANCIATO XYZ", "Acquisto"),
    ("2024-01-01", "CONTO DEPOSITO ABC", "Acquisto"),
}

BLOCK_MESSAGE = (
    "I movimenti in data/transactions.csv sono ancora quelli di esempio distribuiti col "
    "progetto. Le automazioni restano ferme finché non registri i tuoi movimenti reali "
    "dal Registro Transazioni: un report generato su dati inventati è indistinguibile da "
    "uno vero, ed è peggio che non averlo."
)


def _normalize(value: str | None) -> str:
    return (value or "").strip().upper()


def transactions_are_example(path: str) -> bool:
    """True se il registro contiene solo movimenti di esempio.

    Un file mancante o vuoto conta come "di esempio": non c'è nulla di
    reale da cui produrre un report, quindi il blocco vale comunque.
    """
    if not os.path.exists(path):
        return True
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if any((v or "").strip() for v in r.values())]
    except Exception:
        # File illeggibile: non si può dimostrare che sia reale, quindi
        # si resta dalla parte prudente e si blocca.
        return True

    if not rows:
        return True

    for row in rows:
        movement = (
            (row.get("date") or "").strip(),
            _normalize(row.get("ticker")),
            (row.get("type") or "").strip().capitalize(),
        )
        if movement not in EXAMPLE_MOVEMENTS:
            return False
    return True
