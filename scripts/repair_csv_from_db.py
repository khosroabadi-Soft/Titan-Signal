#!/usr/bin/env python3
"""Rewrite data/signals/*.csv from SQLite so status/outcome/pnl match DB.

Usage:
  python scripts/repair_csv_from_db.py
"""
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from titansignal.signal_store import repair_csvs_from_db

if __name__ == "__main__":
    db = ROOT / "data" / "titan_signal.db"
    stats = repair_csvs_from_db(str(db))
    print(f"Done: {stats}")
