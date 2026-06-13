# trading_engine.py
import os
from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException

load_dotenv()

class TradingEngine:
    def __init__(self, api_key=None, api_secret=None, testnet=True):
        self.testnet = testnet
        if api_key and api_secret:
            self.api_key = api_key
            self.api_secret = api_secret
        elif self.testnet:
            self.api_key = os.getenv("BINANCE_API_KEY")
            self.api_secret = os.getenv("BINANCE_API_SECRET")
        else:
            self.api_key = os.getenv("BINANCE_API_KEY_PRODUCCION", os.getenv("BINANCE_API_KEY"))
            self.api_secret = os.getenv("BINANCE_API_SECRET_PRODUCCION", os.getenv("BINANCE_API_SECRET"))

        if not self.api_key or not self.api_secret:
            raise ValueError("❌ Binance API keys missing. Check your .env file.")

        self.client = Client(self.api_key, self.api_secret, testnet=self.testnet)
        mode = "TESTNET" if self.testnet else "PRODUCTION"
        print(f"🔌 Connected to Binance {mode}")

    def get_price(self, symbol="BTCUSDT"):
        try:
            ticker = self.client.get_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            print(f"Price error: {e}")
            return 0.0

    def get_balance(self, asset="USDT"):
        try:
            balance = self.client.get_asset_balance(asset=asset)
            return float(balance['free'])
        except Exception as e:
            print(f"Balance error: {e}")
            return 0.0

    def buy_market(self, symbol="BTCUSDT", quantity=0.001):
        try:
            order = self.client.create_order(
                symbol=symbol,
                side=Client.SIDE_BUY,
                type=Client.ORDER_TYPE_MARKET,
                quantity=quantity
            )
            print(f"✅ Market buy executed: {quantity} {symbol}")
            return order
        except BinanceAPIException as e:
            print(f"Buy error: {e}")
            return None

    def sell_market(self, symbol="BTCUSDT", quantity=0.001):
        try:
            order = self.client.create_order(
                symbol=symbol,
                side=Client.SIDE_SELL,
                type=Client.ORDER_TYPE_MARKET,
                quantity=quantity
            )
            print(f"✅ Market sell executed: {quantity} {symbol}")
            return order
        except BinanceAPIException as e:
            print(f"Sell error: {e}")
            return None
