"""
Binance API Client Wrapper
Handles request signing, retries, and API error mapping.
"""

import logging
import time
from typing import Any, Optional

import requests
import hmac
import hashlib
from urllib.parse import urlencode

from bot.config import (
    TESTNET_BASE_URL,
    PROD_BASE_URL,
    get_base_url,
    MAX_RETRIES,
    RETRY_BACKOFF_BASE,
    REQUEST_TIMEOUT,
    get_api_credentials,
    is_testnet,
)

log = logging.getLogger("bot.client")
api_log = logging.getLogger("bot.api")

# ─── Error Classes ────────────────────────────────────────────────────────────

class BinanceAPIError(Exception):
    """Raised when the Binance API returns a non-2xx response."""
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class AuthenticationError(BinanceAPIError):
    """Raised when API credentials are rejected."""


class InsufficientBalanceError(BinanceAPIError):
    """Raised when the account lacks funds for the requested order."""


class InvalidSymbolError(BinanceAPIError):
    """Raised when the requested symbol does not exist on the exchange."""


class RateLimitError(BinanceAPIError):
    """Raised when API rate limits are exceeded."""


# ─── Binance Client ───────────────────────────────────────────────────────────

class BinanceClient:
    """HTTP client for Binance Futures REST API."""

    BASE_URL: str = ""  # Set dynamically in __init__ based on TESTNET flag

    # Binance Futures API error code mapping
    _ERROR_MAP: dict[int, type[BinanceAPIError]] = {
        -1121: InvalidSymbolError,
        -2010: InsufficientBalanceError,
        -1100: BinanceAPIError,      # Bad parameter
        -1102: BinanceAPIError,      # Missing parameter
        -2011: BinanceAPIError,      # Unknown order sent
        -1022: AuthenticationError,  # Signature invalid
        -2014: AuthenticationError,  # API-key format invalid
        -2015: AuthenticationError,  # Invalid API-key, IP, permissions
    }

    def __init__(self) -> None:
        self.api_key, self.secret_key = get_api_credentials()
        self.BASE_URL = get_base_url()  # Dynamically set based on TESTNET env var
        self.session = requests.Session()
        self.session.headers.update({
            "X-MBX-APIKEY": self.api_key,
            "Content-Type": "application/x-www-form-urlencoded",
        })
        
        mode = "TESTNET" if is_testnet() else "MAINNET"
        
        mode = "TESTNET" if is_testnet() else "MAINNET"
        log.info("BinanceClient initialized (mode=%s, url=%s)", mode, self.BASE_URL)
        
        # Validate endpoint against testnet flag
        if is_testnet() and "testnet" not in self.BASE_URL:
            log.warning("TESTNET=true but using mainnet URL")
        elif not is_testnet() and "testnet" in self.BASE_URL:
            log.warning("TESTNET=false but using testnet URL")


    # ── Signature helpers ──────────────────────────────────────────────────

    def _sign(self, params: dict[str, Any]) -> dict[str, Any]:
        """Inject timestamp, recvWindow, and HMAC signature."""
        params["recvWindow"] = 60000  # 60s window – fixes clock-skew errors
        params["timestamp"] = int(time.time() * 1000)
        query_string = urlencode(params)
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        params["signature"] = signature
        return params

    # ── Low-level HTTP helpers ─────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        signed: bool = False,
    ) -> Any:
        """Executes HTTP request with retry logic and error handling."""
        params = params or {}
        if signed:
            params = self._sign(params)

        url = f"{self.BASE_URL}{path}"
        last_exc: Optional[Exception] = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                api_log.debug("→ %s %s params=%s", method, path, params)
                if method == "GET":
                    response = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
                elif method == "POST":
                    response = self.session.post(url, data=params, timeout=REQUEST_TIMEOUT)
                elif method == "DELETE":
                    response = self.session.delete(url, params=params, timeout=REQUEST_TIMEOUT)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                api_log.debug("← %s %s %s", response.status_code, path, response.text[:500])

                # Rate limit handling
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    log.warning("Rate limit hit. Waiting %ds before retry...", retry_after)
                    time.sleep(retry_after)
                    continue

                data = response.json()

                # Binance returns errors as JSON with 'code' < 0
                if isinstance(data, dict) and "code" in data and data["code"] < 0:
                    self._raise_api_error(data["code"], data.get("msg", "Unknown error"))

                response.raise_for_status()
                return data

            except (requests.ConnectionError, requests.Timeout) as exc:
                wait = RETRY_BACKOFF_BASE ** attempt
                log.warning(
                    "Network error on attempt %d/%d: %s. Retrying in %ds…",
                    attempt, MAX_RETRIES, exc, wait,
                )
                last_exc = exc
                time.sleep(wait)

        raise last_exc  # type: ignore[misc]

    def _raise_api_error(self, code: int, message: str) -> None:
        exc_class = self._ERROR_MAP.get(code, BinanceAPIError)
        raise exc_class(code, message)

    # ── Public API Methods ─────────────────────────────────────────────────

    def get_account_balance(self) -> list[dict]:
        """Fetches futures account balance."""
        data = self._request("GET", "/fapi/v2/balance", signed=True)
        log.info("Account balance fetched: %d assets", len(data))
        return data

    def get_usdt_balance(self) -> float:
        """Return the available USDT balance as a float."""
        balances = self.get_account_balance()
        for asset in balances:
            if asset.get("asset") == "USDT":
                return float(asset.get("availableBalance", 0))
        return 0.0

    def get_symbol_info(self, symbol: str) -> dict:
        """Fetches trading rules for a given symbol."""
        data = self._request("GET", "/fapi/v1/exchangeInfo")
        for s in data.get("symbols", []):
            if s["symbol"] == symbol:
                log.debug("Symbol info found: %s (status=%s)", symbol, s.get("status"))
                return s
        raise InvalidSymbolError(-1121, f"Symbol '{symbol}' not found on the exchange.")

    def place_market_order(self, symbol: str, side: str, quantity: float) -> dict:
        """Places a MARKET order."""
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity,
        }
        log.info("Placing MARKET order: %s %s %s", side, quantity, symbol)
        response = self._request("POST", "/fapi/v1/order", params=params, signed=True)
        log.info(
            "Market order placed: orderId=%s, symbol=%s, side=%s, qty=%s, status=%s",
            response.get("orderId"), symbol, side, quantity, response.get("status"),
        )
        return response

    def place_limit_order(self, symbol: str, side: str, quantity: float, price: float) -> dict:
        """Places a LIMIT order."""
        params = {
            "symbol": symbol,
            "side": side,
            "type": "LIMIT",
            "quantity": quantity,
            "price": price,
            "timeInForce": "GTC",
        }
        log.info(
            "Placing LIMIT order: %s %s %s @ %s", side, quantity, symbol, price
        )
        response = self._request("POST", "/fapi/v1/order", params=params, signed=True)
        log.info(
            "Limit order placed: orderId=%s, symbol=%s, side=%s, qty=%s, price=%s, status=%s",
            response.get("orderId"), symbol, side, quantity, price, response.get("status"),
        )
        return response

    def get_open_orders(self, symbol: Optional[str] = None) -> list[dict]:
        """Fetches open orders."""
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        log.info("Fetching open orders%s…", f" for {symbol}" if symbol else "")
        data = self._request("GET", "/fapi/v1/openOrders", params=params, signed=True)
        log.info("Found %d open order(s)", len(data))
        return data

    def get_order_status(self, symbol: str, order_id: int) -> dict:
        """
        Fetch the status of a specific order.

        Args:
            symbol:   Trading pair the order was placed on.
            order_id: Binance order ID.

        Returns:
            Order detail dict.
        """
        params = {"symbol": symbol, "orderId": order_id}
        log.info("Fetching order status: orderId=%d, symbol=%s", order_id, symbol)
        return self._request("GET", "/fapi/v1/order", params=params, signed=True)

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        """
        Cancel an open order.

        Args:
            symbol:   Trading pair.
            order_id: Binance order ID.

        Returns:
            Cancellation confirmation dict.
        """
        params = {"symbol": symbol, "orderId": order_id}
        log.info("Cancelling order: orderId=%d, symbol=%s", order_id, symbol)
        response = self._request("DELETE", "/fapi/v1/order", params=params, signed=True)
        log.info("Order cancelled: orderId=%d, status=%s", order_id, response.get("status"))
        return response

    def get_ticker_price(self, symbol: str) -> float:
        """Return the current mark/latest price for *symbol*."""
        data = self._request("GET", "/fapi/v1/ticker/price", params={"symbol": symbol})
        return float(data["price"])

    def get_klines(self, symbol: str, interval: str, limit: int = 100) -> list[dict]:
        """
        Fetch kline/candlestick data.
        """
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        data = self._request("GET", "/fapi/v1/klines", params=params)
        # return list of dicts for convenience or raw list. We return raw list.
        return data

    def get_position_risk(self, symbol: str) -> list[dict]:
        """
        Fetch position risk for a specific symbol to check if there's an open position.
        """
        params = {"symbol": symbol}
        return self._request("GET", "/fapi/v2/positionRisk", params=params, signed=True)

    def place_conditional_order(
        self, symbol: str, side: str, order_type: str, quantity: float, stop_price: float, reduce_only: bool = True
    ) -> dict:
        """
        Place a STOP_MARKET or TAKE_PROFIT_MARKET order.
        """
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": quantity,
            "stopPrice": stop_price,
            "reduceOnly": "true" if reduce_only else "false",
        }
        log.info("Placing %s order: %s %s %s @ stopPrice %s", order_type, side, quantity, symbol, stop_price)
        response = self._request("POST", "/fapi/v1/order", params=params, signed=True)
        log.info(
            "%s order placed: orderId=%s, status=%s",
            order_type, response.get("orderId"), response.get("status"),
        )
        return response
