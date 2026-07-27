"""
Portafoglio e registro dei trade — src/engine/ledger.py

Tiene le posizioni aperte, l'equity e lo storico dei trade chiusi. Ogni
trade è registrato **sia in euro sia in R**, e sia al lordo sia al netto
dei costi: sono quattro numeri diversi che rispondono a domande diverse e
confonderli è il modo più comune di trarre conclusioni sbagliate.

  - **R al lordo** dice se il *segnale* ha un edge.
  - **R al netto** dice se quell'edge sopravvive ai costi.
  - **Euro** dicono cosa hanno fatto sizing e leva a quell'edge.

Tenere solo gli euro rende impossibile distinguere "il segnale funziona
ma la leva mi ha ammazzato" da "il segnale non funziona"; tenere solo gli
R nasconde che una size sbagliata può rovinare un segnale buono.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class OpenPosition:
    symbol: str
    direction: str            # "long" | "short"
    entry_date: date
    entry_price: float
    stop: float
    target: float
    size: float
    risk_per_unit: float
    initial_risk_eur: float   # 1R in euro
    entry_cost_eur: float
    confidence: float | None
    leverage: float
    currency: str | None
    signal_date: date         # il close su cui è nato il segnale (≠ entry_date)
    mae_r: float = 0.0
    mfe_r: float = 0.0
    bars_held: int = 0

    @property
    def notional_eur(self) -> float:
        return abs(self.size * self.entry_price)


@dataclass
class ClosedTrade:
    symbol: str
    direction: str
    signal_date: date
    entry_date: date
    entry_price: float
    exit_date: date
    exit_price: float
    exit_reason: str
    size: float
    risk_per_unit: float
    initial_risk_eur: float
    confidence: float | None
    leverage: float
    gross_pnl_eur: float
    costs_eur: float
    net_pnl_eur: float
    gross_r: float
    net_r: float
    mae_r: float
    mfe_r: float
    bars_held: int
    gapped_exit: bool

    @property
    def is_winner(self) -> bool:
        """Vincente si giudica sul **netto**: un trade che guadagna al
        lordo e perde dopo i costi non è una vittoria."""
        return self.net_pnl_eur > 0


@dataclass
class Ledger:
    initial_equity_eur: float
    equity_eur: float = 0.0
    open_positions: dict[str, OpenPosition] = field(default_factory=dict)
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    # Serie temporale dell'equity: (data, equity netta, equity lorda).
    equity_curve: list[tuple[date, float, float]] = field(default_factory=list)
    cumulative_costs_eur: float = 0.0

    def __post_init__(self):
        if not self.equity_eur:
            self.equity_eur = self.initial_equity_eur

    # -- stato aggregato, usato dai cap di rischio in risk.py ------------

    def open_gross_exposure_eur(self) -> float:
        return sum(p.notional_eur for p in self.open_positions.values())

    def open_risk_eur(self) -> float:
        """Somma dei −1R aperti: quanto si perderebbe se tutte le
        posizioni aperte venissero stoppate."""
        return sum(p.initial_risk_eur for p in self.open_positions.values())

    def has_position(self, symbol: str) -> bool:
        return symbol in self.open_positions

    # -- apertura e chiusura --------------------------------------------

    def open_position(self, position: OpenPosition) -> None:
        self.open_positions[position.symbol] = position
        # Il costo di ingresso è pagato subito: l'equity lo riflette
        # immediatamente, non solo alla chiusura del trade.
        self.equity_eur -= position.entry_cost_eur
        self.cumulative_costs_eur += position.entry_cost_eur

    def close_position(self, symbol: str, exit_date: date, exit_price: float,
                        exit_reason: str, exit_cost_eur: float, gapped: bool = False) -> ClosedTrade:
        pos = self.open_positions.pop(symbol)

        delta = ((exit_price - pos.entry_price) if pos.direction == "long"
                 else (pos.entry_price - exit_price))
        gross_pnl = delta * pos.size
        total_costs = pos.entry_cost_eur + exit_cost_eur
        net_pnl = gross_pnl - total_costs

        gross_r = (gross_pnl / pos.initial_risk_eur) if pos.initial_risk_eur else 0.0
        net_r = (net_pnl / pos.initial_risk_eur) if pos.initial_risk_eur else 0.0

        self.equity_eur += gross_pnl - exit_cost_eur
        self.cumulative_costs_eur += exit_cost_eur

        trade = ClosedTrade(
            symbol=symbol, direction=pos.direction,
            signal_date=pos.signal_date, entry_date=pos.entry_date, entry_price=pos.entry_price,
            exit_date=exit_date, exit_price=exit_price, exit_reason=exit_reason,
            size=pos.size, risk_per_unit=pos.risk_per_unit,
            initial_risk_eur=pos.initial_risk_eur,
            confidence=pos.confidence, leverage=pos.leverage,
            gross_pnl_eur=gross_pnl, costs_eur=total_costs, net_pnl_eur=net_pnl,
            gross_r=gross_r, net_r=net_r,
            mae_r=pos.mae_r, mfe_r=pos.mfe_r, bars_held=pos.bars_held,
            gapped_exit=gapped,
        )
        self.closed_trades.append(trade)
        return trade

    # -- valorizzazione giornaliera --------------------------------------

    def mark_to_market(self, on_date: date, prices: dict[str, float]) -> None:
        """Registra l'equity di fine giornata includendo il valore delle
        posizioni ancora aperte. Senza questo, la curva salterebbe solo
        alle chiusure dei trade e il max drawdown risulterebbe più
        piccolo del reale — un drawdown vissuto a posizioni aperte è
        comunque un drawdown."""
        unrealized = 0.0
        for sym, pos in self.open_positions.items():
            price = prices.get(sym)
            if price is None:
                continue
            delta = ((price - pos.entry_price) if pos.direction == "long"
                     else (pos.entry_price - price))
            unrealized += delta * pos.size
        net_equity = self.equity_eur + unrealized
        gross_equity = net_equity + self.cumulative_costs_eur
        self.equity_curve.append((on_date, net_equity, gross_equity))
