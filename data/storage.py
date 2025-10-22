"""
Database storage layer for Meridian Bot
Uses SQLite for persistent storage
"""
import sqlite3
from datetime import datetime
from typing import Optional, List
from contextlib import contextmanager
import logging

from data.models import User, Wallet, Position, Alert, Threshold, AccountBalance

logger = logging.getLogger(__name__)


class Database:
    """Database manager for Meridian Bot"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_database()

    def _init_database(self):
        """Initialize database schema"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Wallets table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS wallets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    wallet_address TEXT NOT NULL,
                    active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    UNIQUE(user_id, wallet_address)
                )
            """)

            # Positions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    qty REAL NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    mark_price REAL,
                    liquidation_price REAL,
                    margin_ratio REAL,
                    unrealized_pnl REAL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (wallet_id) REFERENCES wallets(id),
                    UNIQUE(wallet_id, symbol)
                )
            """)

            # Alerts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_id INTEGER NOT NULL,
                    alert_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    position_symbol TEXT,
                    margin_ratio REAL,
                    liquidation_price REAL,
                    sent BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (wallet_id) REFERENCES wallets(id)
                )
            """)

            # Thresholds table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS thresholds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_id INTEGER UNIQUE NOT NULL,
                    threshold_warning REAL DEFAULT 80.0,
                    threshold_critical REAL DEFAULT 90.0,
                    threshold_urgent REAL DEFAULT 95.0,
                    FOREIGN KEY (wallet_id) REFERENCES wallets(id)
                )
            """)

            # Account balances table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS account_balances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_id INTEGER UNIQUE NOT NULL,
                    total_margin REAL NOT NULL,
                    used_margin REAL NOT NULL,
                    available_margin REAL NOT NULL,
                    unrealized_pnl REAL DEFAULT 0.0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (wallet_id) REFERENCES wallets(id)
                )
            """)

            # Create indexes for performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_wallets_active ON wallets(active)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_wallet_created ON alerts(wallet_id, created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_wallet ON positions(wallet_id)")

            conn.commit()
            logger.info("Database initialized successfully")

    @contextmanager
    def get_connection(self):
        """Get database connection context manager"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # User operations
    def create_user(self, user: User) -> User:
        """Create or get existing user"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO users (telegram_id, username) VALUES (?, ?)",
                    (user.telegram_id, user.username)
                )
                conn.commit()
                user.id = cursor.lastrowid
                logger.info(f"Created user: {user.telegram_id}")
            except sqlite3.IntegrityError:
                # User already exists, fetch it
                cursor.execute(
                    "SELECT * FROM users WHERE telegram_id = ?",
                    (user.telegram_id,)
                )
                row = cursor.fetchone()
                user.id = row['id']
                logger.info(f"User already exists: {user.telegram_id}")
            return user

    def get_user_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        """Get user by Telegram ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            row = cursor.fetchone()
            if row:
                return User(
                    id=row['id'],
                    telegram_id=row['telegram_id'],
                    username=row['username'],
                    created_at=datetime.fromisoformat(row['created_at'])
                )
            return None

    # Wallet operations
    def add_wallet(self, wallet: Wallet) -> Wallet:
        """Add a wallet to track"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO wallets (user_id, wallet_address, active) VALUES (?, ?, ?)",
                    (wallet.user_id, wallet.wallet_address, wallet.active)
                )
                conn.commit()
                wallet.id = cursor.lastrowid
                logger.info(f"Added wallet: {wallet.wallet_address}")
            except sqlite3.IntegrityError:
                # Wallet already exists, reactivate it
                cursor.execute(
                    "UPDATE wallets SET active = 1 WHERE user_id = ? AND wallet_address = ?",
                    (wallet.user_id, wallet.wallet_address)
                )
                conn.commit()
                cursor.execute(
                    "SELECT * FROM wallets WHERE user_id = ? AND wallet_address = ?",
                    (wallet.user_id, wallet.wallet_address)
                )
                row = cursor.fetchone()
                wallet.id = row['id']
                logger.info(f"Reactivated wallet: {wallet.wallet_address}")
            return wallet

    def remove_wallet(self, user_id: int, wallet_address: str) -> bool:
        """Deactivate a wallet"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE wallets SET active = 0 WHERE user_id = ? AND wallet_address = ?",
                (user_id, wallet_address.lower())
            )
            conn.commit()
            logger.info(f"Deactivated wallet: {wallet_address}")
            return cursor.rowcount > 0

    def get_user_wallets(self, user_id: int, active_only: bool = True) -> List[Wallet]:
        """Get all wallets for a user"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if active_only:
                cursor.execute(
                    "SELECT * FROM wallets WHERE user_id = ? AND active = 1",
                    (user_id,)
                )
            else:
                cursor.execute("SELECT * FROM wallets WHERE user_id = ?", (user_id,))

            return [
                Wallet(
                    id=row['id'],
                    user_id=row['user_id'],
                    wallet_address=row['wallet_address'],
                    active=bool(row['active']),
                    created_at=datetime.fromisoformat(row['created_at'])
                )
                for row in cursor.fetchall()
            ]

    def get_all_active_wallets(self) -> List[Wallet]:
        """Get all active wallets across all users"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM wallets WHERE active = 1")
            return [
                Wallet(
                    id=row['id'],
                    user_id=row['user_id'],
                    wallet_address=row['wallet_address'],
                    active=bool(row['active']),
                    created_at=datetime.fromisoformat(row['created_at'])
                )
                for row in cursor.fetchall()
            ]

    # Position operations
    def upsert_position(self, position: Position) -> Position:
        """Insert or update position"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO positions (wallet_id, symbol, qty, side, entry_price,
                                     mark_price, liquidation_price, margin_ratio,
                                     unrealized_pnl, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(wallet_id, symbol) DO UPDATE SET
                    qty = excluded.qty,
                    side = excluded.side,
                    entry_price = excluded.entry_price,
                    mark_price = excluded.mark_price,
                    liquidation_price = excluded.liquidation_price,
                    margin_ratio = excluded.margin_ratio,
                    unrealized_pnl = excluded.unrealized_pnl,
                    updated_at = excluded.updated_at
            """, (
                position.wallet_id, position.symbol, position.qty, position.side,
                position.entry_price, position.mark_price, position.liquidation_price,
                position.margin_ratio, position.unrealized_pnl, datetime.utcnow()
            ))
            conn.commit()
            position.id = cursor.lastrowid
            return position

    def get_wallet_positions(self, wallet_id: int) -> List[Position]:
        """Get all positions for a wallet"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM positions WHERE wallet_id = ?", (wallet_id,))
            return [
                Position(
                    id=row['id'],
                    wallet_id=row['wallet_id'],
                    symbol=row['symbol'],
                    qty=row['qty'],
                    side=row['side'],
                    entry_price=row['entry_price'],
                    mark_price=row['mark_price'],
                    liquidation_price=row['liquidation_price'],
                    margin_ratio=row['margin_ratio'],
                    unrealized_pnl=row['unrealized_pnl'],
                    updated_at=datetime.fromisoformat(row['updated_at'])
                )
                for row in cursor.fetchall()
            ]

    # Alert operations
    def create_alert(self, alert: Alert) -> Alert:
        """Create a new alert"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO alerts (wallet_id, alert_type, message, severity,
                                  position_symbol, margin_ratio, liquidation_price, sent)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                alert.wallet_id, alert.alert_type, alert.message, alert.severity,
                alert.position_symbol, alert.margin_ratio, alert.liquidation_price, alert.sent
            ))
            conn.commit()
            alert.id = cursor.lastrowid
            logger.info(f"Created alert: {alert.alert_type} for wallet_id {alert.wallet_id}")
            return alert

    def mark_alert_sent(self, alert_id: int):
        """Mark alert as sent"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE alerts SET sent = 1 WHERE id = ?", (alert_id,))
            conn.commit()

    def get_recent_alerts(self, wallet_id: int, hours: int = 24) -> List[Alert]:
        """Get recent alerts for a wallet"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM alerts
                WHERE wallet_id = ?
                AND datetime(created_at) > datetime('now', '-' || ? || ' hours')
                ORDER BY created_at DESC
            """, (wallet_id, hours))
            return [
                Alert(
                    id=row['id'],
                    wallet_id=row['wallet_id'],
                    alert_type=row['alert_type'],
                    message=row['message'],
                    severity=row['severity'],
                    position_symbol=row['position_symbol'],
                    margin_ratio=row['margin_ratio'],
                    liquidation_price=row['liquidation_price'],
                    sent=bool(row['sent']),
                    created_at=datetime.fromisoformat(row['created_at'])
                )
                for row in cursor.fetchall()
            ]

    # Threshold operations
    def upsert_threshold(self, threshold: Threshold) -> Threshold:
        """Insert or update threshold"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO thresholds (wallet_id, threshold_warning, threshold_critical, threshold_urgent)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(wallet_id) DO UPDATE SET
                    threshold_warning = excluded.threshold_warning,
                    threshold_critical = excluded.threshold_critical,
                    threshold_urgent = excluded.threshold_urgent
            """, (threshold.wallet_id, threshold.threshold_warning,
                  threshold.threshold_critical, threshold.threshold_urgent))
            conn.commit()
            threshold.id = cursor.lastrowid
            return threshold

    def get_threshold(self, wallet_id: int) -> Optional[Threshold]:
        """Get threshold for a wallet"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM thresholds WHERE wallet_id = ?", (wallet_id,))
            row = cursor.fetchone()
            if row:
                return Threshold(
                    id=row['id'],
                    wallet_id=row['wallet_id'],
                    threshold_warning=row['threshold_warning'],
                    threshold_critical=row['threshold_critical'],
                    threshold_urgent=row['threshold_urgent']
                )
            return None

    # Account balance operations
    def upsert_account_balance(self, balance: AccountBalance) -> AccountBalance:
        """Insert or update account balance"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO account_balances (wallet_id, total_margin, used_margin,
                                             available_margin, unrealized_pnl, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(wallet_id) DO UPDATE SET
                    total_margin = excluded.total_margin,
                    used_margin = excluded.used_margin,
                    available_margin = excluded.available_margin,
                    unrealized_pnl = excluded.unrealized_pnl,
                    updated_at = excluded.updated_at
            """, (
                balance.wallet_id, balance.total_margin, balance.used_margin,
                balance.available_margin, balance.unrealized_pnl, datetime.utcnow()
            ))
            conn.commit()
            balance.id = cursor.lastrowid
            return balance

    def get_account_balance(self, wallet_id: int) -> Optional[AccountBalance]:
        """Get account balance for a wallet"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM account_balances WHERE wallet_id = ?", (wallet_id,))
            row = cursor.fetchone()
            if row:
                return AccountBalance(
                    id=row['id'],
                    wallet_id=row['wallet_id'],
                    total_margin=row['total_margin'],
                    used_margin=row['used_margin'],
                    available_margin=row['available_margin'],
                    unrealized_pnl=row['unrealized_pnl'],
                    updated_at=datetime.fromisoformat(row['updated_at'])
                )
            return None
