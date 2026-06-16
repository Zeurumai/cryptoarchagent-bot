# trading_engine.py - Motor de trading para Binance (Testnet y Producción)
import os
import time
import hmac
import hashlib
import requests
import logging
from datetime import datetime
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


class TradingEngine:
    def __init__(self, testnet=True):
        """
        Inicializa el motor de trading.
        - testnet=True: usa Binance Testnet (por defecto)
        - testnet=False: usa Binance Producción (real)
        """
        self.testnet = testnet

        if self.testnet:
            self.base_url = "https://testnet.binance.vision/api/v3"
            self.ws_url = "wss://testnet.binance.vision/ws"
            self.api_key = os.getenv("BINANCE_TESTNET_API_KEY", "")
            self.secret_key = os.getenv("BINANCE_TESTNET_SECRET_KEY", "")
        else:
            self.base_url = "https://api.binance.com/api/v3"
            self.ws_url = "wss://stream.binance.com:9443/ws"
            self.api_key = os.getenv("BINANCE_API_KEY", "")
            self.secret_key = os.getenv("BINANCE_SECRET_KEY", "")

        if not self.api_key or not self.secret_key:
            logger.warning("⚠️ API keys not found. Please set them in environment variables.")

        self.session = requests.Session()
        self.session.headers.update({
            "X-MBX-APIKEY": self.api_key,
            "Content-Type": "application/json"
        })

    def _generate_signature(self, params):
        """Genera la firma HMAC SHA256 para las solicitudes autenticadas."""
        query_string = urlencode(params)
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return signature

    def _request(self, method, endpoint, params=None, signed=False):
        """Realiza una solicitud HTTP a la API de Binance."""
        url = f"{self.base_url}{endpoint}"
        if signed:
            if params is None:
                params = {}
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = 5000
            signature = self._generate_signature(params)
            params["signature"] = signature
            response = self.session.request(method, url, params=params)
        else:
            response = self.session.request(method, url, params=params)

        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Error en Binance API: {response.status_code} - {response.text}")
            return None

    def get_price(self, symbol):
        """Obtiene el precio actual de un par (ej: BTCUSDT)."""
        endpoint = "/ticker/price"
        params = {"symbol": symbol.upper()}
        data = self._request("GET", endpoint, params)
        if data and "price" in data:
            return float(data["price"])
        return None

    def get_balance(self, asset):
        """Obtiene el saldo de un activo (ej: USDT, BTC)."""
        endpoint = "/account"
        data = self._request("GET", endpoint, signed=True)
        if data and "balances" in data:
            for balance in data["balances"]:
                if balance["asset"] == asset.upper():
                    return float(balance["free"])
        return 0.0

    def buy_market(self, symbol, quantity):
        """
        Realiza una orden de compra a precio de mercado.
        - symbol: par (ej: BTCUSDT)
        - quantity: cantidad a comprar
        """
        endpoint = "/order"
        params = {
            "symbol": symbol.upper(),
            "side": "BUY",
            "type": "MARKET",
            "quantity": quantity
        }
        data = self._request("POST", endpoint, params, signed=True)
        if data and "orderId" in data:
            logger.info(f"✅ Buy order executed: {quantity} {symbol} - Order ID: {data['orderId']}")
            return data
        else:
            logger.error(f"❌ Buy order failed: {data}")
            return None

    def sell_market(self, symbol, quantity):
        """
        Realiza una orden de venta a precio de mercado.
        - symbol: par (ej: BTCUSDT)
        - quantity: cantidad a vender
        """
        endpoint = "/order"
        params = {
            "symbol": symbol.upper(),
            "side": "SELL",
            "type": "MARKET",
            "quantity": quantity
        }
        data = self._request("POST", endpoint, params, signed=True)
        if data and "orderId" in data:
            logger.info(f"✅ Sell order executed: {quantity} {symbol} - Order ID: {data['orderId']}")
            return data
        else:
            logger.error(f"❌ Sell order failed: {data}")
            return None

    def get_order_status(self, symbol, order_id):
        """Consulta el estado de una orden."""
        endpoint = "/order"
        params = {
            "symbol": symbol.upper(),
            "orderId": order_id
        }
        data = self._request("GET", endpoint, params, signed=True)
        return data

    def cancel_order(self, symbol, order_id):
        """Cancela una orden abierta."""
        endpoint = "/order"
        params = {
            "symbol": symbol.upper(),
            "orderId": order_id
        }
        data = self._request("DELETE", endpoint, params, signed=True)
        return data
