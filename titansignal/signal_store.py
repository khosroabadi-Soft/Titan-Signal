"""signal_store.py — Daily CSV for signal review; DB is source of truth for live state.

CSV purpose: human-readable review of issued signals and their final result.
DB purpose: live open/closed state, trailing, telegram_message_id, backtest fields.
"""
from __future__ import annotations

import csv
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

SIGNALS_DIR = "data/signals"

CSV_HEADERS = [
    "symbol", "direction", "scenario_id", "scenario_name",
    "entry_price", "stop_loss", "take_profit",
    "issued_at_tehran", "status", "outcome",
    "hit_time_tehran", "hit_price",
    "broker_fee", "final_pnl_usd", "position_size_usd", "return_pct",
    "signal_source",
]


def ensure_dir():
    os.makedirs(SIGNALS_DIR, exist_ok=True)


def tehran_date_str(dt=None) -> str:
    tz = ZoneInfo("Asia/Tehran")
    now = datetime.now(tz) if dt is None else dt.astimezone(tz)
    return now.strftime("%Y-%m-%d")


def tehran_time_str(dt=None) -> str:
    tz = ZoneInfo("Asia/Tehran")
    now = datetime.now(tz) if dt is None else dt.astimezone(tz)
    return now.strftime("%Y-%m-%d %H:%M:%S")


def daily_csv_path(date_str: str = None) -> str:
    ensure_dir()
    d = tehran_date_str() if date_str is None else date_str
    return os.path.join(SIGNALS_DIR, f"{d}.csv")


def _fmt_price(v) -> str:
    if v is None or v == "":
        return ""
    try:
        return f"{float(v):.8f}"
    except (TypeError, ValueError):
        return str(v)


def _fmt_money(v) -> str:
    if v is None or v == "":
        return ""
    try:
        return f"{float(v):.6f}"
    except (TypeError, ValueError):
        return str(v)


def append_signal_row(
    symbol: str, direction: str, entry_price: float,
    stop_loss: float, take_profit: float, issued_at_tehran: str,
    signal_source: str, scenario_id: str = "", scenario_name: str = "",
    position_size_usd: float = 10.0, risk_level_name: str = None,
) -> str:
    """Append a new OPEN signal row to the daily CSV."""
    path = daily_csv_path()
    file_exists = os.path.isfile(path)

    row = {
        "symbol": symbol,
        "direction": direction,
        "scenario_id": scenario_id or "",
        "scenario_name": scenario_name or "",
        "entry_price": _fmt_price(entry_price),
        "stop_loss": _fmt_price(stop_loss),
        "take_profit": _fmt_price(take_profit),
        "issued_at_tehran": issued_at_tehran,
        "status": "OPEN",
        "outcome": "",
        "hit_time_tehran": "",
        "hit_price": "",
        "broker_fee": "",
        "final_pnl_usd": "",
        "position_size_usd": f"{float(position_size_usd):.2f}",
        "return_pct": "",
        "signal_source": signal_source,
    }

    write_headers = list(CSV_HEADERS)
    if file_exists:
        try:
            with open(path, newline="", encoding="utf-8") as f:
                existing = next(csv.reader(f), None)
            if existing:
                write_headers = list(existing)
                for h in CSV_HEADERS:
                    if h not in write_headers:
                        write_headers.append(h)
                for h in write_headers:
                    row.setdefault(h, "")
        except Exception:
            write_headers = list(CSV_HEADERS)

    with open(path, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=write_headers, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerow({h: row.get(h, "") for h in write_headers})

    return path


def _row_key(symbol, direction, scenario_id, issued_at_tehran) -> str:
    return f"{symbol}|{direction}|{scenario_id or ''}|{issued_at_tehran or ''}"


def update_signal_csv_row(
    symbol: str,
    direction: str,
    scenario_id: str,
    issued_at_tehran: str,
    status: str = "CLOSED",
    outcome: str = "",
    hit_time_tehran: str = "",
    hit_price=None,
    broker_fee=None,
    final_pnl_usd=None,
    return_pct=None,
) -> bool:
    """Update matching row in the CSV of the issue date. Returns True if updated."""
    if not issued_at_tehran or len(issued_at_tehran) < 10:
        return False
    date_str = issued_at_tehran[:10]
    path = daily_csv_path(date_str)
    if not os.path.isfile(path):
        logger.debug("CSV not found for update: %s", path)
        return False

    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or CSV_HEADERS)
            rows = list(reader)
    except Exception as e:
        logger.error("CSV read error %s: %s", path, e)
        return False

    for h in CSV_HEADERS:
        if h not in fieldnames:
            fieldnames.append(h)

    target = _row_key(symbol, direction, scenario_id, issued_at_tehran)
    updated = False
    for row in rows:
        key = _row_key(
            row.get("symbol", ""),
            row.get("direction", ""),
            row.get("scenario_id", ""),
            row.get("issued_at_tehran", ""),
        )
        if key != target:
            continue
        row["status"] = status or "CLOSED"
        if outcome is not None:
            row["outcome"] = outcome or ""
        if hit_time_tehran:
            row["hit_time_tehran"] = hit_time_tehran
        if hit_price is not None and hit_price != "":
            row["hit_price"] = _fmt_price(hit_price)
        if broker_fee is not None and broker_fee != "":
            row["broker_fee"] = _fmt_money(broker_fee)
        if final_pnl_usd is not None and final_pnl_usd != "":
            row["final_pnl_usd"] = _fmt_money(final_pnl_usd)
        if return_pct is not None and return_pct != "":
            row["return_pct"] = _fmt_money(return_pct)
        updated = True
        break

    if not updated:
        logger.debug("No CSV row matched %s", target)
        return False

    try:
        with open(path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({h: row.get(h, "") for h in fieldnames})
        logger.info("CSV updated %s %s [%s] -> %s %s", symbol, direction, scenario_id, status, outcome)
        return True
    except Exception as e:
        logger.error("CSV write error %s: %s", path, e)
        return False


def repair_csvs_from_db(db_path: str = "data/titan_signal.db") -> Dict[str, int]:
    """One-shot: rewrite daily CSVs status/outcome/pnl from SQLite."""
    import sqlite3

    stats = {"files": 0, "rows": 0, "closed": 0, "open": 0}
    if not os.path.isfile(db_path):
        logger.error("DB not found: %s", db_path)
        return stats

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT symbol, direction, scenario_id, scenario_name, entry_price, stop_loss, "
        "take_profit, issued_at_tehran, status, outcome, exit_time, hit_time, exit_price, "
        "hit_price, broker_fee, final_pnl_usd, position_size_usd, return_pct, signal_source "
        "FROM signals ORDER BY issued_at_tehran ASC, id ASC"
    )
    signals = [dict(r) for r in cur.fetchall()]
    conn.close()

    by_date: Dict[str, list] = {}
    for s in signals:
        issued = s.get("issued_at_tehran") or ""
        if len(issued) < 10:
            continue
        d = issued[:10]
        by_date.setdefault(d, []).append(s)

    tz = ZoneInfo("Asia/Tehran")
    ensure_dir()

    for date_str, items in sorted(by_date.items()):
        path = daily_csv_path(date_str)
        rows = []
        for s in items:
            hit_t = s.get("exit_time") or s.get("hit_time")
            hit_tehran = ""
            if hit_t:
                try:
                    if isinstance(hit_t, str):
                        hit_tehran = hit_t
                    else:
                        hit_tehran = hit_t.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S") if hasattr(hit_t, "astimezone") else str(hit_t)
                except Exception:
                    hit_tehran = str(hit_t)
            # sqlite may store naive UTC strings
            if hit_tehran:
                try:
                    raw = hit_tehran.replace("Z", "+00:00")
                    if "T" in raw:
                        dt = datetime.fromisoformat(raw)
                        if dt.tzinfo is None:
                            from datetime import timezone as tzutc
                            dt = dt.replace(tzinfo=tzutc.utc)
                        hit_tehran = dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        # already local-ish string; drop micros
                        hit_tehran = raw.split(".")[0]
                except Exception:
                    hit_tehran = str(hit_tehran).split(".")[0]

            status = s.get("status") or "OPEN"
            outcome = s.get("outcome") or ""
            hit_price = s.get("exit_price") if s.get("exit_price") is not None else s.get("hit_price")
            rows.append({
                "symbol": s.get("symbol") or "",
                "direction": s.get("direction") or "",
                "scenario_id": s.get("scenario_id") or "",
                "scenario_name": s.get("scenario_name") or "",
                "entry_price": _fmt_price(s.get("entry_price")),
                "stop_loss": _fmt_price(s.get("stop_loss")),
                "take_profit": _fmt_price(s.get("take_profit")),
                "issued_at_tehran": issued if (issued := s.get("issued_at_tehran") or "") else "",
                "status": status,
                "outcome": outcome,
                "hit_time_tehran": hit_tehran if status != "OPEN" else "",
                "hit_price": _fmt_price(hit_price) if status != "OPEN" else "",
                "broker_fee": _fmt_money(s.get("broker_fee")) if status != "OPEN" else "",
                "final_pnl_usd": _fmt_money(s.get("final_pnl_usd")) if status != "OPEN" else "",
                "position_size_usd": f"{float(s.get('position_size_usd') or 10):.2f}",
                "return_pct": _fmt_money(s.get("return_pct")) if status != "OPEN" else "",
                "signal_source": s.get("signal_source") or "titan_signal",
            })
            stats["rows"] += 1
            if status == "OPEN":
                stats["open"] += 1
            else:
                stats["closed"] += 1

        with open(path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        stats["files"] += 1
        logger.info("Repaired %s (%s rows)", path, len(rows))

    return stats
