import time
import logging
from typing import Optional
from bot.client import BinanceClient
from bot.strategy.ema import EMAStrategy
from bot.execution.risk import RiskManager
from bot.state import state

log = logging.getLogger("bot.automation.trader")

class AutoTrader:
    """Continuous trading engine evaluating strategy and executing trades."""
    def __init__(self, client: BinanceClient, symbol: str = "BTCUSDT", interval: str = "15m", trade_qty: float = 0.001):
        self.client = client
        self.symbol = symbol
        self.interval = interval
        self.trade_qty = trade_qty
        self.strategy = EMAStrategy()
        self.risk_manager = RiskManager(self.client)
        
        self.last_signal: Optional[str] = None

    def has_open_position(self) -> bool:
        """Check if there's an active position for the symbol."""
        try:
            positions = self.client.get_position_risk(self.symbol)
            for pos in positions:
                if pos.get("symbol") == self.symbol:
                    amount = float(pos.get("positionAmt", 0))
                    if abs(amount) > 0:
                        return True
            return False
        except Exception as e:
            log.error(f"Error checking position: {e}")
            # If we error out, assume we have a position to be safe and avoid overtrading
            return True

    def execute_trade(self, signal: str, current_price: float):
        """Executes market order and applies risk management."""
        side = signal
        
        try:
            # Retry up to 3 times to handle transient API failures
            for attempt in range(1, 4):
                try:
                    response = self.client.place_market_order(
                        symbol=self.symbol,
                        side=side,
                        quantity=self.trade_qty
                    )
                    break
                except Exception as e:
                    if attempt == 3:
                        raise e
                    log.warning(f"Order failed, retrying ({attempt}/3): {e}")
                    time.sleep(1)

            # Apply 1% SL and 2% TP to the executed order
            
            if side == "BUY":
                stop_loss = current_price * 0.99
                take_profit = current_price * 1.02
            else:
                stop_loss = current_price * 1.01
                take_profit = current_price * 0.98
                
            stop_loss = round(stop_loss, 1)
            take_profit = round(take_profit, 1)

            self.risk_manager.apply_bracket_orders(
                symbol=self.symbol,
                entry_side=side,
                quantity=self.trade_qty,
                stop_loss=stop_loss,
                take_profit=take_profit
            )
            
            self.last_signal = signal
            state["last_trade"] = signal
            log.info(f"Successfully executed {signal} and applied SL/TP.")
            
        except Exception as e:
            log.error(f"Failed to execute trade for signal {signal}: {e}")

    def run_loop(self, sleep_interval: int = 10, callback=None):
        """
        Run the infinite automated trading loop.
        `callback` is used to update the CLI UI.
        """
        log.info("Starting AutoTrader loop...")
        
        while True:
            try:
                current_price = self.client.get_ticker_price(self.symbol)
                klines = self.client.get_klines(self.symbol, interval=self.interval, limit=50)
                signal = self.strategy.generate_signal(klines)
                
                status_msg = f"Price: {current_price} | Signal: {signal} | Last: {self.last_signal}"
                if callback:
                    callback(status_msg)
                
                # Check position
                has_pos = self.has_open_position()
                
                # Update shared state
                state["price"] = current_price
                state["signal"] = signal
                state["last_signal"] = self.last_signal
                state["position"] = has_pos
                try:
                    state["balance"] = self.client.get_usdt_balance()
                except Exception as e:
                    log.error(f"Failed to fetch balance: {e}")

                if signal in ["BUY", "SELL"] and signal != self.last_signal:
                    if not has_pos:
                        if callback:
                            callback(f"Executing trade: {signal} @ {current_price}")
                        self.execute_trade(signal, current_price)
                    else:
                        if callback:
                            callback(f"Signal ignored: {self.symbol} already has open position")
                            
            except Exception as e:
                log.error(f"Error in trader loop: {e}")
                if callback:
                    callback(f"Error: {e}")
                    
            time.sleep(sleep_interval)
