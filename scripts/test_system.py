#!/usr/bin/env python3
"""Smoke test: CSV signals + market DB."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from titansignal.database import init_db, save_candles, get_candles
from titansignal.signal_store import save_signal, get_open_signals, update_signal_exit, tehran_time_str

init_db()
print("DB init OK")

n = save_candles("BTC-USDT", "1m", [
    {"t": 1700000000, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10},
    {"t": 1700000060, "o": 1.5, "h": 2.5, "l": 1.0, "c": 2.0, "v": 12},
])
print("candles saved", n)
bars = get_candles("BTC-USDT", "1m", limit=10)
print("candles loaded", len(bars))

sid = save_signal(
    symbol="TEST-USDT", direction="LONG", scenario_id="S1", scenario_name="Test",
    entry_price=100.0, stop_loss=96.0, take_profit=0.0,
    issued_at_tehran=tehran_time_str(), initial_sl=96.0,
    trail_activate=0.003, trail_lock=0.9, leverage=10, margin_usd=10, position_usd=100,
    max_hold_candles=72, telegram_message_id=12345,
)
print("signal_id", sid)
opens = get_open_signals(days=1)
print("opens", len(opens), [s.symbol for s in opens if s.symbol=="TEST-USDT"])
ok = update_signal_exit(
    signal_id=sid, exit_price=101.0, outcome="TRAIL_STOP",
    broker_fee=0.2, final_pnl_usd=0.5, return_pct=0.5,
    symbol="TEST-USDT", direction="LONG", scenario_id="S1",
    issued_at_tehran=[s.issued_at_tehran for s in opens if s.id==sid][0] if any(s.id==sid for s in opens) else tehran_time_str(),
)
print("exit", ok)
opens2 = get_open_signals(days=1)
print("opens after", [s.symbol for s in opens2 if s.symbol=="TEST-USDT"])
assert not any(s.id==sid and s.symbol=="TEST-USDT" for s in opens2)
print("ALL TEST OK")
