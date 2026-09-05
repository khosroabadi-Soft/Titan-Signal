#!/usr/bin/env python3
"""monitor.py — Live trail management + night force-close + daily report.

Modes (env TITAN_MONITOR_MODE):
  manage  — process open signals with trailing (default)
  final   — trail + EOD force-close remaining + full day report + open warning

Usage:
  python monitor.py
  TITAN_MONITOR_MODE=final python monitor.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from titansignal.config import (
    LEVERAGE, MARGIN_USD, POSITION_USD, FEE_PER_TRADE,
)
from titansignal.database import (
    init_db, get_open_signals, get_session, Signal, save_daily_summary,
)
from titansignal.signal_store import tehran_time_str
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


def build_daily_report(report_date: str, closed_today: list, still_open: list) -> str:
    stops = sum(1 for x in closed_today if x.get("outcome") == "STOP_HIT")
    trails = sum(1 for x in closed_today if x.get("outcome") == "TRAIL_STOP")
    holds = sum(1 for x in closed_today if x.get("outcome") == "MAX_HOLD")
    forces = sum(1 for x in closed_today if x.get("outcome") == "EOD_FORCE_CLOSE")
    wins = sum(1 for x in closed_today if (x.get("net_pnl") or 0) > 0)
    losses = sum(1 for x in closed_today if (x.get("net_pnl") or 0) < 0)
    pnl = sum(x.get("net_pnl") or 0 for x in closed_today)
    closed_n = len(closed_today)
    wr = (wins / closed_n * 100) if closed_n else 0.0

    lines = [
        "════════════════════",
        f"📊 <b>گزارش روزانه Titan Signal</b>",
        f"📅 تاریخ: <b>{report_date}</b>",
        f"🕐 {tehran_time_str()}",
        "════════════════════",
        "",
        f"📦 بسته‌شده امروز: <b>{closed_n}</b>",
        f"   🔴 استاپ: {stops}",
        f"   🟢 تریل: {trails}",
        f"   ⏰ سقف زمان: {holds}",
        f"   ⚠️ اجباری پایان‌روز: {forces}",
        f"✅ برد: {wins} | ❌ باخت: {losses}",
        f"🎯 نرخ برد (بسته): <b>{wr:.1f}%</b>",
        f"💰 PnL خالص روز: <b>{pnl:+.4f}$</b>",
        f"(اهرم {LEVERAGE}x | مارجین ${MARGIN_USD:.0f} | پوزیشن ${POSITION_USD:.0f} | کارمزد ${FEE_PER_TRADE:.2f})",
        "",
    ]

    if closed_today:
        lines.append("── جزئیات خروج‌ها ──")
        # sort by pnl desc, limit to avoid telegram flood
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
            "سیستم تلاش کرد با تریل و بستن اجباری پایان‌روز تکلیف را مشخص کند؛ "
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
    logger.info("=" * 60)

    closed = process_open_signals(force_close=force)
    logger.info("Closed this run: %d", len(closed))

    if closed and not force:
        # daytime manage: notify each exit
        await notify_exits(closed)
    elif closed and force:
        # final run: short notice then full report
        await notify_exits(closed[:15])  # cap flood
        if len(closed) > 15:
            await send_telegram(
                f"ℹ️ {len(closed) - 15} خروج دیگر در گزارش روزانه آمده است."
            )

    still_open = get_open_signals(days=7)
    logger.info("Still OPEN: %d", len(still_open))

    # stats for DB summary
    stops = sum(1 for x in closed if x.get("outcome") == "STOP_HIT")
    trails = sum(1 for x in closed if x.get("outcome") == "TRAIL_STOP")
    holds = sum(1 for x in closed if x.get("outcome") == "MAX_HOLD")
    pnl = sum(x.get("net_pnl") or 0 for x in closed)
    wins = sum(1 for x in closed if (x.get("net_pnl") or 0) > 0)
    wr = (wins / len(closed) * 100) if closed else 0.0

    save_daily_summary(
        date_str=report_date,
        total=len(closed) + len(still_open),
        open_count=len(still_open),
        sl=stops,
        trail=trails,
        max_hold=holds,
        win_rate=wr,
        total_pnl=pnl,
    )

    if force:
        report = build_daily_report(report_date, closed, still_open)
        await send_telegram(report)
        logger.info("Final daily report sent")
    else:
        logger.info("Manage cycle done (no full daily report)")

    logger.info("Monitor done.")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
