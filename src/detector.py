"""
Whale Detector + Signal Engine
────────────────────────────────
Binance WebSocket'ten gelen ham veriyi işler:
  • Büyük işlem → whale_trade sinyali
  • Hacim spike  → volume_spike sinyali
  • Bid/Ask imbalance → imbalance sinyali
  • Iceberg emir → iceberg sinyali

Birden fazla sinyal aynı yönde + zaman penceresinde → işlem kararı
"""

import time
from collections import deque
from typing import Optional, List
from src.config import Config, Signal


class WhaleDetector:

    def __init__(self):
        self.current_price:   float = 0.0
        self.recent_trades:   deque = deque(maxlen=500)
        self.volume_baseline: deque = deque(maxlen=60)   # 60s baseline
        self.volume_window:   deque = deque(maxlen=10)   # 10s window
        self.bids: dict = {}
        self.asks: dict = {}
        self._iceberg_tracker: dict[float, int] = {}    # fiyat → tekrar sayısı
        self._last_baseline_update = time.time()

    # ─────────────────────────────────────────
    #  Trade stream işleme
    # ─────────────────────────────────────────

    def process_trade(self, data: dict) -> Optional[Signal]:
        price  = float(data.get("p", 0))
        qty    = float(data.get("q", 0))
        is_buy = not data.get("m", True)   # maker=sell taraf
        now    = time.time()

        self.current_price = price
        self.recent_trades.append({"price": price, "qty": qty, "is_buy": is_buy, "time": now})
        self.volume_window.append(qty)

        # Baseline güncelle (her 1 sn)
        if now - self._last_baseline_update >= 1.0:
            window_vol = sum(t["qty"] for t in self.recent_trades
                            if now - t["time"] < 10)
            self.volume_baseline.append(window_vol)
            self._last_baseline_update = now

        # Büyük tek işlem kontrolü
        if qty >= Config.WHALE_BTC_THRESHOLD:
            direction = "LONG" if is_buy else "SHORT"
            strength  = min(1.0, qty / (Config.WHALE_BTC_THRESHOLD * 5))
            return Signal(
                source="whale_trade",
                direction=direction,
                strength=round(strength, 2),
                price=price,
                details=f"{qty:.2f} BTC {'ALIM' if is_buy else 'SATIM'} @ ${price:,.0f}"
            )
        return None

    def check_volume_spike(self) -> Optional[Signal]:
        """Son 10 sn hacmi, 60 sn ortalamasının 3×'i mi?"""
        if len(self.volume_baseline) < 10:
            return None

        baseline_avg = sum(self.volume_baseline) / len(self.volume_baseline)
        if baseline_avg == 0:
            return None

        now        = time.time()
        recent_vol = sum(t["qty"] for t in self.recent_trades if now - t["time"] < 10)
        ratio      = recent_vol / baseline_avg if baseline_avg > 0 else 0

        if ratio >= Config.VOLUME_SPIKE_MULT:
            # Spike hangi yönde? Son işlemlerin ağırlıklı yönü
            recent = [t for t in self.recent_trades if now - t["time"] < 10]
            buy_vol  = sum(t["qty"] for t in recent if t["is_buy"])
            sell_vol = sum(t["qty"] for t in recent if not t["is_buy"])
            direction = "LONG" if buy_vol > sell_vol else "SHORT"

            return Signal(
                source="volume_spike",
                direction=direction,
                strength=min(1.0, ratio / (Config.VOLUME_SPIKE_MULT * 2)),
                price=self.current_price,
                details=f"Hacim spike {ratio:.1f}× baseline ({recent_vol:.2f} BTC/10sn)"
            )
        return None

    # ─────────────────────────────────────────
    #  Order Book işleme
    # ─────────────────────────────────────────

    def process_order_book(self, data: dict) -> Optional[Signal]:
        for bid in data.get("b", []):
            p, q = float(bid[0]), float(bid[1])
            if q == 0:
                self.bids.pop(p, None)
            else:
                self.bids[p] = q

        for ask in data.get("a", []):
            p, q = float(ask[0]), float(ask[1])
            if q == 0:
                self.asks.pop(p, None)
            else:
                self.asks[p] = q
                # Iceberg: aynı fiyat tekrar ekleniyorsa say
                self._iceberg_tracker[p] = self._iceberg_tracker.get(p, 0) + 1

        imbalance_signal = self._check_imbalance()
        iceberg_signal   = self._check_iceberg()
        return imbalance_signal or iceberg_signal

    def _check_imbalance(self) -> Optional[Signal]:
        if len(self.bids) < 5 or len(self.asks) < 5:
            return None

        # En yakın 20 seviye
        top_bids = sorted(self.bids.keys(), reverse=True)[:20]
        top_asks = sorted(self.asks.keys())[:20]

        bid_vol = sum(self.bids[p] for p in top_bids)
        ask_vol = sum(self.asks[p] for p in top_asks)
        total   = bid_vol + ask_vol
        if total == 0:
            return None

        bid_ratio = bid_vol / total
        ask_ratio = ask_vol / total

        if bid_ratio >= Config.IMBALANCE_THRESHOLD:
            return Signal(
                source="imbalance",
                direction="LONG",
                strength=round((bid_ratio - 0.5) * 2, 2),
                price=self.current_price,
                details=f"Bid baskısı %{bid_ratio*100:.0f} (alıcılar hakim)"
            )
        elif ask_ratio >= Config.IMBALANCE_THRESHOLD:
            return Signal(
                source="imbalance",
                direction="SHORT",
                strength=round((ask_ratio - 0.5) * 2, 2),
                price=self.current_price,
                details=f"Ask baskısı %{ask_ratio*100:.0f} (satıcılar hakim)"
            )
        return None

    def _check_iceberg(self) -> Optional[Signal]:
        """Aynı fiyattan 8+ kez emir geldiyse iceberg şüphesi."""
        for price, count in list(self._iceberg_tracker.items()):
            if count >= 8:
                # Bu seviye hâlâ aktif mi?
                if price in self.asks:
                    self._iceberg_tracker.pop(price)
                    return Signal(
                        source="iceberg",
                        direction="SHORT",
                        strength=0.7,
                        price=self.current_price,
                        details=f"Iceberg satış emri @ ${price:,.0f} ({count}× yenilendi)"
                    )
                elif price in self.bids:
                    self._iceberg_tracker.pop(price)
                    return Signal(
                        source="iceberg",
                        direction="LONG",
                        strength=0.7,
                        price=self.current_price,
                        details=f"Iceberg alış emri @ ${price:,.0f} ({count}× yenilendi)"
                    )
        return None

    def get_stats(self) -> dict:
        now = time.time()
        recent = [t for t in self.recent_trades if now - t["time"] < 60]
        buy_v  = sum(t["qty"] for t in recent if t["is_buy"])
        sell_v = sum(t["qty"] for t in recent if not t["is_buy"])
        total  = buy_v + sell_v

        baseline_avg = (sum(self.volume_baseline) / len(self.volume_baseline)
                        if self.volume_baseline else 0)
        recent_10s   = sum(t["qty"] for t in self.recent_trades if now - t["time"] < 10)
        spike_ratio  = recent_10s / baseline_avg if baseline_avg > 0 else 0

        bid_vol = sum(list(self.bids.values())[:20])
        ask_vol = sum(list(self.asks.values())[:20])
        btotal  = bid_vol + ask_vol
        bid_pct = (bid_vol / btotal * 100) if btotal > 0 else 50

        return {
            "price":       round(self.current_price, 2),
            "buy_vol_1m":  round(buy_v, 3),
            "sell_vol_1m": round(sell_v, 3),
            "buy_pct":     round(buy_v / total * 100, 1) if total > 0 else 50,
            "spike_ratio": round(spike_ratio, 2),
            "bid_pct":     round(bid_pct, 1),
            "ask_pct":     round(100 - bid_pct, 1),
        }


# ─────────────────────────────────────────
#  Signal Engine — sinyalleri birleştirir
# ─────────────────────────────────────────

class SignalEngine:

    def __init__(self):
        self.pending: deque = deque(maxlen=50)
        self.history: deque = deque(maxlen=200)

    def add(self, signal: Signal):
        self.pending.append(signal)
        self.history.append(signal)

    def evaluate(self) -> Optional[dict]:
        """
        Zaman penceresi içindeki sinyalleri değerlendir.
        En az MIN_SIGNALS aynı yönde → işlem kararı döndür.
        """
        now     = time.time()
        cutoff  = now - Config.SIGNAL_WINDOW_SEC
        fresh   = [s for s in self.pending if s.timestamp >= cutoff]

        long_sigs  = [s for s in fresh if s.direction == "LONG"]
        short_sigs = [s for s in fresh if s.direction == "SHORT"]

        for direction, sigs in [("LONG", long_sigs), ("SHORT", short_sigs)]:
            if len(sigs) >= Config.MIN_SIGNALS:
                avg_strength = sum(s.strength for s in sigs) / len(sigs)
                # Değerlendirildikten sonra temizle
                self.pending = deque(
                    [s for s in self.pending if s not in sigs],
                    maxlen=50
                )
                return {
                    "direction":   direction,
                    "strength":    round(avg_strength, 2),
                    "signal_count": len(sigs),
                    "sources":     [s.source for s in sigs],
                    "details":     [s.details for s in sigs],
                    "price":       sigs[-1].price,
                }
        return None

    def recent_signals(self, n: int = 20) -> List[dict]:
        now  = time.time()
        sigs = list(self.history)[-n:]
        return [
            {
                "source":    s.source,
                "direction": s.direction,
                "strength":  s.strength,
                "price":     s.price,
                "details":   s.details,
                "age_sec":   round(now - s.timestamp),
            }
            for s in reversed(sigs)
        ]
