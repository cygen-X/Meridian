"""
Meridian Bot - Main Entry Point
Smart Liquidation Guard Bot for Reya.xyz
"""
import asyncio
import signal
import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import DATABASE_PATH
from data.storage import Database
from bot.reya_client import ReyaAPIClient
from bot.risk_calculator import RiskCalculator
from bot.user_manager import UserManager
from bot.liquidation_monitor import LiquidationMonitor
from bot.telegram_handler import TelegramBot
from websocket.reya_websocket import ReyaWebSocketManager
from utils.logger import setup_logger

logger = setup_logger("meridian")


class MeridianBot:
    """Main bot orchestrator"""

    def __init__(self):
        self.db = None
        self.reya_client = None
        self.ws_manager = None
        self.user_manager = None
        self.risk_calculator = None
        self.liquidation_monitor = None
        self.telegram_bot = None
        self.shutdown_event = asyncio.Event()

    async def initialize(self):
        """Initialize all components"""
        logger.info("🚀 Initializing Meridian Bot...")

        try:
            # Ensure data directory exists
            data_dir = Path(DATABASE_PATH).parent
            data_dir.mkdir(parents=True, exist_ok=True)

            # Initialize database
            logger.info("Initializing database...")
            self.db = Database(DATABASE_PATH)

            # Initialize Reya API client
            logger.info("Initializing Reya API client...")
            self.reya_client = ReyaAPIClient()

            # Initialize WebSocket manager
            logger.info("Initializing WebSocket manager...")
            self.ws_manager = ReyaWebSocketManager()

            # Initialize risk calculator
            logger.info("Initializing risk calculator...")
            self.risk_calculator = RiskCalculator()

            # Initialize user manager
            logger.info("Initializing user manager...")
            self.user_manager = UserManager(self.db)

            # Initialize liquidation monitor
            logger.info("Initializing liquidation monitor...")
            self.liquidation_monitor = LiquidationMonitor(
                database=self.db,
                reya_client=self.reya_client,
                ws_manager=self.ws_manager,
                user_manager=self.user_manager,
                risk_calculator=self.risk_calculator
            )

            # Initialize Telegram bot
            logger.info("Initializing Telegram bot...")
            self.telegram_bot = TelegramBot(
                user_manager=self.user_manager,
                liquidation_monitor=self.liquidation_monitor
            )

            # Link telegram bot to liquidation monitor
            self.liquidation_monitor.set_telegram_bot(self.telegram_bot)

            # Setup Telegram bot handlers
            self.telegram_bot.setup()

            logger.info("✅ All components initialized successfully")

        except Exception as e:
            logger.error(f"❌ Initialization failed: {e}", exc_info=True)
            raise

    async def start(self):
        """Start the bot"""
        logger.info("🚀 Starting Meridian Bot...")

        try:
            # Connect WebSocket
            logger.info("Connecting to WebSocket...")
            await self.ws_manager.connect()

            # Start Telegram bot
            logger.info("Starting Telegram bot...")
            await self.telegram_bot.start()

            # Start monitoring existing wallets
            logger.info("Starting position monitoring...")
            await self.liquidation_monitor.start_all_monitoring()

            logger.info("✅ Meridian Bot is now running!")
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            logger.info("Bot is monitoring positions and ready to send alerts")
            logger.info("Press Ctrl+C to stop")
            logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

            # Wait for shutdown signal
            await self.shutdown_event.wait()

        except Exception as e:
            logger.error(f"❌ Error during startup: {e}", exc_info=True)
            raise

    async def stop(self):
        """Stop the bot gracefully"""
        logger.info("🛑 Stopping Meridian Bot...")

        try:
            # Stop monitoring
            if self.liquidation_monitor:
                logger.info("Stopping position monitoring...")
                await self.liquidation_monitor.stop_all_monitoring()

            # Stop Telegram bot
            if self.telegram_bot:
                logger.info("Stopping Telegram bot...")
                await self.telegram_bot.stop()

            # Disconnect WebSocket
            if self.ws_manager:
                logger.info("Disconnecting WebSocket...")
                await self.ws_manager.disconnect()

            # Close Reya API client
            if self.reya_client:
                logger.info("Closing Reya API client...")
                await self.reya_client.close()

            logger.info("✅ Meridian Bot stopped successfully")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}", exc_info=True)

    def handle_shutdown_signal(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, initiating shutdown...")
        self.shutdown_event.set()


async def main():
    """Main entry point"""
    bot = MeridianBot()

    # Setup signal handlers
    def signal_handler(signum, frame):
        bot.handle_shutdown_signal(signum, frame)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Initialize
        await bot.initialize()

        # Start
        await bot.start()

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

    finally:
        # Cleanup
        await bot.stop()


if __name__ == "__main__":
    # ASCII Art Banner
    print("""
    ███╗   ███╗███████╗██████╗ ██╗██████╗ ██╗ █████╗ ███╗   ██╗
    ████╗ ████║██╔════╝██╔══██╗██║██╔══██╗██║██╔══██╗████╗  ██║
    ██╔████╔██║█████╗  ██████╔╝██║██║  ██║██║███████║██╔██╗ ██║
    ██║╚██╔╝██║██╔══╝  ██╔══██╗██║██║  ██║██║██╔══██║██║╚██╗██║
    ██║ ╚═╝ ██║███████╗██║  ██║██║██████╔╝██║██║  ██║██║ ╚████║
    ╚═╝     ╚═╝╚══════╝╚═╝  ╚═╝╚═╝╚═════╝ ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝

    Smart Liquidation Guard Bot for Reya.xyz
    Version 1.0.0
    """)

    # Run the bot
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown complete. Goodbye! 👋")
