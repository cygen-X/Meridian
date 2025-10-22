"""
Core Liquidation Monitor
Coordinates position monitoring, risk calculation, and alerts
"""
import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

from bot.reya_client import ReyaAPIClient
from bot.risk_calculator import RiskCalculator
from bot.user_manager import UserManager
from websocket.reya_websocket import ReyaWebSocketManager
from data.storage import Database
from data.models import Position, AccountBalance, Alert, AlertSeverity
from utils.formatters import format_liquidation_alert, format_risk_level
from config.settings import (
    ALERT_FREQUENCY_WARNING,
    ALERT_FREQUENCY_CRITICAL,
    ALERT_FREQUENCY_URGENT
)

logger = logging.getLogger(__name__)


class LiquidationMonitor:
    """Monitor positions and send liquidation alerts"""

    def __init__(
        self,
        database: Database,
        reya_client: ReyaAPIClient,
        ws_manager: ReyaWebSocketManager,
        user_manager: UserManager,
        risk_calculator: RiskCalculator
    ):
        self.db = database
        self.reya_client = reya_client
        self.ws_manager = ws_manager
        self.user_manager = user_manager
        self.risk_calculator = risk_calculator

        # Track last alert times to prevent spam
        self.last_alert_times: Dict[str, Dict[str, datetime]] = {}
        # wallet_address -> {position_symbol -> last_alert_time}

        # Store telegram bot reference (will be set later)
        self.telegram_bot = None

        # Monitoring tasks
        self.monitoring_tasks: Dict[str, asyncio.Task] = {}

    def set_telegram_bot(self, telegram_bot):
        """Set telegram bot reference for sending alerts"""
        self.telegram_bot = telegram_bot

    async def start_monitoring_wallet(self, wallet_address: str):
        """
        Start monitoring a wallet's positions

        Args:
            wallet_address: Ethereum wallet address
        """
        wallet_address = wallet_address.lower()

        if wallet_address in self.monitoring_tasks:
            logger.warning(f"Already monitoring wallet: {wallet_address}")
            return

        logger.info(f"Starting monitoring for wallet: {wallet_address}")

        # Fetch initial data
        await self._fetch_wallet_data(wallet_address)

        # Subscribe to WebSocket updates
        await self._subscribe_wallet_websockets(wallet_address)

        # Start periodic update task (fallback)
        task = asyncio.create_task(self._periodic_update_task(wallet_address))
        self.monitoring_tasks[wallet_address] = task

        logger.info(f"Monitoring started for wallet: {wallet_address}")

    async def stop_monitoring_wallet(self, wallet_address: str):
        """Stop monitoring a wallet"""
        wallet_address = wallet_address.lower()

        # Cancel monitoring task
        if wallet_address in self.monitoring_tasks:
            self.monitoring_tasks[wallet_address].cancel()
            try:
                await self.monitoring_tasks[wallet_address]
            except asyncio.CancelledError:
                pass
            del self.monitoring_tasks[wallet_address]

        # Unsubscribe from WebSocket
        await self.ws_manager.unsubscribe("wallet_positions", wallet_address)
        await self.ws_manager.unsubscribe("wallet_balances", wallet_address)

        logger.info(f"Stopped monitoring wallet: {wallet_address}")

    async def _subscribe_wallet_websockets(self, wallet_address: str):
        """Subscribe to WebSocket channels for a wallet"""

        # Position updates callback
        async def position_update_callback(data: dict):
            await self._handle_position_update(wallet_address, data)

        # Balance updates callback
        async def balance_update_callback(data: dict):
            await self._handle_balance_update(wallet_address, data)

        # Subscribe to channels
        await self.ws_manager.subscribe_wallet_positions(
            wallet_address,
            position_update_callback
        )

        await self.ws_manager.subscribe_wallet_balances(
            wallet_address,
            balance_update_callback
        )

        logger.info(f"Subscribed to WebSocket updates for {wallet_address}")

    async def _periodic_update_task(self, wallet_address: str):
        """Periodic update task (fallback if WebSocket fails)"""
        try:
            while True:
                await asyncio.sleep(60)  # Update every minute
                await self._fetch_wallet_data(wallet_address)
        except asyncio.CancelledError:
            logger.info(f"Periodic update task cancelled for {wallet_address}")
            raise

    async def _fetch_wallet_data(self, wallet_address: str):
        """Fetch wallet data from REST API"""
        try:
            logger.warning(f"🔍 FETCHING DATA for wallet {wallet_address}")
            print(f"🔍 FETCHING DATA for wallet {wallet_address}")

            # Fetch accounts first
            accounts = await self.reya_client.get_wallet_accounts(wallet_address)
            logger.warning(f"🔍 Got {len(accounts) if accounts else 0} accounts")
            print(f"🔍 Got {len(accounts) if accounts else 0} accounts: {accounts}")

            # Fetch positions
            positions_data = await self.reya_client.get_wallet_positions(wallet_address)
            logger.warning(f"🔍 Got {len(positions_data) if positions_data else 0} positions")
            print(f"🔍 Got {len(positions_data) if positions_data else 0} positions: {positions_data}")

            # Fetch balances
            balance_data = await self.reya_client.get_wallet_balances(wallet_address)
            logger.warning(f"🔍 Got balance data: {balance_data}")
            print(f"🔍 Got balance data: {balance_data}")

            # Process data
            if balance_data:
                await self._process_balance_data(wallet_address, balance_data)

            if positions_data:
                for position_data in positions_data:
                    await self._process_position_data(wallet_address, position_data)

            # Check risks and send alerts
            await self._check_and_alert(wallet_address)

        except Exception as e:
            logger.error(f"Error fetching wallet data for {wallet_address}: {e}", exc_info=True)
            print(f"❌ ERROR fetching wallet data: {e}")

    async def _process_position_data(self, wallet_address: str, position_data: dict):
        """Process position data and update database"""
        try:
            # Get wallet from database
            wallet = self.user_manager.get_wallet_by_address(wallet_address)
            if not wallet:
                logger.warning(f"Wallet not found in database: {wallet_address}")
                return

            # Extract position fields (adjust based on actual Reya API response)
            position = Position(
                wallet_id=wallet.id,
                symbol=position_data.get('symbol', ''),
                qty=float(position_data.get('qty', 0)),
                side=position_data.get('side', 'LONG'),
                entry_price=float(position_data.get('entry_price', 0)),
                mark_price=float(position_data.get('mark_price', 0)) if position_data.get('mark_price') else None,
                unrealized_pnl=float(position_data.get('unrealized_pnl', 0)) if position_data.get('unrealized_pnl') else None
            )

            # Save to database
            self.db.upsert_position(position)

            logger.debug(f"Updated position: {wallet_address} - {position.symbol}")

        except Exception as e:
            logger.error(f"Error processing position data: {e}", exc_info=True)

    async def _process_balance_data(self, wallet_address: str, balance_data):
        """Process balance data and update database"""
        try:
            # Get wallet from database
            wallet = self.user_manager.get_wallet_by_address(wallet_address)
            if not wallet:
                logger.warning(f"Wallet not found in database: {wallet_address}")
                return

            logger.debug(f"Processing balance data type: {type(balance_data)}, data: {balance_data}")

            # Handle if balance_data is a list (take first item) or dict
            if isinstance(balance_data, list):
                if len(balance_data) == 0:
                    logger.warning(f"Empty balance data list for {wallet_address}")
                    return
                balance_dict = balance_data[0]
            elif isinstance(balance_data, dict):
                # Check if there's a 'balances' key wrapping the actual data
                if 'balances' in balance_data:
                    balances = balance_data['balances']
                    if isinstance(balances, list) and len(balances) > 0:
                        balance_dict = balances[0]
                    elif isinstance(balances, dict):
                        balance_dict = balances
                    else:
                        logger.warning(f"Invalid balances structure for {wallet_address}")
                        return
                else:
                    balance_dict = balance_data
            else:
                logger.error(f"Unexpected balance data type: {type(balance_data)}")
                return

            logger.debug(f"Extracted balance_dict: {balance_dict}")

            # Extract balance fields - try different possible field names
            total_margin = float(balance_dict.get('total_margin',
                                balance_dict.get('totalMargin',
                                balance_dict.get('equity',
                                balance_dict.get('totalEquity', 0)))))

            used_margin = float(balance_dict.get('used_margin',
                               balance_dict.get('usedMargin',
                               balance_dict.get('initialMargin', 0))))

            available_margin = float(balance_dict.get('available_margin',
                                    balance_dict.get('availableMargin',
                                    balance_dict.get('availableBalance', total_margin - used_margin))))

            unrealized_pnl = float(balance_dict.get('unrealized_pnl',
                                   balance_dict.get('unrealizedPnl',
                                   balance_dict.get('unrealizedProfit', 0))))

            logger.info(f"Parsed balance for {wallet_address}: total={total_margin}, used={used_margin}, available={available_margin}, pnl={unrealized_pnl}")

            # Extract balance fields (adjust based on actual Reya API response)
            balance = AccountBalance(
                wallet_id=wallet.id,
                total_margin=total_margin,
                used_margin=used_margin,
                available_margin=available_margin,
                unrealized_pnl=unrealized_pnl
            )

            # Save to database
            self.db.upsert_account_balance(balance)

            logger.debug(f"Updated balance: {wallet_address}")

        except Exception as e:
            logger.error(f"Error processing balance data: {e}", exc_info=True)

    async def _handle_position_update(self, wallet_address: str, data: dict):
        """Handle real-time position update from WebSocket"""
        logger.info(f"Position update received for {wallet_address}")

        # Process the update
        await self._process_position_data(wallet_address, data)

        # Check risks and send alerts
        await self._check_and_alert(wallet_address)

    async def _handle_balance_update(self, wallet_address: str, data: dict):
        """Handle real-time balance update from WebSocket"""
        logger.info(f"Balance update received for {wallet_address}")

        # Process the update
        await self._process_balance_data(wallet_address, data)

        # Check risks and send alerts
        await self._check_and_alert(wallet_address)

    async def _check_and_alert(self, wallet_address: str):
        """Check positions for liquidation risk and send alerts"""
        try:
            # Get wallet from database
            wallet = self.user_manager.get_wallet_by_address(wallet_address)
            if not wallet:
                return

            # Get positions and balance
            positions = self.db.get_wallet_positions(wallet.id)
            balance = self.db.get_account_balance(wallet.id)

            if not balance:
                logger.debug(f"No balance data for {wallet_address}")
                return

            if not positions:
                logger.debug(f"No positions for {wallet_address}")
                return

            # Get threshold settings
            threshold = self.user_manager.get_wallet_threshold(wallet.id)

            # Check each position
            for position in positions:
                # Skip positions with invalid data
                if not position.entry_price or position.entry_price == 0:
                    logger.warning(f"Skipping position {position.symbol} - invalid entry price")
                    continue

                try:
                    # Calculate risk metrics
                    risk_metrics = self.risk_calculator.calculate_risk_metrics(
                        position,
                        balance
                    )

                    # Update position in database with calculated values
                    self.db.upsert_position(risk_metrics.position)

                    # Determine alert level
                    alert_level = threshold.get_alert_level(balance.margin_ratio)

                    if alert_level:
                        # Check if we should send alert (not too frequent)
                        should_alert = self._should_send_alert(
                            wallet_address,
                            position.symbol,
                            alert_level
                        )

                        if should_alert:
                            await self._send_alert(
                                wallet,
                                risk_metrics,
                                alert_level
                            )
                except Exception as e:
                    logger.error(f"Error calculating risk for position {position.symbol}: {e}", exc_info=True)
                    continue

        except Exception as e:
            logger.error(f"Error checking alerts for {wallet_address}: {e}", exc_info=True)

    def _should_send_alert(
        self,
        wallet_address: str,
        position_symbol: str,
        alert_level: AlertSeverity
    ) -> bool:
        """Check if enough time has passed since last alert"""

        # Get frequency based on severity
        if alert_level == AlertSeverity.URGENT:
            min_interval = ALERT_FREQUENCY_URGENT
        elif alert_level == AlertSeverity.CRITICAL:
            min_interval = ALERT_FREQUENCY_CRITICAL
        else:
            min_interval = ALERT_FREQUENCY_WARNING

        # Check last alert time
        if wallet_address not in self.last_alert_times:
            self.last_alert_times[wallet_address] = {}

        key = f"{position_symbol}:{alert_level.value}"
        last_time = self.last_alert_times[wallet_address].get(key)

        if last_time:
            time_elapsed = (datetime.utcnow() - last_time).total_seconds()
            if time_elapsed < min_interval:
                logger.debug(f"Skipping alert (too soon): {wallet_address} - {key}")
                return False

        return True

    async def _send_alert(
        self,
        wallet,
        risk_metrics,
        alert_level: AlertSeverity
    ):
        """Send alert to user via Telegram"""
        try:
            # Get user
            user = self.user_manager.get_user_by_wallet(wallet.wallet_address)
            if not user:
                logger.error(f"User not found for wallet {wallet.wallet_address}")
                return

            # Format alert message
            message = format_liquidation_alert(risk_metrics, wallet.wallet_address)

            # Create alert record
            alert = Alert(
                wallet_id=wallet.id,
                alert_type="liquidation_risk",
                message=message,
                severity=alert_level.value,
                position_symbol=risk_metrics.position.symbol,
                margin_ratio=risk_metrics.account_balance.margin_ratio,
                liquidation_price=risk_metrics.liquidation_price
            )
            alert = self.db.create_alert(alert)

            # Send via Telegram
            if self.telegram_bot:
                await self.telegram_bot.send_alert(
                    user.telegram_id,
                    message,
                    add_buttons=True
                )
                self.db.mark_alert_sent(alert.id)

                # Update last alert time
                if wallet.wallet_address not in self.last_alert_times:
                    self.last_alert_times[wallet.wallet_address] = {}

                key = f"{risk_metrics.position.symbol}:{alert_level.value}"
                self.last_alert_times[wallet.wallet_address][key] = datetime.utcnow()

                logger.info(
                    f"Alert sent: {user.telegram_id} - "
                    f"{wallet.wallet_address} - {alert_level.value}"
                )
            else:
                logger.warning("Telegram bot not set, cannot send alert")

        except Exception as e:
            logger.error(f"Error sending alert: {e}", exc_info=True)

    async def get_wallet_status(self, wallet_address: str) -> Optional[Dict[str, Any]]:
        """Get current status of a wallet"""
        try:
            wallet = self.user_manager.get_wallet_by_address(wallet_address)
            if not wallet:
                return None

            positions = self.db.get_wallet_positions(wallet.id)
            balance = self.db.get_account_balance(wallet.id)

            if not balance:
                return {
                    "position_count": 0,
                    "margin_ratio": 0.0,
                    "status": "No data"
                }

            # Determine status
            margin_ratio = balance.margin_ratio
            if margin_ratio >= 95:
                status = "🚨 CRITICAL"
            elif margin_ratio >= 90:
                status = "🔴 HIGH RISK"
            elif margin_ratio >= 80:
                status = "🟡 WARNING"
            else:
                status = "✅ HEALTHY"

            return {
                "position_count": len(positions),
                "margin_ratio": margin_ratio,
                "status": status,
                "total_margin": balance.total_margin,
                "used_margin": balance.used_margin,
                "available_margin": balance.available_margin
            }

        except Exception as e:
            logger.error(f"Error getting wallet status: {e}", exc_info=True)
            return None

    async def get_portfolio_summary(self, wallet_address: str) -> Optional[Dict[str, Any]]:
        """Get portfolio summary for a wallet"""
        try:
            wallet = self.user_manager.get_wallet_by_address(wallet_address)
            if not wallet:
                return None

            positions = self.db.get_wallet_positions(wallet.id)
            balance = self.db.get_account_balance(wallet.id)

            if not balance:
                return None

            # Calculate portfolio metrics
            portfolio_metrics = self.risk_calculator.assess_portfolio_risk(
                positions,
                balance
            )

            return {
                "positions": positions,
                "balance": portfolio_metrics
            }

        except Exception as e:
            logger.error(f"Error getting portfolio summary: {e}", exc_info=True)
            return None

    async def start_all_monitoring(self):
        """Start monitoring all active wallets"""
        wallets = self.user_manager.get_all_monitored_wallets()

        logger.info(f"Starting monitoring for {len(wallets)} wallets")

        for wallet in wallets:
            try:
                await self.start_monitoring_wallet(wallet.wallet_address)
            except Exception as e:
                logger.error(
                    f"Error starting monitoring for {wallet.wallet_address}: {e}",
                    exc_info=True
                )

        logger.info("All wallet monitoring started")

    async def stop_all_monitoring(self):
        """Stop monitoring all wallets"""
        wallets = list(self.monitoring_tasks.keys())

        for wallet_address in wallets:
            try:
                await self.stop_monitoring_wallet(wallet_address)
            except Exception as e:
                logger.error(
                    f"Error stopping monitoring for {wallet_address}: {e}",
                    exc_info=True
                )

        logger.info("All wallet monitoring stopped")
