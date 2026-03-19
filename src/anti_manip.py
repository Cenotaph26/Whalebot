"""
Anti-Manipulation Filter Engine  v2.0
──────────────────────────────────────
Düzeltmeler (v2.0):
  • Spoof: minimum 3sn gözlem süresi + flag_type bazlı cooldown 120sn'e çıkarıldı
  • Stop Hunt: margin BTC fiyatına göre dinamik (fiyat * 0.0007 ≈ %0.07)
  • News Lock: sadece kendi vol_spike event'inden tetiklenir, spoof'tan tetiklenmez
  • Layering: cooldown 120sn, HIGH yerine MEDIUM severity (işlemi engellemez tek başına)
  • _add_flag: flag tipi başına cooldown parametresi alır
  • get_summary: is_safe_to_trade tek çağrı (Bug 2 fix korundu)
"""

import time
from collections import deque
from typing import List, Tuple, Dict
from src.config import Config, ManipFlag


# Flag tipi başına cooldown (saniye) — sık tetiklenen tipleri bastırır
_FLAG_COOLDOWNS: Dict[str, int] = {
    "spoof":      120,
    "wash":        90,
    "stop_hunt":   60,
    "news_lock":  120,
    "layering":   120,
}


class AntiManipEngine:

    def __init__(self):
        # Spoof: (fiyat → (ilk_görülme, miktar, gözlem_sayısı))
        self._order_appearances: dict[float, Tuple[float, float, int]] = {}

        # Wash: son işlemler
        self._recent_trades: deque = deque(maxlen=200)

        # Layering: son 5 dk'da book'tan çekilen seviyeler
        self._pulled_levels: deque = deque(maxlen=500)

        # News lockout
        self._news_lock_until: float = 0.0
        self._last_news_event: str   = ""

        self.flags: deque = deque(maxlen=100)
        self.active_flags: List[ManipFlag] = []

    # ─────────────────────────────────────────
    #  PUBLIC: Ana kontrol noktası
    # ─────────────────────────────────────────

    def is_safe_to_trade(self) -> Tuple[bool, str]:
        self.active_flags = [f for f in self.flags
                             if time.time() - f.timestamp < 120]

        high_flags = [f for f in self.active_flags if f.severity == "HIGH"]
        med_flags  = [f for f in self.active_flags if f.severity == "MEDIUM"]

        if high_flags:
            return False, f"HIGH manip flag: {high_flags[0].flag_type} — {high_flags[0].detail}"
        if len(med_flags) >= 2:
            return False, f"Çoklu MEDIUM flag ({len(med_flags)}) — beklemede"
        if self._news_lock_active():
            secs = int(self._news_lock_until - time.time())
            return False, f"Haber kilidi — {secs}sn kaldı ({self._last_news_event})"

        return True, f"Güvenli ({len(self.active_flags)} aktif flag)"

    # ─────────────────────────────────────────
    #  1. SPOOF DETECTOR  (v2: min 3sn gözlem)
    # ─────────────────────────────────────────

    def update_order_book(self, bids: dict, asks: dict):
        now = time.time()
        all_levels = {**bids, **asks}

        for price, qty in all_levels.items():
            if qty == 0:
                if price in self._order_appearances:
                    first_seen, size, obs = self._order_appearances.pop(price)
                    lifetime = now - first_seen

                    # v2: En az 3sn gözlemlenmeli + büyük miktar + çok hızlı çekildi
                    min_obs = 3  # en az 3 book güncellemesi görülmeli
                    if (size >= Config.WHALE_BTC_THRESHOLD
                            and lifetime < Config.SPOOF_MIN_LIFETIME_SEC
                            and lifetime >= 0.3        # 300ms altı = veri artefaktı, yoksay
                            and obs >= min_obs):
                        self._add_flag(ManipFlag(
                            flag_type="spoof",
                            severity="HIGH",
                            detail=(f"${price:,.0f}'de {size:.1f} BTC duvar "
                                    f"{lifetime:.1f}sn içinde çekildi "
                                    f"(min {Config.SPOOF_MIN_LIFETIME_SEC}sn, {obs} obs)")
                        ))
                self._pulled_levels.append((price, now))
            else:
                if price not in self._order_appearances:
                    self._order_appearances[price] = (now, qty, 1)
                else:
                    first_seen, old_size, obs = self._order_appearances[price]
                    # Miktar güncellendiyse max al, gözlem sayısını artır
                    self._order_appearances[price] = (first_seen, max(old_size, qty), obs + 1)

        self._check_layering()

    # ─────────────────────────────────────────
    #  2. WASH TRADE DETECTOR
    # ─────────────────────────────────────────

    def record_trade(self, price: float, qty: float, is_buy: bool):
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
            and abs(t["qty"] - qty) < qty * 0.02
            and abs(t["price"] - price) < price * 0.001
            and now - t["time"] < window
        ]
        if opposite and qty >= Config.WHALE_BTC_THRESHOLD * 0.5:
            self._add_flag(ManipFlag(
                flag_type="wash",
                severity="MEDIUM",
                detail=f"{qty:.2f} BTC @ ${price:,.0f} — {window}sn içinde eşleşen karşı işlem"
            ))

    # ─────────────────────────────────────────
    #  3. STOP HUNT RADAR  (v2: dinamik margin)
    # ─────────────────────────────────────────

    def check_stop_hunt(self, current_price: float) -> bool:
        # v2: Sabit $50 yerine fiyatın %0.07'si (BTC $70k = $49, $30k = $21)
        # v4: strict < margin (dist==margin artık tetiklemez)
        margin = max(current_price * 0.0007, Config.STOP_HUNT_ROUND_MARGIN)
        danger_zones = [
            round(current_price / 1000) * 1000,
            round(current_price / 500)  * 500,
        ]

        for zone in danger_zones:
            dist = abs(current_price - zone)
            if 0 < dist < margin:   # strict < (dist==margin = boundary, tetikleme)
                self._add_flag(ManipFlag(
                    flag_type="stop_hunt",
                    severity="MEDIUM",
                    detail=f"Fiyat ${current_price:,.0f} → zone ${zone:,} sadece ${dist:.0f} uzakta (margin ${margin:.0f})"
                ))
                return True
        return False

    # ─────────────────────────────────────────
    #  4. NEWS LOCKOUT  (v2: dışarıdan trigger, spoof'tan DEĞİL)
    # ─────────────────────────────────────────

    def trigger_news_lock(self, event_name: str = "Bilinmeyen haber"):
        """Sadece engine.py'den vol_spike üzerine çağrılır."""
        # Zaten aktif kilitde yeni lock tetiklenmesin
        if self._news_lock_active():
            return
        self._news_lock_until = time.time() + Config.NEWS_LOCKOUT_SEC
        self._last_news_event = event_name
        self._add_flag(ManipFlag(
            flag_type="news_lock",
            severity="HIGH",
            detail=f"{event_name} → {Config.NEWS_LOCKOUT_SEC}sn işlem kilidi"
        ))

    def _news_lock_active(self) -> bool:
        return time.time() < self._news_lock_until

    # ─────────────────────────────────────────
    #  5. LAYERING CHECKER  (v2: MEDIUM severity)
    # ─────────────────────────────────────────

    def _check_layering(self):
        now = time.time()
        recent_pulls = [t for _, t in self._pulled_levels if now - t < 300]
        if len(recent_pulls) >= Config.LAYERING_PULL_THRESHOLD:
            self._add_flag(ManipFlag(
                flag_type="layering",
                severity="MEDIUM",   # v2: HIGH→MEDIUM, tek başına işlemi bloke etmez
                detail=f"Son 5dk'da {len(recent_pulls)} seviye çekildi (eşik: {Config.LAYERING_PULL_THRESHOLD})"
            ))

    # ─────────────────────────────────────────
    #  Yardımcı
    # ─────────────────────────────────────────

    def _add_flag(self, flag: ManipFlag):
        """Flag tipi başına dinamik cooldown — sık tetiklenen tipleri bastırır."""
        now = time.time()
        cooldown = _FLAG_COOLDOWNS.get(flag.flag_type, 60)
        for f in self.flags:
            if f.flag_type == flag.flag_type and now - f.timestamp < cooldown:
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
            "flags": [
                {
                    "type":     f.flag_type,
                    "severity": f.severity,
                    "detail":   f.detail,
                    "age_sec":  round(now - f.timestamp)
                }
                for f in active
            ],
            "news_locked":         self._news_lock_active(),
            "news_lock_secs_left": max(0, int(self._news_lock_until - now))
        }
