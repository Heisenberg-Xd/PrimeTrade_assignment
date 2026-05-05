"""
Validators Module
==================
Pydantic-based validation models for all trading bot inputs.
Enforces exchange rules such as step size, tick size, and minimum notional value.
"""

import math
import re
from decimal import Decimal, ROUND_DOWN
from typing import Any, Optional

from pydantic import BaseModel, field_validator, model_validator

# ─── Constants ────────────────────────────────────────────────────────────────
VALID_SIDES = {"BUY", "SELL"}
VALID_ORDER_TYPES = {"MARKET", "LIMIT"}
SYMBOL_PATTERN = re.compile(r"^[A-Z]{2,20}$")
MIN_NOTIONAL_USDT = 5.0  # Binance Futures minimum notional


# ─── Helpers ──────────────────────────────────────────────────────────────────

# ─── Rounding and step helpers ────────────────────────────────────────────────
# These functions ensure values comply with exchange precision requirements.
def _round_step(value: float, step: float) -> float:
    """Round *value* down to the nearest multiple of *step*."""
    if step == 0:
        return value
    precision = int(round(-math.log10(step)))
    factor = Decimal(10) ** precision
    return float(
        (Decimal(str(value)) / Decimal(str(step))).quantize(Decimal("1"), rounding=ROUND_DOWN)
        * Decimal(str(step))
    )


def _complies_with_step(value: float, step: float) -> bool:
    """Return True if *value* is an exact multiple of *step* (within float tolerance)."""
    if step == 0:
        return True
    remainder = value % step
    return remainder < 1e-9 or (step - remainder) < 1e-9


# ─── Base Order Model ─────────────────────────────────────────────────────────

class OrderBase(BaseModel):
    """Shared fields and validators for all order types."""

    symbol: str
    side: str
    quantity: float

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        v = v.strip().upper()
        if not SYMBOL_PATTERN.match(v):
            raise ValueError(
                f"Invalid symbol '{v}'. Symbol must be uppercase letters only (e.g., BTCUSDT)."
            )
        return v

    @field_validator("side")
    @classmethod
    def validate_side(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in VALID_SIDES:
            raise ValueError(f"Side must be one of {VALID_SIDES}, got '{v}'.")
        return v

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"Quantity must be a positive number, got {v}.")
        return v


# ─── Market Order ─────────────────────────────────────────────────────────────

class MarketOrderInput(OrderBase):
    """Validated input for a MARKET order."""
    order_type: str = "MARKET"


# ─── Limit Order ──────────────────────────────────────────────────────────────

class LimitOrderInput(OrderBase):
    """Validated input for a LIMIT order."""

    order_type: str = "LIMIT"
    price: float

    @field_validator("price")
    @classmethod
    def validate_price(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"Price must be a positive number, got {v}.")
        return v


# ─── Exchange-Rule Validator ──────────────────────────────────────────────────

class ExchangeRuleValidator:
    """
    Validates order parameters against live exchange rules fetched from
    ``get_symbol_info()``.

    Usage::

        validator = ExchangeRuleValidator(symbol_info)
        validator.validate_quantity(0.001)
        validator.validate_price(43000.0)
        validator.validate_notional(0.001, 43000.0)
    """

    def __init__(self, symbol_info: dict[str, Any]) -> None:
        self.symbol_info = symbol_info
        self._parse_filters()

    # ── Internal helpers ───────────────────────────────────────────────────

    def _parse_filters(self) -> None:
        filters: list[dict] = self.symbol_info.get("filters", [])
        self.min_qty: float = 0.0
        self.max_qty: float = float("inf")
        self.step_size: float = 0.0
        self.tick_size: float = 0.0
        self.min_notional: float = MIN_NOTIONAL_USDT

        for f in filters:
            ft = f.get("filterType", "")
            if ft == "LOT_SIZE":
                self.min_qty = float(f.get("minQty", 0))
                self.max_qty = float(f.get("maxQty", float("inf")))
                self.step_size = float(f.get("stepSize", 0))
            elif ft == "PRICE_FILTER":
                self.tick_size = float(f.get("tickSize", 0))
            elif ft in ("MIN_NOTIONAL", "NOTIONAL"):
                self.min_notional = float(f.get("notional", f.get("minNotional", MIN_NOTIONAL_USDT)))

    # ── Public validators ──────────────────────────────────────────────────

    def validate_quantity(self, quantity: float) -> float:
        """
        Validate and round quantity to the nearest valid step size.

        Raises:
            ValueError: If quantity is outside [min_qty, max_qty].
        """
        if self.step_size and not _complies_with_step(quantity, self.step_size):
            rounded = _round_step(quantity, self.step_size)
            raise ValueError(
                f"Quantity {quantity} does not comply with step size {self.step_size}. "
                f"Try {rounded}."
            )
        if self.min_qty and quantity < self.min_qty:
            raise ValueError(
                f"Quantity {quantity} is below the minimum allowed ({self.min_qty})."
            )
        if self.max_qty and quantity > self.max_qty:
            raise ValueError(
                f"Quantity {quantity} exceeds the maximum allowed ({self.max_qty})."
            )
        return quantity

    def validate_price(self, price: float) -> float:
        """
        Validate price against tick size.

        Raises:
            ValueError: If price does not comply with tick size.
        """
        if self.tick_size and not _complies_with_step(price, self.tick_size):
            raise ValueError(
                f"Price {price} does not comply with tick size {self.tick_size}."
            )
        return price

    def validate_notional(self, quantity: float, price: float) -> None:
        """
        Validate that the order meets the minimum notional value requirement.

        Args:
            quantity: Order quantity in base asset.
            price:    Order price in quote asset.

        Raises:
            ValueError: If notional value is below minimum.
        """
        notional = quantity * price
        if notional < self.min_notional:
            raise ValueError(
                f"Order notional value ${notional:.2f} is below the minimum "
                f"required ${self.min_notional:.2f}."
            )

    def round_quantity(self, quantity: float) -> float:
        """Return quantity rounded down to the nearest valid step size."""
        if self.step_size:
            return _round_step(quantity, self.step_size)
        return quantity

    def round_price(self, price: float) -> float:
        """Return price rounded down to the nearest valid tick size."""
        if self.tick_size:
            return _round_step(price, self.tick_size)
        return price


# ─── Grid Trading Validator ───────────────────────────────────────────────────

class GridOrderInput(BaseModel):
    """Validated input for grid trading commands."""

    symbol: str
    levels: int
    price_range: float

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        v = v.strip().upper()
        if not SYMBOL_PATTERN.match(v):
            raise ValueError(f"Invalid symbol '{v}'.")
        return v

    @field_validator("levels")
    @classmethod
    def validate_levels(cls, v: int) -> int:
        if v < 2:
            raise ValueError("Grid levels must be at least 2.")
        if v > 50:
            raise ValueError("Grid levels cannot exceed 50.")
        return v

    @field_validator("price_range")
    @classmethod
    def validate_range(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Price range must be a positive number.")
        return v
