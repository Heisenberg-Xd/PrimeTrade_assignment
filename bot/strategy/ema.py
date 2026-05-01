import pandas as pd
import numpy as np

class EMAStrategy:
    """
    Basic EMA Crossover Strategy.
    BUY when fast EMA crosses above slow EMA.
    SELL when fast EMA crosses below slow EMA.
    """
    def __init__(self, fast_period: int = 9, slow_period: int = 21):
        self.fast_period = fast_period
        self.slow_period = slow_period

    def generate_signal(self, klines: list[dict]) -> str:
        """
        klines: List of Binance API klines.
        Format: [ [ Open time, Open, High, Low, Close, Volume, Close time, ... ], ... ]
        """
        if len(klines) < self.slow_period + 1:
            return "HOLD"
            
        # Extract closing prices
        try:
            closes = [float(k[4]) for k in klines]
        except (IndexError, ValueError):
            return "HOLD"
            
        df = pd.DataFrame(closes, columns=['close'])
        
        # Calculate EMAs
        df['ema_fast'] = df['close'].ewm(span=self.fast_period, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=self.slow_period, adjust=False).mean()
        
        # Get last two rows for crossover check
        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]
        
        # Crossover logic
        fast_now = last_row['ema_fast']
        slow_now = last_row['ema_slow']
        fast_prev = prev_row['ema_fast']
        slow_prev = prev_row['ema_slow']
        
        if fast_prev <= slow_prev and fast_now > slow_now:
            return "BUY"
        elif fast_prev >= slow_prev and fast_now < slow_now:
            return "SELL"
            
        return "HOLD"
