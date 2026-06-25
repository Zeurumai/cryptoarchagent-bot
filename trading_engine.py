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

        # Inicializar cliente de Binance con el parámetro testnet
        try:
            self.client = Client(self.api_key, self.api_secret, testnet=testnet)
            logger.info(f"✅ Binance client initialized (testnet={testnet})")
        except Exception as e:
            logger.error(f"❌ Error initializing Binance client: {e}")
            self.client = None

        # =====================================================
        # SOLANA CLIENT (OPCIONAL, CON MANEJO DE ERRORES)
        # =====================================================
        try:
            from solana.rpc.api import Client as SolanaClient
            from solana.keypair import Keypair
            import base58

            solana_private_key = os.getenv("SOLANA_PRIVATE_KEY")
            endpoint = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

            self.solana_client = SolanaClient(endpoint)
            self.solana_keypair = None

            if solana_private_key:
                try:
                    keypair_bytes = base58.b58decode(solana_private_key)
                    self.solana_keypair = Keypair.from_secret_key(keypair_bytes)
                    logger.info("✅ Solana client initialized with keypair")
                except Exception as e:
                    logger.warning(f"⚠️ Invalid Solana private key: {e}")
            else:
                logger.info("✅ Solana client initialized without keypair (read-only)")

        except ImportError:
            logger.warning("⚠️ Solana libraries not installed. Solana features disabled.")
            self.solana_client = None
            self.solana_keypair = None
        except Exception as e:
            logger.warning(f"⚠️ Solana client init failed: {e}")
            self.solana_client = None
            self.solana_keypair = None

    # =====================================================
    # BINANCE FUNCTIONS
    # =====================================================

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

    # =====================================================
    # SOLANA FUNCTIONS (MEMECOINS Y JUPITER)
    # =====================================================

    def get_solana_token_price(self, mint_address: str) -> float:
        try:
            import requests
            url = f"https://quote-api.jup.ag/v6/price?ids={mint_address}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return float(data.get('data', {}).get(mint_address, {}).get('price', 0))
            return 0.0
        except Exception as e:
            logger.error(f"Error getting Solana token price: {e}")
            return 0.0

    def get_new_solana_tokens(self, limit=10) -> list:
        try:
            import requests
            url = f"https://api.dexscreener.com/latest/dex/search?q=solana"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                tokens = []
                for pair in data.get('pairs', [])[:limit]:
                    if pair.get('chainId') != 'solana':
                        continue
                    base = pair.get('baseToken', {})
                    tokens.append({
                        'name': base.get('name', 'Unknown'),
                        'symbol': base.get('symbol', '???'),
                        'address': base.get('address', ''),
                        'chain': 'solana',
                        'price_usd': pair.get('priceUsd', '0'),
                        'volume_24h': pair.get('volume', {}).get('h24', '0'),
                        'market_cap': pair.get('marketCap', '0'),
                    })
                return tokens
            return []
        except Exception as e:
            logger.error(f"Error getting Solana tokens: {e}")
            return []

    def swap_solana(self, input_mint: str, output_mint: str, amount: float, slippage_bps: int = 300) -> dict:
        if not self.solana_keypair:
            return {"error": "Solana keypair not configured"}
        try:
            import requests
            url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={int(amount * 1e9)}&slippageBps={slippage_bps}"
            quote_response = requests.get(url, timeout=10)
            if quote_response.status_code != 200:
                return {"error": "Failed to get quote"}
            quote_data = quote_response.json()
            swap_url = "https://quote-api.jup.ag/v6/swap"
            swap_payload = {
                "quoteResponse": quote_data,
                "userPublicKey": str(self.solana_keypair.public_key),
                "wrapAndUnwrapSol": True,
                "computeUnitPriceMicroLamports": 100000
            }
            swap_response = requests.post(swap_url, json=swap_payload, timeout=10)
            if swap_response.status_code != 200:
                return {"error": "Failed to execute swap"}
            return swap_response.json()
        except Exception as e:
            logger.error(f"Error executing Solana swap: {e}")
            return {"error": str(e)}
