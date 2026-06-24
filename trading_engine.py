# -*- coding: utf-8 -*-
import os
import logging
from binance.client import Client
from binance.exceptions import BinanceAPIException

logger = logging.getLogger(__name__)

class TradingEngine:
    def __init__(self, testnet=False):
        self.api_key = os.getenv("BINANCE_API_KEY")
        self.api_secret = os.getenv("BINANCE_SECRET_KEY")
        self.testnet = testnet

        # Determinar la URL base para Binance
        base_url = os.getenv("BINANCE_API_URL", "https://api.binance.com")
        if self.testnet:
            base_url = "https://testnet.binance.vision"

        # Inicializar cliente de Binance (usando requests_params para compatibilidad)
        try:
            self.client = Client(self.api_key, self.api_secret)
            # Configurar la URL base manualmente
            if base_url != "https://api.binance.com":
                self.client.API_URL = base_url + "/api/v3"
                self.client.WS_URL = base_url.replace("https://", "wss://") + "/ws"
            logger.info("✅ Binance client initialized")
        except Exception as e:
            logger.error(f"❌ Error initializing Binance client: {e}")
            self.client = None

        # Solana desactivado para evitar errores
        self.solana_client = None
        logger.info("ℹ️ Solana client disabled")

    def get_balance(self, asset="USDT"):
        if not self.client:
            return None
        try:
            balance = self.client.get_asset_balance(asset=asset)
            if balance is None:
                return 0.0
            return float(balance.get('free', 0.0))
        except BinanceAPIException as e:
            logger.error(f"Binance API error for {asset}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error getting balance for {asset}: {e}")
            return None

    def get_price(self, symbol="BTCUSDT"):
        if not self.client:
            return None
        try:
            ticker = self.client.get_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            logger.error(f"Error getting price for {symbol}: {e}")
            return None

    def buy_market(self, symbol, quantity):
        if not self.client:
            return None
        try:
            order = self.client.order_market_buy(symbol=symbol, quantity=quantity)
            logger.info(f"✅ Buy order executed: {order['orderId']}")
            return order
        except Exception as e:
            logger.error(f"Error executing buy order: {e}")
            return None

    def sell_market(self, symbol, quantity):
        if not self.client:
            return None
        try:
            order = self.client.order_market_sell(symbol=symbol, quantity=quantity)
            logger.info(f"✅ Sell order executed: {order['orderId']}")
            return order
        except Exception as e:
            logger.error(f"Error executing sell order: {e}")
            return None
