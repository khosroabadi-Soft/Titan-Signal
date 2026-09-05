#!/usr/bin/env python3
"""Test all critical components of Titan Signal V3.1."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('TITAN_DATABASE_URL', 'sqlite:///data/test_signal.db')

from titansignal.database import init_db, save_signal, get_open_signals, update_signal_exit

print('=== Testing Database ===')
init_db()

sid = save_signal(
    symbol='BTC-USDT', direction='LONG', scenario_id='S1', scenario_name='Prometheus',
    entry_price=65000.0, stop_loss=65000*0.96, take_profit=0.0, initial_sl=65000*0.96,
    trail_activate=0.003, trail_lock=0.90, max_hold_candles=72,
    leverage=10, margin_usd=10.0, position_usd=100.0,
    issued_at_tehran='2026-09-01 12:00:00', issued_at_unix=1725172800,
)
print(f'  Saved signal id={sid}')
assert sid > 0

opens = get_open_signals(days=7)
print(f'  Open signals: {len(opens)}')
assert len(opens) == 1
s = opens[0]
print(f'  {s.symbol} {s.direction} SL={s.initial_sl:.0f} trail={s.trail_activate}/{s.trail_lock}')
assert s.initial_sl == 65000 * 0.96
assert s.leverage == 10
assert s.position_usd == 100.0

update_signal_exit(
    signal_id=sid, exit_price=65500.0, outcome='TRAIL_STOP',
    broker_fee=0.20, final_pnl_usd=0.77, return_pct=0.77, margin_roi_pct=7.7,
    status='CLOSED',
)
opens2 = get_open_signals(days=7)
assert len(opens2) == 0
print('  Exit updated, no more open signals')

os.remove('data/test_signal.db')
print('Database: PASS\n')

# Test indicators
print('=== Testing Indicators ===')
from titansignal.indicators import calculate_adx, calculate_rsi, calculate_ema
import random
random.seed(42)
candles = []
price = 100.0
for i in range(336):
    change = random.gauss(0, 0.5)
    candles.append({'h': price+abs(change)+1, 'l': price-abs(change)-1, 'c': price+change, 'o': price})
    price += change

adx, dip, dim = calculate_adx(candles)
print(f'  ADX={adx} (0-100: {0<=adx<=100})')
assert 0 <= adx <= 100

rsi = calculate_rsi([c['c'] for c in candles])
print(f'  RSI={rsi:.1f} (0-100: {0<=rsi<=100})')
assert 0 <= rsi <= 100

ema = calculate_ema([c['c'] for c in candles], 21)
print(f'  EMA21={ema:.2f}')
assert ema is not None
print('Indicators: PASS\n')

# Test config
print('=== Testing Config ===')
from titansignal.config import SCENARIOS, LEVERAGE, MARGIN_USD, POSITION_USD, FEE_PER_TRADE
assert LEVERAGE == 10 and MARGIN_USD == 10.0 and POSITION_USD == 100.0 and FEE_PER_TRADE == 0.20
for sid, sc in SCENARIOS.items():
    assert sc['sl_pct'] == 0.04, f'{sid} sl_pct != 0.04'
    assert 'trail_activate' in sc
    assert 'trail_lock' in sc
    assert 'max_hold_candles' in sc
    print(f'  {sid}: SL=4% trail_act={sc["trail_activate"]*100}% lock={sc["trail_lock"]*100}% hold={sc["max_hold_candles"]}')
print('Config: PASS\n')

# Test RSI filter
print('=== Testing V3.1 RSI Filter ===')
from titansignal.v31_filters import rsi_zone
from titansignal.config import RSI_LONG_ZONE, RSI_SHORT_ZONE
assert rsi_zone('LONG', 50, RSI_LONG_ZONE, RSI_SHORT_ZONE) == True
assert rsi_zone('LONG', 38, RSI_LONG_ZONE, RSI_SHORT_ZONE) == False
assert rsi_zone('SHORT', 45, RSI_LONG_ZONE, RSI_SHORT_ZONE) == True
assert rsi_zone('SHORT', 30, RSI_LONG_ZONE, RSI_SHORT_ZONE) == False
print(f'  LONG zone: {RSI_LONG_ZONE}')
print(f'  SHORT zone: {RSI_SHORT_ZONE}')
print('RSI Filter: PASS\n')

# Test trailing stop
print('=== Testing Trailing Stop ===')
entry = 100.0
sl = entry * 0.96
trail_candles = [
    {'t': 1, 'h': 100.5, 'l': 99.5, 'c': 100.3},
    {'t': 2, 'h': 101.0, 'l': 100.2, 'c': 100.8},
    {'t': 3, 'h': 101.5, 'l': 100.5, 'c': 101.0},
    {'t': 4, 'h': 101.4, 'l': 100.0, 'c': 100.5},
    {'t': 5, 'h': 101.2, 'l': 99.5, 'c': 100.0},
]
trail_active = False; max_fav = entry; outcome = None; exit_price = None
for c in trail_candles:
    if c['l'] <= sl: outcome='STOP_HIT'; exit_price=sl; break
    if c['h'] > max_fav: max_fav = c['h']
    if not trail_active:
        if max_fav >= entry * 1.003: trail_active = True
    else:
        ts = entry + (max_fav - entry) * 0.90
        if c['l'] <= ts: outcome='TRAIL_STOP'; exit_price=ts; break

print(f'  Outcome: {outcome}, Exit: {exit_price}')
assert outcome == 'TRAIL_STOP'

net = 100.0 * (exit_price - entry) / entry - 0.20
print(f'  Net PnL: ${net:.4f}')
assert net > 0
print('Trailing Stop: PASS\n')

print('=' * 50)
print('ALL TESTS PASSED!')
print('=' * 50)
