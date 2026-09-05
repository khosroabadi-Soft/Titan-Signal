#!/usr/bin/env python3
"""پاک‌سازی پیام‌های سیگنال در کانال تلگرام.

روش درست (Bot API):
  - getUpdates تاریخچهٔ کانال را برنمی‌گرداند → اسکریپت قبلی تقریباً هیچ‌وقت کار نمی‌کرد.
  - message_idهای ذخیره‌شده در SQLite (ستون telegram_message_id) را می‌خوانیم و delete می‌کنیم.
  - اختیاری: بازهٔ دستی با env SCAN_FROM / SCAN_TO برای پیام‌های بدون رکورد در DB.

Usage:
  TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python scripts/clear_telegram_channel.py

Env:
  DELETE_LIMIT   حداکثر تعداد حذف (پیش‌فرض 3000)
  SCAN_FROM      اگر ست شود، از این message_id به پایین هم امتحان می‌کند
  SCAN_TO        کف بازه (پیش‌فرض 1)
  CLEAR_DB_IDS   اگر 1 باشد بعد از حذف موفق، telegram_message_id را در DB خالی می‌کند
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import List, Optional, Set

import aiohttp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("clear_telegram")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "titan_signal.db"


def load_message_ids_from_db(db_path: Path) -> List[int]:
    if not db_path.exists():
        logger.warning("DB not found: %s", db_path)
        return []
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT telegram_message_id FROM signals "
            "WHERE telegram_message_id IS NOT NULL "
            "ORDER BY telegram_message_id DESC"
        )
        ids = []
        seen: Set[int] = set()
        for (mid,) in cur.fetchall():
            try:
                m = int(mid)
            except (TypeError, ValueError):
                continue
            if m > 0 and m not in seen:
                seen.add(m)
                ids.append(m)
        return ids
    finally:
        conn.close()


def clear_ids_in_db(db_path: Path, ids: List[int]) -> None:
    if not ids or not db_path.exists():
        return
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.executemany(
            "UPDATE signals SET telegram_message_id = NULL WHERE telegram_message_id = ?",
            [(i,) for i in ids],
        )
        conn.commit()
        logger.info("Cleared telegram_message_id in DB for %s rows", cur.rowcount)
    except Exception as e:
        conn.rollback()
        logger.error("DB update failed: %s", e)
    finally:
        conn.close()


async def delete_one(
    session: aiohttp.ClientSession,
    token: str,
    chat_id: str,
    message_id: int,
) -> str:
    """Returns: ok | not_found | fail"""
    url = f"https://api.telegram.org/bot{token}/deleteMessage"
    try:
        async with session.post(
            url,
            json={"chat_id": chat_id, "message_id": message_id},
            timeout=20,
        ) as resp:
            body = await resp.json(content_type=None)
            if body.get("ok"):
                return "ok"
            desc = (body.get("description") or "").lower()
            if "message to delete not found" in desc or "message can't be deleted" in desc:
                return "not_found"
            if resp.status == 429 or body.get("error_code") == 429:
                wait = int((body.get("parameters") or {}).get("retry_after") or 3)
                wait = min(max(wait, 1), 8)
                await asyncio.sleep(wait)
                async with session.post(
                    url,
                    json={"chat_id": chat_id, "message_id": message_id},
                    timeout=20,
                ) as resp2:
                    body2 = await resp2.json(content_type=None)
                    if body2.get("ok"):
                        return "ok"
                    return "fail"
            logger.debug("delete %s: %s", message_id, body)
            return "fail"
    except Exception as e:
        logger.debug("delete error %s: %s", message_id, e)
        return "fail"


async def clear_channel_messages() -> None:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    limit = int(os.getenv("DELETE_LIMIT") or "3000")
    clear_db = (os.getenv("CLEAR_DB_IDS") or "1").strip() in ("1", "true", "yes")
    db_path = Path(os.getenv("TITAN_DB_PATH") or DEFAULT_DB)

    if not token or not chat_id:
        logger.error("TELEGRAM_BOT_TOKEN یا TELEGRAM_CHAT_ID تنظیم نشده")
        sys.exit(1)

    ids = load_message_ids_from_db(db_path)
    logger.info("Loaded %s message_id(s) from DB %s", len(ids), db_path)

    scan_from = os.getenv("SCAN_FROM")
    if scan_from:
        try:
            hi = int(scan_from)
            lo = int(os.getenv("SCAN_TO") or "1")
            extra = list(range(hi, lo - 1, -1))
            seen = set(ids)
            for m in extra:
                if m not in seen:
                    ids.append(m)
                    seen.add(m)
            logger.info("Added range scan %s..%s → total candidates %s", hi, lo, len(ids))
        except ValueError:
            logger.warning("Invalid SCAN_FROM/SCAN_TO ignored")

    if not ids:
        logger.warning(
            "هیچ message_id برای حذف نیست. "
            "DB خالی است یا ستون telegram_message_id پر نشده. "
            "اختیاری: SCAN_FROM=<آخرین message_id کانال> بگذارید."
        )
        sys.exit(0)

    ids = ids[: max(1, limit)]
    deleted = 0
    missing = 0
    failed = 0
    ok_ids: List[int] = []

    async with aiohttp.ClientSession() as session:
        # verify bot
        async with session.get(
            f"https://api.telegram.org/bot{token}/getMe", timeout=15
        ) as resp:
            me = await resp.json(content_type=None)
            if not me.get("ok"):
                logger.error("getMe failed: %s", me)
                sys.exit(1)
            logger.info("Bot: @%s", me["result"].get("username"))

        for i, mid in enumerate(ids, 1):
            status = await delete_one(session, token, chat_id, mid)
            if status == "ok":
                deleted += 1
                ok_ids.append(mid)
                if deleted % 25 == 0:
                    logger.info("Progress: deleted=%s missing=%s failed=%s", deleted, missing, failed)
            elif status == "not_found":
                missing += 1
                ok_ids.append(mid)  # already gone — clear DB id
            else:
                failed += 1
            # short pause — protect Actions minutes + Telegram limits
            if i % 15 == 0:
                await asyncio.sleep(0.8)
            else:
                await asyncio.sleep(0.05)

    logger.info(
        "Done. deleted=%s already_gone=%s failed=%s (attempted=%s)",
        deleted,
        missing,
        failed,
        len(ids),
    )

    if clear_db and ok_ids:
        clear_ids_in_db(db_path, ok_ids)

    # optional report to channel (one short message)
    try:
        async with aiohttp.ClientSession() as session:
            text = (
                f"🧹 پاک‌سازی کانال\n"
                f"✅ حذف‌شده: {deleted}\n"
                f"ℹ️ از قبل نبود: {missing}\n"
                f"❌ ناموفق: {failed}"
            )
            async with session.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=20,
            ) as resp:
                body = await resp.json(content_type=None)
                if not body.get("ok"):
                    logger.warning("report send failed: %s", body)
    except Exception as e:
        logger.warning("report error: %s", e)


def main():
    try:
        asyncio.run(clear_channel_messages())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
