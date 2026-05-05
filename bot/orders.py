"""
Order Manager Module
Orchestrates order validation, balance checks, and execution.
"""

import logging
from typing import Any, Optional

from bot.client import (
    BinanceClient,
    BinanceAPIError,
    AuthenticationError,
    InsufficientBalanceError,
    InvalidSymbolError,
    RateLimitError,
)
from bot.validators import (
    MarketOrderInput,
    LimitOrderInput,
    ExchangeRuleValidator,
)

log = logging.getLogger("bot.orders")


# ─── Order Execution Manager ──────────────────────────────────────────────────
# This class handles the logic for executing and validating orders.
class OrderManager:
    """High-level order management wrapping BinanceClient with validation."""

    def __init__(self, client: BinanceClient, dry_run: bool = False) -> None:
        self.client = client
        self.dry_run = dry_run
        if dry_run:
            log.info("DRY-RUN mode active – no orders will be placed.")

    # ── Pre-flight checks ──────────────────────────────────────────────────

    def _get_validated_symbol_info(self, symbol: str) -> dict:
        """Fetch symbol info and assert the symbol is active/tradeable."""
        info = self.client.get_symbol_info(symbol)
        status = info.get("status", "")
        if status != "TRADING":
            raise ValueError(
                f"Symbol '{symbol}' is not currently tradeable (status={status})."
            )
        return info

    def _check_balance(self, required_usdt: float) -> float:
        """Verifies available USDT covers the required amount."""
        balance = self.client.get_usdt_balance()
        if balance < required_usdt:
            raise InsufficientBalanceError(
                -2010,
                f"Insufficient balance. Required: ${required_usdt:.2f} USDT, "
                f"Available: ${balance:.2f} USDT.",
            )
        return balance

    # ── Structured response builder ────────────────────────────────────────

    @staticmethod
    def _build_response(raw: dict) -> dict[str, Any]:
        """Normalise a Binance order response into a consistent dict."""
        return {
            "orderId": raw.get("orderId"),
            "clientOrderId": raw.get("clientOrderId"),
            "symbol": raw.get("symbol"),
            "side": raw.get("side"),
            "type": raw.get("type"),
            "origQty": raw.get("origQty"),
            "executedQty": raw.get("executedQty"),
            "avgPrice": raw.get("avgPrice") or raw.get("price"),
            "status": raw.get("status"),
            "timeInForce": raw.get("timeInForce"),
            "updateTime": raw.get("updateTime"),
            "dry_run": False,
        }

    @staticmethod
    def _build_dry_run_response(
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
    ) -> dict[str, Any]:
        """Return a mock order response for dry-run mode."""
        return {
            "orderId": "DRY-RUN",
            "clientOrderId": "dry_run_order",
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "origQty": str(quantity),
            "executedQty": "0",
            "avgPrice": str(price) if price else "N/A (market)",
            "status": "DRY_RUN_SIMULATED",
            "timeInForce": "GTC" if order_type == "LIMIT" else "N/A",
            "updateTime": None,
            "dry_run": True,
        }

    # ── Public order methods ───────────────────────────────────────────────

    def execute_market_order(self, symbol: str, side: str, quantity: float) -> dict[str, Any]:
        """Validates and executes a MARKET order."""
        validated = MarketOrderInput(symbol=symbol, side=side, quantity=quantity)
        symbol, side = validated.symbol, validated.side

        symbol_info = self._get_validated_symbol_info(symbol)
        rule_validator = ExchangeRuleValidator(symbol_info)
        quantity = rule_validator.validate_quantity(validated.quantity)

        current_price = self.client.get_ticker_price(symbol)
        estimated_cost = quantity * current_price
        
        if side == "BUY":
            self._check_balance(estimated_cost)

        rule_validator.validate_notional(quantity, current_price)

        log.info("Pre-flight passed for MARKET %s %s %s (est. cost: $%.2f)", side, quantity, symbol, estimated_cost)

        # ── Step 5: Place or simulate ──────────────────────────────────────
        if self.dry_run:
            log.info("DRY-RUN: Skipping actual market order placement.")
            return self._build_dry_run_response(symbol, side, "MARKET", quantity)

        raw = self.client.place_market_order(symbol, side, quantity)
        response = self._build_response(raw)

        # Handle partial fills
        executed = float(response.get("executedQty") or 0)
        original = float(response.get("origQty") or quantity)
        if executed < original:
            log.warning(
                "Partial fill: executed %s / %s for orderId=%s",
                executed, original, response.get("orderId"),
            )

        return response

    def execute_limit_order(self, symbol: str, side: str, quantity: float, price: float) -> dict[str, Any]:
        """Validates and executes a LIMIT order."""
        validated = LimitOrderInput(symbol=symbol, side=side, quantity=quantity, price=price)
        symbol, side = validated.symbol, validated.side

        symbol_info = self._get_validated_symbol_info(symbol)
        rule_validator = ExchangeRuleValidator(symbol_info)
        quantity = rule_validator.validate_quantity(validated.quantity)
        price = rule_validator.validate_price(validated.price)
        rule_validator.validate_notional(quantity, price)

        if side == "BUY":
            self._check_balance(quantity * price)

        log.info("Pre-flight passed for LIMIT %s %s %s @ %s", side, quantity, symbol, price)

        # ── Step 4: Place or simulate ──────────────────────────────────────
        if self.dry_run:
            log.info("DRY-RUN: Skipping actual limit order placement.")
            return self._build_dry_run_response(symbol, side, "LIMIT", quantity, price)

        raw = self.client.place_limit_order(symbol, side, quantity, price)
        return self._build_response(raw)

    def get_open_orders(self, symbol: Optional[str] = None) -> list[dict]:
        """Fetch open orders, optionally filtered by symbol."""
        return self.client.get_open_orders(symbol)

    def get_order_status(self, symbol: str, order_id: int) -> dict:
        """Fetch the current status of an order."""
        return self.client.get_order_status(symbol, order_id)
