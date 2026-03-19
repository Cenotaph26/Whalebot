"""
Whale Detector + Signal Engine  v2.0
──────────────────────────────────────
Düzeltmeler (v2.0):
  • SignalEngine.add(): Aynı source+direction için 10sn dedup (imbalance flood engeli)
  • check_volume_spike(): cooldown 15sn — 100ms interval'da tekrar tetiklenmesin
  • _check_iceberg(): iceberg tracker boyutu sınırlandırıldı (memory leak önlemi)
  • get_stats(): bid/ask doğru şekilde top 20 sıralı seviyelerden alınıyor
"""

import time
from collections import deque
from typing import Optional, List
from src.config import Config, Signal


# İmbalance sinyali için minimum yeniden tetiklenme süresi (saniye)
_IMBALANCE_COOLDOWN_SEC = 10
_VOLUME_SPIKE_COOLDOWN_SEC = 15


class WhaleDetector:

    def __init__(self):
        self.current_price:   float = 0.0
        self.recent_trades:   deque = deque(maxlen=500)
        self.volume_baseline: deque = deque(maxlen=60)
        self.volume_window:   deque = deque(maxlen=10)
        self.bids: dict = {}
        self.asks: dict = {}
        self._iceberg_tracker: dict[float, int] = {}
        self._last_baseline_update = time.time()
        self._last_vol_spike_time:   float = 0.0   # v2: cooldown

    # ─────────────────────────────────────────
    #  Trade stream işleme
    # ─────────────────────────────────────────

    def process_trade(self, data: dict) -> Optional[Signal]:
        price  = float(data.get("p", 0))
        qty    = float(data.get("q", 0))
        is_buy = not data.get("m", True)
        now    = time.time()

        self.current_price = price
        self.recent_trades.append({"price": price, "qty": qty, "is_buy": is_buy, "time": now})
        self.volume_window.append(qty)

        if now - self._last_baseline_update >= 1.0:
            window_vol = sum(t["qty"] for t in self.recent_trades if now - t["time"] < 10)
            self.volume_baseline.append(window_vol)
            self._last_baseline_update = now

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
        """Son 10sn hacmi baseline'ın 3×'i mi? — v2: 15sn cooldown"""
        if len(self.volume_baseline) < 10:
            return None

        # v2: cooldown — saniyede çok fazla tetiklenmesin
        now = time.time()
        if now - self._last_vol_spike_time < _VOLUME_SPIKE_COOLDOWN_SEC:
            return None

        baseline_avg = sum(self.volume_baseline) / len(self.volume_baseline)
        if baseline_avg == 0:
            return None

        recent_vol = sum(t["qty"] for t in self.recent_trades if now - t["time"] < 10)
        ratio      = recent_vol / baseline_avg

        if ratio >= Config.VOLUME_SPIKE_MULT:
            self._last_vol_spike_time = now   # cooldown başlat
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
                self._iceberg_tracker[p] = self._iceberg_tracker.get(p, 0) + 1

        # v2: iceberg tracker hafıza sızıntısını önle
        if len(self._iceberg_tracker) > 1000:
            # En eski (düşük sayılı) kayıtları temizle
            sorted_keys = sorted(self._iceberg_tracker, key=lambda k: self._iceberg_tracker[k])
            for k in sorted_keys[:200]:
                del self._iceberg_tracker[k]

        imbalance_signal = self._check_imbalance()
        iceberg_signal   = self._check_iceberg()
        return imbalance_signal or iceberg_signal

    def _check_imbalance(self) -> Optional[Signal]:
        if len(self.bids) < 5 or len(self.asks) < 5:
            return None

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
        for price, count in list(self._iceberg_tracker.items()):
            if count >= 8:
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

        # v2: Doğru sıralı top-20
        top_bids = sorted(self.bids.keys(), reverse=True)[:20]
        top_asks = sorted(self.asks.keys())[:20]
        bid_vol  = sum(self.bids[p] for p in top_bids)
        ask_vol  = sum(self.asks[p] for p in top_asks)
        btotal   = bid_vol + ask_vol
        bid_pct  = (bid_vol / btotal * 100) if btotal > 0 else 50

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
#  Signal Engine — v2.0
# ─────────────────────────────────────────

class SignalEngine:

    def __init__(self):
        self.pending: deque = deque(maxlen=50)
        self.history: deque = deque(maxlen=200)
        # v2: source+direction → son eklenme zamanı (flood önleme)
        self._last_signal_time: dict[str, float] = {}

    def add(self, signal: Signal) -> bool:
        """
        v2: Aynı source+direction için cooldown uygula.
        imbalance: 10sn, diğerleri: 5sn
        v4: Kabul edildi/reddedildi bool döndürür (log spam önleme için).
        """
        key = f"{signal.source}:{signal.direction}"
        now = signal.timestamp
        cooldown = _IMBALANCE_COOLDOWN_SEC if signal.source == "imbalance" else 5

        last = self._last_signal_time.get(key, 0)
        if now - last < cooldown:
            return False   # çok yakın zamanda aynı sinyal geldi, yoksay

        self._last_signal_time[key] = now
        self.pending.append(signal)
        self.history.append(signal)
        return True

    def evaluate(self) -> Optional[dict]:
        now    = time.time()
        cutoff = now - Config.SIGNAL_WINDOW_SEC
        fresh  = [s for s in self.pending if s.timestamp >= cutoff]

        long_sigs  = [s for s in fresh if s.direction == "LONG"]
        short_sigs = [s for s in fresh if s.direction == "SHORT"]

        for direction, sigs in [("LONG", long_sigs), ("SHORT", short_sigs)]:
            if len(sigs) >= Config.MIN_SIGNALS:
                avg_strength = sum(s.strength for s in sigs) / len(sigs)
                self.pending = deque(
                    [s for s in self.pending if s not in sigs],
                    maxlen=50
                )
                return {
                    "direction":    direction,
                    "strength":     round(avg_strength, 2),
                    "signal_count": len(sigs),
                    "sources":      [s.source for s in sigs],
                    "details":      [s.details for s in sigs],
                    "price":        sigs[-1].price,
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
