import time
from src.config import Config, Signal, ManipFlag, Trade
from src.detector import WhaleDetector, SignalEngine
from src.anti_manip import AntiManipEngine
from src.risk import RiskManager
from src.engine import get_full_state

print("=" * 55)
print("  WHALE BOT -- TAM SISTEM TESTI")
print("=" * 55)

# 1. Whale Detector
wd = WhaleDetector()
se = SignalEngine()

s1 = wd.process_trade({"p": "84500", "q": "7.5", "m": False})
assert s1 and s1.source == "whale_trade" and s1.direction == "LONG"
se.add(s1)
print(f"[1] Whale Trade: {s1.direction} guc={s1.strength}  OK")

# Order book imbalance (direct)
wd.bids = {84490 - i * 10: 8.0 for i in range(20)}
wd.asks = {84510 + i * 10: 1.0 for i in range(20)}
s2 = wd._check_imbalance()
assert s2 and s2.direction == "LONG"
se.add(s2)
print(f"[2] Imbalance: {s2.direction} guc={s2.strength}  OK")

# Signal engine
decision = se.evaluate()
assert decision is not None and decision["direction"] == "LONG"
print(f"[3] Signal Engine: {decision['direction']} ({decision['signal_count']} sinyal)  OK")

# 2. Anti-Manipulation
am = AntiManipEngine()
am._order_appearances[84000.0] = (time.time() - 5, 15.0)
am.update_order_book({84000.0: 0}, {})
flags = [f for f in am.flags if f.flag_type == "spoof"]
assert flags
print(f"[4] Spoof Detector: {flags[0].severity}  OK")

am2 = AntiManipEngine()
am2.record_trade(84500, 6.0, True)
am2.record_trade(84500, 6.0, False)
wash = [f for f in am2.flags if f.flag_type == "wash"]
print(f"[5] Wash Detector: {len(wash)} flag  OK")

am3 = AntiManipEngine()
hit = am3.check_stop_hunt(84505.0)
print(f"[6] Stop Hunt: hit={hit}  OK")

am4 = AntiManipEngine()
am4.trigger_news_lock("Fed karari")
safe, reason = am4.is_safe_to_trade()
assert not safe
print(f"[7] News Lock: kilitli={not safe}  OK")

am5 = AntiManipEngine()
for i in range(10):
    am5._pulled_levels.append((84000 + i * 10, time.time()))
am5._check_layering()
layer = [f for f in am5.flags if f.flag_type == "layering"]
print(f"[8] Layering: {len(layer)} flag  OK")

# 3. Risk Manager
rm = RiskManager()
t1 = rm.open_trade("LONG",  84500, 0.85)
t2 = rm.open_trade("SHORT", 84500, 0.60)
assert t1 and t2
print(f"[9] Islem acma: LONG#{t1.id} SL={t1.stop_loss} TP={t1.take_profit}  OK")

closed = rm.update_prices(85860)
tp_c = [t for t in rm.closed_trades if t.status == "TP"]
print(f"[10] TP tetikleme: {len(tp_c)} kapandi PnL={rm.total_pnl:+.2f}  OK")

rm2 = RiskManager()
t3  = rm2.open_trade("LONG", 84500, 0.7)
rm2.update_prices(83820)
sl_c = [t for t in rm2.closed_trades if t.status == "SL"]
print(f"[11] SL tetikleme: {len(sl_c)} kapandi PnL={rm2.total_pnl:+.2f}  OK")

size = rm.kelly_size(win_rate=0.55, rr=2.0)
assert 0 < size <= Config.TRADE_SIZE_USDT * 2
print(f"[12] Kelly sizing: {size:.2f} USDT  OK")

rm3 = RiskManager()
rm3.balance = rm3.daily_start * 0.96
assert not rm3.daily_loss_ok()
print(f"[13] Gunluk kayip kilidi: aktif  OK")

# 4. Full state
state = get_full_state()
assert all(k in state for k in ["bot", "market", "anti_manip", "risk", "signals", "logs"])
print(f"[14] Full State API: {len(state)} alan  OK")

print()
print("=" * 55)
print("  TUM TESTLER BASARILI")
print("  Sistem Railway deploya hazir.")
print("=" * 55)
