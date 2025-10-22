"""
Data models for Meridian Bot
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
from enum import Enum


class PositionSide(Enum):
    """Position side enumeration"""
    LONG = "LONG"
    SHORT = "SHORT"


class AlertSeverity(Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    URGENT = "urgent"


@dataclass
class User:
    """User model"""
    telegram_id: int
    username: Optional[str] = None
    id: Optional[int] = None
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


@dataclass
class Wallet:
    """Wallet model"""
    user_id: int
    wallet_address: str
    active: bool = True
    id: Optional[int] = None
    created_at: Optional[datetime] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
        # Normalize wallet address to lowercase
        self.wallet_address = self.wallet_address.lower()


@dataclass
class Position:
    """Position model"""
    wallet_id: int
    symbol: str
    qty: float
    side: str
    entry_price: float
    mark_price: Optional[float] = None
    liquidation_price: Optional[float] = None
    margin_ratio: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    id: Optional[int] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        if self.updated_at is None:
            self.updated_at = datetime.utcnow()

    @property
    def position_side(self) -> PositionSide:
        """Get position side as enum"""
        return PositionSide.LONG if self.side.upper() == "LONG" else PositionSide.SHORT

    @property
    def position_value(self) -> float:
        """Calculate position value"""
        return abs(self.qty) * (self.mark_price or self.entry_price)


@dataclass
class Alert:
    """Alert model"""
    wallet_id: int
    alert_type: str
    message: str
    severity: str
    position_symbol: Optional[str] = None
    margin_ratio: Optional[float] = None
    liquidation_price: Optional[float] = None
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    sent: bool = False

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()

    @property
    def severity_enum(self) -> AlertSeverity:
        """Get severity as enum"""
        return AlertSeverity(self.severity)


@dataclass
class Threshold:
    """Alert threshold configuration"""
    wallet_id: int
    threshold_warning: float = 80.0  # Yellow alert
    threshold_critical: float = 90.0  # Red alert
    threshold_urgent: float = 95.0  # Critical alert
    id: Optional[int] = None

    def get_alert_level(self, margin_ratio: float) -> Optional[AlertSeverity]:
        """Determine alert level based on margin ratio"""
        if margin_ratio >= self.threshold_urgent:
            return AlertSeverity.URGENT
        elif margin_ratio >= self.threshold_critical:
            return AlertSeverity.CRITICAL
        elif margin_ratio >= self.threshold_warning:
            return AlertSeverity.WARNING
        return None


@dataclass
class AccountBalance:
    """Account balance model"""
    wallet_id: int
    total_margin: float
    used_margin: float
    available_margin: float
    unrealized_pnl: float = 0.0
    id: Optional[int] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        if self.updated_at is None:
            self.updated_at = datetime.utcnow()

    @property
    def margin_ratio(self) -> float:
        """Calculate margin utilization ratio"""
        if self.total_margin == 0:
            return 0.0
        return (self.used_margin / self.total_margin) * 100


@dataclass
class MarketSummary:
    """Market summary data"""
    symbol: str
    mark_price: float
    index_price: float
    funding_rate: float
    next_funding_time: Optional[datetime] = None
    volume_24h: Optional[float] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        if self.updated_at is None:
            self.updated_at = datetime.utcnow()

    @property
    def funding_rate_pct(self) -> float:
        """Get funding rate as percentage"""
        return self.funding_rate * 100


@dataclass
class RiskMetrics:
    """Risk calculation metrics"""
    position: Position
    account_balance: AccountBalance
    liquidation_price: float
    distance_to_liquidation: float  # percentage
    estimated_hours_to_liquidation: Optional[float] = None
    recommended_actions: List[str] = field(default_factory=list)

    @property
    def is_at_risk(self) -> bool:
        """Check if position is at risk"""
        return self.account_balance.margin_ratio >= 80.0

    @property
    def risk_level(self) -> AlertSeverity:
        """Get current risk level"""
        ratio = self.account_balance.margin_ratio
        if ratio >= 95:
            return AlertSeverity.URGENT
        elif ratio >= 90:
            return AlertSeverity.CRITICAL
        elif ratio >= 80:
            return AlertSeverity.WARNING
        return AlertSeverity.INFO
