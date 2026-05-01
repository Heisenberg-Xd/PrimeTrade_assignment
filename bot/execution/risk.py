import logging
from bot.client import BinanceClient

log = logging.getLogger("bot.execution.risk")

class RiskManager:
    """
    Manages automated Stop Loss and Take Profit placement after order execution.
    """
    def __init__(self, client: BinanceClient):
        self.client = client

    def apply_bracket_orders(self, symbol: str, entry_side: str, quantity: float, stop_loss: float, take_profit: float):
        """
        Place STOP_MARKET and TAKE_PROFIT_MARKET orders for a filled entry order.
        """
        # The exit side is the opposite of the entry side
        exit_side = "SELL" if entry_side.upper() == "BUY" else "BUY"
        
        try:
            # Place Stop Loss
            if stop_loss > 0:
                self.client.place_conditional_order(
                    symbol=symbol,
                    side=exit_side,
                    order_type="STOP_MARKET",
                    quantity=quantity,
                    stop_price=stop_loss,
                    reduce_only=True
                )
                log.info(f"Stop Loss applied for {symbol} at {stop_loss}")
                
            # Place Take Profit
            if take_profit > 0:
                self.client.place_conditional_order(
                    symbol=symbol,
                    side=exit_side,
                    order_type="TAKE_PROFIT_MARKET",
                    quantity=quantity,
                    stop_price=take_profit,
                    reduce_only=True
                )
                log.info(f"Take Profit applied for {symbol} at {take_profit}")
                
        except Exception as e:
            log.error(f"Failed to apply bracket orders: {e}")
            raise
