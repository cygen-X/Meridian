"""
Configuration settings for Meridian Bot
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Reya API Configuration
REYA_API_URL = os.getenv("REYA_API_URL", "https://api.reya.xyz")
REYA_WS_URL = os.getenv("REYA_WS_URL", "wss://ws.reya.xyz")

# Database Configuration
DATABASE_PATH = os.getenv("DATABASE_PATH", "./data/meridian.db")

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "./logs/meridian.log")

# Alert Thresholds (default values)
DEFAULT_ALERT_THRESHOLD_WARNING = 80  # Yellow alert at 80%
DEFAULT_ALERT_THRESHOLD_CRITICAL = 90  # Red alert at 90%
DEFAULT_ALERT_THRESHOLD_URGENT = 95  # Critical alert at 95%

# Alert Frequency (seconds between repeated alerts)
ALERT_FREQUENCY_WARNING = 3600  # 1 hour for warning alerts
ALERT_FREQUENCY_CRITICAL = 1800  # 30 minutes for critical alerts
ALERT_FREQUENCY_URGENT = 300  # 5 minutes for urgent alerts

# API Rate Limiting
API_RATE_LIMIT = 30  # requests per minute
API_REQUEST_SPACING = 0.1  # seconds between requests

# WebSocket Configuration
WS_RECONNECT_INITIAL_DELAY = 1  # seconds
WS_RECONNECT_MAX_DELAY = 60  # seconds
WS_RECONNECT_MULTIPLIER = 2  # exponential backoff multiplier
WS_PING_INTERVAL = 30  # seconds
WS_PING_TIMEOUT = 10  # seconds

# Position Monitoring
POSITION_UPDATE_INTERVAL = 60  # seconds for REST API fallback
PRICE_UPDATE_INTERVAL = 5  # seconds for price checks

# Risk Calculation Constants
MAINTENANCE_MARGIN_RATIO = 0.03  # 3% maintenance margin (adjust based on Reya's actual values)
VOLATILITY_CONSTANT = 0.05  # 5% daily volatility assumption for time estimation

# Alert Messages
ALERT_EMOJI = {
    "warning": "🟡",
    "critical": "🔴",
    "urgent": "🚨",
    "info": "ℹ️",
    "success": "✅",
    "error": "❌"
}

# Telegram Message Limits
MAX_MESSAGE_LENGTH = 4096

# Validation
ETHEREUM_ADDRESS_PATTERN = r"^0x[a-fA-F0-9]{40}$"

# Feature Flags
ENABLE_FUNDING_RATE_ALERTS = True
ENABLE_PNL_TRACKING = True
ENABLE_POSITION_SUGGESTIONS = True
