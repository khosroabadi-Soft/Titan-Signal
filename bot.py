#!/usr/bin/env python3
"""bot.py — Titan Signal Live Bot

هر اجرا:
  1) مدیریت لایو سیگنال‌های OPEN (trailing)
  2) تولید سیگنال‌های جدید

Usage:
    python bot.py
"""
from __future__ import annotations

import aiohttp
import asyncio
import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from titansignal.config import SYMBOLS, SCENARIOS, ACTIVE_SCENARIOS
from titansignal.indicators import calculate_rsi, calculate_ema, calculate_macd, calculate_atr
from titansignal.rules import generate_signal
from titansignal.database import init_db, save_signal, has_open_signal
from titansignal.signal_store import tehran_time_str
from titansignal.trailing import process_open_signals
from titansignal.telegram_util import send_telegram, fmt_price, outcome_label

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

KUCOIN_URL = "https://api.kucoin.com/api/v1/market/candles"
INTERVALS = {
    "1m": "1min", "5m": "5min", "15m": "15min",
    "30m": "30min", "1h": "1hour", "4h": "4hour",
}


async def fetch_timeframe(session, symbol, tf, days):
    api_tf = INTERVALS[tf]
    end_time = int(datetime.now(tz=ZoneInfo("UTC")).timestamp())
    start_time = end_time - days * 24 * 3600
    params = {"symbol": symbol, "type": api_tf, "startAt": start_time, "endAt": end_time}
    try:
        async with session.get(KUCOIN_URL, params=params, timeout=30) as resp:
            if resp.status == 200:
                data = await resp.json()
                candles_raw = data.get("data", [])
                parsed = [
                    {"t": int(c[0]), "o": float(c[1]), "c": float(c[2]),
                     "h": float(c[3]), "l": float(c[4]), "v": float(c[5])}
                    for c in candles_raw
                ]
                return tf, list(reversed(parsed))
            logger.warning("HTTP %s for %s %s", resp.status, symbol, tf)
            return tf, []
    except Exception as e:
        logger.error("Error fetching %s %s: %s", symbol, tf, e)
        return tf, []


async def fetch_all_timeframes(session, symbol):
    settings = {"1m": 1, "5m": 3, "15m": 5, "30m": 7, "1h": 14, "4h": 45}
    tasks = [fetch_timeframe(session, symbol, tf, days) for tf, days in settings.items()]
    results = await asyncio.gather(*tasks)
    return {tf: candles for tf, candles in results}


async def notify_exit(item: dict):
    from titansignal.telegram_util import send_telegram, build_exit_message
    reply_id = item.get("telegram_message_id")
    msg = build_exit_message(item)
    await send_telegram(msg, reply_to_message_id=reply_id)



async def process_symbol(symbol, data, idx, total):
    logger.info("[%s/%s] Checking %s...", idx, total, symbol)

    if not data.get("30m") or len(data["30m"]) < 60:
        logger.warning("Insufficient 30m data for %s", symbol)
        return

    closes_30 = [c["c"] for c in data["30m"]]
    ema21_30m = calculate_ema(closes_30, 21)
    ema50_30m = calculate_ema(closes_30, 50)
    ema8_30m = calculate_ema(closes_30, 8)
    if ema21_30m is None or ema50_30m is None:
        return

    direction = "LONG" if ema21_30m > ema50_30m else "SHORT"

    def safe_candle(tf, fallback):
        candles = data.get(tf, [])
        return candles[-1] if candles else {"o": fallback, "c": fallback, "h": fallback, "l": fallback}

    price = closes_30[-1]
    c1m = safe_candle("1m", price)
    c5m = safe_candle("5m", price)
    c15 = safe_candle("15m", price)
    closes_1h = [c["c"] for c in data.get("1h", [])]
    closes_4h = [c["c"] for c in data.get("4h", [])]
    macd_30m = calculate_macd(closes_30)
    rsi_30m = calculate_rsi(closes_30)
    atr_30m = calculate_atr(data["30m"]) if "30m" in data else None

    for scenario_id in ACTIVE_SCENARIOS:
        scenario = SCENARIOS.get(scenario_id)
        if not scenario:
            continue
        if symbol not in (scenario.get("symbols_list") or []):
            continue
        direction_only = scenario.get("direction_only")
        if direction_only and direction != direction_only:
            continue
        if has_open_signal(symbol, direction, scenario_id, within_seconds=scenario.get("cooldown_seconds", 14400)):
            logger.debug("  [%s] %s %s duplicate skip", scenario_id, symbol, direction)
            continue
        try:
            signal = await generate_signal(
                symbol=symbol, direction=direction, prefer_risk="LOW",
                price_30m=price,
                open_15m=c15["o"], close_15m=c15["c"], high_15m=c15["h"], low_15m=c15["l"],
                open_5m=c5m["o"], close_5m=c5m["c"], high_5m=c5m["h"], low_5m=c5m["l"],
                open_1m=c1m["o"], close_1m=c1m["c"], high_1m=c1m["h"], low_1m=c1m["l"],
                ema21_30m=ema21_30m, ema50_30m=ema50_30m, ema8_30m=ema8_30m,
                ema21_1h=calculate_ema(closes_1h, 21) if closes_1h else None,
                ema50_1h=calculate_ema(closes_1h, 50) if closes_1h else None,
                ema21_4h=calculate_ema(closes_4h, 21) if len(closes_4h) >= 21 else None,
                ema50_4h=calculate_ema(closes_4h, 50) if len(closes_4h) >= 50 else None,
                ema200_4h=calculate_ema(closes_4h, 200) if len(closes_4h) >= 200 else None,
                macd_line_30m=macd_30m.get("macd") if macd_30m else None,
                hist_30m=macd_30m.get("histogram") if macd_30m else None,
                rsi_30m=rsi_30m, atr_val_30m=atr_30m or 0.0,
                curr_vol=data["30m"][-1].get("v", 0.0), avg_vol_30m=0.0,
                divergence_detected=False,
                candles=data["30m"], prices_series_30m=closes_30[-120:],
                closes_by_tf=data, scenario_id=scenario_id,
            )
            if signal and signal.get("status") == "SIGNAL":
                logger.info("  SIGNAL: [%s] %s %s @ %s", scenario_id, symbol, signal["direction"], signal["price"])
                db_id = save_signal(
                    symbol=symbol,
                    direction=signal["direction"],
                    scenario_id=scenario_id,
                    scenario_name=f"{scenario.get('name_fa', '')} ({scenario.get('name_en', '')})".strip(),
                    entry_price=signal["price"],
                    stop_loss=signal.get("stop_loss", 0),
                    take_profit=0.0,
                    issued_at_tehran=tehran_time_str(),
                    position_size_usd=scenario.get("margin_usd", 10.0),
                    initial_sl=signal.get("stop_loss", 0),
                    trail_activate=scenario.get("trail_activate", 0.003),
                    trail_lock=scenario.get("trail_lock", 0.90),
                    sl_pct=scenario.get("sl_pct", 0.040),
                    leverage=scenario.get("leverage", 10),
                    margin_usd=scenario.get("margin_usd", 10.0),
                    position_usd=scenario.get("margin_usd", 10.0) * scenario.get("leverage", 10),
                    max_hold_candles=scenario.get("max_hold_candles", 72),
                    telegram_message_id=signal.get("telegram_message_id"),
                )
                if db_id > 0:
                    logger.info("  DB saved: signal_id=%s telegram_message_id=%s", db_id, signal.get("telegram_message_id"))
        except Exception as e:
            logger.error("  Error in %s for %s: %s", scenario_id, symbol, e)


async def main_async():
    init_db()
    from titansignal.version import VERSION_LABEL, __version__
    logger.info("=" * 60)
    logger.info("Titan Signal %s — Live cycle (manage opens + new signals)", VERSION_LABEL)
    logger.info("Scenarios: %s", ", ".join(ACTIVE_SCENARIOS))
    logger.info("Symbols: %s", len(SYMBOLS))
    logger.info("=" * 60)

    # 1) Live management of ALL open signals first
    logger.info("Phase 1: trailing management of OPEN signals...")
    closed = process_open_signals(force_close=False)
    logger.info("Closed in phase 1: %s", len(closed))
    for i, item in enumerate(closed):
        await notify_exit(item)
        if i < len(closed) - 1:
            await asyncio.sleep(1.1)

    # 2) Fetch market data & maybe open new signals
    logger.info("Phase 2: scan for new signals...")
    async with aiohttp.ClientSession() as session:
        # sequential-ish batches to reduce KuCoin 429
        batch = 4
        for start in range(0, len(SYMBOLS), batch):
            chunk = SYMBOLS[start:start + batch]
            tasks = [fetch_all_timeframes(session, sym) for sym in chunk]
            results = await asyncio.gather(*tasks)
            for j, data in enumerate(results):
                idx = start + j + 1
                await process_symbol(chunk[j], data, idx, len(SYMBOLS))
            await asyncio.sleep(0.8)

    logger.info("Titan Signal — Cycle complete")


if __name__ == "__main__":
    asyncio.run(main_async())
