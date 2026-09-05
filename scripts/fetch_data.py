#!/usr/bin/env python3
"""fetch_data.py — Fetch historical 30m candles for backtesting.

Usage:
    python scripts/fetch_data.py [days]
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone
import requests

KUCOIN_URL = "https://api.kucoin.com/api/v1/market/candles"
SYMBOLS = [
    'BTC-USDT', 'ETH-USDT', 'BNB-USDT', 'SOL-USDT', 'XRP-USDT',
    'XAUT-USDT', 'LTC-USDT', 'DOGE-USDT', 'SUI-USDT', 'NEAR-USDT',
    'DOT-USDT', 'ADA-USDT', 'LINK-USDT', 'AVAX-USDT', 'ATOM-USDT',
    'FIL-USDT', 'INJ-USDT', 'SEI-USDT', 'TIA-USDT', 'POL-USDT', 'OP-USDT',
    'PEPE-USDT', 'SHIB-USDT',
]
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "historical")


def fetch(symbol, days):
    end = int(datetime.now(timezone.utc).timestamp())
    start = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    params = {"symbol": symbol, "type": "30min", "startAt": start, "endAt": end}
    for attempt in range(3):
        try:
            r = requests.get(KUCOIN_URL, params=params, timeout=30)
            if r.status_code == 200:
                data = r.json().get("data", [])
                candles = [{"t": int(c[0]), "o": float(c[1]), "c": float(c[2]),
                             "h": float(c[3]), "l": float(c[4]), "v": float(c[5])}
                            for c in data]
                return list(reversed(candles))
            if r.status_code == 429:
                time.sleep(10)
        except Exception as e:
            print(f"  Error: {e}")
            time.sleep(5)
    return []


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 180
    os.makedirs(DATA_DIR, exist_ok=True)
    print(f"Fetching {len(SYMBOLS)} symbols, {days} days of 30m candles...")
    for i, sym in enumerate(SYMBOLS, 1):
        fname = sym.replace("-", "_") + ".json"
        path = os.path.join(DATA_DIR, fname)
        candles = fetch(sym, days)
        if candles:
            with open(path, "w") as f:
                json.dump(candles, f)
            print(f"  [{i}/{len(SYMBOLS)}] {sym}: {len(candles)} candles")
        else:
            print(f"  [{i}/{len(SYMBOLS)}] {sym}: FAILED")
        time.sleep(0.3)
    print("Done.")


if __name__ == "__main__":
    main()
