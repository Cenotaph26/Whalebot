"""
Bot Engine — Ana Orkestratör
──────────────────────────────
Binance Testnet WebSocket bağlantıları:
  • /ws/btcusdt@trade           → tek işlemler
  • /ws/btcusdt@depth20@100ms  → order book
  • /ws/btcusdt@aggTrade        → aggregate trades

Tüm modülleri bağlar ve shared state günceller.
"""

import asyncio
import json
import time
import logging
from collections import deque
from typing import Optional

import websockets

from src.config import Config, Signal
from src.detector import WhaleDetector, SignalEngine
from src.anti_manip import AntiManipEngine
from src.risk import RiskManager

logger = logging.getLogger("bot")


class BotState:
    """Tüm modüller bu nesneyi paylaşır. FastAPI buradan okur."""

    def __init__(self):
        self.running:       bool  = True
        self.connected:     bool  = False
        self.started_at:    float = time.time()
        self.tick_count:    int   = 0
        self.last_tick:     float = 0.0
        self.status_msg:    str   = "Başlatılıyor..."
        self.log_lines:     deque = deque(maxlen=80)

    def log(self, msg: str, level: str = "INFO"):
        ts = time.strftime("%H:%M:%S")
        self.log_lines.append({"ts": ts, "level": level, "msg": msg})
        if level == "ERROR":
            logger.error(msg)
        elif level == "WARN":
            logger.warning(msg)
        else:
            logger.info(msg)


# ── Singleton state nesneleri ────────────────────────────────────
state       = BotState()
whale       = WhaleDetector()
signals     = SignalEngine()
anti_manip  = AntiManipEngine()
risk        = RiskManager()


# ────────────────────────────────────────────────────────────────
#  WebSocket handler — Trade stream
# ────────────────────────────────────────────────────────────────

async def _trade_stream():
    url = f"{Config.STREAM_URL}/{Config.SYMBOL.lower()}@aggTrade"
    reconnect_delay = 2

    while state.running:
        try:
            state.log(f"Trade stream bağlanıyor: {url}")
            async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                state.connected = True
                state.log("✓ Trade stream bağlandı", "INFO")
                reconnect_delay = 2

                async for raw in ws:
                    if not state.running:
                        break
                    data = json.loads(raw)
                    await _handle_trade(data)

        except websockets.exceptions.ConnectionClosed as e:
            state.connected = False
            state.log(f"Trade stream koptu ({e.code}), {reconnect_delay}sn sonra yeniden bağlanılıyor", "WARN")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)
        except Exception as e:
            state.connected = False
            state.log(f"Trade stream hata: {e}", "ERROR")
            await asyncio.sleep(reconnect_delay)


async def _handle_trade(data: dict):
    price = float(data.get("p", 0))
    qty   = float(data.get("q", 0))
    is_buy = not data.get("m", True)

    # Anti-manip: wash trade kaydı
    anti_manip.record_trade(price, qty, is_buy)

    # Stop hunt kontrolü
    anti_manip.check_stop_hunt(price)

    # Whale sinyali
    sig = whale.process_trade(data)
    if sig:
        signals.add(sig)
        state.log(f"🐋 {sig.direction} sinyali [{sig.source}] güç={sig.strength:.2f} — {sig.details}")

    # Hacim spike kontrolü
    vol_sig = whale.check_volume_spike()
    if vol_sig:
        signals.add(vol_sig)
        state.log(f"📈 Hacim spike {vol_sig.direction} — {vol_sig.details}")

        # Çok büyük spike → haber kilidi tetikle
        if vol_sig.strength > 0.8:
            anti_manip.trigger_news_lock("Volatilite spike (olası haber)")
            state.log("🔒 Haber kilidi devreye girdi", "WARN")

    # TP/SL kontrol
    closed_now = risk.update_prices(price)
    for t in closed_now:
        emoji = "✅" if t.status == "TP" else "❌"
        state.log(f"{emoji} İşlem kapandı [{t.id}] {t.direction} {t.status} "
                  f"PnL: ${t.pnl:+.2f}", "WARN" if t.pnl < 0 else "INFO")

    # Sinyal değerlendirme → işlem kararı
    decision = signals.evaluate()
    if decision:
        await _try_open_trade(decision)

    state.tick_count += 1
    state.last_tick   = time.time()


# ────────────────────────────────────────────────────────────────
#  WebSocket handler — Order Book stream
# ────────────────────────────────────────────────────────────────

async def _book_stream():
    url = f"{Config.STREAM_URL}/{Config.SYMBOL.lower()}@depth@100ms"
    reconnect_delay = 2

    while state.running:
        try:
            state.log(f"Order book stream bağlanıyor...")
            async with websockets.connect(url, ping_interval=20) as ws:
                state.log("✓ Order book stream bağlandı")
                reconnect_delay = 2

                async for raw in ws:
                    if not state.running:
                        break
                    data = json.loads(raw)

                    # Anti-manip: spoof kontrolü
                    anti_manip.update_order_book(
                        {float(b[0]): float(b[1]) for b in data.get("b", [])},
                        {float(a[0]): float(a[1]) for a in data.get("a", [])}
                    )

                    # Sinyal: imbalance / iceberg
                    sig = whale.process_order_book(data)
                    if sig:
                        signals.add(sig)
                        state.log(f"📊 {sig.direction} sinyali [{sig.source}] — {sig.details}")

        except Exception as e:
            state.log(f"Book stream hata: {e}", "WARN")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)


# ────────────────────────────────────────────────────────────────
#  İşlem açma
# ────────────────────────────────────────────────────────────────

async def _try_open_trade(decision: dict):
    # 1. Anti-manipülasyon kontrolü
    safe, reason = anti_manip.is_safe_to_trade()
    if not safe:
        state.log(f"⚠️  İşlem engellendi (anti-manip): {reason}", "WARN")
        return

    # 2. Risk kontrolü
    trade = risk.open_trade(
        direction=decision["direction"],
        price=decision["price"],
        strength=decision["strength"],
    )
    if not trade:
        ok, msg = risk.can_open(decision["direction"])
        state.log(f"⚠️  İşlem engellendi (risk): {msg}", "WARN")
        return

    sources = ", ".join(decision["sources"])
    state.log(
        f"🟢 İŞLEM AÇILDI [{trade.id}] {trade.direction} "
        f"@ ${trade.entry_price:,.0f} | "
        f"SL: ${trade.stop_loss:,.0f} | TP: ${trade.take_profit:,.0f} | "
        f"Boyut: ${trade.size_usdt:.0f} | Sinyaller: {sources}"
    )


# ────────────────────────────────────────────────────────────────
#  State API (FastAPI tarafından çağrılır)
# ────────────────────────────────────────────────────────────────

def get_full_state() -> dict:
    price = whale.current_price or 0.0
    return {
        "bot": {
            "running":     state.running,
            "connected":   state.connected,
            "uptime_sec":  round(time.time() - state.started_at),
            "tick_count":  state.tick_count,
            "status":      state.status_msg,
            "symbol":      Config.SYMBOL,
        },
        "market":    whale.get_stats(),
        "anti_manip": anti_manip.get_summary(),
        "risk":      risk.stats(price),
        "signals":   signals.recent_signals(30),
        "logs":      list(state.log_lines)[-40:],
        "ts":        time.time(),
    }


# ────────────────────────────────────────────────────────────────
#  Bot başlatma
# ────────────────────────────────────────────────────────────────

async def run_bot():
    state.status_msg = "Çalışıyor"
    state.log(f"🚀 Whale Bot başlatıldı — {Config.SYMBOL} | Testnet modu")
    state.log(f"Balina eşiği: {Config.WHALE_BTC_THRESHOLD} BTC | "
              f"Min sinyal: {Config.MIN_SIGNALS} | "
              f"Anti-manip filtreleri: 5")

    await asyncio.gather(
        _trade_stream(),
        _book_stream(),
    )
