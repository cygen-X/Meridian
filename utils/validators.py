"""
Input validation utilities
"""
import re
from typing import Optional
from config.settings import ETHEREUM_ADDRESS_PATTERN


def is_valid_ethereum_address(address: str) -> bool:
    """
    Validate Ethereum address format

    Args:
        address: Ethereum address string

    Returns: True if valid, False otherwise
    """
    if not address:
        return False

    # Check format using regex
    pattern = re.compile(ETHEREUM_ADDRESS_PATTERN)
    return bool(pattern.match(address))


def validate_threshold(threshold: float) -> bool:
    """
    Validate alert threshold value

    Args:
        threshold: Threshold percentage

    Returns: True if valid (0-100), False otherwise
    """
    return 0 <= threshold <= 100


def validate_wallet_address(address: str) -> tuple[bool, Optional[str]]:
    """
    Validate and normalize wallet address

    Args:
        address: Wallet address string

    Returns: Tuple of (is_valid, normalized_address or error_message)
    """
    if not address:
        return False, "Wallet address cannot be empty"

    # Remove whitespace
    address = address.strip()

    # Check format
    if not is_valid_ethereum_address(address):
        return False, (
            "Invalid wallet address format. "
            "Must be 42 characters starting with '0x' followed by 40 hex characters."
        )

    # Normalize to lowercase
    normalized = address.lower()

    return True, normalized


def validate_alert_frequency(seconds: int) -> bool:
    """
    Validate alert frequency value

    Args:
        seconds: Frequency in seconds

    Returns: True if valid, False otherwise
    """
    # Minimum 60 seconds, maximum 1 day
    return 60 <= seconds <= 86400


def sanitize_input(text: str, max_length: int = 1000) -> str:
    """
    Sanitize user input text

    Args:
        text: Input text
        max_length: Maximum allowed length

    Returns: Sanitized text
    """
    if not text:
        return ""

    # Remove control characters except newline and tab
    sanitized = ''.join(
        char for char in text
        if char.isprintable() or char in ['\n', '\t']
    )

    # Truncate to max length
    return sanitized[:max_length]


def validate_position_data(position_data: dict) -> bool:
    """
    Validate position data structure

    Args:
        position_data: Position data dictionary

    Returns: True if valid, False otherwise
    """
    required_fields = ['symbol', 'qty', 'side', 'entry_price']

    for field in required_fields:
        if field not in position_data:
            return False

        # Check for None or empty values
        if position_data[field] is None or position_data[field] == '':
            return False

    # Validate numeric fields
    try:
        float(position_data['qty'])
        float(position_data['entry_price'])
    except (ValueError, TypeError):
        return False

    # Validate side
    if position_data['side'].upper() not in ['LONG', 'SHORT']:
        return False

    return True


def validate_balance_data(balance_data: dict) -> bool:
    """
    Validate account balance data structure

    Args:
        balance_data: Balance data dictionary

    Returns: True if valid, False otherwise
    """
    required_fields = ['total_margin', 'used_margin', 'available_margin']

    for field in required_fields:
        if field not in balance_data:
            return False

        # Check for None values
        if balance_data[field] is None:
            return False

    # Validate numeric fields
    try:
        total = float(balance_data['total_margin'])
        used = float(balance_data['used_margin'])
        available = float(balance_data['available_margin'])

        # Basic sanity checks
        if total < 0 or used < 0 or available < 0:
            return False

    except (ValueError, TypeError):
        return False

    return True
