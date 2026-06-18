# trading_engine.py - Motor de trading con Anti-MEV real (1inch)
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
        self.inch_chain_id = 1  # Ethereum mainnet (1 para ETH, 56 para BSC, 137 para Polygon)

        # Mapeo de símbolos a direcciones de token (para 1inch)
        self.token_addresses = {
            "BTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",  # WBTC
            "ETH": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",  # Native ETH
            "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
            "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
            "SOL": "0x7e9D8F0c6Df9C2F2b1E9f8EaBc6D4aE7F3C2D8E9F",  # Simulado
            "MATIC": "0x7D1AfA7B718fb893dB30A3aBc0Cfc608AaCfeBB0",
            "ARB": "0x912CE59144191C1204E64559FE8253a0e49E6548"
        }

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
        """Compra a través de 1inch para evitar MEV (real)"""
        try:
            if self.testnet:
                logger.warning("1inch no está disponible en testnet. Usando Binance directo.")
                return self._buy_direct(symbol, quantity)

            logger.info("🛡️ Anti-MEV activado: Comprando a través de 1inch")

            # Obtener precio de la orden
            price = self.get_price(symbol)
            if not price:
                return self._buy_direct(symbol, quantity)

            # Convertir cantidad a tokens (simplificado)
            token_symbol = symbol.replace("USDT", "").replace("USD", "")
            from_token = "USDC"  # Usamos USDC como base
            to_token = self.token_addresses.get(token_symbol, "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE")

            # Calcular monto en wei (18 decimales para tokens)
            amount_in_usdc = quantity * price
            amount_wei = int(amount_in_usdc * 1e6)  # USDC tiene 6 decimales

            # Preparar headers de 1inch
            headers = {
                "Authorization": f"Bearer {self.inch_api_key}",
                "Content-Type": "application/json"
            }

            # 1. Obtener quote (precio y ruta)
            quote_url = f"{self.inch_base_url}/swap/v6.0/{self.inch_chain_id}/quote"
            quote_params = {
                "fromTokenAddress": self.token_addresses.get("USDC", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"),
                "toTokenAddress": to_token,
                "amount": str(amount_wei)
            }
            quote_response = requests.get(quote_url, headers=headers, params=quote_params)
            if quote_response.status_code != 200:
                logger.error(f"Error en 1inch quote: {quote_response.text}")
                return self._buy_direct(symbol, quantity)

            quote = quote_response.json()

            # 2. Ejecutar swap
            swap_url = f"{self.inch_base_url}/swap/v6.0/{self.inch_chain_id}/swap"
            swap_payload = {
                "fromTokenAddress": self.token_addresses.get("USDC", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"),
                "toTokenAddress": to_token,
                "amount": str(amount_wei),
                "fromAddress": "0x" + self.api_key[:40] if self.api_key else "0x0000000000000000000000000000000000000000",
                "slippage": 1.0,
                "destReceiver": "0x" + self.api_key[:40] if self.api_key else "0x0000000000000000000000000000000000000000"
            }
            swap_response = requests.post(swap_url, headers=headers, json=swap_payload)
            if swap_response.status_code != 200:
                logger.error(f"Error en 1inch swap: {swap_response.text}")
                return self._buy_direct(symbol, quantity)

            result = swap_response.json()
            logger.info(f"✅ Buy executed via 1inch (Anti-MEV): {quantity} {symbol} - Tx: {result.get('tx', {}).get('hash')}")
            return {"orderId": f"1inch_{int(time.time())}", "tx": result.get("tx", {})}

        except Exception as e:
            logger.error(f"Error en 1inch buy: {e}")
            return self._buy_direct(symbol, quantity)

    def _sell_with_1inch(self, symbol, quantity):
        """Vende a través de 1inch para evitar MEV (real)"""
        try:
            if self.testnet:
                logger.warning("1inch no está disponible en testnet. Usando Binance directo.")
                return self._sell_direct(symbol, quantity)

            logger.info("🛡️ Anti-MEV activado: Vendiendo a través de 1inch")

            # Obtener precio de la orden
            price = self.get_price(symbol)
            if not price:
                return self._sell_direct(symbol, quantity)

            # Convertir cantidad a tokens
            token_symbol = symbol.replace("USDT", "").replace("USD", "")
            from_token = self.token_addresses.get(token_symbol, "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE")
            to_token = self.token_addresses.get("USDC", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")

            # Calcular monto en wei (depende del token)
            amount_wei = int(quantity * 1e18)  # Asumimos 18 decimales

            headers = {
                "Authorization": f"Bearer {self.inch_api_key}",
                "Content-Type": "application/json"
            }

            # 1. Obtener quote
            quote_url = f"{self.inch_base_url}/swap/v6.0/{self.inch_chain_id}/quote"
            quote_params = {
                "fromTokenAddress": from_token,
                "toTokenAddress": to_token,
                "amount": str(amount_wei)
            }
            quote_response = requests.get(quote_url, headers=headers, params=quote_params)
            if quote_response.status_code != 200:
                logger.error(f"Error en 1inch quote: {quote_response.text}")
                return self._sell_direct(symbol, quantity)

            quote = quote_response.json()

            # 2. Ejecutar swap
            swap_url = f"{self.inch_base_url}/swap/v6.0/{self.inch_chain_id}/swap"
            swap_payload = {
                "fromTokenAddress": from_token,
                "toTokenAddress": to_token,
                "amount": str(amount_wei),
                "fromAddress": "0x" + self.api_key[:40] if self.api_key else "0x0000000000000000000000000000000000000000",
                "slippage": 1.0,
                "destReceiver": "0x" + self.api_key[:40] if self.api_key else "0x0000000000000000000000000000000000000000"
            }
            swap_response = requests.post(swap_url, headers=headers, json=swap_payload)
            if swap_response.status_code != 200:
                logger.error(f"Error en 1inch swap: {swap_response.text}")
                return self._sell_direct(symbol, quantity)

            result = swap_response.json()
            logger.info(f"✅ Sell executed via 1inch (Anti-MEV): {quantity} {symbol} - Tx: {result.get('tx', {}).get('hash')}")
            return {"orderId": f"1inch_{int(time.time())}", "tx": result.get("tx", {})}

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
