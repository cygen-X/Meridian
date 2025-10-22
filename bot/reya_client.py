"""
Reya API Client for REST endpoints
Handles all HTTP requests to Reya.xyz API
"""
import aiohttp
import asyncio
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from config.settings import REYA_API_URL, API_RATE_LIMIT, API_REQUEST_SPACING

logger = logging.getLogger(__name__)


class ReyaAPIClient:
    """Client for Reya.xyz REST API"""

    def __init__(self, api_url: str = REYA_API_URL):
        self.api_url = api_url.rstrip('/')
        self.session: Optional[aiohttp.ClientSession] = None
        self.last_request_time = 0
        self.request_spacing = API_REQUEST_SPACING

    async def _ensure_session(self):
        """Ensure aiohttp session exists"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()

    async def _rate_limit(self):
        """Implement rate limiting"""
        current_time = asyncio.get_event_loop().time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.request_spacing:
            await asyncio.sleep(self.request_spacing - time_since_last)
        self.last_request_time = asyncio.get_event_loop().time()

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        retry_count: int = 3
    ) -> Optional[Dict[str, Any]]:
        """Make HTTP request with retry logic"""
        await self._ensure_session()
        await self._rate_limit()

        url = f"{self.api_url}{endpoint}"

        for attempt in range(retry_count):
            try:
                async with self.session.request(
                    method,
                    url,
                    params=params,
                    json=json_data,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.debug(f"Request successful: {method} {endpoint}")
                        return data
                    elif response.status == 429:
                        # Rate limited, wait and retry
                        retry_after = int(response.headers.get('Retry-After', 5))
                        logger.warning(f"Rate limited, waiting {retry_after}s")
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        logger.error(f"Request failed: {response.status} - {await response.text()}")
                        return None

            except asyncio.TimeoutError:
                logger.error(f"Request timeout: {method} {endpoint}")
                if attempt < retry_count - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    continue
                return None

            except aiohttp.ClientError as e:
                logger.error(f"Request error: {e}")
                if attempt < retry_count - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None

            except Exception as e:
                logger.error(f"Unexpected error in request: {e}", exc_info=True)
                return None

        return None

    async def get_wallet_positions(self, wallet_address: str) -> Optional[List[Dict[str, Any]]]:
        """
        Get all positions for a wallet
        GET /api/trading/wallet/{address}/positions
        """
        endpoint = f"/api/trading/wallet/{wallet_address}/positions"
        response = await self._make_request('GET', endpoint)

        logger.debug(f"Positions API response for {wallet_address}: {response}")

        if response:
            # Handle different response formats
            if isinstance(response, list):
                logger.info(f"Fetched {len(response)} positions for {wallet_address}")
                return response
            elif isinstance(response, dict) and 'positions' in response:
                logger.info(f"Fetched {len(response['positions'])} positions for {wallet_address}")
                return response['positions']
            else:
                logger.info(f"Positions response: {response}")
                return []

        logger.warning(f"No positions found for {wallet_address}")
        return []

    async def get_wallet_balances(self, wallet_address: str) -> Optional[Dict[str, Any]]:
        """
        Get account balances for a wallet
        Try multiple endpoints:
        - /api/trading/wallet/{address}/accounts/balances
        - /api/trading/wallet/{address}/account
        - /api/v2/accounts/{address}
        """
        # Try primary endpoint
        endpoint = f"/api/trading/wallet/{wallet_address}/accounts/balances"
        response = await self._make_request('GET', endpoint)

        logger.info(f"Balance API response for {wallet_address}: {response}")

        if response:
            return response

        # Try alternative endpoint
        logger.info(f"Trying alternative endpoint for {wallet_address}")
        endpoint = f"/api/trading/wallet/{wallet_address}/account"
        response = await self._make_request('GET', endpoint)

        if response:
            logger.info(f"Got balance from alternative endpoint: {response}")
            return response

        logger.warning(f"No balances found for {wallet_address} on any endpoint")
        return None

    async def get_markets(self) -> Optional[List[Dict[str, Any]]]:
        """
        Get all available markets
        GET /api/trading/markets
        """
        endpoint = "/api/trading/markets"
        response = await self._make_request('GET', endpoint)

        if response and 'markets' in response:
            logger.info(f"Fetched {len(response['markets'])} markets")
            return response['markets']

        logger.warning("No markets found")
        return []

    async def get_market_summary(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get market summary including funding rate
        GET /api/trading/market/{symbol}/summary
        """
        endpoint = f"/api/trading/market/{symbol}/summary"
        response = await self._make_request('GET', endpoint)

        if response:
            logger.info(f"Fetched market summary for {symbol}")
            return response

        logger.warning(f"No market summary found for {symbol}")
        return None

    async def get_market_price(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get current market price
        GET /api/trading/market/{symbol}/price
        """
        endpoint = f"/api/trading/market/{symbol}/price"
        response = await self._make_request('GET', endpoint)

        if response:
            logger.debug(f"Fetched price for {symbol}")
            return response

        return None

    async def get_position_details(self, wallet_address: str, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed position information
        GET /api/trading/wallet/{address}/position/{symbol}
        """
        endpoint = f"/api/trading/wallet/{wallet_address}/position/{symbol}"
        response = await self._make_request('GET', endpoint)

        if response:
            logger.info(f"Fetched position details for {wallet_address} - {symbol}")
            return response

        return None

    async def get_funding_history(self, symbol: str, limit: int = 100) -> Optional[List[Dict[str, Any]]]:
        """
        Get funding rate history
        GET /api/trading/market/{symbol}/funding
        """
        endpoint = f"/api/trading/market/{symbol}/funding"
        params = {'limit': limit}
        response = await self._make_request('GET', endpoint, params=params)

        if response and 'funding_history' in response:
            logger.info(f"Fetched {len(response['funding_history'])} funding records for {symbol}")
            return response['funding_history']

        return []

    async def validate_wallet_address(self, wallet_address: str) -> bool:
        """
        Validate if a wallet address exists on Reya
        Returns True if wallet is valid and has data
        """
        try:
            # Try to fetch positions
            response = await self.get_wallet_balances(wallet_address)
            if response is not None:
                logger.info(f"Wallet {wallet_address} is valid")
                return True

            logger.warning(f"Wallet {wallet_address} validation failed")
            return False

        except Exception as e:
            logger.error(f"Error validating wallet {wallet_address}: {e}")
            return False

    async def close(self):
        """Close the aiohttp session"""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("Reya API client session closed")

    async def __aenter__(self):
        """Async context manager entry"""
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()


# Singleton instance
_reya_client: Optional[ReyaAPIClient] = None


def get_reya_client() -> ReyaAPIClient:
    """Get singleton Reya API client"""
    global _reya_client
    if _reya_client is None:
        _reya_client = ReyaAPIClient()
    return _reya_client
