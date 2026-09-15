"""Test del blocco sui dati di esempio (src/example_data.py).

Il difetto che questo modulo previene non e' un crash: e' un'automazione
che gira correttamente e produce output ben formattati e completamente
falsi. Fra il 20/07 e il 07/09/2026 il job settimanale ha prodotto otto
report su un portafoglio inventato, e nessun test falliva.

La proprieta' da verificare non e' "riconosce il file di esempio" ma
"basta un movimento vero perche' il blocco cada da solo": un blocco che
richiedesse di ricordarsi di disattivarlo sarebbe lo stesso difetto in
un'altra forma.
"""
import os
import subprocess
import sys

from src import example_data as ed

INTESTAZIONE = "date,ticker,type,quantity,price,amount,fees,currency,category,manual_price,note\n"
RIGHE_ESEMPIO = [
    "2024-03-15,AAPL,Acquisto,10,180.50,,0,USD,Azione,,Esempio - sostituisci con i tuoi movimenti reali\n",
    "2023-11-02,ENI.MI,Acquisto,150,13.20,,0,EUR,Azione,,Esempio - Borsa Italiana usa suffisso .MI\n",
    "2023-06-10,SWDA.MI,Acquisto,80,85.40,,0,EUR,ETF,,iShares Core MSCI World - esempio ETF\n",
    "2024-01-10,BTP-2030,Acquisto,1000,98.50,,0,EUR,Obbligazione,99.20,Esempio obbligazione\n",
    "2024-02-01,Fondo Bilanciato XYZ,Acquisto,500,105.00,,0,EUR,Fondo/SICAV,108.50,Esempio fondo\n",
    "2024-01-01,Conto Deposito ABC,Acquisto,3000,1,,0,EUR,Liquidità,,Esempio liquidità\n",
]


def _scrivi(tmp_path, righe, nome="transactions.csv"):
    path = tmp_path / nome
    path.write_text(INTESTAZIONE + "".join(righe), encoding="utf-8")
    return str(path)


def test_il_file_distribuito_col_progetto_e_riconosciuto(tmp_path):
    assert ed.transactions_are_example(_scrivi(tmp_path, RIGHE_ESEMPIO))


def test_un_solo_movimento_vero_sblocca(tmp_path):
    """La proprieta' che conta: non serve ricordarsi di disattivare nulla."""
    righe = RIGHE_ESEMPIO + [
        "2026-09-14,VWCE.DE,Acquisto,12,128.40,,1,EUR,ETF,,primo acquisto vero\n"
    ]
    assert not ed.transactions_are_example(_scrivi(tmp_path, righe))


def test_cancellare_la_nota_non_basta_a_far_sembrare_reali_i_dati(tmp_path):
    """Il riconoscimento e' per impronta del movimento, non per il testo
    della nota: altrimenti basterebbe svuotare una colonna."""
    righe = [r.rsplit(",", 1)[0] + ",\n" for r in RIGHE_ESEMPIO]
    assert ed.transactions_are_example(_scrivi(tmp_path, righe))


def test_sottoinsieme_dell_esempio_resta_esempio(tmp_path):
    """Cancellare qualche riga di esempio non rende reale il resto."""
    assert ed.transactions_are_example(_scrivi(tmp_path, RIGHE_ESEMPIO[:2]))


def test_file_vuoto_o_mancante_conta_come_esempio(tmp_path):
    """Non c'e' nulla di reale da cui produrre un report: si blocca lo
    stesso, invece di generare un report su un portafoglio vuoto."""
    assert ed.transactions_are_example(_scrivi(tmp_path, []))
    assert ed.transactions_are_example(str(tmp_path / "inesistente.csv"))


def test_file_illeggibile_blocca_invece_di_passare(tmp_path):
    """In dubbio si sta dalla parte prudente."""
    path = tmp_path / "rotto.csv"
    path.write_bytes(b"\xff\xfe\x00rotto")
    assert ed.transactions_are_example(str(path))


def test_lo_script_del_report_si_rifiuta_di_girare_sui_dati_di_esempio():
    """Test di integrazione sul comportamento vero: lo script non deve
    scrivere nessun file. Non richiede rete perche' si ferma prima di
    scaricare i prezzi."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    prima = set(os.listdir(os.path.join(base, "reports")))

    esito = subprocess.run(
        [sys.executable, "scripts/generate_weekly_report.py"],
        cwd=base, capture_output=True, text=True, timeout=120,
        env={**os.environ, "PYTHONPATH": base},
    )

    assert "quelli di esempio" in esito.stdout
    assert set(os.listdir(os.path.join(base, "reports"))) == prima
