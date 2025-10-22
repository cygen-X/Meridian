"""
User and Wallet Management System
"""
import logging
from typing import Optional, List

from data.storage import Database
from data.models import User, Wallet, Threshold
from utils.validators import validate_wallet_address
from config.settings import (
    DEFAULT_ALERT_THRESHOLD_WARNING,
    DEFAULT_ALERT_THRESHOLD_CRITICAL,
    DEFAULT_ALERT_THRESHOLD_URGENT
)

logger = logging.getLogger(__name__)


class UserManager:
    """Manage users and their wallets"""

    def __init__(self, database: Database):
        self.db = database

    def register_user(self, telegram_id: int, username: Optional[str] = None) -> User:
        """
        Register a new user or get existing user

        Args:
            telegram_id: Telegram user ID
            username: Telegram username (optional)

        Returns: User object
        """
        user = User(telegram_id=telegram_id, username=username)
        user = self.db.create_user(user)
        logger.info(f"User registered: {telegram_id} (username: {username})")
        return user

    def get_user(self, telegram_id: int) -> Optional[User]:
        """Get user by Telegram ID"""
        return self.db.get_user_by_telegram_id(telegram_id)

    def add_wallet(
        self,
        telegram_id: int,
        wallet_address: str
    ) -> tuple[bool, str, Optional[Wallet]]:
        """
        Add a wallet to monitor for a user

        Args:
            telegram_id: Telegram user ID
            wallet_address: Ethereum wallet address

        Returns: Tuple of (success, message, wallet_object)
        """
        # Validate wallet address
        is_valid, result = validate_wallet_address(wallet_address)
        if not is_valid:
            logger.warning(f"Invalid wallet address: {wallet_address}")
            return False, result, None

        wallet_address = result

        # Get or create user
        user = self.db.get_user_by_telegram_id(telegram_id)
        if not user:
            logger.error(f"User not found: {telegram_id}")
            return False, "User not found. Please use /start first.", None

        # Check if user already has this wallet
        existing_wallets = self.db.get_user_wallets(user.id, active_only=False)
        for w in existing_wallets:
            if w.wallet_address == wallet_address:
                if w.active:
                    return False, "This wallet is already being monitored.", None
                else:
                    # Reactivate wallet
                    wallet = self.db.add_wallet(
                        Wallet(user_id=user.id, wallet_address=wallet_address)
                    )
                    logger.info(f"Reactivated wallet for user {telegram_id}: {wallet_address}")
                    return True, "Wallet monitoring reactivated!", wallet

        # Add new wallet
        wallet = Wallet(user_id=user.id, wallet_address=wallet_address)
        wallet = self.db.add_wallet(wallet)

        # Create default thresholds for this wallet
        self._create_default_thresholds(wallet.id)

        logger.info(f"Added wallet for user {telegram_id}: {wallet_address}")
        return True, "Wallet added successfully! Monitoring started.", wallet

    def remove_wallet(
        self,
        telegram_id: int,
        wallet_address: str
    ) -> tuple[bool, str]:
        """
        Remove (deactivate) a wallet from monitoring

        Args:
            telegram_id: Telegram user ID
            wallet_address: Ethereum wallet address

        Returns: Tuple of (success, message)
        """
        # Validate wallet address
        is_valid, result = validate_wallet_address(wallet_address)
        if not is_valid:
            return False, result

        wallet_address = result

        # Get user
        user = self.db.get_user_by_telegram_id(telegram_id)
        if not user:
            return False, "User not found."

        # Deactivate wallet
        success = self.db.remove_wallet(user.id, wallet_address)

        if success:
            logger.info(f"Removed wallet for user {telegram_id}: {wallet_address}")
            return True, "Wallet removed. Monitoring stopped."
        else:
            return False, "Wallet not found or already removed."

    def get_user_wallets(
        self,
        telegram_id: int,
        active_only: bool = True
    ) -> List[Wallet]:
        """
        Get all wallets for a user

        Args:
            telegram_id: Telegram user ID
            active_only: Only return active wallets

        Returns: List of Wallet objects
        """
        user = self.db.get_user_by_telegram_id(telegram_id)
        if not user:
            return []

        return self.db.get_user_wallets(user.id, active_only=active_only)

    def get_all_monitored_wallets(self) -> List[Wallet]:
        """Get all active wallets being monitored"""
        return self.db.get_all_active_wallets()

    def set_wallet_threshold(
        self,
        telegram_id: int,
        wallet_address: str,
        threshold: float
    ) -> tuple[bool, str]:
        """
        Set custom alert threshold for a wallet

        Args:
            telegram_id: Telegram user ID
            wallet_address: Ethereum wallet address
            threshold: Custom threshold percentage

        Returns: Tuple of (success, message)
        """
        # Validate threshold
        if not (0 <= threshold <= 100):
            return False, "Threshold must be between 0 and 100."

        # Get user
        user = self.db.get_user_by_telegram_id(telegram_id)
        if not user:
            return False, "User not found."

        # Validate and normalize wallet address
        is_valid, result = validate_wallet_address(wallet_address)
        if not is_valid:
            return False, result

        wallet_address = result

        # Find wallet
        wallets = self.db.get_user_wallets(user.id, active_only=True)
        wallet = next((w for w in wallets if w.wallet_address == wallet_address), None)

        if not wallet:
            return False, "Wallet not found or not active."

        # Update thresholds
        # Adjust critical and urgent thresholds proportionally
        warning = threshold
        critical = min(threshold + 10, 100)
        urgent = min(threshold + 15, 100)

        threshold_obj = Threshold(
            wallet_id=wallet.id,
            threshold_warning=warning,
            threshold_critical=critical,
            threshold_urgent=urgent
        )
        self.db.upsert_threshold(threshold_obj)

        logger.info(f"Updated threshold for wallet {wallet_address}: {warning}%")
        return True, f"Alert threshold set to {warning}% (critical: {critical}%, urgent: {urgent}%)"

    def get_wallet_threshold(
        self,
        wallet_id: int
    ) -> Threshold:
        """
        Get threshold settings for a wallet

        Args:
            wallet_id: Wallet ID

        Returns: Threshold object (creates default if not exists)
        """
        threshold = self.db.get_threshold(wallet_id)
        if threshold:
            return threshold

        # Create default
        return self._create_default_thresholds(wallet_id)

    def _create_default_thresholds(self, wallet_id: int) -> Threshold:
        """Create default threshold settings for a wallet"""
        threshold = Threshold(
            wallet_id=wallet_id,
            threshold_warning=DEFAULT_ALERT_THRESHOLD_WARNING,
            threshold_critical=DEFAULT_ALERT_THRESHOLD_CRITICAL,
            threshold_urgent=DEFAULT_ALERT_THRESHOLD_URGENT
        )
        return self.db.upsert_threshold(threshold)

    def get_wallet_by_address(self, wallet_address: str) -> Optional[Wallet]:
        """Get wallet by address (searches all active wallets)"""
        all_wallets = self.db.get_all_active_wallets()
        return next(
            (w for w in all_wallets if w.wallet_address == wallet_address.lower()),
            None
        )

    def get_user_by_wallet(self, wallet_address: str) -> Optional[User]:
        """Get user who owns a wallet"""
        wallet = self.get_wallet_by_address(wallet_address)
        if not wallet:
            return None

        # Get user by user_id
        # Need to query database directly since we only have user_id
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE id = ?", (wallet.user_id,))
            row = cursor.fetchone()
            if row:
                return User(
                    id=row['id'],
                    telegram_id=row['telegram_id'],
                    username=row['username']
                )
        return None
