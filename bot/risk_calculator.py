"""
Risk Calculator for liquidation price and risk metrics
"""
import logging
from typing import Optional, List, Tuple
from dataclasses import dataclass

from data.models import Position, AccountBalance, RiskMetrics, PositionSide
from config.settings import MAINTENANCE_MARGIN_RATIO, VOLATILITY_CONSTANT

logger = logging.getLogger(__name__)


class RiskCalculator:
    """Calculate liquidation risk and provide recommendations"""

    def __init__(
        self,
        maintenance_margin_ratio: float = MAINTENANCE_MARGIN_RATIO,
        volatility_constant: float = VOLATILITY_CONSTANT
    ):
        self.maintenance_margin_ratio = maintenance_margin_ratio
        self.volatility_constant = volatility_constant

    def calculate_liquidation_price(
        self,
        position: Position,
        leverage: Optional[float] = None
    ) -> float:
        """
        Calculate liquidation price for a position

        Formula:
        - Long: liq_price = entry_price * (1 - maintenance_margin_ratio)
        - Short: liq_price = entry_price * (1 + maintenance_margin_ratio)

        With leverage:
        - Long: liq_price = entry_price * (1 - 1/leverage + maintenance_margin_ratio)
        - Short: liq_price = entry_price * (1 + 1/leverage - maintenance_margin_ratio)
        """
        entry_price = position.entry_price

        if leverage:
            # More precise calculation with leverage
            if position.position_side == PositionSide.LONG:
                liq_price = entry_price * (1 - (1 / leverage) + self.maintenance_margin_ratio)
            else:  # SHORT
                liq_price = entry_price * (1 + (1 / leverage) - self.maintenance_margin_ratio)
        else:
            # Simplified calculation
            if position.position_side == PositionSide.LONG:
                liq_price = entry_price * (1 - self.maintenance_margin_ratio)
            else:  # SHORT
                liq_price = entry_price * (1 + self.maintenance_margin_ratio)

        logger.debug(f"Liquidation price for {position.symbol} {position.side}: ${liq_price:.2f}")
        return liq_price

    def calculate_distance_to_liquidation(
        self,
        current_price: float,
        liquidation_price: float
    ) -> float:
        """
        Calculate percentage distance to liquidation price

        Returns: Percentage distance (positive value)
        """
        distance = abs(current_price - liquidation_price) / current_price * 100
        return distance

    def estimate_time_to_liquidation(
        self,
        current_price: float,
        liquidation_price: float,
        position_side: PositionSide,
        price_trend: Optional[float] = None
    ) -> Optional[float]:
        """
        Estimate hours until liquidation based on price movement

        Args:
            current_price: Current market price
            liquidation_price: Calculated liquidation price
            position_side: LONG or SHORT
            price_trend: Price change rate (% per hour), if known

        Returns: Estimated hours to liquidation, or None if not applicable
        """
        distance = self.calculate_distance_to_liquidation(current_price, liquidation_price)

        # Determine if price is moving toward liquidation
        if position_side == PositionSide.LONG:
            is_approaching = current_price > liquidation_price and (price_trend or 0) < 0
        else:  # SHORT
            is_approaching = current_price < liquidation_price and (price_trend or 0) > 0

        if not is_approaching:
            return None

        # Use provided trend or estimate with volatility constant
        hourly_change_rate = abs(price_trend) if price_trend else self.volatility_constant

        if hourly_change_rate == 0:
            return None

        # Calculate hours
        hours = distance / hourly_change_rate

        logger.debug(f"Estimated time to liquidation: {hours:.1f} hours")
        return hours

    def calculate_margin_impact(
        self,
        account_balance: AccountBalance,
        additional_margin: float
    ) -> float:
        """
        Calculate new margin ratio after adding collateral

        Returns: New margin ratio percentage
        """
        new_total_margin = account_balance.total_margin + additional_margin
        if new_total_margin == 0:
            return 0.0

        new_margin_ratio = (account_balance.used_margin / new_total_margin) * 100
        return new_margin_ratio

    def calculate_position_reduction_impact(
        self,
        position: Position,
        account_balance: AccountBalance,
        reduction_percentage: float
    ) -> float:
        """
        Calculate new margin ratio after reducing position size

        Args:
            position: Current position
            account_balance: Current account balance
            reduction_percentage: Percentage to reduce position (0-100)

        Returns: New margin ratio percentage
        """
        # Calculate freed margin
        position_value = position.position_value
        position_margin = position_value / 10  # Assuming 10x leverage as estimate

        freed_margin = position_margin * (reduction_percentage / 100)

        new_used_margin = account_balance.used_margin - freed_margin
        if account_balance.total_margin == 0:
            return 0.0

        new_margin_ratio = (new_used_margin / account_balance.total_margin) * 100
        return max(0, new_margin_ratio)

    def generate_recommendations(
        self,
        position: Position,
        account_balance: AccountBalance,
        current_margin_ratio: float,
        target_ratio: float = 60.0
    ) -> List[str]:
        """
        Generate actionable recommendations to reduce risk

        Args:
            position: Current position
            account_balance: Current account balance
            current_margin_ratio: Current margin utilization
            target_ratio: Target margin ratio to achieve

        Returns: List of recommendation strings
        """
        recommendations = []

        if current_margin_ratio <= target_ratio:
            recommendations.append(f"✅ Position is healthy (Risk: {current_margin_ratio:.1f}%)")
            return recommendations

        # Calculate required reduction
        risk_reduction_needed = current_margin_ratio - target_ratio

        # Option 1: Close percentage of position
        close_percentage = (risk_reduction_needed / current_margin_ratio) * 100
        close_percentage = min(100, max(10, close_percentage))  # Between 10-100%

        new_ratio_close = self.calculate_position_reduction_impact(
            position, account_balance, close_percentage
        )

        recommendations.append(
            f"📉 Close {close_percentage:.0f}% of {position.symbol} position "
            f"→ Risk drops to {new_ratio_close:.1f}%"
        )

        # Option 2: Add collateral
        additional_margin_needed = account_balance.used_margin * (
            (100 / target_ratio) - (100 / current_margin_ratio)
        )

        if additional_margin_needed > 0:
            new_ratio_margin = self.calculate_margin_impact(
                account_balance, additional_margin_needed
            )

            recommendations.append(
                f"💰 Add ${additional_margin_needed:,.0f} collateral "
                f"→ Risk drops to {new_ratio_margin:.1f}%"
            )

        # Option 3: Combination approach
        moderate_close = min(50, close_percentage / 2)
        moderate_margin = additional_margin_needed / 2

        new_ratio_combo = self.calculate_position_reduction_impact(
            position, account_balance, moderate_close
        )
        new_ratio_combo = self.calculate_margin_impact(
            AccountBalance(
                wallet_id=account_balance.wallet_id,
                total_margin=account_balance.total_margin,
                used_margin=account_balance.used_margin * (1 - moderate_close / 100),
                available_margin=account_balance.available_margin
            ),
            moderate_margin
        )

        recommendations.append(
            f"🎯 Close {moderate_close:.0f}% + Add ${moderate_margin:,.0f} "
            f"→ Risk drops to ~{new_ratio_combo:.1f}%"
        )

        # Option 4: Set stop-loss
        if position.liquidation_price:
            stop_loss_buffer = 0.05  # 5% buffer above liquidation
            if position.position_side == PositionSide.LONG:
                suggested_stop = position.liquidation_price * (1 + stop_loss_buffer)
            else:
                suggested_stop = position.liquidation_price * (1 - stop_loss_buffer)

            recommendations.append(
                f"🛑 Set stop-loss at ${suggested_stop:,.2f} "
                f"(5% buffer above liquidation)"
            )

        return recommendations

    def calculate_risk_metrics(
        self,
        position: Position,
        account_balance: AccountBalance,
        current_price: Optional[float] = None,
        leverage: Optional[float] = None,
        price_trend: Optional[float] = None
    ) -> RiskMetrics:
        """
        Calculate comprehensive risk metrics for a position

        Returns: RiskMetrics object with all calculations
        """
        # Use current price or mark price
        mark_price = current_price or position.mark_price or position.entry_price

        # Calculate liquidation price
        liquidation_price = self.calculate_liquidation_price(position, leverage)

        # Calculate distance to liquidation
        distance = self.calculate_distance_to_liquidation(mark_price, liquidation_price)

        # Estimate time to liquidation
        hours_to_liq = self.estimate_time_to_liquidation(
            mark_price,
            liquidation_price,
            position.position_side,
            price_trend
        )

        # Generate recommendations
        recommendations = self.generate_recommendations(
            position,
            account_balance,
            account_balance.margin_ratio
        )

        # Update position with calculated values
        position.mark_price = mark_price
        position.liquidation_price = liquidation_price
        position.margin_ratio = account_balance.margin_ratio

        return RiskMetrics(
            position=position,
            account_balance=account_balance,
            liquidation_price=liquidation_price,
            distance_to_liquidation=distance,
            estimated_hours_to_liquidation=hours_to_liq,
            recommended_actions=recommendations
        )

    def assess_portfolio_risk(
        self,
        positions: List[Position],
        account_balance: AccountBalance
    ) -> dict:
        """
        Assess overall portfolio risk across all positions

        Returns: Dictionary with portfolio risk metrics
        """
        if not positions:
            return {
                "total_positions": 0,
                "overall_margin_ratio": 0.0,
                "positions_at_risk": 0,
                "total_exposure": 0.0,
                "most_risky_position": None
            }

        total_exposure = sum(
            abs(pos.qty) * (pos.mark_price or pos.entry_price)
            for pos in positions
        )

        positions_at_risk = sum(
            1 for pos in positions
            if pos.margin_ratio and pos.margin_ratio >= 80
        )

        # Find most risky position
        most_risky = max(
            positions,
            key=lambda p: p.margin_ratio or 0,
            default=None
        )

        return {
            "total_positions": len(positions),
            "overall_margin_ratio": account_balance.margin_ratio,
            "margin_ratio": account_balance.margin_ratio,
            "positions_at_risk": positions_at_risk,
            "total_exposure": total_exposure,
            "most_risky_position": most_risky.symbol if most_risky else None,
            "total_margin": account_balance.total_margin,
            "available_margin": account_balance.available_margin,
            "used_margin": account_balance.used_margin,
            "unrealized_pnl": account_balance.unrealized_pnl
        }
