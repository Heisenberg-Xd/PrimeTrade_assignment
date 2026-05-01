from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import threading

from bot.state import state
from bot.automation.trader import AutoTrader
from bot.client import BinanceClient

app = FastAPI(title="Trading Bot Dashboard")
templates = Jinja2Templates(directory="templates")

# Initialize Client & Trader
client = BinanceClient()
trader = AutoTrader(client=client)

def run_trader():
    trader.run_loop()

@app.on_event("startup")
def start_trader():
    thread = threading.Thread(target=run_trader, daemon=True)
    thread.start()

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "state": state})

@app.get("/api/status")
async def api_status():
    return state
