"""signal_store.py — Persist signals to daily CSV files.

Each day gets its own CSV file in the signals/ directory.
"""

import csv
import os
from datetime import datetime
from zoneinfo import ZoneInfo

SIGNALS_DIR = "data/signals"

CSV_HEADERS = [
    "symbol", "direction", "scenario_id", "scenario_name",
    "entry_price", "stop_loss", "take_profit",
    "issued_at_tehran", "status", "hit_time_tehran", "hit_price",
    "broker_fee", "final_pnl_usd", "position_size_usd", "return_pct",
    "signal_source"
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


def append_signal_row(
    symbol: str, direction: str, entry_price: float,
    stop_loss: float, take_profit: float, issued_at_tehran: str,
    signal_source: str, scenario_id: str = "", scenario_name: str = "",
    position_size_usd: float = 10.0, risk_level_name: str = None,
) -> str:
    """Append a signal row to the daily CSV. Returns the file path."""
    path = daily_csv_path()
    file_exists = os.path.isfile(path)

    row = {
        "symbol": symbol,
        "direction": direction,
        "scenario_id": scenario_id or "",
        "scenario_name": scenario_name or "",
        "entry_price": f"{entry_price:.8f}",
        "stop_loss": f"{stop_loss:.8f}",
        "take_profit": f"{take_profit:.8f}",
        "issued_at_tehran": issued_at_tehran,
        "status": "OPEN",
        "hit_time_tehran": "",
        "hit_price": "",
        "broker_fee": "",
        "final_pnl_usd": "",
        "position_size_usd": f"{position_size_usd:.2f}",
        "return_pct": "",
        "signal_source": signal_source,
    }

    write_headers = CSV_HEADERS
    if file_exists:
        try:
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                existing = next(reader, None)
            if existing:
                write_headers = existing
                for h in write_headers:
                    if h not in row:
                        row[h] = ""
        except Exception:
            write_headers = CSV_HEADERS

    with open(path, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=write_headers, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerow({h: row.get(h, "") for h in write_headers})

    return path
