"""
Bot Engine — Ana Orkestratör
WebSocket bağlantıları + tüm modülleri birleştirir.
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
    def __init__(self):
        self.running:    bool  = True
        self.connected:  bool  = False
        self.started_at: float = time.time()
        self.tick_count: int   = 0
        self.last_tick:  float = 0.0
        self.status_msg: str   = "Baslatiliyor..."
        self.log_lines:  deque = deque(maxlen=80)

    def log(self, msg: str, level: str = "INFO"):
        ts = time.strftime("%H:%M:%S")
        self.log_lines.append({"ts": ts, "level": level, "msg": msg})
        getattr(logger, level.lower() if level != "WARN" else "warning")(msg)


state      = BotState()
whale      = WhaleDetector()
signals    = SignalEngine()
anti_manip = AntiManipEngine()
risk       = RiskManager()

# URL listesi: önce birincil, sonra backup denenir
_STREAM_URLS = [
    Config.STREAM_URL,
    Config.STREAM_URL_BACKUP,
]


# ─────────────────────────────────────────
#  Trade Stream
# ─────────────────────────────────────────

async def _trade_stream():
    url_index = 0
    reconnect_delay = 2

    while state.running:
        base_url = _STREAM_URLS[url_index % len(_STREAM_URLS)]
        url = f"{base_url}/{Config.SYMBOL.lower()}@aggTrade"

        try:
            state.log(f"Trade stream baglanıyor: {url}")
            async with websockets.connect(
                url,
                ping_interval=20,
                ping_timeout=10,
                open_timeout=15,
            ) as ws:
                state.connected = True
                state.log(f"Trade stream baglandi ({base_url.split('/')[2]})")
                reconnect_delay = 2

                async for raw in ws:
                    if not state.running:
                        break
                    data = json.loads(raw)
                    await _handle_trade(data)

        except websockets.exceptions.ConnectionClosed as e:
            state.connected = False
            state.log(f"Trade stream koptu (kod:{e.code}), {reconnect_delay}sn sonra tekrar", "WARN")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)

        except OSError as e:
            # DNS / network hatası — backup URL'e gec
            state.connected = False
            url_index += 1
            state.log(
                f"Baglanti hatasi [{base_url.split('/')[2]}]: {e} "
                f"— {'backup URL deneniyor' if url_index % 2 == 1 else 'tekrar birincil URL'}",
                "WARN"
            )
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)

        except Exception as e:
            state.connected = False
            state.log(f"Trade stream beklenmedik hata: {e}", "ERROR")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)


# ─────────────────────────────────────────
#  Order Book Stream
# ─────────────────────────────────────────

async def _book_stream():
    url_index = 0
    reconnect_delay = 2

    while state.running:
        base_url = _STREAM_URLS[url_index % len(_STREAM_URLS)]
        url = f"{base_url}/{Config.SYMBOL.lower()}@depth@100ms"

        try:
            state.log(f"Order book stream baglanıyor: {url}")
            async with websockets.connect(url, ping_interval=20, open_timeout=15) as ws:
                state.log(f"Order book stream baglandi")
                reconnect_delay = 2

                async for raw in ws:
                    if not state.running:
                        break
                    data = json.loads(raw)

                    anti_manip.update_order_book(
                        {float(b[0]): float(b[1]) for b in data.get("b", [])},
                        {float(a[0]): float(a[1]) for a in data.get("a", [])}
                    )

                    sig = whale.process_order_book(data)
                    if sig:
                        signals.add(sig)
                        state.log(f"Sinyal [{sig.source}] {sig.direction} — {sig.details}")

        except OSError as e:
            state.connected = False
            url_index += 1
            state.log(f"Book stream hata: {e}", "WARN")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)

        except Exception as e:
            state.log(f"Book stream hata: {e}", "WARN")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)


# ─────────────────────────────────────────
#  Trade Handler
# ─────────────────────────────────────────

async def _handle_trade(data: dict):
    price  = float(data.get("p", 0))
    qty    = float(data.get("q", 0))
    is_buy = not data.get("m", True)

    anti_manip.record_trade(price, qty, is_buy)
    anti_manip.check_stop_hunt(price)

    sig = whale.process_trade(data)
    if sig:
        signals.add(sig)
        state.log(f"Balina {sig.direction} [{sig.source}] guc={sig.strength:.2f} — {sig.details}")

    vol_sig = whale.check_volume_spike()
    if vol_sig:
        signals.add(vol_sig)
        state.log(f"Hacim spike {vol_sig.direction} — {vol_sig.details}")
        if vol_sig.strength > 0.8:
            anti_manip.trigger_news_lock("Volatilite spike")
            state.log("Haber kilidi devreye girdi", "WARN")

    for t in risk.update_prices(price):
        state.log(
            f"Islem kapandi [{t.id}] {t.direction} {t.status} PnL: ${t.pnl:+.2f}",
            "WARN" if t.pnl < 0 else "INFO"
        )

    decision = signals.evaluate()
    if decision:
        await _try_open_trade(decision)

    state.tick_count += 1
    state.last_tick   = time.time()


# ─────────────────────────────────────────
#  Trade Execution
# ─────────────────────────────────────────

async def _try_open_trade(decision: dict):
    safe, reason = anti_manip.is_safe_to_trade()
    if not safe:
        state.log(f"Islem engellendi (anti-manip): {reason}", "WARN")
        return

    trade = risk.open_trade(decision["direction"], decision["price"], decision["strength"])
    if not trade:
        _, msg = risk.can_open(decision["direction"])
        state.log(f"Islem engellendi (risk): {msg}", "WARN")
        return

    state.log(
        f"ISLEM ACILDI [{trade.id}] {trade.direction} @ ${trade.entry_price:,.0f} "
        f"SL=${trade.stop_loss:,.0f} TP=${trade.take_profit:,.0f} "
        f"Boyut=${trade.size_usdt:.0f} | {', '.join(decision['sources'])}"
    )


# ─────────────────────────────────────────
#  State API
# ─────────────────────────────────────────

def get_full_state() -> dict:
    price = whale.current_price or 0.0
    return {
        "bot": {
            "running":    state.running,
            "connected":  state.connected,
            "uptime_sec": round(time.time() - state.started_at),
            "tick_count": state.tick_count,
            "status":     state.status_msg,
            "symbol":     Config.SYMBOL,
        },
        "market":     whale.get_stats(),
        "anti_manip": anti_manip.get_summary(),
        "risk":       risk.stats(price),
        "signals":    signals.recent_signals(30),
        "logs":       list(state.log_lines)[-40:],
        "ts":         time.time(),
    }


# ─────────────────────────────────────────
#  Bot Start
# ─────────────────────────────────────────

async def run_bot():
    state.status_msg = "Calisiyor"
    state.log(
        f"WhaleBot baslatildi | {Config.SYMBOL} | "
        f"Balina esigi: {Config.WHALE_BTC_THRESHOLD} BTC | "
        f"Primary: {Config.STREAM_URL} | "
        f"Backup: {Config.STREAM_URL_BACKUP}"
    )
    await asyncio.gather(
        _trade_stream(),
        _book_stream(),
    )
