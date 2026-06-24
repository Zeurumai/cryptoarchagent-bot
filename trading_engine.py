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

        # Inicializar cliente de Binance (usando base_url directamente)
        try:
            self.client = Client(self.api_key, self.api_secret, base_url=base_url)
            logger.info("✅ Binance client initialized")
        except Exception as e:
            logger.error(f"❌ Error initializing Binance client: {e}")
            self.client = None

        # =====================================================
        # SOLANA CLIENT (CON MANEJO DE ERRORES Y SOPORTE PARA LLAVE PRIVADA)
        # =====================================================
        try:
            from solana.rpc.api import Client as SolanaClient
            from solana.keypair import Keypair
            import base58

            solana_private_key = os.getenv("SOLANA_PRIVATE_KEY")
            endpoint = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

            # Inicializar cliente base (sin keypair)
            self.solana_client = SolanaClient(endpoint)

            # Si hay una llave privada configurada, intentar usarla
            if solana_private_key:
                try:
                    keypair_bytes = base58.b58decode(solana_private_key)
                    keypair = Keypair.from_secret_key(keypair_bytes)
                    self.solana_client = SolanaClient(endpoint, keypair=keypair)
                    logger.info("✅ Solana client initialized with keypair")
                except Exception as e:
                    logger.warning(f"⚠️ Invalid Solana private key, using client without keypair: {e}")
            else:
                logger.info("✅ Solana client initialized without keypair (read-only mode)")

        except ImportError:
            logger.warning("⚠️ Solana libraries not installed. Solana features disabled.")
            self.solana_client = None
        except Exception as e:
            logger.warning(f"⚠️ Solana client initialization failed: {e}")
            self.solana_client = None

    def get_balance(self, asset="USDT"):
        if not self.client:
            return None
        try:
            balance = self.client.get_asset_balance(asset=asset)
            return float(balance['free'])
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
