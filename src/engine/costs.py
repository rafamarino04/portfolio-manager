"""
Modello di costo — src/engine/costs.py

I risultati al lordo dei costi sono attivamente fuorvianti: a questa
dimensione di conto i costi sono decisivi, e una strategia che mostra il
15% lordo annuo può collassare a quasi zero una volta pagati. Il motore
applica i costi **a livello di singolo trade** e riporta sempre sia la
curva lorda sia quella netta, così il peso del costo è esplicito invece
che nascosto nel risultato finale.

Tre componenti, per ogni round trip:

1. **Commissione per ordine.** Trade Republic: 1 EUR a ordine nel modello
   "Best Price" (default), 2 EUR in "Direct Price" (scelta della venue,
   usata per operare direttamente su NYSE/Nasdaq in USD). Un round trip
   completo costa quindi 2 EUR (Best Price) o 4 EUR (Direct Price).

2. **Conversione valutaria (solo strumenti in USD).** È la voce
   genuinamente opaca. Dopo il divieto UE di Payment for Order Flow (30
   giugno 2026) Trade Republic esegue sulla propria infrastruttura e il
   costo FX è **incorporato nello spread di esecuzione**, non pubblicato
   come percentuale. Le stime indipendenti sono in conflitto tra loro
   (0,10-0,25%, 0,5-1%, un 0,25%/0,15% a scaglioni che però precede il
   cambio di luglio 2026, uno 0,14% usato da Interactive Brokers come
   propria assunzione di modello). Nessuna fonte fornisce una percentuale
   attualmente pubblicata da TR. Qui si assume **0,5% per gamba in USD**
   come default prudenziale dichiarato (≈1% sul round trip), esposto come
   parametro modificabile: è una stima difendibile del caso peggiore, non
   un dato ufficiale.

   Nota importante: la maggior parte degli ETF UCITS più diffusi (IWDA,
   VWCE, EUNL, CSPX, SXR8) quota in EUR su Trade Republic, quindi il
   costo FX **non si applica** a loro. Va applicato solo agli strumenti
   denominati in USD.

3. **Spread bid-ask e slippage.** Anche pagate commissione e FX, si
   attraversa comunque lo spread: si compra all'ask e si vende al bid. Si
   modella almeno metà spread per lato. Il trend-following è
   particolarmente esposto allo slippage perché compra strumenti già in
   movimento nella direzione del trade.
"""
from __future__ import annotations

from dataclasses import dataclass

# Commissioni Trade Republic per singolo ordine (EUR).
TR_BEST_PRICE_FEE_EUR = 1.0
TR_DIRECT_PRICE_FEE_EUR = 2.0

# Costo FX per gamba su strumenti in USD, in percentuale del controvalore.
# Default prudenziale: vedi il punto 2 del docstring del modulo.
DEFAULT_FX_COST_PCT_PER_LEG = 0.5

# Mezzo spread + slippage per lato, in punti base del controvalore.
# Default per mega-cap ed ETF molto liquidi; da allargare per strumenti
# meno liquidi (il Technical Tradeability Score, src/tradeability.py,
# serve anche a sapere quali sono).
DEFAULT_SLIPPAGE_BPS_PER_SIDE = 5.0


@dataclass
class CostModel:
    """Tutti i parametri di costo in un unico oggetto passato al motore,
    così un backtest dichiara sempre con quali costi è stato prodotto
    invece di ereditarli da costanti sparse."""

    order_fee_eur: float = TR_BEST_PRICE_FEE_EUR
    fx_cost_pct_per_leg: float = DEFAULT_FX_COST_PCT_PER_LEG
    slippage_bps_per_side: float = DEFAULT_SLIPPAGE_BPS_PER_SIDE
    # La valuta dello strumento decide se il costo FX si applica: EUR no,
    # USD sì. Non è un flag manuale, arriva da yfinance (`currency`).
    base_currency: str = "EUR"

    def applies_fx(self, instrument_currency: str | None) -> bool:
        if not instrument_currency:
            # Valuta sconosciuta: si assume il caso peggiore (costo FX
            # applicato) invece di ignorarlo silenziosamente. Un costo
            # dimenticato è esattamente il modo in cui un backtest si
            # lusinga da solo.
            return True
        return instrument_currency.upper() != self.base_currency.upper()

    def entry_cost_eur(self, notional_eur: float, instrument_currency: str | None) -> float:
        """Costo di una gamba di ingresso: commissione fissa + FX (se
        applicabile) + mezzo spread/slippage."""
        return self._leg_cost_eur(notional_eur, instrument_currency)

    def exit_cost_eur(self, notional_eur: float, instrument_currency: str | None) -> float:
        """Costo della gamba di uscita, con la stessa struttura di quella
        di ingresso ma calcolato sul controvalore effettivo di uscita (che
        differisce da quello di ingresso quanto il trade ha guadagnato o
        perso)."""
        return self._leg_cost_eur(notional_eur, instrument_currency)

    def _leg_cost_eur(self, notional_eur: float, instrument_currency: str | None) -> float:
        notional = abs(notional_eur)
        cost = self.order_fee_eur
        if self.applies_fx(instrument_currency):
            cost += notional * self.fx_cost_pct_per_leg / 100.0
        cost += notional * self.slippage_bps_per_side / 10_000.0
        return cost

    def round_trip_cost_eur(self, entry_notional_eur: float, exit_notional_eur: float,
                             instrument_currency: str | None) -> float:
        return (self.entry_cost_eur(entry_notional_eur, instrument_currency)
                + self.exit_cost_eur(exit_notional_eur, instrument_currency))

    def describe(self) -> str:
        """Descrizione testuale dei costi applicati, da mostrare accanto
        ai risultati: un backtest netto senza dire *di che cosa* è netto
        non è verificabile."""
        fx = (f"{self.fx_cost_pct_per_leg:g}% per gamba sugli strumenti non {self.base_currency}"
              if self.fx_cost_pct_per_leg else "nessun costo FX")
        return (f"{self.order_fee_eur:g} EUR per ordine · {fx} · "
                f"{self.slippage_bps_per_side:g} bp di spread/slippage per lato")
