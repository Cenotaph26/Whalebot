"""
Anti-Manipulation Filter Engine
─────────────────────────────────
5 filtre katmanı:
  1. Spoof Detector      – emir duvarı gerçek mi?
  2. Wash Trade Detector – kendine işlem mi?
  3. Stop Hunt Radar     – round number tuzağı mı?
  4. News Lockout        – haber kilidinde miyiz?
  5. Layering Checker    – kitap manipüle mi?

Her filtre True döndürürse o tehdit VAR demektir.
"""

import time
import math
from collections import deque
from typing import List, Tuple
from src.config import Config, ManipFlag


class AntiManipEngine:

    def __init__(self):
        # Spoof: (fiyat, miktar, ilk_görülme_zamanı)
        self._order_appearances: dict[float, Tuple[float, float]] = {}

        # Wash: son işlemler (fiyat, miktar, yön, zaman)
        self._recent_trades: deque = deque(maxlen=200)

        # Layering: son 5 dk'da book'tan çekilen seviyeler
        self._pulled_levels: deque = deque(maxlen=500)
        self._book_snapshot: dict[float, float] = {}

        # News lockout
        self._news_lock_until: float = 0.0
        self._last_news_event: str   = ""

        self.flags: deque = deque(maxlen=100)   # son 100 flag
        self.active_flags: List[ManipFlag] = []

    # ─────────────────────────────────────────
    #  PUBLIC: Ana kontrol noktası
    # ─────────────────────────────────────────

    def is_safe_to_trade(self) -> Tuple[bool, str]:
        """
        True → işlem açılabilir
        False, reason → manipülasyon riski, bekle
        """
        self.active_flags = [f for f in self.flags
                             if time.time() - f.timestamp < 120]  # 2 dk taze flag

        high_flags = [f for f in self.active_flags if f.severity == "HIGH"]
        med_flags  = [f for f in self.active_flags if f.severity == "MEDIUM"]

        if high_flags:
            return False, f"HIGH manip flag: {high_flags[0].flag_type} — {high_flags[0].detail}"
        if len(med_flags) >= 2:
            return False, f"Çoklu MEDIUM flag ({len(med_flags)}) — beklemede"
        if self._news_lock_active():
            secs = int(self._news_lock_until - time.time())
            return False, f"Haber kilidi — {secs}sn kaldı ({self._last_news_event})"

        passes = Config.MIN_FILTER_PASS - len(med_flags)
        return True, f"Güvenli ({len(self.active_flags)} aktif flag)"

    # ─────────────────────────────────────────
    #  1. SPOOF DETECTOR
    # ─────────────────────────────────────────

    def update_order_book(self, bids: dict, asks: dict):
        """
        Order book güncellemesi alır.
        Emir duvarları hiç dolmadan uzun süre bekliyorsa → spoof şüphesi.
        """
        now = time.time()
        all_levels = {**bids, **asks}

        for price, qty in all_levels.items():
            if qty == 0:
                # Emir çekildi — ne kadar süre kaldı?
                if price in self._order_appearances:
                    first_seen, size = self._order_appearances.pop(price)
                    lifetime = now - first_seen
                    if size >= Config.WHALE_BTC_THRESHOLD and lifetime < Config.SPOOF_MIN_LIFETIME_SEC:
                        self._add_flag(ManipFlag(
                            flag_type="spoof",
                            severity="HIGH",
                            detail=f"${price:,.0f} seviyesinde {size:.1f} BTC duvar "
                                   f"{lifetime:.0f}sn içinde çekildi (min {Config.SPOOF_MIN_LIFETIME_SEC}sn)"
                        ))
                # Layering: çekilen seviyeyi kaydet
                self._pulled_levels.append((price, now))
            else:
                if price not in self._order_appearances:
                    self._order_appearances[price] = (now, qty)

        # Layering kontrolü
        self._check_layering()

    # ─────────────────────────────────────────
    #  2. WASH TRADE DETECTOR
    # ─────────────────────────────────────────

    def record_trade(self, price: float, qty: float, is_buy: bool):
        """Her gelen işlemi kaydet, eşleşen çift var mı bak."""
        now = time.time()
        self._recent_trades.append({
            "price": price, "qty": qty, "is_buy": is_buy, "time": now
        })
        self._check_wash_trade(price, qty, is_buy, now)

    def _check_wash_trade(self, price: float, qty: float, is_buy: bool, now: float):
        window = Config.WASH_PAIR_WINDOW_SEC
        opposite = [
            t for t in self._recent_trades
            if t["is_buy"] != is_buy
            and abs(t["qty"] - qty) < qty * 0.02        # %2 tolerans
            and abs(t["price"] - price) < price * 0.001  # %0.1 fiyat farkı
            and now - t["time"] < window
        ]
        if opposite and qty >= Config.WHALE_BTC_THRESHOLD * 0.5:
            self._add_flag(ManipFlag(
                flag_type="wash",
                severity="MEDIUM",
                detail=f"{qty:.2f} BTC @ ${price:,.0f} — {window}sn içinde eşleşen karşı işlem bulundu"
            ))

    # ─────────────────────────────────────────
    #  3. STOP HUNT RADAR
    # ─────────────────────────────────────────

    def check_stop_hunt(self, current_price: float) -> bool:
        """
        Round number yakınında mıyız?
        Balinalar birikim noktalarını (500, 1000 katları) hedefler.
        """
        margin = Config.STOP_HUNT_ROUND_MARGIN
        danger_zones = [
            round(current_price / 1000) * 1000,
            round(current_price / 500)  * 500,
            round(current_price / 100)  * 100,
        ]
        for zone in danger_zones:
            dist = abs(current_price - zone)
            if 0 < dist < margin:
                self._add_flag(ManipFlag(
                    flag_type="stop_hunt",
                    severity="MEDIUM",
                    detail=f"Fiyat ${current_price:,.0f} → round zone ${zone:,} sadece ${dist:.0f} uzakta"
                ))
                return True
        return False

    # ─────────────────────────────────────────
    #  4. NEWS LOCKOUT
    # ─────────────────────────────────────────

    def trigger_news_lock(self, event_name: str = "Bilinmeyen haber"):
        """
        Dışarıdan çağrılır (ör. volatilite spike tespit edildiğinde).
        """
        self._news_lock_until  = time.time() + Config.NEWS_LOCKOUT_SEC
        self._last_news_event  = event_name
        self._add_flag(ManipFlag(
            flag_type="news_lock",
            severity="HIGH",
            detail=f"{event_name} → {Config.NEWS_LOCKOUT_SEC}sn işlem kilidi"
        ))

    def _news_lock_active(self) -> bool:
        return time.time() < self._news_lock_until

    # ─────────────────────────────────────────
    #  5. LAYERING CHECKER
    # ─────────────────────────────────────────

    def _check_layering(self):
        """Son 5 dakikada çok sayıda seviye çekildiyse → layering."""
        now = time.time()
        recent_pulls = [t for _, t in self._pulled_levels if now - t < 300]  # 5 dk
        if len(recent_pulls) >= Config.LAYERING_PULL_THRESHOLD:
            self._add_flag(ManipFlag(
                flag_type="layering",
                severity="HIGH",
                detail=f"Son 5 dk'da {len(recent_pulls)} seviye çekildi (eşik: {Config.LAYERING_PULL_THRESHOLD})"
            ))

    # ─────────────────────────────────────────
    #  Yardımcı
    # ─────────────────────────────────────────

    def _add_flag(self, flag: ManipFlag):
        # Aynı tip flag 60 sn içinde tekrar eklenmesin
        now = time.time()
        for f in self.flags:
            if f.flag_type == flag.flag_type and now - f.timestamp < 60:
                return
        self.flags.append(flag)

    def get_summary(self) -> dict:
        now = time.time()
        active = [f for f in self.flags if now - f.timestamp < 120]
        is_safe, reason = self.is_safe_to_trade()
        return {
            "safe":          is_safe,
            "reason":        reason,
            "active_flags":  len(active),
            "flags":         [
                {
                    "type":      f.flag_type,
                    "severity":  f.severity,
                    "detail":    f.detail,
                    "age_sec":   round(now - f.timestamp)
                }
                for f in active
            ],
            "news_locked":   self._news_lock_active(),
            "news_lock_secs_left": max(0, int(self._news_lock_until - now))
        }
