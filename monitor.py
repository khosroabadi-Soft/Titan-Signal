#!/usr/bin/env python3
"""monitor.py — Live trail management + night force-close + daily report.

V4.2.0 OperationalWindows:
  Modes (env TITAN_MONITOR_MODE):
    manage  — process open signals with trailing (default)
    final   — trail + EOD force-close remaining + full day report + open warning

  Time windows (Tehran):
    07:00–18:00  صدور سیگنال جدید + مدیریت
    18:00–02:00  فقط مدیریت سیگنال‌های باز
    02:00        بستن اجباری (force-close) در حالت final

Usage:
  python monitor.py
  TITAN_MONITOR_MODE=final python monitor.py
"""
from __future__ import annotations

import asyncio
import csv
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from titansignal.config import (
    LEVERAGE, MARGIN_USD, POSITION_USD, FEE_PER_TRADE,
    SIGNAL_WINDOW_START, SIGNAL_WINDOW_END,
)
from titansignal.database import init_db
from titansignal.signal_store import get_open_signals

from titansignal.signal_store import tehran_time_str, daily_csv_path, _read_csv
from titansignal.version import VERSION_LABEL, __version__
from titansignal.trailing import process_open_signals
from titansignal.telegram_util import (
    send_telegram, fmt_price, outcome_label, build_exit_message, scenario_full_name,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)
TEHRAN_TZ = ZoneInfo("Asia/Tehran")


def tehran_now():
    return datetime.now(TEHRAN_TZ)


def get_closed_signals_for_date(report_date: str) -> list:
    """Read ALL closed signals for the given date from CSV.

    This is the FIX for the zero-report bug: previously monitor only
    counted signals closed in the current run (process_open_signals),
    missing signals closed earlier in the day by bot.py's trailing.
    Now we read the full day's CSV to get all closed signals.
    """
    path = daily_csv_path(report_date)
    if not os.path.isfile(path):
        logger.warning("No CSV file for date %s at %s", report_date, path)
        return []

    _, rows = _read_csv(path)
    closed = []
    for row in rows:
        status = (row.get("status") or "").upper()
        if status != "CLOSED":
            continue

        # Parse numeric fields from CSV
        def fget(key, default=0.0):
            v = row.get(key, "")
            if v is None or v == "":
                return default
            try:
                return float(v)
            except (TypeError, ValueError):
                return default

        closed.append({
            "signal_id": row.get("signal_id", ""),
            "symbol": row.get("symbol", ""),
            "direction": row.get("direction", ""),
            "scenario_id": row.get("scenario_id", ""),
            "scenario_name": row.get("scenario_name", ""),
            "entry_price": fget("entry_price"),
            "exit_price": fget("hit_price"),
            "outcome": row.get("outcome", ""),
            "net_pnl": fget("final_pnl_usd"),  # CSV stores as final_pnl_usd
            "return_pct": fget("return_pct"),
            "issued_at_tehran": row.get("issued_at_tehran", ""),
            "hit_time_tehran": row.get("hit_time_tehran", ""),
        })

    logger.info("Loaded %d closed signals from CSV for %s", len(closed), report_date)
    return closed


def build_daily_report(report_date: str, closed_today: list, still_open: list) -> str:
    """Build the daily Telegram report from all closed signals of the day."""
    stops = sum(1 for x in closed_today if x.get("outcome") == "STOP_HIT")
    trails = sum(1 for x in closed_today if x.get("outcome") == "TRAIL_STOP")
    holds = sum(1 for x in closed_today if x.get("outcome") == "MAX_HOLD")
    forces = sum(1 for x in closed_today if x.get("outcome") == "EOD_FORCE_CLOSE")
    wins = sum(1 for x in closed_today if (x.get("net_pnl") or 0) > 0)
    losses = sum(1 for x in closed_today if (x.get("net_pnl") or 0) < 0)
    be = sum(1 for x in closed_today if (x.get("net_pnl") or 0) == 0)
    pnl = sum(x.get("net_pnl") or 0 for x in closed_today)
    closed_n = len(closed_today)
    wr = (wins / closed_n * 100) if closed_n else 0.0

    lines = [
        "════════════════════",
        f"📊 <b>گزارش روزانه Titan Signal</b>",
        f"📅 تاریخ: <b>{report_date}</b>",
        f"🕐 {tehran_time_str()}",
        f"📌 نسخه: <b>{VERSION_LABEL}</b>",
        "════════════════════",
        "",
        f"📦 بسته‌شده امروز: <b>{closed_n}</b>",
        f"   🔴 استاپ اولیه: {stops}",
        f"   🟢 خروج تریل: {trails}",
        f"   ⏰ سقف زمان: {holds}",
        f"   ⚠️ بستن اجباری پایان‌روز (EOD): {forces}",
        "",
        f"✅ برد: {wins} | ❌ باخت: {losses} | ➖ بریک‌ایون: {be}",
        f"🎯 نرخ برد (بسته): <b>{wr:.1f}%</b>",
        f"💰 PnL خالص روز: <b>{pnl:+.4f}$</b>",
        f"(اهرم {LEVERAGE}x | مارجین ${MARGIN_USD:.0f} | پوزیشن ${POSITION_USD:.0f} | کارمزد ${FEE_PER_TRADE:.2f})",
        "",
    ]

    # Per-scenario breakdown
    if closed_today:
        sc_stats = defaultdict(lambda: {"count": 0, "wins": 0, "pnl": 0.0})
        for x in closed_today:
            sid = x.get("scenario_id") or "—"
            sc_stats[sid]["count"] += 1
            if (x.get("net_pnl") or 0) > 0:
                sc_stats[sid]["wins"] += 1
            sc_stats[sid]["pnl"] += (x.get("net_pnl") or 0)

        lines.append("── عملکرد سناریوها ──")
        for sid in sorted(sc_stats.keys()):
            s = sc_stats[sid]
            s_wr = (s["wins"] / s["count"] * 100) if s["count"] else 0
            s_name = scenario_full_name(sid)
            lines.append(
                f"  [{sid}] {s_name}: {s['count']} سیگنال | "
                f"نرخ برد {s_wr:.0f}% | PnL {s['pnl']:+.4f}$"
            )
        lines.append("")

    # Exit details
    if closed_today:
        lines.append("── جزئیات خروج‌ها ──")
        for item in sorted(closed_today, key=lambda x: x.get("net_pnl") or 0, reverse=True)[:40]:
            pe = "➕" if (item.get("net_pnl") or 0) >= 0 else "➖"
            lines.append(
                f"{pe} {item['symbol']} {item['direction']} {scenario_full_name(item.get('scenario_id'), item.get('scenario_name'))} "
                f"{outcome_label(item.get('outcome', ''))} | "
                f"{fmt_price(item.get('entry_price'))}→{fmt_price(item.get('exit_price'))} | "
                f"{(item.get('net_pnl') or 0):+.4f}$"
            )
        if len(closed_today) > 40:
            lines.append(f"… و {len(closed_today) - 40} مورد دیگر")

    lines.append("")
    if still_open:
        lines.append("⚠️ <b>هشدار — سیگنال‌های هنوز باز</b>")
        lines.append(f"تعداد باز: <b>{len(still_open)}</b>")
        for sig in still_open[:25]:
            lines.append(
                f"• {sig.symbol} {sig.direction} {scenario_full_name(sig.scenario_id, sig.scenario_name)} "
                f"ورود {fmt_price(sig.entry_price)} | {sig.issued_at_tehran}"
            )
        if len(still_open) > 25:
            lines.append(f"… و {len(still_open) - 25} مورد دیگر")
        lines.append("")
        lines.append(
            "❗️ <b>مسئولیت مدیریت/بستن این موقعیت‌ها با خود شماست.</b>\n"
            "سیستم تلاش کرد با تریل و بستن اجباری پایان‌روز تکلیف را مشخص کرد؛ "
            "موارد باقی‌مانده خارج از کنترل خودکار تلقی می‌شوند."
        )
    else:
        lines.append("✅ هیچ سیگنال بازی باقی نمانده است.")

    lines.append("")
    lines.append(f"— Titan Signal {VERSION_LABEL} —")
    return "\n".join(lines)


async def notify_exits(closed: list):
    """Send individual exit cards; reply to original signal when possible."""
    for i, item in enumerate(closed):
        reply_id = item.get("telegram_message_id")
        await send_telegram(build_exit_message(item), reply_to_message_id=reply_id)
        if i < len(closed) - 1:
            await asyncio.sleep(1.2)


async def main_async():
    mode = (os.getenv("TITAN_MONITOR_MODE") or "manage").strip().lower()
    force = mode in ("final", "force", "eod", "night")
    init_db()
    now = tehran_now()
    report_date = now.strftime("%Y-%m-%d")

    logger.info("=" * 60)
    logger.info("Titan Monitor %s mode=%s force_close=%s date=%s", VERSION_LABEL, mode, force, report_date)
    logger.info("Signal window: %02d:00–%02d:00 Tehran", SIGNAL_WINDOW_START, SIGNAL_WINDOW_END)
    logger.info("=" * 60)

    # Phase 1: trailing management of open signals
    closed_this_run = process_open_signals(force_close=force)
    logger.info("Closed this run: %d", len(closed_this_run))

    if closed_this_run and not force:
        # daytime manage: notify each exit
        await notify_exits(closed_this_run)
    elif closed_this_run and force:
        # final run: short notice then full report
        await notify_exits(closed_this_run[:15])  # cap flood
        if len(closed_this_run) > 15:
            await send_telegram(
                f"ℹ️ {len(closed_this_run) - 15} خروج دیگر در گزارش روزانه آمده است."
            )

    still_open = get_open_signals(days=7)
    logger.info("Still OPEN: %d", len(still_open))

    # Phase 2: Build daily report from CSV (ALL closed signals today, not just this run)
    # This fixes the zero-report bug
    if force:
        # Read ALL closed signals for today from CSV
        closed_today = get_closed_signals_for_date(report_date)

        # Also check yesterday's CSV for signals that might have been closed today
        # (e.g., EOD force-close run at 02:00 closes signals from previous day)
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        closed_yesterday = get_closed_signals_for_date(yesterday)

        # Filter yesterday's closed signals to only include those closed TODAY
        today_str = report_date
        for item in closed_yesterday:
            hit_time = item.get("hit_time_tehran", "")
            if hit_time and hit_time.startswith(today_str):
                closed_today.append(item)

        logger.info(
            "Report: total closed today = %d (from today CSV: %d, from yesterday CSV cross-day: %d)",
            len(closed_today), len(get_closed_signals_for_date(report_date)),
            len(closed_today) - len(get_closed_signals_for_date(report_date)),
        )

        # Build and send report
        report = build_daily_report(report_date, closed_today, still_open)
        await send_telegram(report)
        logger.info("Final daily report sent (%d closed signals reported)", len(closed_today))
    else:
        # Manage mode: log summary of signals closed this run
        stops = sum(1 for x in closed_this_run if x.get("outcome") == "STOP_HIT")
        trails = sum(1 for x in closed_this_run if x.get("outcome") == "TRAIL_STOP")
        holds = sum(1 for x in closed_this_run if x.get("outcome") == "MAX_HOLD")
        pnl = sum(x.get("net_pnl") or 0 for x in closed_this_run)
        forces = sum(1 for x in closed_this_run if x.get("outcome") == "EOD_FORCE_CLOSE")
        logger.info(
            "Manage cycle: closed=%s open=%s stops=%s trails=%s holds=%s eod=%s pnl=%+.4f",
            len(closed_this_run), len(still_open), stops, trails, holds, forces, pnl,
        )
        logger.info("Manage cycle done (no full daily report)")

    logger.info("Monitor done.")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
