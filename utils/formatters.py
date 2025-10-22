"""
Message formatting utilities for Telegram
"""
from datetime import datetime
from typing import Optional, List
from data.models import Position, RiskMetrics, Alert, AlertSeverity
from config.settings import ALERT_EMOJI, MAX_MESSAGE_LENGTH


def format_price(price: float) -> str:
    """Format price with appropriate decimals"""
    if price >= 1000:
        return f"${price:,.2f}"
    elif price >= 1:
        return f"${price:.4f}"
    else:
        return f"${price:.8f}"


def format_percentage(value: float) -> str:
    """Format percentage value"""
    return f"{value:.2f}%"


def format_position_side(side: str) -> str:
    """Format position side with emoji"""
    if side.upper() == "LONG":
        return "📈 LONG"
    else:
        return "📉 SHORT"


def format_risk_level(margin_ratio: float) -> str:
    """Format risk level with emoji and color indicator"""
    if margin_ratio >= 95:
        return f"{ALERT_EMOJI['urgent']} CRITICAL ({margin_ratio:.1f}%)"
    elif margin_ratio >= 90:
        return f"{ALERT_EMOJI['critical']} HIGH RISK ({margin_ratio:.1f}%)"
    elif margin_ratio >= 80:
        return f"{ALERT_EMOJI['warning']} WARNING ({margin_ratio:.1f}%)"
    else:
        return f"{ALERT_EMOJI['success']} HEALTHY ({margin_ratio:.1f}%)"


def format_liquidation_alert(risk_metrics: RiskMetrics, wallet_address: str) -> str:
    """
    Format liquidation risk alert message

    Args:
        risk_metrics: Risk metrics data
        wallet_address: Wallet address

    Returns: Formatted alert message
    """
    position = risk_metrics.position
    balance = risk_metrics.account_balance

    # Truncate wallet address
    wallet_short = f"{wallet_address[:6]}...{wallet_address[-4:]}"

    # Build message
    lines = [
        f"{ALERT_EMOJI['urgent']} LIQUIDATION RISK ALERT - MERIDIAN",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"Wallet: `{wallet_short}`",
        f"Symbol: {position.symbol}",
        f"Side: {format_position_side(position.side)}",
        f"Size: {abs(position.qty):.4f}",
        f"Entry Price: {format_price(position.entry_price)}",
    ]

    if position.mark_price:
        lines.append(f"Current Price: {format_price(position.mark_price)}")

    lines.extend([
        f"Margin Ratio: {format_risk_level(balance.margin_ratio)}",
        f"Liquidation Price: {format_price(risk_metrics.liquidation_price)}",
        f"Distance to Liquidation: {format_percentage(risk_metrics.distance_to_liquidation)}",
    ])

    if risk_metrics.estimated_hours_to_liquidation:
        hours = risk_metrics.estimated_hours_to_liquidation
        if hours < 24:
            time_str = f"~{hours:.1f} hours"
        else:
            time_str = f"~{hours/24:.1f} days"
        lines.append(f"Time to Liquidation: {time_str} (if trend continues)")

    if position.unrealized_pnl:
        pnl_emoji = "🟢" if position.unrealized_pnl > 0 else "🔴"
        lines.append(f"Unrealized P&L: {pnl_emoji} ${position.unrealized_pnl:,.2f}")

    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "💡 Recommendations:",
    ])

    # Add recommendations
    for i, recommendation in enumerate(risk_metrics.recommended_actions[:3], 1):
        lines.append(f"{i}. {recommendation}")

    message = "\n".join(lines)

    # Truncate if too long
    if len(message) > MAX_MESSAGE_LENGTH:
        message = message[:MAX_MESSAGE_LENGTH-3] + "..."

    return message


def format_position_summary(position: Position, balance: Optional[dict] = None) -> str:
    """Format position summary"""
    lines = [
        f"📊 {position.symbol}",
        f"  {format_position_side(position.side)} | Size: {abs(position.qty):.4f}",
        f"  Entry: {format_price(position.entry_price)}",
    ]

    if position.mark_price:
        lines.append(f"  Current: {format_price(position.mark_price)}")

    if position.liquidation_price:
        lines.append(f"  Liquidation: {format_price(position.liquidation_price)}")

    if position.unrealized_pnl:
        pnl_emoji = "🟢" if position.unrealized_pnl > 0 else "🔴"
        lines.append(f"  P&L: {pnl_emoji} ${position.unrealized_pnl:,.2f}")

    return "\n".join(lines)


def format_portfolio_summary(
    positions: List[Position],
    balance: dict,
    wallet_address: str
) -> str:
    """Format complete portfolio summary"""
    wallet_short = f"{wallet_address[:6]}...{wallet_address[-4:]}"

    lines = [
        "📈 PORTFOLIO SUMMARY",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"Wallet: `{wallet_short}`",
        "",
        "💰 BALANCE:",
    ]

    # Safe access to balance fields
    total_margin = balance.get('total_margin', 0)
    used_margin = balance.get('used_margin', 0)
    available_margin = balance.get('available_margin', total_margin - used_margin if total_margin and used_margin else 0)
    unrealized_pnl = balance.get('unrealized_pnl', 0)
    margin_ratio = balance.get('margin_ratio', balance.get('overall_margin_ratio', 0))

    lines.extend([
        f"  Total Margin: ${total_margin:,.2f}",
        f"  Used Margin: ${used_margin:,.2f}",
        f"  Available: ${available_margin:,.2f}",
    ])

    if unrealized_pnl != 0:
        pnl_emoji = "🟢" if unrealized_pnl > 0 else "🔴"
        lines.append(f"  Unrealized P&L: {pnl_emoji} ${unrealized_pnl:,.2f}")

    if margin_ratio > 0:
        lines.append(f"  Margin Ratio: {format_risk_level(margin_ratio)}")

    lines.extend(["", f"📊 POSITIONS ({len(positions)}):"])

    if not positions:
        lines.append("  No open positions")
    else:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        for position in positions[:10]:
            lines.append(format_position_summary(position))
            lines.append("")

        if len(positions) > 10:
            lines.append(f"... and {len(positions) - 10} more positions")

    return "\n".join(lines)


def format_welcome_message() -> str:
    """Format welcome message for new users"""
    return """
🚀 Welcome to MERIDIAN - Your Liquidation Guard Bot!

I monitor your positions on Reya.xyz and alert you about liquidation risks in real-time.

🔍 What I do:
• Real-time position monitoring via WebSocket
• Smart liquidation risk calculations
• Instant alerts when positions are at risk
• Actionable recommendations to protect your funds

🛠️ Commands:
/add_wallet <address> - Start monitoring a wallet
/status - Check all monitored positions
/portfolio - View complete portfolio summary
/set_alert_threshold <percentage> - Customize alerts
/history - View alert history
/help - Show all commands

🔒 Security:
• 100% non-custodial (read-only access)
• No private keys required
• Public API endpoints only

Let's get started! Use /add_wallet to add your first wallet address.
"""


def format_help_message() -> str:
    """Format help message with all commands"""
    return """
📚 MERIDIAN BOT COMMANDS

👛 Wallet Management:
/add_wallet <address> - Start monitoring a wallet
/remove_wallet <address> - Stop monitoring a wallet

📊 Status & Monitoring:
/status - View all monitored positions
/portfolio - Complete portfolio summary
/history - Alert history (last 24h)

⚙️ Settings:
/set_alert_threshold <percentage> - Set custom alert threshold (e.g., 75)
  Default thresholds: 80% (warning), 90% (critical), 95% (urgent)

❓ Help:
/help - Show this message
/start - Show welcome message

💡 Example Usage:
/add_wallet 0x1234567890abcdef1234567890abcdef12345678
/set_alert_threshold 75
/status

🔔 Alert Levels:
🟡 Warning (80%) - Position requires attention
🔴 Critical (90%) - Position at high risk
🚨 Urgent (95%) - Liquidation imminent!

Need help? Visit: https://github.com/your-repo/meridian
"""


def format_alert_history(alerts: List[Alert]) -> str:
    """Format alert history"""
    if not alerts:
        return f"{ALERT_EMOJI['info']} No alerts in the last 24 hours. All positions are healthy!"

    lines = [
        "📜 ALERT HISTORY (Last 24h)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ""
    ]

    for alert in alerts[:20]:  # Limit to 20 recent alerts
        severity_emoji = ALERT_EMOJI.get(alert.severity, "ℹ️")
        timestamp = alert.created_at.strftime("%m/%d %H:%M") if alert.created_at else "N/A"

        line = f"{severity_emoji} {timestamp} | {alert.alert_type}"
        if alert.position_symbol:
            line += f" | {alert.position_symbol}"
        if alert.margin_ratio:
            line += f" | {alert.margin_ratio:.1f}%"

        lines.append(line)

    return "\n".join(lines)


def format_error_message(error: str) -> str:
    """Format error message"""
    return f"{ALERT_EMOJI['error']} Error: {error}"


def format_success_message(message: str) -> str:
    """Format success message"""
    return f"{ALERT_EMOJI['success']} {message}"


def format_info_message(message: str) -> str:
    """Format info message"""
    return f"{ALERT_EMOJI['info']} {message}"


def truncate_message(message: str, max_length: int = MAX_MESSAGE_LENGTH) -> str:
    """Truncate message to maximum length"""
    if len(message) <= max_length:
        return message
    return message[:max_length-3] + "..."
