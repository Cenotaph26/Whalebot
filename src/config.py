import os
import time
from dataclasses import dataclass, field
from typing import Optional


class Config:
    # ── Binance Testnet ──────────────────────────────────────────
    TESTNET_BASE_URL   = "https://testnet.binance.vision"
    STREAM_URL         = "wss://stream.binance.vision/ws"   # public market data

    # ── Trading ──────────────────────────────────────────────────
    SYMBOL             = "BTCUSDT"
    TRADE_SIZE_USDT    = 100.0
    MAX_OPEN_TRADES    = 3
    STOP_LOSS_PCT      = 0.8         # %0.8 stop
    TAKE_PROFIT_PCT    = 1.6         # %1.6 TP  (2:1 R:R)

    # ── Whale Detection ──────────────────────────────────────────
    WHALE_BTC_THRESHOLD  = 5.0       # tek işlemde ≥5 BTC → balina
    VOLUME_SPIKE_MULT    = 3.0       # 3× baseline hacim → spike
    IMBALANCE_THRESHOLD  = 0.68      # bid/(bid+ask) > 0.68 → LONG baskı

    # ── Anti-Manipulation Filters ────────────────────────────────
    SPOOF_MIN_LIFETIME_SEC  = 30     # emir en az 30 sn yaşamalı → gerçek
    WASH_PAIR_WINDOW_SEC    = 3      # 3 sn içinde eşit alım/satım → wash
    STOP_HUNT_ROUND_MARGIN  = 50     # round sayıya $50 yakınlık → tehlike
    NEWS_LOCKOUT_SEC        = 90     # haber sonrası 90 sn dur
    LAYERING_PULL_THRESHOLD = 8      # 5 dk'da 8+ seviye çekilirse → layering

    # ── Signal Engine ────────────────────────────────────────────
    MIN_SIGNALS          = 2         # en az 2 sinyal aynı anda
    SIGNAL_WINDOW_SEC    = 30        # 30 sn içinde olmalı
    MIN_FILTER_PASS      = 3         # 5 filtreden en az 3'ü geçmeli

    # ── Risk ─────────────────────────────────────────────────────
    STARTING_BALANCE     = 10_000.0  # testnet sanal bakiye
    DAILY_LOSS_LIMIT_PCT = 3.0       # günlük %3 → bot durur

    # ── API Keys (Railway env vars'tan okunur) ───────────────────
    API_KEY    = os.getenv("BINANCE_TESTNET_KEY",    "DEMO")
    API_SECRET = os.getenv("BINANCE_TESTNET_SECRET", "DEMO")


# ── Shared data models ───────────────────────────────────────────

@dataclass
class Signal:
    source:    str    # whale_trade | volume_spike | imbalance | iceberg
    direction: str    # LONG | SHORT
    strength:  float  # 0.0–1.0
    price:     float
    timestamp: float = field(default_factory=time.time)
    details:   str   = ""


@dataclass
class ManipFlag:
    flag_type: str    # spoof | wash | stop_hunt | news_lock | layering
    severity:  str    # LOW | MEDIUM | HIGH
    detail:    str
    timestamp: float = field(default_factory=time.time)


@dataclass
class Trade:
    id:           str
    direction:    str    # LONG | SHORT
    entry_price:  float
    size_usdt:    float
    stop_loss:    float
    take_profit:  float
    open_time:    float  = field(default_factory=time.time)
    status:       str    = "OPEN"   # OPEN | TP | SL | MANUAL
    pnl:          float  = 0.0
    close_price:  float  = 0.0
    close_time:   Optional[float] = None
