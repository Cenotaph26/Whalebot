"""
Risk Manager + Trade Engine
────────────────────────────
• Kelly Criterion ile pozisyon boyutu
• Günlük kayıp kilidi
• Korelasyon filtresi (aynı yönde max 2 açık işlem)
• TP/SL takibi
• Testnet paper trading (API_KEY=DEMO → simüle)
"""

import time
import uuid
import asyncio
import hmac
import hashlib
import aiohttp
from typing import List, Optional
from src.config import Config, Trade


class RiskManager:

    def __init__(self):
        self.balance:       float = Config.STARTING_BALANCE
        self.daily_start:   float = Config.STARTING_BALANCE
        self.day_start_ts:  float = time.time()
        self.open_trades:   List[Trade] = []
        self.closed_trades: List[Trade] = []
        self.total_pnl:     float = 0.0

    # ─────────────────────────────────────────
    #  Günlük sıfırlama
    # ─────────────────────────────────────────

    def _maybe_reset_day(self):
        if time.time() - self.day_start_ts > 86400:
            self.daily_start  = self.balance
            self.day_start_ts = time.time()

    # ─────────────────────────────────────────
    #  Günlük kayıp limiti kontrolü
    # ─────────────────────────────────────────

    def daily_loss_ok(self) -> bool:
        self._maybe_reset_day()
        if self.daily_start == 0:
            return True
        loss_pct = (self.daily_start - self.balance) / self.daily_start * 100
        return loss_pct < Config.DAILY_LOSS_LIMIT_PCT

    def daily_loss_pct(self) -> float:
        self._maybe_reset_day()
        if self.daily_start == 0:
            return 0.0
        return round((self.daily_start - self.balance) / self.daily_start * 100, 2)

    # ─────────────────────────────────────────
    #  Max açık işlem kontrolü
    # ─────────────────────────────────────────

    def can_open(self, direction: str) -> tuple[bool, str]:
        if not self.daily_loss_ok():
            return False, f"Günlük kayıp limiti: %{self.daily_loss_pct()}"
        if len(self.open_trades) >= Config.MAX_OPEN_TRADES:
            return False, f"Maks açık işlem: {Config.MAX_OPEN_TRADES}"

        same_dir = [t for t in self.open_trades if t.direction == direction]
        if len(same_dir) >= 2:
            return False, f"Aynı yönde 2+ açık işlem var ({direction})"

        return True, "OK"

    # ─────────────────────────────────────────
    #  Kelly ile pozisyon boyutu
    # ─────────────────────────────────────────

    def kelly_size(self, win_rate: float = 0.55, rr: float = 2.0) -> float:
        """
        Kelly fraksiyonu = W - (1-W)/R
        W = kazanma oranı, R = ödül/risk
        Güvenlik için yarım Kelly kullanılır.
        """
        kelly = win_rate - (1 - win_rate) / rr
        kelly = max(0.0, min(kelly, 0.25))  # maks %25
        half_kelly = kelly * 0.5
        size = self.balance * half_kelly
        return round(min(size, Config.TRADE_SIZE_USDT * 2), 2)

    # ─────────────────────────────────────────
    #  İşlem aç
    # ─────────────────────────────────────────

    def open_trade(self, direction: str, price: float, strength: float) -> Optional[Trade]:
        ok, reason = self.can_open(direction)
        if not ok:
            return None

        size = self.kelly_size(
            win_rate=0.52 + strength * 0.08,  # güce göre win rate tahmini
            rr=Config.TAKE_PROFIT_PCT / Config.STOP_LOSS_PCT
        )

        sl_mult = Config.STOP_LOSS_PCT   / 100
        tp_mult = Config.TAKE_PROFIT_PCT / 100

        if direction == "LONG":
            stop_loss   = round(price * (1 - sl_mult), 2)
            take_profit = round(price * (1 + tp_mult), 2)
        else:
            stop_loss   = round(price * (1 + sl_mult), 2)
            take_profit = round(price * (1 - tp_mult), 2)

        trade = Trade(
            id=str(uuid.uuid4())[:8].upper(),
            direction=direction,
            entry_price=price,
            size_usdt=size,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        self.open_trades.append(trade)
        return trade

    # ─────────────────────────────────────────
    #  Fiyat güncelle → TP/SL kontrol
    # ─────────────────────────────────────────

    def update_prices(self, current_price: float) -> List[Trade]:
        """Fiyat günceller, kapanan işlemleri döndürür."""
        closed = []
        for trade in list(self.open_trades):
            if trade.direction == "LONG":
                if current_price >= trade.take_profit:
                    self._close(trade, current_price, "TP")
                    closed.append(trade)
                elif current_price <= trade.stop_loss:
                    self._close(trade, current_price, "SL")
                    closed.append(trade)
            else:  # SHORT
                if current_price <= trade.take_profit:
                    self._close(trade, current_price, "TP")
                    closed.append(trade)
                elif current_price >= trade.stop_loss:
                    self._close(trade, current_price, "SL")
                    closed.append(trade)
        return closed

    def _close(self, trade: Trade, price: float, reason: str):
        trade.close_price = price
        trade.close_time  = time.time()
        trade.status      = reason

        if trade.direction == "LONG":
            pnl_pct = (price - trade.entry_price) / trade.entry_price
        else:
            pnl_pct = (trade.entry_price - price) / trade.entry_price

        trade.pnl = round(trade.size_usdt * pnl_pct, 2)
        self.balance   += trade.pnl
        self.total_pnl += trade.pnl
        self.open_trades.remove(trade)
        self.closed_trades.append(trade)

    # ─────────────────────────────────────────
    #  Anlık PnL (açık işlemler için)
    # ─────────────────────────────────────────

    def unrealized_pnl(self, current_price: float) -> float:
        total = 0.0
        for t in self.open_trades:
            if t.direction == "LONG":
                pct = (current_price - t.entry_price) / t.entry_price
            else:
                pct = (t.entry_price - current_price) / t.entry_price
            total += t.size_usdt * pct
        return round(total, 2)

    # ─────────────────────────────────────────
    #  Stats
    # ─────────────────────────────────────────

    def stats(self, current_price: float) -> dict:
        closed = self.closed_trades
        wins   = [t for t in closed if t.pnl > 0]
        losses = [t for t in closed if t.pnl <= 0]
        win_rate = len(wins) / len(closed) * 100 if closed else 0

        open_trades_data = []
        for t in self.open_trades:
            if t.direction == "LONG":
                upnl_pct = (current_price - t.entry_price) / t.entry_price * 100
            else:
                upnl_pct = (t.entry_price - current_price) / t.entry_price * 100
            open_trades_data.append({
                "id":          t.id,
                "direction":   t.direction,
                "entry":       t.entry_price,
                "current":     current_price,
                "sl":          t.stop_loss,
                "tp":          t.take_profit,
                "size":        t.size_usdt,
                "upnl":        round(t.size_usdt * upnl_pct / 100, 2),
                "upnl_pct":    round(upnl_pct, 2),
                "age_min":     round((time.time() - t.open_time) / 60, 1),
            })

        recent_closed = []
        for t in list(reversed(closed))[:10]:
            recent_closed.append({
                "id":        t.id,
                "direction": t.direction,
                "entry":     t.entry_price,
                "exit":      t.close_price,
                "pnl":       t.pnl,
                "status":    t.status,
                "dur_min":   round((t.close_time - t.open_time) / 60, 1) if t.close_time else 0,
            })

        return {
            "balance":        round(self.balance, 2),
            "total_pnl":      round(self.total_pnl, 2),
            "unrealized_pnl": self.unrealized_pnl(current_price),
            "win_rate":       round(win_rate, 1),
            "total_trades":   len(closed),
            "wins":           len(wins),
            "losses":         len(losses),
            "daily_loss_pct": self.daily_loss_pct(),
            "bot_halted":     not self.daily_loss_ok(),
            "open_trades":    open_trades_data,
            "closed_trades":  recent_closed,
        }
