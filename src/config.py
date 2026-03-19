import os
import time
from dataclasses import dataclass, field
from typing import Optional


def _float(key, default):
    try:    return float(os.getenv(key, default))
    except: return float(default)

def _int(key, default):
    try:    return int(os.getenv(key, default))
    except: return int(default)

def _str(key, default):
    return os.getenv(key, default)


class Config:
    # ── Binance URLs ─────────────────────────────────────────────
    TESTNET_BASE_URL  = "https://testnet.binance.vision"
    STREAM_URL        = "wss://stream.binance.vision:9443/ws"
    STREAM_URL_BACKUP = "wss://stream.binance.com:9443/ws"

    # ── API Keys ─────────────────────────────────────────────────
    API_KEY    = _str("BINANCE_TESTNET_KEY",    "DEMO")
    API_SECRET = _str("BINANCE_TESTNET_SECRET", "DEMO")

    # ── Trading ──────────────────────────────────────────────────
    SYMBOL           = _str  ("SYMBOL",           "BTCUSDT")
    TRADE_SIZE_USDT  = _float("TRADE_SIZE_USDT",  100.0)
    MAX_OPEN_TRADES  = _int  ("MAX_OPEN_TRADES",  3)
    STOP_LOSS_PCT    = _float("STOP_LOSS_PCT",    0.8)
    TAKE_PROFIT_PCT  = _float("TAKE_PROFIT_PCT",  1.6)

    # ── Whale Detection ──────────────────────────────────────────
    WHALE_BTC_THRESHOLD  = _float("WHALE_BTC_THRESHOLD",  5.0)
    VOLUME_SPIKE_MULT    = _float("VOLUME_SPIKE_MULT",    3.0)
    IMBALANCE_THRESHOLD  = _float("IMBALANCE_THRESHOLD",  0.68)

    # ── Anti-Manipulation ────────────────────────────────────────
    SPOOF_MIN_LIFETIME_SEC  = _int  ("SPOOF_MIN_LIFETIME_SEC",  15)   # v2: 30→15 (gerçek spoof hızlı)
    WASH_PAIR_WINDOW_SEC    = _int  ("WASH_PAIR_WINDOW_SEC",    3)
    # v2: Sabit $50 yerine dinamik (fiyat*0.0007), bu değer minimum floor
    STOP_HUNT_ROUND_MARGIN  = _float("STOP_HUNT_ROUND_MARGIN",  150.0)  # v2: 50→100
    NEWS_LOCKOUT_SEC        = _int  ("NEWS_LOCKOUT_SEC",        90)
    # v2: 300→500 — aktif BTC piyasasında 5dk'da 300 seviye çekilmek normal
    LAYERING_PULL_THRESHOLD = _int  ("LAYERING_PULL_THRESHOLD", 500)

    # ── Signal Engine ────────────────────────────────────────────
    MIN_SIGNALS       = _int("MIN_SIGNALS",       2)
    SIGNAL_WINDOW_SEC = _int("SIGNAL_WINDOW_SEC", 30)
    MIN_FILTER_PASS   = _int("MIN_FILTER_PASS",   3)

    # ── Risk ─────────────────────────────────────────────────────
    STARTING_BALANCE     = _float("STARTING_BALANCE",     10000.0)
    DAILY_LOSS_LIMIT_PCT = _float("DAILY_LOSS_LIMIT_PCT", 3.0)

    # ── Canli reload interval ─────────────────────────────────────
    CONFIG_RELOAD_SEC = _int("CONFIG_RELOAD_SEC", 30)


def reload_config():
    mapping = {
        "TRADE_SIZE_USDT":        (_float, 100.0),
        "MAX_OPEN_TRADES":        (_int,   3),
        "STOP_LOSS_PCT":          (_float, 0.8),
        "TAKE_PROFIT_PCT":        (_float, 1.6),
        "WHALE_BTC_THRESHOLD":    (_float, 5.0),
        "VOLUME_SPIKE_MULT":      (_float, 3.0),
        "IMBALANCE_THRESHOLD":    (_float, 0.68),
        "SPOOF_MIN_LIFETIME_SEC": (_int,   15),
        "WASH_PAIR_WINDOW_SEC":   (_int,   3),
        "STOP_HUNT_ROUND_MARGIN": (_float, 150.0),
        "NEWS_LOCKOUT_SEC":       (_int,   90),
        "LAYERING_PULL_THRESHOLD":(_int,   500),
        "MIN_SIGNALS":            (_int,   2),
        "SIGNAL_WINDOW_SEC":      (_int,   30),
        "MIN_FILTER_PASS":        (_int,   3),
        "DAILY_LOSS_LIMIT_PCT":   (_float, 3.0),
        "CONFIG_RELOAD_SEC":      (_int,   30),
    }
    changed = []
    for key, (fn, default) in mapping.items():
        new_val = fn(key, default)
        old_val = getattr(Config, key, None)
        if old_val != new_val:
            setattr(Config, key, new_val)
            changed.append(f"{key}: {old_val} → {new_val}")
    return changed


# ── Shared data models ───────────────────────────────────────────

@dataclass
class Signal:
    source:    str
    direction: str
    strength:  float
    price:     float
    timestamp: float = field(default_factory=time.time)
    details:   str   = ""


@dataclass
class ManipFlag:
    flag_type: str
    severity:  str
    detail:    str
    timestamp: float = field(default_factory=time.time)


@dataclass
class Trade:
    id:          str
    direction:   str
    entry_price: float
    size_usdt:   float
    stop_loss:   float
    take_profit: float
    open_time:   float = field(default_factory=time.time)
    status:      str   = "OPEN"
    pnl:         float = 0.0
    close_price: float = 0.0
    close_time:  Optional[float] = None
