# trading_engine.py
import os
from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException

load_dotenv()

class TradingEngine:
    def __init__(self, testnet=True):
        self.testnet = testnet
        if self.testnet:
            self.api_key = os.getenv("BINANCE_API_KEY")
            self.api_secret = os.getenv("BINANCE_API_SECRET")
        else:
            # Para producción (real) usarías otras claves
            self.api_key = os.getenv("BINANCE_API_KEY_PRODUCCION")
            self.api_secret = os.getenv("BINANCE_API_SECRET_PRODUCCION")
        
        if not self.api_key or not self.api_secret:
            raise ValueError("❌ Faltan claves API de Binance")
        
        self.client = Client(self.api_key, self.api_secret, testnet=self.testnet)
        print(f"🔌 Conectado a Binance {'TESTNET' if self.testnet else 'PRODUCCIÓN'}")
    
    def obtener_precio(self, simbolo="BTCUSDT"):
        try:
            ticker = self.client.get_symbol_ticker(symbol=simbolo)
            return float(ticker['price'])
        except Exception as e:
            print(f"Error precio: {e}")
            return 0.0
    
    def obtener_balance(self, activo="USDT"):
        try:
            balance = self.client.get_asset_balance(asset=activo)
            return float(balance['free'])
        except Exception as e:
            print(f"Error balance: {e}")
            return 0.0
    
    def comprar_market(self, simbolo="BTCUSDT", cantidad=0.001):
        try:
            orden = self.client.create_order(
                symbol=simbolo,
                side=Client.SIDE_BUY,
                type=Client.ORDER_TYPE_MARKET,
                quantity=cantidad
            )
            return orden
        except BinanceAPIException as e:
            print(f"Error compra: {e}")
            return None
    
    def vender_market(self, simbolo="BTCUSDT", cantidad=0.001):
        try:
            orden = self.client.create_order(
                symbol=simbolo,
                side=Client.SIDE_SELL,
                type=Client.ORDER_TYPE_MARKET,
                quantity=cantidad
            )
            return orden
        except BinanceAPIException as e:
            print(f"Error venta: {e}")
            return None