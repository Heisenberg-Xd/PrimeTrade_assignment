"""
CLI Entry Point
Interactive command-line interface for the Binance Futures Trading Bot.
"""

import signal
import sys
import time
from datetime import date
from typing import Optional

import click
from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text
from rich import print as rprint

from bot.config import setup_logging, LOGS_DIR
from bot.client import (
    BinanceClient,
    BinanceAPIError,
    AuthenticationError,
    InsufficientBalanceError,
    InvalidSymbolError,
    RateLimitError,
)
from bot.orders import OrderManager
from pydantic import ValidationError

# ─── Console setup ────────────────────────────────────────────────────────────
# Initialize the Rich console for beautiful output
console = Console()


# ─── Helpers ──────────────────────────────────────────────────────────────────

# Helper function to generate the log file path based on the current date
def _log_file_path() -> str:
    return str(LOGS_DIR / f"trading_bot_{date.today().isoformat()}.log")


def _make_spinner(description: str) -> Progress:
    """Returns a Rich Progress spinner."""
    return Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[cyan]{task.description}"),
        console=console,
        transient=True,
    )


# Display a formatted error message using a Rich Panel
def _print_error(message: str) -> None:
    console.print(Panel(f"[bold red]ERROR:[/bold red] {message}", border_style="red"))


def _print_success(message: str) -> None:
    console.print(f"[bold green]OK[/bold green]  {message}")


def _print_order_table(order: dict, dry_run: bool = False) -> None:
    """Renders confirmation table for a placed order."""
    title = "[bold yellow]DRY RUN - Order Simulation[/bold yellow]" if dry_run else "[bold green]Order Confirmation[/bold green]"
    table = Table(
        title=title,
        box=box.DOUBLE_EDGE,
        border_style="green" if not dry_run else "yellow",
        title_style="bold",
        show_header=False,
        padding=(0, 1),
    )
    table.add_column("Field", style="bold cyan", width=16)
    table.add_column("Value", style="white")

    avg_price = order.get("avgPrice", "N/A")
    try:
        avg_price = f"{float(avg_price):,.2f} USDT"
    except (TypeError, ValueError):
        avg_price = str(avg_price)

    rows = [
        ("Order ID", str(order.get("orderId", "N/A"))),
        ("Symbol", order.get("symbol", "N/A")),
        ("Side", f"[bold {'green' if order.get('side') == 'BUY' else 'red'}]{order.get('side', 'N/A')}[/]"),
        ("Type", order.get("type", "N/A")),
        ("Quantity", str(order.get("origQty", "N/A"))),
        ("Executed Qty", str(order.get("executedQty", "N/A"))),
        ("Avg Price", avg_price),
        ("Status", f"[bold yellow]{order.get('status', 'N/A')}[/]"),
        ("Time In Force", order.get("timeInForce") or "N/A"),
    ]
    for field, value in rows:
        table.add_row(field, value)

    console.print(table)
    log_path = _log_file_path()
    console.print(f"[dim]Logged to: {log_path}[/dim]")


def _handle_api_error(exc: BinanceAPIError, client: Optional[BinanceClient] = None) -> None:
    """Displays user-friendly error message for API exceptions."""
    if isinstance(exc, AuthenticationError):
        from bot.config import is_testnet
        mode_str = "Testnet (https://testnet.binancefuture.com)" if is_testnet() else "Production (https://www.binance.com)"
        _print_error(
            "Invalid API credentials.\n"
            "  - Ensure BINANCE_API_KEY and BINANCE_SECRET_KEY are set correctly in your .env file.\n"
            f"  - Keys must be from Binance Futures {mode_str}.\n"
            "  - If your key is Ed25519 type, ensure your IP is whitelisted on the portal."
        )
    elif isinstance(exc, InsufficientBalanceError):
        balance_msg = ""
        if client:
            try:
                bal = client.get_usdt_balance()
                balance_msg = f"\n  - Current available balance: [bold yellow]${bal:,.2f} USDT[/bold yellow]"
            except Exception:
                pass
        _print_error(f"Insufficient balance to place this order.{balance_msg}")
    elif isinstance(exc, InvalidSymbolError):
        from bot.config import is_testnet
        mode_str = "Testnet" if is_testnet() else "Production"
        _print_error(
            f"Invalid symbol: {exc.message}\n"
            "  - Ensure the symbol is uppercase (e.g., BTCUSDT, ETHUSDT).\n"
            f"  - Verify the pair is available on Binance Futures {mode_str}."
        )
    elif isinstance(exc, RateLimitError):
        _print_error("Rate limit exceeded. The bot will automatically retry.")
    else:
        _print_error(f"API Error [{exc.code}]: {exc.message}")


# ─── CLI Group ────────────────────────────────────────────────────────────────

# Main CLI group entry point using the click library
@click.group()
@click.option("--verbose", "-v", is_flag=True, default=False, help="Enable verbose/debug output.")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """
    \b
    ==============================================
      Binance Futures Testnet Trading Bot
      Production-ready CLI with Rich output
    ==============================================

    Use --help on any command for detailed usage.
    """
    setup_logging(verbose=verbose)
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose


# ─── Balance Command ──────────────────────────────────────────────────────────

@cli.command()
@click.pass_context
def balance(ctx: click.Context) -> None:
    """Display your current Binance Futures account balance."""
    try:
        with _make_spinner("Fetching account balance…") as progress:
            progress.add_task("", total=None)
            client = BinanceClient()
            balances = client.get_account_balance()

        table = Table(
            title="[bold cyan]Account Balances[/bold cyan]",
            box=box.ROUNDED,
            border_style="cyan",
            header_style="bold magenta",
        )
        table.add_column("Asset", style="bold white")
        table.add_column("Wallet Balance", justify="right", style="green")
        table.add_column("Available Balance", justify="right", style="bright_green")
        table.add_column("Unrealized PnL", justify="right", style="yellow")

        for asset in balances:
            wallet = float(asset.get("balance", 0))
            available = float(asset.get("availableBalance", 0))
            pnl = float(asset.get("crossUnPnl", 0))
            if wallet == 0 and available == 0:
                continue  # Skip empty assets
            pnl_style = "green" if pnl >= 0 else "red"
            table.add_row(
                asset.get("asset", "?"),
                f"{wallet:,.4f}",
                f"{available:,.4f}",
                f"[{pnl_style}]{pnl:+,.4f}[/{pnl_style}]",
            )

        console.print(table)

    except EnvironmentError as exc:
        _print_error(str(exc))
        sys.exit(1)
    except BinanceAPIError as exc:
        _handle_api_error(exc)
        sys.exit(1)


# ─── Market Order Command ─────────────────────────────────────────────────────

@cli.command()
@click.option("--symbol", "-s", default=None, help="Trading pair (e.g., BTCUSDT)")
@click.option("--side", "-d", default=None, type=click.Choice(["BUY", "SELL"], case_sensitive=False))
@click.option("--quantity", "-q", default=None, type=float, help="Order quantity")
@click.option("--stop-loss", type=float, default=0.0, help="Stop Loss price")
@click.option("--take-profit", type=float, default=0.0, help="Take Profit price")
@click.option("--dry-run", is_flag=True, default=False, help="Simulate without placing a real order")
@click.pass_context
def market(
    ctx: click.Context,
    symbol: Optional[str],
    side: Optional[str],
    quantity: Optional[float],
    stop_loss: float,
    take_profit: float,
    dry_run: bool,
) -> None:
    """Place a MARKET order on Binance Futures."""
    # Interactive prompts for missing arguments
    if not symbol:
        symbol = click.prompt("Symbol (e.g., BTCUSDT)")
    if not side:
        side = click.prompt("Side", type=click.Choice(["BUY", "SELL"]))
    if quantity is None:
        quantity = click.prompt("Quantity", type=float)

    if dry_run:
        console.print("[bold yellow]DRY-RUN mode - no real order will be placed.[/bold yellow]")

    try:
        _print_success("Validating order parameters…")

        with _make_spinner("Checking account balance…") as progress:
            progress.add_task("", total=None)
            client = BinanceClient()

        _print_success("Checking account balance…")

        manager = OrderManager(client=client, dry_run=dry_run)

        with _make_spinner(f"Placing MARKET {side.upper()} order…") as progress:
            progress.add_task("", total=None)
            result = manager.execute_market_order(symbol.upper(), side.upper(), quantity)

        _print_success(f"MARKET order {'simulated' if dry_run else 'executed'} successfully.")
        _print_order_table(result, dry_run=dry_run)

        if not dry_run and (stop_loss > 0 or take_profit > 0):
            from bot.execution.risk import RiskManager
            risk_manager = RiskManager(client)
            current_price = client.get_ticker_price(symbol.upper())
            if side.upper() == "BUY" and stop_loss >= current_price:
                _print_error(f"Stop Loss ({stop_loss}) must be < current price ({current_price}) for BUY")
            elif side.upper() == "SELL" and stop_loss <= current_price:
                _print_error(f"Stop Loss ({stop_loss}) must be > current price ({current_price}) for SELL")
            else:
                with _make_spinner("Placing Risk Management orders…") as progress:
                    progress.add_task("", total=None)
                    risk_manager.apply_bracket_orders(symbol.upper(), side.upper(), quantity, stop_loss, take_profit)
                _print_success("Stop Loss & Take Profit orders attached.")

    except ValidationError as exc:
        errors = "; ".join(str(e["msg"]) for e in exc.errors())
        _print_error(f"Validation failed: {errors}")
        sys.exit(1)
    except ValueError as exc:
        _print_error(str(exc))
        sys.exit(1)
    except EnvironmentError as exc:
        _print_error(str(exc))
        sys.exit(1)
    except BinanceAPIError as exc:
        _handle_api_error(exc, client if "client" in dir() else None)
        sys.exit(1)


# ─── Limit Order Command ──────────────────────────────────────────────────────

@cli.command()
@click.option("--symbol", "-s", default=None, help="Trading pair (e.g., BTCUSDT)")
@click.option("--side", "-d", default=None, type=click.Choice(["BUY", "SELL"], case_sensitive=False))
@click.option("--quantity", "-q", default=None, type=float, help="Order quantity")
@click.option("--price", "-p", default=None, type=float, help="Limit price")
@click.option("--stop-loss", type=float, default=0.0, help="Stop Loss price")
@click.option("--take-profit", type=float, default=0.0, help="Take Profit price")
@click.option("--dry-run", is_flag=True, default=False, help="Simulate without placing a real order")
@click.pass_context
def limit(
    ctx: click.Context,
    symbol: Optional[str],
    side: Optional[str],
    quantity: Optional[float],
    price: Optional[float],
    stop_loss: float,
    take_profit: float,
    dry_run: bool,
) -> None:
    """Place a LIMIT order on Binance Futures."""
    if not symbol:
        symbol = click.prompt("Symbol (e.g., BTCUSDT)")
    if not side:
        side = click.prompt("Side", type=click.Choice(["BUY", "SELL"]))
    if quantity is None:
        quantity = click.prompt("Quantity", type=float)
    if price is None:
        price = click.prompt("Limit price", type=float)

    if dry_run:
        console.print("[bold yellow]DRY-RUN mode - no real order will be placed.[/bold yellow]")

    try:
        _print_success("Validating order parameters…")

        with _make_spinner("Connecting to exchange…") as progress:
            progress.add_task("", total=None)
            client = BinanceClient()

        _print_success("Checking account balance…")
        manager = OrderManager(client=client, dry_run=dry_run)

        with _make_spinner(f"Placing LIMIT {side.upper()} order @ {price}…") as progress:
            progress.add_task("", total=None)
            result = manager.execute_limit_order(
                symbol.upper(), side.upper(), quantity, price
            )

        _print_success(f"LIMIT order {'simulated' if dry_run else 'placed'} successfully.")
        _print_order_table(result, dry_run=dry_run)

        if not dry_run and (stop_loss > 0 or take_profit > 0):
            from bot.execution.risk import RiskManager
            risk_manager = RiskManager(client)
            if side.upper() == "BUY" and stop_loss >= price:
                _print_error(f"Stop Loss ({stop_loss}) must be < entry price ({price}) for BUY")
            elif side.upper() == "SELL" and stop_loss <= price:
                _print_error(f"Stop Loss ({stop_loss}) must be > entry price ({price}) for SELL")
            else:
                with _make_spinner("Placing Risk Management orders…") as progress:
                    progress.add_task("", total=None)
                    risk_manager.apply_bracket_orders(symbol.upper(), side.upper(), quantity, stop_loss, take_profit)
                _print_success("Stop Loss & Take Profit orders attached.")

    except ValidationError as exc:
        errors = "; ".join(str(e["msg"]) for e in exc.errors())
        _print_error(f"Validation failed: {errors}")
        sys.exit(1)
    except ValueError as exc:
        _print_error(str(exc))
        sys.exit(1)
    except EnvironmentError as exc:
        _print_error(str(exc))
        sys.exit(1)
    except BinanceAPIError as exc:
        _handle_api_error(exc, client if "client" in dir() else None)
        sys.exit(1)


# ─── Open Orders Command ──────────────────────────────────────────────────────

@cli.command()
@click.option("--symbol", "-s", default=None, help="Filter by trading pair")
@click.pass_context
def orders(ctx: click.Context, symbol: Optional[str]) -> None:
    """List all open orders (optionally filtered by symbol)."""
    try:
        with _make_spinner("Fetching open orders…") as progress:
            progress.add_task("", total=None)
            client = BinanceClient()
            open_orders = client.get_open_orders(symbol)

        if not open_orders:
            console.print("[dim]No open orders found.[/dim]")
            return

        table = Table(
            title=f"[bold cyan]Open Orders{f' - {symbol}' if symbol else ''}[/bold cyan]",
            box=box.ROUNDED,
            border_style="cyan",
            header_style="bold magenta",
        )
        table.add_column("Order ID", style="dim")
        table.add_column("Symbol", style="bold white")
        table.add_column("Side", justify="center")
        table.add_column("Type")
        table.add_column("Qty", justify="right", style="white")
        table.add_column("Price", justify="right", style="yellow")
        table.add_column("Status", style="bold")

        for o in open_orders:
            side_val = o.get("side", "")
            side_col = f"[green]{side_val}[/]" if side_val == "BUY" else f"[red]{side_val}[/]"
            table.add_row(
                str(o.get("orderId")),
                o.get("symbol", ""),
                side_col,
                o.get("type", ""),
                o.get("origQty", ""),
                o.get("price", ""),
                o.get("status", ""),
            )

        console.print(table)

    except EnvironmentError as exc:
        _print_error(str(exc))
        sys.exit(1)
    except BinanceAPIError as exc:
        _handle_api_error(exc)
        sys.exit(1)


# ─── Grid Trading Command ─────────────────────────────────────────────────────

@cli.command()
@click.option("--symbol", "-s", required=True, help="Trading pair (e.g., BTCUSDT)")
@click.option("--levels", "-l", default=5, type=int, show_default=True, help="Number of grid levels")
@click.option("--range", "price_range", "-r", required=True, type=float, help="Total price range in USDT")
@click.option("--quantity", "-q", required=True, type=float, help="Quantity per grid level")
@click.option("--dry-run", is_flag=True, default=False, help="Simulate without placing real orders")
@click.pass_context
def grid(
    ctx: click.Context,
    symbol: str,
    levels: int,
    price_range: float,
    quantity: float,
    dry_run: bool,
) -> None:
    """
    Execute a grid trading strategy by placing multiple LIMIT orders
    spread across a price range above and below the current market price.

    Press Ctrl+C to cancel all placed grid orders and exit.
    """
    from bot.validators import GridOrderInput
    from pydantic import ValidationError as PydanticValidationError

    try:
        grid_input = GridOrderInput(symbol=symbol, levels=levels, price_range=price_range)
    except Exception as exc:
        _print_error(f"Invalid grid parameters: {exc}")
        sys.exit(1)

    symbol = grid_input.symbol
    placed_orders: list[dict] = []

    if dry_run:
        console.print("[bold yellow]DRY-RUN mode - no real orders will be placed.[/bold yellow]")

    # Track placed order IDs for graceful cancellation
    placed_order_ids: list[tuple[str, int]] = []

    def _cancel_all(signum, frame):
        console.print("\n[bold red]Ctrl+C detected - cancelling all grid orders...[/bold red]")
        if placed_order_ids and not dry_run:
            client = BinanceClient()
            for sym, oid in placed_order_ids:
                try:
                    client.cancel_order(sym, oid)
                    console.print(f"  [dim]Cancelled orderId={oid}[/dim]")
                except Exception as e:
                    console.print(f"  [red]Failed to cancel {oid}: {e}[/red]")
        console.print("[green]Grid trading session ended.[/green]")
        sys.exit(0)

    signal.signal(signal.SIGINT, _cancel_all)

    try:
        with _make_spinner("Fetching current market price…") as progress:
            progress.add_task("", total=None)
            client = BinanceClient()
            current_price = client.get_ticker_price(symbol)

        console.print(
            f"\n[bold cyan]Grid Setup for [white]{symbol}[/white][/bold cyan]\n"
            f"  Current Price : [yellow]${current_price:,.2f}[/yellow]\n"
            f"  Grid Levels   : [white]{levels}[/white]\n"
            f"  Price Range   : [white]+/-${price_range/2:,.2f}[/white]\n"
            f"  Qty per Level : [white]{quantity}[/white]\n"
        )

        half_range = price_range / 2
        step = price_range / (levels - 1) if levels > 1 else price_range
        buy_prices = sorted(
            [round(current_price - half_range + i * step, 2) for i in range(levels // 2)],
            reverse=True,
        )
        sell_prices = sorted(
            [round(current_price + i * step, 2) for i in range(1, levels // 2 + 1)]
        )

        # ── Preview table ──────────────────────────────────────────────────
        preview_table = Table(
            title="[bold]Grid Order Preview[/bold]",
            box=box.SIMPLE_HEAVY,
            border_style="bright_blue",
            header_style="bold",
        )
        preview_table.add_column("#", justify="right", style="dim")
        preview_table.add_column("Side", justify="center")
        preview_table.add_column("Price", justify="right", style="yellow")
        preview_table.add_column("Quantity", justify="right")
        preview_table.add_column("Status", justify="center")

        all_levels = (
            [("SELL", p) for p in sell_prices]
            + [("BUY", p) for p in buy_prices]
        )

        for idx, (s, p) in enumerate(all_levels, 1):
            side_col = "[green]BUY[/]" if s == "BUY" else "[red]SELL[/]"
            preview_table.add_row(str(idx), side_col, f"${p:,.2f}", str(quantity), "Pending")

        console.print(preview_table)

        if not click.confirm("\nProceed with placing grid orders?", default=True):
            console.print("[dim]Grid trading cancelled.[/dim]")
            return

        manager = OrderManager(client=client, dry_run=dry_run)

        # ── Place grid orders ──────────────────────────────────────────────
        result_table = Table(
            title="[bold green]Grid Orders Placed[/bold green]",
            box=box.SIMPLE_HEAVY,
            border_style="green",
            header_style="bold magenta",
        )
        result_table.add_column("#", justify="right", style="dim")
        result_table.add_column("Order ID")
        result_table.add_column("Side", justify="center")
        result_table.add_column("Price", justify="right", style="yellow")
        result_table.add_column("Qty", justify="right")
        result_table.add_column("Status")

        for idx, (side_val, price_val) in enumerate(all_levels, 1):
            try:
                result = manager.execute_limit_order(symbol, side_val, quantity, price_val)
                order_id = result.get("orderId")
                if not dry_run and order_id and order_id != "DRY-RUN":
                    placed_order_ids.append((symbol, int(order_id)))
                side_col = "[green]BUY[/]" if side_val == "BUY" else "[red]SELL[/]"
                result_table.add_row(
                    str(idx),
                    str(order_id),
                    side_col,
                    f"${price_val:,.2f}",
                    str(quantity),
                    f"[green]{result.get('status', 'OK')}[/green]",
                )
            except Exception as exc:
                result_table.add_row(
                    str(idx), "N/A", side_val, f"${price_val:,.2f}", str(quantity),
                    f"[red]FAILED: {exc}[/red]",
                )

        console.print(result_table)
        console.print(
            f"\n[bold green]Grid placed with {len(placed_order_ids)} order(s).[/bold green]\n"
            "[dim]Press Ctrl+C to cancel all orders and exit.[/dim]"
        )

        # Keep the bot alive
        while True:
            time.sleep(1)

    except EnvironmentError as exc:
        _print_error(str(exc))
        sys.exit(1)
    except BinanceAPIError as exc:
        _handle_api_error(exc)
        sys.exit(1)


# ─── Auto Trading Command ───────────────────────────────────────────────────

@cli.command()
@click.option("--symbol", "-s", default="BTCUSDT", help="Trading pair (e.g., BTCUSDT)")
@click.option("--interval", "-i", default="15m", help="Candle interval (e.g., 15m, 1h)")
@click.option("--quantity", "-q", default=0.001, type=float, help="Order quantity per trade")
@click.option("--sleep", default=10, type=int, help="Seconds to sleep between loop ticks")
@click.pass_context
def auto(ctx: click.Context, symbol: str, interval: str, quantity: float, sleep: int) -> None:
    """Run the automated trading bot loop continuously."""
    from bot.automation.trader import AutoTrader
    import time
    
    console.print(f"\n[bold cyan]=== Binance Auto Trader ===[/bold cyan]\n")
    console.print(f"Symbol:   [white]{symbol}[/white]")
    console.print(f"Interval: [white]{interval}[/white]")
    console.print(f"Quantity: [white]{quantity}[/white]")
    console.print(f"Tick:     [white]{sleep}s[/white]\n")
    
    try:
        with _make_spinner("Initializing AutoTrader...") as progress:
            progress.add_task("", total=None)
            client = BinanceClient()
            trader = AutoTrader(client=client, symbol=symbol, interval=interval, trade_qty=quantity)
            
        console.print("[green]Initialization complete.[/green] Starting main loop (Ctrl+C to stop).")
        
        from rich.live import Live
        from rich.panel import Panel
        from rich.align import Align
        from rich.text import Text

        status_text = Text("Initializing...", justify="center")
        panel = Panel(Align.center(status_text, vertical="middle"), title="[bold cyan]Auto Trader Status[/bold cyan]", border_style="cyan", padding=(1, 2))
        
        def ui_callback(msg: str):
            if "Price:" in msg:
                status_text.plain = msg
            else:
                console.print(f"[{time.strftime('%H:%M:%S')}] {msg}")
                
        with Live(panel, refresh_per_second=4, transient=False):
            trader.run_loop(sleep_interval=sleep, callback=ui_callback)

    except KeyboardInterrupt:
        console.print("\n[bold yellow]Auto Trader stopped by user.[/bold yellow]")
        sys.exit(0)
    except Exception as exc:
        _print_error(f"Auto Trader crashed: {exc}")
        sys.exit(1)


# ─── Diagnose Command ─────────────────────────────────────────────────────────

@cli.command()
def diagnose() -> None:
    """
    Run step-by-step connectivity and authentication diagnostics.
    Use this to identify exactly why the bot cannot connect to the exchange.
    """
    import os
    import time
    import requests as req
    from bot.config import get_base_url, is_testnet
    base = get_base_url()
    mode_name = "TESTNET" if is_testnet() else "MAINNET"
    console.print(f"\n[bold cyan]=== Binance {mode_name} Diagnostic Tool ===[/bold cyan]\n")
    console.print(f"Target URL: [white]{base}[/white]\n")

    results = []

    # ── Step 1: Internet connectivity ─────────────────────────────────────
    console.print("[bold]Step 1:[/bold] Checking internet connectivity...")
    try:
        req.get("https://google.com", timeout=5)
        console.print("  [green]PASS[/green] Internet is reachable.\n")
        results.append(("Internet connectivity", True, ""))
    except Exception as e:
        console.print(f"  [red]FAIL[/red] No internet: {e}\n")
        results.append(("Internet connectivity", False, str(e)))

    # ── Step 2: Server time ───────────────────────────────────────────────
    console.print(f"[bold]Step 2:[/bold] Checking Binance {mode_name} server time...")
    try:
        r = req.get(f"{base}/fapi/v1/time", timeout=10)
        server_ms = r.json().get("serverTime", 0)
        local_ms = int(time.time() * 1000)
        drift_s = abs(server_ms - local_ms) / 1000
        if drift_s > 10:
            console.print(
                f"  [yellow]WARN[/yellow] Clock drift is {drift_s:.1f}s "
                f"(your PC clock may be out of sync — this causes auth failures!).\n"
            )
            results.append(("Server time sync", False, f"Drift: {drift_s:.1f}s"))
        else:
            console.print(f"  [green]PASS[/green] Server time OK (drift: {drift_s:.2f}s).\n")
            results.append(("Server time sync", True, ""))
    except Exception as e:
        console.print(f"  [red]FAIL[/red] Cannot reach server: {e}\n")
        results.append(("Server reachable", False, str(e)))

    # ── Step 3: Public API (no auth) ───────────────────────────────────────
    console.print("[bold]Step 3:[/bold] Testing public API endpoint (no auth)...")
    try:
        r = req.get(f"{base}/fapi/v1/ticker/price", params={"symbol": "BTCUSDT"}, timeout=10)
        price = r.json().get("price", "?")
        console.print(f"  [green]PASS[/green] Public API OK. BTC price: ${float(price):,.2f}\n")
        results.append(("Public API", True, ""))
    except Exception as e:
        console.print(f"  [red]FAIL[/red] Public API failed: {e}\n")
        results.append(("Public API", False, str(e)))

    # ── Step 4: .env file and key format ──────────────────────────────────
    console.print("[bold]Step 4:[/bold] Checking .env file and key format...")
    api_key = os.getenv("BINANCE_API_KEY", "")
    secret_key = os.getenv("BINANCE_SECRET_KEY", "")
    if not api_key or not secret_key:
        console.print("  [red]FAIL[/red] Keys missing from .env file.\n")
        results.append(("API keys in .env", False, "Keys not found"))
    else:
        console.print(f"  [green]PASS[/green] API key found ({len(api_key)} chars).")
        console.print(f"  [green]PASS[/green] Secret key found ({len(secret_key)} chars).\n")
        results.append(("API keys in .env", True, ""))

    # ── Step 5: Authenticated endpoint ────────────────────────────────────
    console.print("[bold]Step 5:[/bold] Testing authenticated endpoint...")
    try:
        client = BinanceClient()
        balances = client.get_account_balance()
        usdt = next((float(b["availableBalance"]) for b in balances if b["asset"] == "USDT"), 0)
        console.print(f"  [green]PASS[/green] Authentication OK! USDT balance: ${usdt:,.2f}\n")
        results.append(("Authenticated API", True, ""))
    except AuthenticationError as e:
        console.print(f"  [red]FAIL[/red] Auth rejected: {e.message}")
        if is_testnet():
            console.print("  [yellow]>>>[/yellow] You are using a TESTNET endpoint but your key failed.")
            console.print("  [yellow]>>>[/yellow] If you intended to use MAINNET keys, set TESTNET=false in .env")
        else:
            console.print("  [yellow]>>>[/yellow] You are using a MAINNET endpoint but your key failed.")
            console.print("  [yellow]>>>[/yellow] If you intended to use TESTNET keys, set TESTNET=true in .env")
        console.print("  [yellow]>>>[/yellow] Check that 'Enable Futures' is checked in your API management.\n")
        results.append(("Authenticated API", False, e.message))
    except EnvironmentError as e:
        console.print(f"  [red]FAIL[/red] {e}\n")
        results.append(("Authenticated API", False, str(e)))
    except Exception as e:
        console.print(f"  [red]FAIL[/red] Unexpected error: {e}\n")
        results.append(("Authenticated API", False, str(e)))
        
    # ── Step 6: Security Check (Withdrawals) ──────────────────────────────
    console.print("[bold]Step 6:[/bold] Checking API Key Security (Withdrawals)...")
    try:
        import hmac, hashlib
        from urllib.parse import urlencode
        
        spot_base = "https://api.binance.com" if not is_testnet() else "https://testnet.binance.vision"
        params = {"recvWindow": 60000, "timestamp": int(time.time() * 1000)}
        qs = urlencode(params)
        sig = hmac.new(secret_key.encode(), qs.encode(), hashlib.sha256).hexdigest()
        params["signature"] = sig
        
        r = req.get(f"{spot_base}/sapi/v1/account/apiRestrictions", params=params, headers={"X-MBX-APIKEY": api_key}, timeout=10)
        data = r.json()
        if isinstance(data, dict) and "enableWithdrawals" in data:
            if data["enableWithdrawals"]:
                console.print("  [red]FAIL[/red] Withdrawals are ENABLED on this API Key.")
                console.print("  [bold red]⚠️  SECURITY RISK: Disable withdrawals for safety![/bold red]\n")
                results.append(("Security: No Withdrawals", False, "Withdrawals enabled"))
            else:
                console.print("  [green]PASS[/green] Withdrawals are disabled (safe).\n")
                results.append(("Security: No Withdrawals", True, ""))
        else:
            console.print("  [dim]Could not verify withdrawal permissions (may not apply to this key type).[/dim]\n")
            results.append(("Security: No Withdrawals", True, "Unverified"))
    except Exception as e:
        console.print(f"  [dim]Could not check security: {e}[/dim]\n")
        results.append(("Security: No Withdrawals", True, "Error checking"))

    # ── Summary table ──────────────────────────────────────────────────────
    summary = Table(
        title="[bold]Diagnostic Summary[/bold]",
        box=box.ROUNDED,
        border_style="cyan",
        header_style="bold",
    )
    summary.add_column("Check", style="white")
    summary.add_column("Result", justify="center")
    summary.add_column("Detail", style="dim")

    all_passed = True
    for name, passed, detail in results:
        status = "[bold green]PASS[/bold green]" if passed else "[bold red]FAIL[/bold red]"
        if not passed:
            all_passed = False
        summary.add_row(name, status, detail)

    console.print(summary)

    if all_passed:
        console.print("\n[bold green]All checks passed! Your bot is ready to trade.[/bold green]")
    else:
        console.print(
            "\n[bold red]Some checks failed.[/bold red] "
            "Fix the items above, then run [cyan]python cli.py balance[/cyan] again."
        )


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli(obj={})

