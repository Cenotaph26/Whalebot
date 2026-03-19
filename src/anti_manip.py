"""
Anti-Manipulation Filter Engine  v5.0
──────────────────────────────────────
v5.0 değişiklikler:
  • Spoof: "fiyata yakın duvar" kontrolü eklendi — uzak duvarlar false positive üretmez
    Emir, ekleme anında current_price'ın %0.5'i içindeyse spoof adayı sayılır
  • Spoof: _order_appearances hafıza sızıntısı kapatıldı (max 2000 seviye, TTL 5dk)
  • Stop Hunt: dinamik margin price*0.1% (floor kaldırıldı) — $70k'da $70 eşiği
    cooldown 60sn → 120sn (STOP_HUNT eşiği için flag_cooldowns'da güncellendi)
  • Layering: severity MEDIUM → tamamen bilgi amaçlı, tek başına hiç bloklamamalı
    is_safe_to_trade: layering flagları MEDIUM sayılmaz (ayrı kategori)
  • _add_flag: flag tipi bazlı cooldown dict'ten alınır (v4'ten korundu)
"""

import time
from collections import deque
from typing import List, Tuple, Dict
from src.config import Config, ManipFlag


_FLAG_COOLDOWNS: Dict[str, int] = {
    "spoof":      120,
    "wash":        90,
    "stop_hunt":  120,   # v5: 60→120
    "news_lock":  120,
    "layering":   180,   # v5: 120→180, sık tetiklenme bastırılır
}

# Spoof için: ekleme anında fiyata bu kadar yakın olmalı (%)
_SPOOF_PRICE_PROXIMITY_PCT = 0.005   # %0.5 — $70k'da ±$350


class AntiManipEngine:

    def __init__(self):
        # Spoof: fiyat → (ilk_görülme, miktar, obs_sayısı, ekleme_anı_fiyat)
        self._order_appearances: dict[float, Tuple[float, float, int, float]] = {}
        self._last_price: float = 0.0

        self._recent_trades: deque = deque(maxlen=200)
        self._pulled_levels: deque = deque(maxlen=500)

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
        # v5: layering flagları MEDIUM'a dahil edilmez — sadece spoof/wash/stop_hunt/news
        med_flags  = [f for f in self.active_flags
                      if f.severity == "MEDIUM" and f.flag_type != "layering"]

        if high_flags:
            return False, f"HIGH manip flag: {high_flags[0].flag_type} — {high_flags[0].detail}"
        if len(med_flags) >= 2:
            return False, f"Çoklu MEDIUM flag ({len(med_flags)}) — beklemede"
        if self._news_lock_active():
            secs = int(self._news_lock_until - time.time())
            return False, f"Haber kilidi — {secs}sn kaldı ({self._last_news_event})"

        return True, f"Güvenli ({len(self.active_flags)} aktif flag)"

    # ─────────────────────────────────────────
    #  1. SPOOF DETECTOR  (v5: proximity check + TTL cleanup)
    # ─────────────────────────────────────────

    def update_order_book(self, bids: dict, asks: dict, current_price: float = 0.0):
        """
        v5: current_price parametresi eklendi — proximity kontrolü için.
        Engine.py'den çağırılırken whale.current_price geçirilmeli.
        """
        if current_price > 0:
            self._last_price = current_price
        price_ref = self._last_price

        now = time.time()
        all_levels = {**bids, **asks}

        # v5: TTL cleanup — 5 dk'dan eski ve hâlâ aktif (çekilmemiş) kayıtları sil
        stale_keys = [
            p for p, (first_seen, *_) in self._order_appearances.items()
            if now - first_seen > 300
        ]
        for k in stale_keys:
            del self._order_appearances[k]

        # v5: max boyut sınırı — 2000 üzerinde en eski kayıtları temizle
        if len(self._order_appearances) > 2000:
            sorted_by_age = sorted(self._order_appearances.items(), key=lambda x: x[1][0])
            for k, _ in sorted_by_age[:500]:
                del self._order_appearances[k]

        for price, qty in all_levels.items():
            if qty == 0:
                if price in self._order_appearances:
                    first_seen, size, obs, entry_price = self._order_appearances.pop(price)
                    lifetime = now - first_seen

                    # v5: Proximity check — ekleme anında fiyata yakın mıydı?
                    near_price = (
                        entry_price == 0  # fiyat bilinmiyorsa, geç (konservatif)
                        or (entry_price > 0
                            and abs(price - entry_price) / entry_price < _SPOOF_PRICE_PROXIMITY_PCT)
                    )

                    if (size >= Config.WHALE_BTC_THRESHOLD
                            and lifetime < Config.SPOOF_MIN_LIFETIME_SEC
                            and lifetime >= 0.3
                            and obs >= 3
                            and near_price):
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
                    self._order_appearances[price] = (now, qty, 1, price_ref)
                else:
                    first_seen, old_size, obs, ep = self._order_appearances[price]
                    self._order_appearances[price] = (first_seen, max(old_size, qty), obs + 1, ep)

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
    #  3. STOP HUNT RADAR  (v5: saf dinamik margin, %0.1)
    # ─────────────────────────────────────────

    def check_stop_hunt(self, current_price: float) -> bool:
        # v5: Sadece price*0.1% — $70k'da $70, $30k'da $30
        # Floor kaldırıldı — sabit $150 BTC'nin her seviyesinde çok geniş
        margin = current_price * 0.001   # %0.1
        danger_zones = [
            round(current_price / 1000) * 1000,
            round(current_price / 500)  * 500,
        ]

        for zone in danger_zones:
            dist = abs(current_price - zone)
            if 0 < dist < margin:
                self._add_flag(ManipFlag(
                    flag_type="stop_hunt",
                    severity="MEDIUM",
                    detail=f"Fiyat ${current_price:,.0f} → zone ${zone:,} ${dist:.0f} uzakta (eşik ${margin:.0f})"
                ))
                return True
        return False

    # ─────────────────────────────────────────
    #  4. NEWS LOCKOUT
    # ─────────────────────────────────────────

    def trigger_news_lock(self, event_name: str = "Bilinmeyen haber"):
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
    #  5. LAYERING CHECKER  (v5: INFO-only, bloklama yok)
    # ─────────────────────────────────────────

    def _check_layering(self):
        now = time.time()
        recent_pulls = [t for _, t in self._pulled_levels if now - t < 300]
        if len(recent_pulls) >= Config.LAYERING_PULL_THRESHOLD:
            self._add_flag(ManipFlag(
                flag_type="layering",
                severity="LOW",    # v5: MEDIUM→LOW, is_safe_to_trade'de sayılmaz
                detail=f"Son 5dk'da {len(recent_pulls)} seviye çekildi (eşik: {Config.LAYERING_PULL_THRESHOLD})"
            ))

    # ─────────────────────────────────────────
    #  Yardımcı
    # ─────────────────────────────────────────

    def _add_flag(self, flag: ManipFlag):
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
