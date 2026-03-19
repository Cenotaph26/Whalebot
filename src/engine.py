"""
Bot Engine — Ana Orkestrator  v5.0
────────────────────────────────────
v5.0: update_order_book'a current_price geçirilir (spoof proximity check için)
"""

import asyncio
import json
import time
import logging
from collections import deque

import websockets

from src.config import Config, reload_config
from src.detector import WhaleDetector, SignalEngine
from src.anti_manip import AntiManipEngine
from src.risk import RiskManager

logger = logging.getLogger("bot")


class BotState:
    def __init__(self):
        self.running:       bool  = True
        self.connected:     bool  = False
        self.started_at:    float = time.time()
        self.tick_count:    int   = 0
        self.last_tick:     float = 0.0
        self.status_msg:    str   = "Baslatiliyor..."
        self.last_reload:   float = 0.0
        self.log_lines:     deque = deque(maxlen=80)
        self._last_block_log:    float = 0.0
        self._last_block_reason: str   = ""

    def log(self, msg: str, level: str = "INFO"):
        ts = time.strftime("%H:%M:%S")
        self.log_lines.append({"ts": ts, "level": level, "msg": msg})
        getattr(logger, level.lower() if level != "WARN" else "warning")(msg)

    def log_block(self, reason: str, level: str = "WARN"):
        """Engelleme mesajlarını 30sn'de bir logla."""
        now = time.time()
        if reason != self._last_block_reason or now - self._last_block_log > 30:
            self.log(reason, level)
            self._last_block_log    = now
            self._last_block_reason = reason


state      = BotState()
whale      = WhaleDetector()
signals    = SignalEngine()
anti_manip = AntiManipEngine()
risk       = RiskManager()

_STREAM_URLS = [Config.STREAM_URL, Config.STREAM_URL_BACKUP]


async def _config_reload_loop():
    await asyncio.sleep(10)
    while state.running:
        try:
            interval = Config.CONFIG_RELOAD_SEC
            changed  = reload_config()
            if changed:
                for c in changed:
                    state.log(f"Config guncellendi: {c}", "WARN")
            state.last_reload = time.time()
        except Exception as e:
            state.log(f"Config reload hatasi: {e}", "ERROR")
        await asyncio.sleep(interval)


async def _trade_stream():
    url_index       = 0
    reconnect_delay = 2

    while state.running:
        base = _STREAM_URLS[url_index % len(_STREAM_URLS)]
        url  = f"{base}/{Config.SYMBOL.lower()}@aggTrade"
        try:
            state.log(f"Trade stream baglanıyor: {url}")
            async with websockets.connect(url, ping_interval=20, open_timeout=15) as ws:
                state.connected = True
                state.log("Trade stream baglandi")
                reconnect_delay = 2
                async for raw in ws:
                    if not state.running:
                        break
                    await _handle_trade(json.loads(raw))

        except websockets.exceptions.ConnectionClosed as e:
            state.connected = False
            state.log(f"Trade stream koptu (kod:{e.code}), {reconnect_delay}sn sonra tekrar", "WARN")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)

        except OSError as e:
            state.connected = False
            url_index += 1
            state.log(f"Baglanti hatasi, backup URL deneniyor: {e}", "WARN")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)

        except Exception as e:
            state.connected = False
            state.log(f"Trade stream beklenmedik hata: {e}", "ERROR")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)


async def _book_stream():
    url_index       = 0
    reconnect_delay = 2

    while state.running:
        base = _STREAM_URLS[url_index % len(_STREAM_URLS)]
        url  = f"{base}/{Config.SYMBOL.lower()}@depth@100ms"
        try:
            async with websockets.connect(url, ping_interval=20, open_timeout=15) as ws:
                reconnect_delay = 2
                async for raw in ws:
                    if not state.running:
                        break
                    data = json.loads(raw)
                    # v5: current_price geçirilir — spoof proximity check için
                    anti_manip.update_order_book(
                        {float(b[0]): float(b[1]) for b in data.get("b", [])},
                        {float(a[0]): float(a[1]) for a in data.get("a", [])},
                        current_price=whale.current_price
                    )
                    sig = whale.process_order_book(data)
                    if sig:
                        added = signals.add(sig)
                        if added:
                            state.log(f"Sinyal [{sig.source}] {sig.direction} — {sig.details}")

        except OSError as e:
            url_index += 1
            state.log(f"Book stream hata, backup deneniyor: {e}", "WARN")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)

        except Exception as e:
            state.log(f"Book stream hata: {e}", "WARN")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)


async def _handle_trade(data: dict):
    price  = float(data.get("p", 0))
    qty    = float(data.get("q", 0))
    is_buy = not data.get("m", True)

    anti_manip.record_trade(price, qty, is_buy)
    anti_manip.check_stop_hunt(price)

    sig = whale.process_trade(data)
    if sig:
        added = signals.add(sig)
        if added:
            state.log(f"Balina {sig.direction} [{sig.source}] guc={sig.strength:.2f} — {sig.details}")

    vol_sig = whale.check_volume_spike()
    if vol_sig:
        added = signals.add(vol_sig)
        if added:
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


async def _try_open_trade(decision: dict):
    safe, reason = anti_manip.is_safe_to_trade()
    if not safe:
        state.log_block(f"Islem engellendi (anti-manip): {reason}")
        return

    trade = risk.open_trade(decision["direction"], decision["price"], decision["strength"])
    if not trade:
        _, msg = risk.can_open(decision["direction"])
        state.log_block(f"Islem engellendi (risk): {msg}")
        return

    state.log(
        f"ISLEM ACILDI [{trade.id}] {trade.direction} @ ${trade.entry_price:,.0f} "
        f"SL=${trade.stop_loss:,.0f} TP=${trade.take_profit:,.0f} "
        f"Boyut=${trade.size_usdt:.0f} | {', '.join(decision['sources'])}"
    )


def get_full_state() -> dict:
    price = whale.current_price or 0.0
    now   = time.time()
    return {
        "bot": {
            "running":       state.running,
            "connected":     state.connected,
            "uptime_sec":    round(now - state.started_at),
            "tick_count":    state.tick_count,
            "status":        state.status_msg,
            "symbol":        Config.SYMBOL,
            "last_reload":   round(now - state.last_reload) if state.last_reload else None,
        },
        "config": {
            "LAYERING_PULL_THRESHOLD": Config.LAYERING_PULL_THRESHOLD,
            "MIN_SIGNALS":             Config.MIN_SIGNALS,
            "WHALE_BTC_THRESHOLD":     Config.WHALE_BTC_THRESHOLD,
            "STOP_LOSS_PCT":           Config.STOP_LOSS_PCT,
            "TAKE_PROFIT_PCT":         Config.TAKE_PROFIT_PCT,
            "TRADE_SIZE_USDT":         Config.TRADE_SIZE_USDT,
            "DAILY_LOSS_LIMIT_PCT":    Config.DAILY_LOSS_LIMIT_PCT,
            "CONFIG_RELOAD_SEC":       Config.CONFIG_RELOAD_SEC,
        },
        "market":     whale.get_stats(),
        "anti_manip": anti_manip.get_summary(),
        "risk":       risk.stats(price),
        "signals":    signals.recent_signals(30),
        "logs":       list(state.log_lines)[-40:],
        "ts":         now,
    }


async def run_bot():
    state.status_msg = "Calisiyor"
    state.log(
        f"WhaleBot v5 baslatildi | {Config.SYMBOL} | "
        f"Layering esigi: {Config.LAYERING_PULL_THRESHOLD} | "
        f"Config reload: her {Config.CONFIG_RELOAD_SEC}sn"
    )
    await asyncio.gather(
        _trade_stream(),
        _book_stream(),
        _config_reload_loop(),
    )
