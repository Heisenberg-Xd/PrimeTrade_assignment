from binance.client import Client

client = Client(BINANCE_API_KEY,BINANCE_SECRET_KEY)
print(client.futures_account_balance())