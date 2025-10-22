"""
Reya WebSocket Manager for real-time updates
Handles WebSocket connections to Reya.xyz
"""
import asyncio
import json
import logging
from typing import Dict, Callable, Any, Optional, Set
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from config.settings import (
    REYA_WS_URL,
    WS_RECONNECT_INITIAL_DELAY,
    WS_RECONNECT_MAX_DELAY,
    WS_RECONNECT_MULTIPLIER,
    WS_PING_INTERVAL,
    WS_PING_TIMEOUT
)

logger = logging.getLogger(__name__)


class ReyaWebSocketManager:
    """Manages WebSocket connections to Reya.xyz"""

    def __init__(self, ws_url: str = REYA_WS_URL):
        self.ws_url = ws_url
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.subscriptions: Dict[str, Set[str]] = {}  # channel_type -> set of identifiers
        self.callbacks: Dict[str, Callable] = {}  # channel -> callback function
        self.is_connected = False
        self.reconnect_delay = WS_RECONNECT_INITIAL_DELAY
        self.should_reconnect = True
        self.connection_task: Optional[asyncio.Task] = None
        self.ping_task: Optional[asyncio.Task] = None

    async def connect(self):
        """Establish WebSocket connection"""
        try:
            logger.info(f"Connecting to WebSocket: {self.ws_url}")
            self.websocket = await websockets.connect(
                self.ws_url,
                ping_interval=WS_PING_INTERVAL,
                ping_timeout=WS_PING_TIMEOUT,
                close_timeout=10
            )
            self.is_connected = True
            self.reconnect_delay = WS_RECONNECT_INITIAL_DELAY
            logger.info("WebSocket connected successfully")

            # Resubscribe to all channels
            await self._resubscribe_all()

            # Start listening for messages
            self.connection_task = asyncio.create_task(self._listen())

        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            self.is_connected = False
            await self._handle_reconnection()

    async def disconnect(self):
        """Disconnect from WebSocket"""
        self.should_reconnect = False

        if self.connection_task:
            self.connection_task.cancel()
            try:
                await self.connection_task
            except asyncio.CancelledError:
                pass

        if self.ping_task:
            self.ping_task.cancel()
            try:
                await self.ping_task
            except asyncio.CancelledError:
                pass

        if self.websocket and not self.websocket.closed:
            await self.websocket.close()
            logger.info("WebSocket disconnected")

        self.is_connected = False

    async def _listen(self):
        """Listen for incoming WebSocket messages"""
        try:
            while self.is_connected and self.websocket:
                try:
                    message = await self.websocket.recv()
                    await self._handle_message(message)

                except ConnectionClosed:
                    logger.warning("WebSocket connection closed")
                    self.is_connected = False
                    await self._handle_reconnection()
                    break

                except Exception as e:
                    logger.error(f"Error receiving message: {e}", exc_info=True)

        except asyncio.CancelledError:
            logger.info("WebSocket listener cancelled")
            raise

    async def _handle_message(self, message: str):
        """Handle incoming WebSocket message"""
        try:
            data = json.loads(message)

            # Determine message type/channel
            channel = data.get('channel') or data.get('type')

            if not channel:
                logger.warning(f"Message without channel: {data}")
                return

            # Call registered callback for this channel
            callback = self.callbacks.get(channel)
            if callback:
                try:
                    await callback(data)
                except Exception as e:
                    logger.error(f"Error in callback for {channel}: {e}", exc_info=True)
            else:
                logger.debug(f"No callback registered for channel: {channel}")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse message: {e}")
        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)

    async def _handle_reconnection(self):
        """Handle reconnection with exponential backoff"""
        if not self.should_reconnect:
            return

        self.is_connected = False

        logger.info(f"Reconnecting in {self.reconnect_delay}s...")
        await asyncio.sleep(self.reconnect_delay)

        # Exponential backoff
        self.reconnect_delay = min(
            self.reconnect_delay * WS_RECONNECT_MULTIPLIER,
            WS_RECONNECT_MAX_DELAY
        )

        await self.connect()

    async def subscribe(self, channel_type: str, identifier: str, callback: Callable):
        """
        Subscribe to a WebSocket channel

        Args:
            channel_type: Type of channel (e.g., 'wallet_positions', 'prices')
            identifier: Identifier for the channel (e.g., wallet address, symbol)
            callback: Async function to call when messages arrive
        """
        channel = f"{channel_type}:{identifier}"

        # Store subscription
        if channel_type not in self.subscriptions:
            self.subscriptions[channel_type] = set()
        self.subscriptions[channel_type].add(identifier)

        # Store callback
        self.callbacks[channel] = callback

        # Send subscribe message if connected
        if self.is_connected and self.websocket:
            await self._send_subscription(channel_type, identifier)

        logger.info(f"Subscribed to {channel}")

    async def unsubscribe(self, channel_type: str, identifier: str):
        """Unsubscribe from a WebSocket channel"""
        channel = f"{channel_type}:{identifier}"

        # Remove subscription
        if channel_type in self.subscriptions:
            self.subscriptions[channel_type].discard(identifier)

        # Remove callback
        if channel in self.callbacks:
            del self.callbacks[channel]

        # Send unsubscribe message if connected
        if self.is_connected and self.websocket:
            await self._send_unsubscription(channel_type, identifier)

        logger.info(f"Unsubscribed from {channel}")

    async def _send_subscription(self, channel_type: str, identifier: str):
        """Send subscription message to WebSocket"""
        try:
            # Format subscription message based on Reya's WebSocket protocol
            # This is a placeholder - adjust based on actual Reya WebSocket API
            subscribe_msg = {
                "type": "subscribe",
                "channel": channel_type,
                "id": identifier
            }

            # Different formats for different channel types
            if channel_type == "wallet_positions":
                subscribe_msg = {
                    "type": "subscribe",
                    "channel": f"/v2/wallet/{identifier}/positions"
                }
            elif channel_type == "wallet_balances":
                subscribe_msg = {
                    "type": "subscribe",
                    "channel": f"/v2/wallet/{identifier}/accounts/balances"
                }
            elif channel_type == "prices":
                subscribe_msg = {
                    "type": "subscribe",
                    "channel": f"/v2/prices/{identifier}"
                }
            elif channel_type == "market_summary":
                subscribe_msg = {
                    "type": "subscribe",
                    "channel": f"/v2/market/{identifier}/summary"
                }

            await self.websocket.send(json.dumps(subscribe_msg))
            logger.debug(f"Sent subscription: {subscribe_msg}")

        except Exception as e:
            logger.error(f"Error sending subscription: {e}")

    async def _send_unsubscription(self, channel_type: str, identifier: str):
        """Send unsubscription message to WebSocket"""
        try:
            unsubscribe_msg = {
                "type": "unsubscribe",
                "channel": channel_type,
                "id": identifier
            }

            await self.websocket.send(json.dumps(unsubscribe_msg))
            logger.debug(f"Sent unsubscription: {unsubscribe_msg}")

        except Exception as e:
            logger.error(f"Error sending unsubscription: {e}")

    async def _resubscribe_all(self):
        """Resubscribe to all channels after reconnection"""
        logger.info("Resubscribing to all channels...")

        for channel_type, identifiers in self.subscriptions.items():
            for identifier in identifiers:
                await self._send_subscription(channel_type, identifier)

        logger.info(f"Resubscribed to {sum(len(ids) for ids in self.subscriptions.values())} channels")

    async def subscribe_wallet_positions(self, wallet_address: str, callback: Callable):
        """Subscribe to position updates for a wallet"""
        await self.subscribe("wallet_positions", wallet_address, callback)

    async def subscribe_wallet_balances(self, wallet_address: str, callback: Callable):
        """Subscribe to balance updates for a wallet"""
        await self.subscribe("wallet_balances", wallet_address, callback)

    async def subscribe_price(self, symbol: str, callback: Callable):
        """Subscribe to price updates for a symbol"""
        await self.subscribe("prices", symbol, callback)

    async def subscribe_market_summary(self, symbol: str, callback: Callable):
        """Subscribe to market summary including funding rate"""
        await self.subscribe("market_summary", symbol, callback)

    def get_connection_status(self) -> Dict[str, Any]:
        """Get current connection status"""
        return {
            "is_connected": self.is_connected,
            "subscriptions_count": sum(len(ids) for ids in self.subscriptions.values()),
            "subscriptions": {
                channel_type: list(identifiers)
                for channel_type, identifiers in self.subscriptions.items()
            }
        }


# Singleton instance
_ws_manager: Optional[ReyaWebSocketManager] = None


def get_ws_manager() -> ReyaWebSocketManager:
    """Get singleton WebSocket manager"""
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = ReyaWebSocketManager()
    return _ws_manager
