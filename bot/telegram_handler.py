"""
Telegram Bot Handler
Manages all Telegram bot commands and interactions
"""
import logging
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler
)

from bot.user_manager import UserManager
from bot.liquidation_monitor import LiquidationMonitor
from utils.formatters import (
    format_welcome_message,
    format_help_message,
    format_error_message,
    format_success_message,
    format_info_message,
    format_alert_history,
    format_portfolio_summary
)
from utils.validators import validate_threshold
from config.settings import TELEGRAM_BOT_TOKEN

logger = logging.getLogger(__name__)


class TelegramBot:
    """Telegram bot handler"""

    def __init__(
        self,
        user_manager: UserManager,
        liquidation_monitor: LiquidationMonitor
    ):
        self.user_manager = user_manager
        self.liquidation_monitor = liquidation_monitor
        self.application: Optional[Application] = None

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        if not user:
            return

        # Register user
        self.user_manager.register_user(user.id, user.username)

        # Send welcome message
        await update.message.reply_text(
            format_welcome_message(),
            parse_mode='Markdown'
        )

        logger.info(f"User started bot: {user.id} (@{user.username})")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        await update.message.reply_text(
            format_help_message(),
            parse_mode='Markdown'
        )

    async def add_wallet_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /add_wallet command"""
        user = update.effective_user
        if not user:
            return

        # Check for wallet address argument
        if not context.args or len(context.args) == 0:
            await update.message.reply_text(
                format_error_message(
                    "Please provide a wallet address.\n"
                    "Usage: /add_wallet 0x1234..."
                )
            )
            return

        wallet_address = context.args[0]

        # Add wallet
        success, message, wallet = self.user_manager.add_wallet(
            user.id,
            wallet_address
        )

        if success:
            await update.message.reply_text(format_success_message(message))

            # Start monitoring this wallet
            try:
                await self.liquidation_monitor.start_monitoring_wallet(wallet.wallet_address)
                await update.message.reply_text(
                    format_info_message(
                        f"Monitoring started for wallet {wallet_address[:10]}...\n"
                        "You'll receive alerts when positions are at risk."
                    )
                )
            except Exception as e:
                logger.error(f"Error starting monitoring: {e}", exc_info=True)
                await update.message.reply_text(
                    format_error_message(
                        f"Wallet added but monitoring failed to start: {str(e)}"
                    )
                )
        else:
            await update.message.reply_text(format_error_message(message))

        logger.info(f"Add wallet request: {user.id} - {wallet_address} - {message}")

    async def remove_wallet_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /remove_wallet command"""
        user = update.effective_user
        if not user:
            return

        # Check for wallet address argument
        if not context.args or len(context.args) == 0:
            await update.message.reply_text(
                format_error_message(
                    "Please provide a wallet address.\n"
                    "Usage: /remove_wallet 0x1234..."
                )
            )
            return

        wallet_address = context.args[0]

        # Remove wallet
        success, message = self.user_manager.remove_wallet(
            user.id,
            wallet_address
        )

        if success:
            await update.message.reply_text(format_success_message(message))

            # Stop monitoring this wallet
            try:
                await self.liquidation_monitor.stop_monitoring_wallet(wallet_address)
            except Exception as e:
                logger.error(f"Error stopping monitoring: {e}", exc_info=True)
        else:
            await update.message.reply_text(format_error_message(message))

        logger.info(f"Remove wallet request: {user.id} - {wallet_address} - {message}")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        user = update.effective_user
        if not user:
            return

        # Get user's wallets
        wallets = self.user_manager.get_user_wallets(user.id)

        if not wallets:
            await update.message.reply_text(
                format_info_message(
                    "You have no wallets being monitored.\n"
                    "Use /add_wallet to add one!"
                )
            )
            return

        # Get status for each wallet
        status_messages = []
        for wallet in wallets:
            try:
                status = await self.liquidation_monitor.get_wallet_status(wallet.wallet_address)

                if status:
                    wallet_short = f"{wallet.wallet_address[:6]}...{wallet.wallet_address[-4:]}"
                    status_messages.append(
                        f"📊 Wallet: `{wallet_short}`\n"
                        f"   Positions: {status['position_count']}\n"
                        f"   Margin Ratio: {status['margin_ratio']:.2f}%\n"
                        f"   Status: {status['status']}\n"
                    )
                else:
                    status_messages.append(
                        f"⚠️ Wallet: `{wallet.wallet_address[:10]}...`\n"
                        f"   No data available\n"
                    )

            except Exception as e:
                logger.error(f"Error getting status for {wallet.wallet_address}: {e}")
                status_messages.append(
                    f"❌ Wallet: `{wallet.wallet_address[:10]}...`\n"
                    f"   Error retrieving status\n"
                )

        message = "📈 MONITORING STATUS\n\n" + "\n".join(status_messages)
        await update.message.reply_text(message, parse_mode='Markdown')

    async def portfolio_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /portfolio command"""
        user = update.effective_user
        if not user:
            return

        # Get user's wallets
        wallets = self.user_manager.get_user_wallets(user.id)

        if not wallets:
            await update.message.reply_text(
                format_info_message(
                    "You have no wallets being monitored.\n"
                    "Use /add_wallet to add one!"
                )
            )
            return

        # Get portfolio for first wallet (or combine if multiple)
        # For simplicity, showing first wallet's portfolio
        wallet = wallets[0]

        try:
            portfolio_data = await self.liquidation_monitor.get_portfolio_summary(
                wallet.wallet_address
            )

            if portfolio_data:
                message = format_portfolio_summary(
                    portfolio_data['positions'],
                    portfolio_data['balance'],
                    wallet.wallet_address
                )
                await update.message.reply_text(message, parse_mode='Markdown')
            else:
                await update.message.reply_text(
                    format_info_message("No positions found for this wallet.")
                )

        except Exception as e:
            logger.error(f"Error getting portfolio: {e}", exc_info=True)
            await update.message.reply_text(
                format_error_message("Failed to retrieve portfolio data.")
            )

    async def set_alert_threshold_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /set_alert_threshold command"""
        user = update.effective_user
        if not user:
            return

        # Check for threshold argument
        if not context.args or len(context.args) == 0:
            await update.message.reply_text(
                format_error_message(
                    "Please provide a threshold percentage.\n"
                    "Usage: /set_alert_threshold 75"
                )
            )
            return

        try:
            threshold = float(context.args[0])
        except ValueError:
            await update.message.reply_text(
                format_error_message("Invalid threshold value. Please provide a number.")
            )
            return

        # Validate threshold
        if not validate_threshold(threshold):
            await update.message.reply_text(
                format_error_message("Threshold must be between 0 and 100.")
            )
            return

        # Get user's wallets
        wallets = self.user_manager.get_user_wallets(user.id)

        if not wallets:
            await update.message.reply_text(
                format_info_message("You have no wallets. Add one first!")
            )
            return

        # Set threshold for all user's wallets
        results = []
        for wallet in wallets:
            success, message = self.user_manager.set_wallet_threshold(
                user.id,
                wallet.wallet_address,
                threshold
            )
            results.append((wallet.wallet_address, success, message))

        # Send response
        if all(r[1] for r in results):
            await update.message.reply_text(
                format_success_message(
                    f"Alert threshold set to {threshold}% for all wallets!"
                )
            )
        else:
            error_messages = [f"❌ {r[0][:10]}...: {r[2]}" for r in results if not r[1]]
            await update.message.reply_text(
                format_error_message("\n".join(error_messages))
            )

        logger.info(f"Set threshold: {user.id} - {threshold}%")

    async def history_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /history command"""
        user = update.effective_user
        if not user:
            return

        # Get user's wallets
        wallets = self.user_manager.get_user_wallets(user.id)

        if not wallets:
            await update.message.reply_text(
                format_info_message("You have no wallets being monitored.")
            )
            return

        # Get alerts for all wallets
        all_alerts = []
        for wallet in wallets:
            alerts = self.liquidation_monitor.db.get_recent_alerts(wallet.id, hours=24)
            all_alerts.extend(alerts)

        # Sort by created_at descending
        all_alerts.sort(key=lambda a: a.created_at, reverse=True)

        # Format and send
        message = format_alert_history(all_alerts)
        await update.message.reply_text(message, parse_mode='Markdown')

    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        await query.answer()

        # Parse callback data
        # Format: "action:wallet_address:optional_data"
        data_parts = query.data.split(':')
        action = data_parts[0]

        if action == "close_position":
            # TODO: Implement position closing (requires write access)
            await query.edit_message_text(
                "⚠️ Position closing requires wallet connection and is not yet implemented.\n"
                "Please close positions manually on Reya.xyz"
            )

        elif action == "add_margin":
            # TODO: Implement margin addition (requires write access)
            await query.edit_message_text(
                "⚠️ Adding margin requires wallet connection and is not yet implemented.\n"
                "Please add margin manually on Reya.xyz"
            )

        elif action == "settings":
            await query.edit_message_text(
                "⚙️ Settings\n\n"
                "Use /set_alert_threshold to customize alert thresholds.\n"
                "Use /remove_wallet to stop monitoring a wallet."
            )

    async def send_alert(
        self,
        telegram_id: int,
        message: str,
        add_buttons: bool = True
    ):
        """
        Send alert message to user

        Args:
            telegram_id: Telegram user ID
            message: Alert message text
            add_buttons: Whether to add action buttons
        """
        try:
            if add_buttons:
                keyboard = [
                    [
                        InlineKeyboardButton("📊 View Portfolio", callback_data="portfolio"),
                        InlineKeyboardButton("⚙️ Settings", callback_data="settings")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await self.application.bot.send_message(
                    chat_id=telegram_id,
                    text=message,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
            else:
                await self.application.bot.send_message(
                    chat_id=telegram_id,
                    text=message,
                    parse_mode='Markdown'
                )

            logger.info(f"Alert sent to user {telegram_id}")

        except Exception as e:
            logger.error(f"Error sending alert to {telegram_id}: {e}", exc_info=True)

    def setup(self):
        """Setup bot handlers"""
        # Create application
        self.application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        # Add command handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("add_wallet", self.add_wallet_command))
        self.application.add_handler(CommandHandler("remove_wallet", self.remove_wallet_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("portfolio", self.portfolio_command))
        self.application.add_handler(CommandHandler("set_alert_threshold", self.set_alert_threshold_command))
        self.application.add_handler(CommandHandler("history", self.history_command))

        # Add callback query handler
        self.application.add_handler(CallbackQueryHandler(self.handle_callback_query))

        logger.info("Telegram bot handlers configured")

    async def start(self):
        """Start the bot"""
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        logger.info("Telegram bot started")

    async def stop(self):
        """Stop the bot"""
        if self.application:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
        logger.info("Telegram bot stopped")
