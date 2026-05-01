"""Test auth against all 3 Binance endpoints: Spot Testnet, Futures Testnet, Production Futures."""
import hmac
import hashlib
import time
import os
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("BINANCE_API_KEY", "")
secret  = os.getenv("BINANCE_SECRET_KEY", "")

print(f"API Key (first 8 chars): {api_key[:8]}...")
print(f"Secret  (first 8 chars): {secret[:8]}...")
print()

ENDPOINTS = {
    "Spot Testnet     (testnet.binance.vision)":    ("https://testnet.binance.vision",    "/api/v3/account",   "spot"),
    "Futures Testnet  (testnet.binancefuture.com)": ("https://testnet.binancefuture.com", "/fapi/v2/balance",  "futures"),
    "Production Spot  (api.binance.com)":           ("https://api.binance.com",           "/api/v3/account",   "spot"),
    "Production Futures (fapi.binance.com)":        ("https://fapi.binance.com",          "/fapi/v2/balance",  "futures"),
}

def sign(params, secret_key):
    qs = urlencode(params)
    sig = hmac.new(secret_key.encode(), qs.encode(), hashlib.sha256).hexdigest()
    params["signature"] = sig
    return params

headers = {"X-MBX-APIKEY": api_key}

for label, (base, path, kind) in ENDPOINTS.items():
    print(f"Testing: {label}")
    try:
        params = sign({"recvWindow": 60000, "timestamp": int(time.time() * 1000)}, secret)
        r = requests.get(f"{base}{path}", params=params, headers=headers, timeout=10)
        data = r.json()
        if isinstance(data, list) and kind == "futures":
            usdt = next((b for b in data if b.get("asset") == "USDT"), None)
            bal = usdt["availableBalance"] if usdt else "N/A"
            print(f"  [PASS] Auth OK! USDT available: {bal}")
        elif isinstance(data, dict) and "balances" in data:
            usdt = next((b for b in data["balances"] if b["asset"] == "USDT"), None)
            bal = usdt["free"] if usdt else "N/A"
            print(f"  [PASS] Auth OK! USDT free: {bal}")
        elif isinstance(data, dict) and data.get("code", 0) < 0:
            code = data["code"]
            msg  = data.get("msg", "")
            if code == -2015:
                print(f"  [FAIL] -2015: Key invalid OR Futures permission NOT enabled on this key")
            elif code == -1022:
                print(f"  [FAIL] -1022: Signature invalid (clock skew or wrong secret)")
            else:
                print(f"  [FAIL] {code}: {msg}")
        else:
            print(f"  [???]  Unexpected: {str(data)[:120]}")
    except Exception as e:
        print(f"  [ERR]  {e}")
    print()
