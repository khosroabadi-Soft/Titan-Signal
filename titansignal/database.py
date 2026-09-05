import os
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session

logger = logging.getLogger(__name__)

_raw_db_url = os.getenv("TITAN_DATABASE_URL", "")
os.makedirs("data", exist_ok=True)
DB_URL = _raw_db_url.strip() if _raw_db_url.strip() else "sqlite:///data/titan_signal.db"
engine = create_engine(DB_URL, connect_args={"check_same_thread": False} if "sqlite" in DB_URL else {})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

TEHRAN_TZ = ZoneInfo("Asia/Tehran")


# ──────────────────────────────────────────────
# Model
# ──────────────────────────────────────────────
class Signal(Base):
    __tablename__ = "signals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    direction = Column(String(10), nullable=False)
    scenario_id = Column(String(5), nullable=False, index=True)
    scenario_name = Column(String(120), default="")
    entry_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    take_profit = Column(Float, nullable=False)
    issued_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    issued_at_tehran = Column(String(30), nullable=False)
    issued_at_unix = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="OPEN", index=True)
    hit_time = Column(DateTime(timezone=True), nullable=True)
    hit_price = Column(Float, nullable=True)
    broker_fee = Column(Float, default=0.0)
    final_pnl_usd = Column(Float, default=0.0)
    return_pct = Column(Float, default=0.0)
    position_size_usd = Column(Float, default=10.0)
    signal_source = Column(String(30), default="titan_signal")
    # ── V3.1 trailing-stop columns ──
    initial_sl = Column(Float, nullable=True)
    trail_activate = Column(Float, nullable=True)
    trail_lock = Column(Float, nullable=True)
    max_hold_candles = Column(Integer, nullable=True)
    leverage = Column(Integer, nullable=True)
    margin_usd = Column(Float, nullable=True)
    position_usd = Column(Float, nullable=True)
    exit_time = Column(DateTime(timezone=True), nullable=True)
    exit_price = Column(Float, nullable=True)
    outcome = Column(String(20), nullable=True)
    margin_roi_pct = Column(Float, nullable=True)
    telegram_message_id = Column(Integer, nullable=True)


class DailySummary(Base):
    __tablename__ = "daily_summaries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String(10), nullable=False, unique=True, index=True)
    total_signals = Column(Integer, default=0)
    open_signals = Column(Integer, default=0)
    tp_hits = Column(Integer, default=0)
    sl_hits = Column(Integer, default=0)
    manual_closes = Column(Integer, default=0)
    trail_exits = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)
    total_pnl_usd = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ──────────────────────────────────────────────
# DB init & migration
# ──────────────────────────────────────────────
_MIGRATION_COLUMNS = {
    "status":              "TEXT DEFAULT 'OPEN'",
    "hit_time":            "TIMESTAMP",
    "hit_price":           "REAL",
    "position_size_usd":   "REAL DEFAULT 10.0",
    "initial_sl":          "REAL",
    "trail_activate":      "REAL",
    "trail_lock":          "REAL",
    "max_hold_candles":    "INTEGER",
    "leverage":            "INTEGER",
    "margin_usd":          "REAL",
    "position_usd":        "REAL",
    "scenario_id":         "TEXT",
    "scenario_name":       "TEXT",
    "issued_at_tehran":    "TEXT",
    "issued_at_unix":      "INTEGER",
    "exit_time":           "TIMESTAMP",
    "exit_price":          "REAL",
    "broker_fee":          "REAL",
    "final_pnl_usd":       "REAL",
    "return_pct":          "REAL",
    "outcome":             "TEXT",
    "margin_roi_pct":      "REAL",
    "signal_source":       "TEXT",
    "telegram_message_id": "INTEGER",
    "stop_loss":           "REAL",
    "take_profit":         "REAL",
}


def _migrate_db():
    """Add missing columns to existing SQLite tables (safe, idempotent)."""
    if "sqlite" not in DB_URL:
        return
    import sqlite3
    db_path = DB_URL.replace("sqlite:///", "")
    if not os.path.isfile(db_path):
        return
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(signals)")
        existing = {row[1] for row in cursor.fetchall()}
        for col_name, col_type in _MIGRATION_COLUMNS.items():
            if col_name not in existing:
                sql = f"ALTER TABLE signals ADD COLUMN {col_name} {col_type}"
                logger.info(f"DB migration: adding column {col_name}")
                cursor.execute(sql)
        conn.commit()
        conn.close()
        logger.info("DB migration complete")
    except Exception as e:
        logger.error(f"DB migration error: {e}")


def init_db():
    Base.metadata.create_all(bind=engine)
    _migrate_db()
    logger.info(f"Database initialized: {DB_URL}")


def get_session() -> Session:
    return SessionLocal()


# ──────────────────────────────────────────────
# Signal CRUD
# ──────────────────────────────────────────────
def save_signal(
    symbol, direction, scenario_id, scenario_name,
    entry_price, stop_loss, take_profit, issued_at_tehran,
    position_size_usd=10.0, signal_source="titan_signal",
    initial_sl=None, sl_pct=None,
    trail_activate=None, trail_lock=None,
    max_hold_candles=None, leverage=None, margin_usd=None, position_usd=None,
    issued_at_unix=None,
    telegram_message_id=None,
    **kwargs,
) -> int:
    """Save a new signal. Accepts both `stop_loss` and `initial_sl` param names."""
    session = get_session()
    try:
        sl_value = stop_loss if stop_loss and stop_loss > 0 else (initial_sl or stop_loss)
        _leverage = leverage or (int(kwargs.get('leverage', 0)) if kwargs.get('leverage') else None)
        _margin = margin_usd or kwargs.get('margin_usd')
        _position_usd = position_usd or (_margin * (_leverage or 10) if _margin else None)

        sig = Signal(
            symbol=symbol,
            direction=direction,
            scenario_id=scenario_id,
            scenario_name=scenario_name,
            entry_price=entry_price,
            stop_loss=sl_value,
            take_profit=take_profit,
            issued_at_tehran=issued_at_tehran,
            issued_at_unix=issued_at_unix or int(datetime.now(timezone.utc).timestamp()),
            position_size_usd=position_size_usd,
            signal_source=signal_source,
            initial_sl=initial_sl if initial_sl is not None else sl_value,
            trail_activate=trail_activate or kwargs.get('trail_activate'),
            trail_lock=trail_lock or kwargs.get('trail_lock'),
            max_hold_candles=max_hold_candles or kwargs.get('max_hold_candles'),
            leverage=_leverage,
            margin_usd=_margin,
            position_usd=_position_usd,
            telegram_message_id=telegram_message_id or kwargs.get('telegram_message_id'),
        )
        session.add(sig)
        session.commit()
        session.refresh(sig)
        return sig.id
    except Exception as e:
        session.rollback()
        logger.error(f"DB save error: {e}")
        return -1
    finally:
        session.close()


def update_signal_status(signal_id, status, hit_price=None,
                         broker_fee=0.0, final_pnl_usd=0.0, return_pct=0.0):
    session = get_session()
    try:
        sig = session.query(Signal).filter(Signal.id == signal_id).first()
        if sig:
            sig.status = status
            sig.hit_price = hit_price
            sig.hit_time = datetime.now(timezone.utc)
            sig.broker_fee = broker_fee
            sig.final_pnl_usd = final_pnl_usd
            sig.return_pct = return_pct
            session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"DB update error: {e}")
    finally:
        session.close()


def update_signal_exit(
    signal_id,
    exit_price,
    outcome,
    broker_fee=0.0,
    final_pnl_usd=0.0,
    return_pct=0.0,
    margin_roi_pct=None,
    exit_time=None,
    status="CLOSED",
    **kwargs,
):
    """Close signal with trailing-stop / force-close result."""
    session = get_session()
    try:
        sig = session.query(Signal).filter(Signal.id == signal_id).first()
        if sig:
            sig.status = status or "CLOSED"
            sig.exit_price = exit_price
            sig.exit_time = exit_time or datetime.now(timezone.utc)
            sig.outcome = outcome
            sig.broker_fee = broker_fee
            sig.final_pnl_usd = final_pnl_usd
            sig.return_pct = return_pct
            if margin_roi_pct is not None:
                sig.margin_roi_pct = margin_roi_pct
            sig.hit_price = exit_price
            sig.hit_time = sig.exit_time
            # capture CSV keys before close
            _sym = sig.symbol
            _dir = sig.direction
            _sc = sig.scenario_id
            _issued = sig.issued_at_tehran
            session.commit()
            logger.info(f"Signal #{signal_id} exit: {outcome} @ {exit_price}")
            try:
                from .signal_store import update_signal_csv_row, tehran_time_str
                hit_tehran = tehran_time_str(sig.exit_time) if sig.exit_time else tehran_time_str()
                update_signal_csv_row(
                    symbol=_sym,
                    direction=_dir,
                    scenario_id=_sc or "",
                    issued_at_tehran=_issued or "",
                    status=status or "CLOSED",
                    outcome=outcome or "",
                    hit_time_tehran=hit_tehran,
                    hit_price=exit_price,
                    broker_fee=broker_fee,
                    final_pnl_usd=final_pnl_usd,
                    return_pct=return_pct,
                )
            except Exception as csv_e:
                logger.error(f"CSV sync on exit failed: {csv_e}")
    except Exception as e:
        session.rollback()
        logger.error(f"DB update_signal_exit error: {e}")
    finally:
        session.close()



def set_telegram_message_id(signal_id, message_id):
    """Store Telegram message_id for later reply-to on exit."""
    if not signal_id or message_id is None:
        return
    session = get_session()
    try:
        sig = session.query(Signal).filter(Signal.id == signal_id).first()
        if sig:
            sig.telegram_message_id = int(message_id)
            session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"set_telegram_message_id error: {e}")
    finally:
        session.close()


def has_open_signal(symbol, direction=None, scenario_id=None, within_seconds=None):
    """Check if there is an open signal for the given criteria."""
    session = get_session()
    try:
        from datetime import timedelta
        q = session.query(Signal).filter(Signal.status == "OPEN", Signal.symbol == symbol)
        if direction:
            q = q.filter(Signal.direction == direction)
        if scenario_id:
            q = q.filter(Signal.scenario_id == scenario_id)
        if within_seconds:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=within_seconds)
            q = q.filter(Signal.issued_at >= cutoff)
        return q.first() is not None
    finally:
        session.close()


def get_open_signals(days=3):
    session = get_session()
    try:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return session.query(Signal).filter(
            Signal.status == "OPEN",
            Signal.issued_at >= cutoff
        ).order_by(Signal.issued_at.asc()).all()
    finally:
        session.close()


# ──────────────────────────────────────────────
# Daily summary
# ──────────────────────────────────────────────
def save_daily_summary(
    date_str,
    total=0, open_count=0, open_signals=0,
    tp=0, sl=0, stop=0, manual=0, max_hold=0,
    trail=0, win_rate=0.0, wr=0.0,
    total_pnl=0.0, pnl=0.0,
    **kwargs,
):
    session = get_session()
    try:
        _total = total or 0
        _open = open_count or open_signals or 0
        _tp = tp or 0
        _sl = sl or stop or 0
        _manual = manual or max_hold or 0
        _trail = trail or 0
        _wr = win_rate or wr or 0.0
        _pnl = total_pnl or pnl or 0.0

        existing = session.query(DailySummary).filter(
            DailySummary.date == date_str).first()
        if existing:
            existing.total_signals = _total
            existing.open_signals = _open
            existing.tp_hits = _tp
            existing.sl_hits = _sl
            existing.manual_closes = _manual
            existing.trail_exits = _trail
            existing.win_rate = _wr
            existing.total_pnl_usd = _pnl
        else:
            summary = DailySummary(
                date=date_str, total_signals=_total,
                open_signals=_open, tp_hits=_tp, sl_hits=_sl,
                manual_closes=_manual, trail_exits=_trail,
                win_rate=_wr, total_pnl_usd=_pnl,
            )
            session.add(summary)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"DB summary error: {e}")
    finally:
        session.close()
