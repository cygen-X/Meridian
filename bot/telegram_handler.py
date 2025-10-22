"""
Telegram Bot Handler
Manages all Telegram bot commands and interactions
"""
import logging
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters
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

# Conversation states
WAITING_FOR_WALLET_ADDRESS = 1


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

        # Persistent menu keyboard
        self.main_keyboard = ReplyKeyboardMarkup([
            [KeyboardButton("➕ Add Wallet"), KeyboardButton("📊 Status")],
            [KeyboardButton("💼 Portfolio"), KeyboardButton("📜 History")],
            [KeyboardButton("⚙️ Settings"), KeyboardButton("❓ Help")]
        ], resize_keyboard=True)

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        if not user:
            return

        # Register user
        self.user_manager.register_user(user.id, user.username)

        # Send welcome message with keyboard
        await update.message.reply_text(
            format_welcome_message(),
            parse_mode='Markdown',
            reply_markup=self.main_keyboard
        )

        logger.info(f"User started bot: {user.id} (@{user.username})")

    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show main menu with action buttons"""
        keyboard = [
            [
                InlineKeyboardButton("➕ Add Wallet", callback_data="menu_add_wallet"),
                InlineKeyboardButton("➖ Remove Wallet", callback_data="menu_remove_wallet")
            ],
            [
                InlineKeyboardButton("📊 Status", callback_data="menu_status"),
                InlineKeyboardButton("💼 Portfolio", callback_data="menu_portfolio")
            ],
            [
                InlineKeyboardButton("🔔 Set Alert Threshold", callback_data="menu_threshold"),
                InlineKeyboardButton("📜 History", callback_data="menu_history")
            ],
            [
                InlineKeyboardButton("❓ Help", callback_data="menu_help")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        menu_text = (
            "🎛️ *Main Menu*\n\n"
            "Choose an action below:"
        )

        if update.callback_query:
            await update.callback_query.edit_message_text(
                menu_text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                menu_text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )

    async def menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /menu command"""
        await self.show_main_menu(update, context)

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
        await self._add_wallet_flow(update, context, wallet_address)

    async def _add_wallet_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE, wallet_address: str):
        """Common flow for adding wallet"""
        user = update.effective_user
        if not user:
            return

        # Send processing message
        if update.callback_query:
            processing_msg = await update.callback_query.message.reply_text(
                "🔍 Validating wallet address..."
            )
        else:
            processing_msg = await update.message.reply_text(
                "🔍 Validating wallet address..."
            )

        # Add wallet
        success, message, wallet = self.user_manager.add_wallet(
            user.id,
            wallet_address
        )

        if success:
            await processing_msg.edit_text(
                f"✅ *Wallet Added Successfully!*\n\n"
                f"📍 Address: `{wallet_address[:10]}...{wallet_address[-8:]}`\n"
                f"📊 Status: Active\n\n"
                f"Starting monitoring...",
                parse_mode='Markdown'
            )

            # Start monitoring this wallet
            try:
                await self.liquidation_monitor.start_monitoring_wallet(wallet.wallet_address)
                await processing_msg.edit_text(
                    f"✅ *Wallet Added Successfully!*\n\n"
                    f"📍 Address: `{wallet_address[:10]}...{wallet_address[-8:]}`\n"
                    f"📊 Status: Monitoring Active\n"
                    f"🔔 Alerts: Enabled\n\n"
                    f"You'll receive alerts when positions are at risk of liquidation.",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Error starting monitoring: {e}", exc_info=True)
                await processing_msg.edit_text(
                    f"⚠️ *Wallet Added with Warning*\n\n"
                    f"📍 Address: `{wallet_address[:10]}...{wallet_address[-8:]}`\n"
                    f"❌ Monitoring failed to start: {str(e)}\n\n"
                    f"Please contact support if this persists.",
                    parse_mode='Markdown'
                )
        else:
            await processing_msg.edit_text(
                f"❌ *Failed to Add Wallet*\n\n"
                f"{message}\n\n"
                f"Please check the address and try again.",
                parse_mode='Markdown'
            )

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
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=self.main_keyboard)

    async def portfolio_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /portfolio command"""
        user = update.effective_user
        if not user:
            return

        logger.info(f"Portfolio command triggered by user {user.id}")

        # Get user's wallets
        wallets = self.user_manager.get_user_wallets(user.id)
        logger.info(f"User has {len(wallets)} wallets")

        if not wallets:
            await update.message.reply_text(
                format_info_message(
                    "You have no wallets being monitored.\n"
                    "Use the ➕ Add Wallet button!"
                ),
                reply_markup=self.main_keyboard
            )
            return

        # Show all wallets' portfolios
        for wallet in wallets:
            logger.info(f"Getting portfolio for wallet {wallet.wallet_address}")
            try:
                # Force fetch fresh data first
                await self.liquidation_monitor._fetch_wallet_data(wallet.wallet_address)

                portfolio_data = await self.liquidation_monitor.get_portfolio_summary(
                    wallet.wallet_address
                )

                logger.info(f"Portfolio data: {portfolio_data}")

                if portfolio_data and portfolio_data.get('balance'):
                    message = format_portfolio_summary(
                        portfolio_data.get('positions', []),
                        portfolio_data['balance'],
                        wallet.wallet_address
                    )
                    await update.message.reply_text(message, parse_mode='Markdown', reply_markup=self.main_keyboard)
                else:
                    await update.message.reply_text(
                        f"ℹ️ Wallet `{wallet.wallet_address[:10]}...`: No data available",
                        parse_mode='Markdown',
                        reply_markup=self.main_keyboard
                    )

            except Exception as e:
                logger.error(f"Error getting portfolio for {wallet.wallet_address}: {e}", exc_info=True)
                await update.message.reply_text(
                    format_error_message(f"Failed to retrieve data for {wallet.wallet_address[:10]}..."),
                    reply_markup=self.main_keyboard
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

        # Handle menu actions
        if action == "menu_add_wallet":
            await query.edit_message_text(
                "➕ *Add Wallet*\n\n"
                "Please send your wallet address in the next message.\n\n"
                "Format: `0x1234...`\n\n"
                "You can also use: `/add_wallet 0x1234...`",
                parse_mode='Markdown'
            )
            # Store state for next message
            context.user_data['awaiting_wallet'] = True

        elif action == "menu_remove_wallet":
            user = update.effective_user
            if not user:
                return

            wallets = self.user_manager.get_user_wallets(user.id)
            if not wallets:
                await query.edit_message_text(
                    "❌ You have no wallets to remove.\n\n"
                    "Use the menu to add a wallet first.",
                    parse_mode='Markdown'
                )
                return

            # Show wallet selection buttons
            keyboard = []
            for wallet in wallets:
                wallet_short = f"{wallet.wallet_address[:6]}...{wallet.wallet_address[-4:]}"
                keyboard.append([
                    InlineKeyboardButton(
                        f"🗑️ {wallet_short}",
                        callback_data=f"remove_wallet:{wallet.wallet_address}"
                    )
                ])
            keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")])
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                "➖ *Remove Wallet*\n\n"
                "Select a wallet to remove:",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )

        elif action == "menu_status":
            await self._show_status_via_callback(update, context)

        elif action == "menu_portfolio":
            await self._show_portfolio_via_callback(update, context)

        elif action == "menu_threshold":
            await query.edit_message_text(
                "🔔 *Set Alert Threshold*\n\n"
                "Send a message with your desired threshold percentage.\n\n"
                "Example: `75` (for 75% margin ratio)\n\n"
                "Or use: `/set_alert_threshold 75`",
                parse_mode='Markdown'
            )
            context.user_data['awaiting_threshold'] = True

        elif action == "menu_history":
            await self._show_history_via_callback(update, context)

        elif action == "menu_help":
            await query.edit_message_text(
                format_help_message(),
                parse_mode='Markdown'
            )

        elif action == "back_to_menu":
            await self.show_main_menu(update, context)

        elif action == "remove_wallet":
            if len(data_parts) < 2:
                await query.answer("Invalid wallet address")
                return

            wallet_address = data_parts[1]
            user = update.effective_user
            if not user:
                return

            # Remove wallet
            success, message = self.user_manager.remove_wallet(user.id, wallet_address)

            if success:
                try:
                    await self.liquidation_monitor.stop_monitoring_wallet(wallet_address)
                except Exception as e:
                    logger.error(f"Error stopping monitoring: {e}", exc_info=True)

                await query.edit_message_text(
                    f"✅ *Wallet Removed*\n\n"
                    f"📍 Address: `{wallet_address[:10]}...{wallet_address[-8:]}`\n"
                    f"📊 Status: Monitoring Stopped\n\n"
                    f"The wallet has been removed from monitoring.",
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text(
                    f"❌ *Failed to Remove Wallet*\n\n"
                    f"{message}",
                    parse_mode='Markdown'
                )

        elif action == "close_position":
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

        elif action == "portfolio":
            await self._show_portfolio_via_callback(update, context)

        elif action == "settings":
            await query.edit_message_text(
                "⚙️ Settings\n\n"
                "Use /set_alert_threshold to customize alert thresholds.\n"
                "Use /remove_wallet to stop monitoring a wallet."
            )

    async def _show_status_via_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show status via callback query"""
        user = update.effective_user
        if not user:
            return

        wallets = self.user_manager.get_user_wallets(user.id)

        if not wallets:
            await update.callback_query.edit_message_text(
                "ℹ️ You have no wallets being monitored.\n\n"
                "Use the menu to add a wallet first!",
                parse_mode='Markdown'
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

        message = "📈 *MONITORING STATUS*\n\n" + "\n".join(status_messages)
        await update.callback_query.edit_message_text(message, parse_mode='Markdown')

    async def _show_portfolio_via_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show portfolio via callback query"""
        user = update.effective_user
        if not user:
            return

        wallets = self.user_manager.get_user_wallets(user.id)

        if not wallets:
            await update.callback_query.edit_message_text(
                "ℹ️ You have no wallets being monitored.\n\n"
                "Use the menu to add a wallet first!",
                parse_mode='Markdown'
            )
            return

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
                await update.callback_query.edit_message_text(message, parse_mode='Markdown')
            else:
                await update.callback_query.edit_message_text(
                    "ℹ️ No positions found for this wallet.",
                    parse_mode='Markdown'
                )

        except Exception as e:
            logger.error(f"Error getting portfolio: {e}", exc_info=True)
            await update.callback_query.edit_message_text(
                "❌ Failed to retrieve portfolio data.",
                parse_mode='Markdown'
            )

    async def _show_history_via_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show history via callback query"""
        user = update.effective_user
        if not user:
            return

        wallets = self.user_manager.get_user_wallets(user.id)

        if not wallets:
            await update.callback_query.edit_message_text(
                "ℹ️ You have no wallets being monitored.",
                parse_mode='Markdown'
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
        await update.callback_query.edit_message_text(message, parse_mode='Markdown')

    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages for wallet address or threshold input"""
        user = update.effective_user
        if not user:
            return

        text = update.message.text.strip()

        # Handle keyboard button presses
        if text == "➕ Add Wallet":
            await update.message.reply_text(
                "➕ *Add Wallet*\n\n"
                "Please send your wallet address:\n\n"
                "Format: `0x1234...`",
                parse_mode='Markdown',
                reply_markup=self.main_keyboard
            )
            context.user_data['awaiting_wallet'] = True
            return
        elif text == "📊 Status":
            await self.status_command(update, context)
            return
        elif text == "💼 Portfolio":
            await self.portfolio_command(update, context)
            return
        elif text == "📜 History":
            await self.history_command(update, context)
            return
        elif text == "⚙️ Settings":
            await update.message.reply_text(
                "⚙️ *Settings*\n\n"
                "Send your desired alert threshold (0-100):\n\n"
                "Example: `75`",
                parse_mode='Markdown',
                reply_markup=self.main_keyboard
            )
            context.user_data['awaiting_threshold'] = True
            return
        elif text == "❓ Help":
            await self.help_command(update, context)
            return

        # Check if awaiting wallet address
        if context.user_data.get('awaiting_wallet'):
            context.user_data['awaiting_wallet'] = False
            await self._add_wallet_flow(update, context, text)
            return

        # Check if awaiting threshold
        if context.user_data.get('awaiting_threshold'):
            context.user_data['awaiting_threshold'] = False
            try:
                threshold = float(text)
                if not validate_threshold(threshold):
                    await update.message.reply_text(
                        format_error_message("Threshold must be between 0 and 100."),
                        reply_markup=self.main_keyboard
                    )
                    return

                wallets = self.user_manager.get_user_wallets(user.id)

                if not wallets:
                    await update.message.reply_text(
                        format_info_message("You have no wallets. Add one first!"),
                        reply_markup=self.main_keyboard
                    )
                    return

                # Set threshold for all user's wallets
                for wallet in wallets:
                    self.user_manager.set_wallet_threshold(
                        user.id,
                        wallet.wallet_address,
                        threshold
                    )

                await update.message.reply_text(
                    f"✅ *Threshold Updated*\n\n"
                    f"🔔 Alert threshold set to *{threshold}%* for all wallets!\n\n"
                    f"You'll receive alerts when margin ratio reaches this level.",
                    parse_mode='Markdown',
                    reply_markup=self.main_keyboard
                )
            except ValueError:
                await update.message.reply_text(
                    format_error_message("Invalid threshold value. Please provide a number."),
                    reply_markup=self.main_keyboard
                )
            return

        # Default response if no state is set
        await update.message.reply_text(
            "ℹ️ Use the menu buttons below or /help for more information.",
            parse_mode='Markdown',
            reply_markup=self.main_keyboard
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
        self.application.add_handler(CommandHandler("menu", self.menu_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("add_wallet", self.add_wallet_command))
        self.application.add_handler(CommandHandler("remove_wallet", self.remove_wallet_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        self.application.add_handler(CommandHandler("portfolio", self.portfolio_command))
        self.application.add_handler(CommandHandler("set_alert_threshold", self.set_alert_threshold_command))
        self.application.add_handler(CommandHandler("history", self.history_command))

        # Add callback query handler
        self.application.add_handler(CallbackQueryHandler(self.handle_callback_query))

        # Add text message handler (for wallet address and threshold input)
        # This should be last to avoid catching commands
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_message))

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
