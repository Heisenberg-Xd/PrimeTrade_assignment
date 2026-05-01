# Binance Futures Testnet Trading Bot

## Overview

This project is a Python-based trading bot designed for the Binance Futures Testnet. It provides a robust command-line interface (CLI) for executing market and limit orders, alongside an automated trading engine that utilizes an Exponential Moving Average (EMA) crossover strategy. The bot features structured logging, comprehensive error handling, automatic stop-loss and take-profit mechanisms, and a lightweight web dashboard for real-time monitoring.

## Features

* Market and Limit orders
* BUY/SELL support
* CLI interface
* Logging and error handling
* Testnet integration
* Auto trading (EMA crossover)
* Stop-loss and take-profit
* Lightweight web dashboard

## Project Structure

```
trading_bot/
  bot/
    client.py
    config.py
    orders.py
    state.py
    validators.py
    automation/
      trader.py
    execution/
      risk.py
    strategy/
      ema.py
  logs/
  templates/
    index.html
  app.py
  cli.py
  requirements.txt
```

## Setup Instructions

### 1. Clone repository

```bash
git clone <repository-url>
cd trading_bot
```

### 2. Create virtual environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the root directory:

```env
BINANCE_API_KEY=your_key
BINANCE_SECRET_KEY=your_secret
TESTNET=true
```

## Running the Application

### CLI Commands

The primary interface for the bot is the CLI:

```bash
# Check current account balance
python cli.py balance

# Execute a MARKET order
python cli.py market --symbol BTCUSDT --side BUY --quantity 0.001

# Execute a LIMIT order
python cli.py limit --symbol BTCUSDT --side SELL --quantity 0.001 --price 70000

# List active open orders
python cli.py orders

# Start the automated trading loop
python cli.py auto
```

### Running the Web Dashboard

The web dashboard runs as a separate FastAPI process and provides real-time visibility into the automated trader's memory state.

```bash
python -m uvicorn app:app --reload
```

Open a browser and navigate to:

```text
http://127.0.0.1:8000
```

## Example Usage

**Market Order Execution:**
```bash
python cli.py market --symbol ETHUSDT --side BUY --quantity 0.05
```

**Limit Order Execution:**
```bash
python cli.py limit --symbol BTCUSDT --side SELL --quantity 0.002 --price 68500.00
```

## Logging

* Logs are stored in the `/logs` directory.
* Log files rotate automatically and are named using the current date format (`trading_bot_YYYY-MM-DD.log`).
* Logging captures detailed execution flows, including API request payloads, HTTP response codes, and runtime errors.

## Notes and Assumptions

* The codebase currently targets the Binance Futures Testnet.
* Valid Binance Futures Testnet API credentials must be supplied.
* Simulated execution on the testnet may differ in slippage and latency compared to the production environment.

## Future Improvements

* Integrate backtesting capabilities against historical data.
* Expand the strategy engine to support multiple concurrent indicators.
* Enhance the dashboard with historical trade charts.
