# trading_engine.py - Motor de trading con soporte Anti-MEV (1inch)
import os
import requests
import logging
import time
import hmac
import hashlib
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

class TradingEngine:
    def __init__(self, testnet=True, use_1inch=True):
        self.testnet = testnet
        self.use_1inch = use_1inch

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

        # 1inch API para Anti-MEV
        self.inch_api_key = os.getenv("INCH_API_KEY", "")
        self.inch_base_url = "https://api.1inch.dev"
        self.inch_chain_id = 1  # Ethereum mainnet

        if not self.api_key or not self.secret_key:
            logger.warning("⚠️ API keys not found. Please set them in environment variables.")

        self.session = requests.Session()
        self.session.headers.update({
            "X-MBX-APIKEY": self.api_key,
            "Content-Type": "application/json"
        })

    def _generate_signature(self, params):
        query_string = urlencode(params)
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return signature

    def _request(self, method, endpoint, params=None, signed=False):
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
        endpoint = "/ticker/price"
        params = {"symbol": symbol.upper()}
        data = self._request("GET", endpoint, params)
        if data and "price" in data:
            return float(data["price"])
        return None

    def get_balance(self, asset):
        endpoint = "/account"
        data = self._request("GET", endpoint, signed=True)
        if data and "balances" in data:
            for balance in data["balances"]:
                if balance["asset"] == asset.upper():
                    return float(balance["free"])
        return 0.0

    def buy_market(self, symbol, quantity, use_1inch=True):
        if use_1inch and self.inch_api_key and not self.testnet:
            return self._buy_with_1inch(symbol, quantity)
        else:
            return self._buy_direct(symbol, quantity)

    def sell_market(self, symbol, quantity, use_1inch=True):
        if use_1inch and self.inch_api_key and not self.testnet:
            return self._sell_with_1inch(symbol, quantity)
        else:
            return self._sell_direct(symbol, quantity)

    def _buy_direct(self, symbol, quantity):
        endpoint = "/order"
        params = {
            "symbol": symbol.upper(),
            "side": "BUY",
            "type": "MARKET",
            "quantity": quantity
        }
        data = self._request("POST", endpoint, params, signed=True)
        if data and "orderId" in data:
            logger.info(f"✅ Buy executed directly: {quantity} {symbol} - Order ID: {data['orderId']}")
            return data
        else:
            logger.error(f"❌ Direct buy failed: {data}")
            return None

    def _sell_direct(self, symbol, quantity):
        endpoint = "/order"
        params = {
            "symbol": symbol.upper(),
            "side": "SELL",
            "type": "MARKET",
            "quantity": quantity
        }
        data = self._request("POST", endpoint, params, signed=True)
        if data and "orderId" in data:
            logger.info(f"✅ Sell executed directly: {quantity} {symbol} - Order ID: {data['orderId']}")
            return data
        else:
            logger.error(f"❌ Direct sell failed: {data}")
            return None

    def _buy_with_1inch(self, symbol, quantity):
        try:
            # Si estamos en testnet, usamos directo (1inch no tiene testnet)
            if self.testnet:
                logger.warning("1inch no está disponible en testnet. Usando Binance directo.")
                return self._buy_direct(symbol, quantity)

            # Simular llamada a 1inch (por ahora es simulación hasta que configuremos la integración real)
            logger.info("🛡️ Anti-MEV activado: Comprando a través de 1inch (simulación)")
            # En producción, aquí iría la llamada real a 1inch
            return {"orderId": f"1inch_sim_{time.time()}", "simulated": True}
        except Exception as e:
            logger.error(f"Error en 1inch buy: {e}")
            return self._buy_direct(symbol, quantity)

    def _sell_with_1inch(self, symbol, quantity):
        try:
            if self.testnet:
                logger.warning("1inch no está disponible en testnet. Usando Binance directo.")
                return self._sell_direct(symbol, quantity)

            logger.info("🛡️ Anti-MEV activado: Vendiendo a través de 1inch (simulación)")
            return {"orderId": f"1inch_sim_{time.time()}", "simulated": True}
        except Exception as e:
            logger.error(f"Error en 1inch sell: {e}")
            return self._sell_direct(symbol, quantity)

    def get_order_status(self, symbol, order_id):
        endpoint = "/order"
        params = {
            "symbol": symbol.upper(),
            "orderId": order_id
        }
        data = self._request("GET", endpoint, params, signed=True)
        return data

    def cancel_order(self, symbol, order_id):
        endpoint = "/order"
        params = {
            "symbol": symbol.upper(),
            "orderId": order_id
        }
        data = self._request("DELETE", endpoint, params, signed=True)
        return data
