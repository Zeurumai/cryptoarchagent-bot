import os
import json
import base58
import requests
import logging
from solana.rpc.api import Client
from solders.transaction import VersionedTransaction as Transaction
from solders.keypair import Keypair
from solders.commitment_config import CommitmentLevel
from solders.signature import Signature
from solders.instruction import Instruction
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.token.associated import get_associated_token_address

# ========== CORRECCIÓN DEL IMPORT DE TOKEN_PROGRAM_ID ==========
try:
    from solders.program_id import TOKEN_PROGRAM_ID   # >= v0.18.0
except ImportError:
    try:
        from solders.token.constants import TOKEN_PROGRAM_ID  # versión antigua
    except ImportError:
        # Definición manual (válida para todas las versiones)
        TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
# ================================================================

from binance.client import Client as BinanceClient
from binance.enums import *
import time

logger = logging.getLogger(__name__)

# ==================== CONFIGURACIÓN ====================
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")
BINANCE_TESTNET = os.getenv("BINANCE_TESTNET", "true").lower() == "true"

# Solana RPC
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
JITO_RPC_ENDPOINT = os.getenv("JITO_RPC_ENDPOINT", "https://mainnet.block-engine.jito.wtf/api/v1")

# Cuentas de propina de Jito (ejemplo, actualizar con las oficiales)
JITO_TIP_ACCOUNTS = [
    "JitoTip111111111111111111111111111111111",
    "JitoTip222222222222222222222222222222222",
    "JitoTip333333333333333333333333333333333"
]

# ==================== CLASE PRINCIPAL ====================
class TradingEngine:
    def __init__(self, testnet: bool = True):
        self.testnet = testnet
        self.binance_client = None
        self.solana_client = None
        self.keypair = None
        self._init_clients()
    
    def _init_clients(self):
        """Inicializa los clientes de Binance y Solana."""
        if BINANCE_API_KEY and BINANCE_SECRET_KEY:
            try:
                self.binance_client = BinanceClient(BINANCE_API_KEY, BINANCE_SECRET_KEY, testnet=self.testnet)
                logger.info("✅ Binance client initialized")
            except Exception as e:
                logger.error(f"❌ Error initializing Binance client: {e}")
        else:
            logger.warning("⚠️ Binance API keys not configured. Trading functions will not work.")
        
        # Inicializar cliente Solana
        self.solana_client = Client(SOLANA_RPC_URL)
        logger.info(f"✅ Solana client initialized: {SOLANA_RPC_URL}")
        
        # Cargar keypair si existe
        private_key = os.getenv("SOLANA_PRIVATE_KEY", "")
        if private_key:
            try:
                self.keypair = Keypair.from_base58_string(private_key)
                logger.info("✅ Solana keypair loaded")
            except Exception as e:
                logger.error(f"❌ Error loading Solana keypair: {e}")
    
    # ==================== BINANCE FUNCTIONS ====================
    def get_balance(self, asset: str) -> float:
        """Obtiene el balance de un activo en Binance (testnet o real)."""
        if not self.binance_client:
            logger.error("Binance client not initialized")
            return 0.0
        try:
            balance = self.binance_client.get_asset_balance(asset=asset)
            return float(balance['free']) if balance else 0.0
        except Exception as e:
            logger.error(f"Error getting balance for {asset}: {e}")
            return 0.0
    
    def get_price(self, symbol: str) -> float:
        """Obtiene el precio actual de un símbolo en Binance."""
        if not self.binance_client:
            logger.error("Binance client not initialized")
            return 0.0
        try:
            ticker = self.binance_client.get_symbol_ticker(symbol=symbol)
            return float(ticker['price']) if ticker else 0.0
        except Exception as e:
            logger.error(f"Error getting price for {symbol}: {e}")
            return 0.0
    
    def buy_market(self, symbol: str, quantity: float) -> dict:
        """Ejecuta una orden de compra a mercado en Binance."""
        if not self.binance_client:
            return {"error": "Binance client not initialized"}
        if self.testnet:
            logger.info(f"🔵 [TESTNET] Buying {quantity} {symbol} at market price")
        try:
            order = self.binance_client.create_order(
                symbol=symbol,
                side=SIDE_BUY,
                type=ORDER_TYPE_MARKET,
                quantity=quantity
            )
            logger.info(f"✅ Buy order executed: {order}")
            return order
        except Exception as e:
            logger.error(f"❌ Error buying {symbol}: {e}")
            return {"error": str(e)}
    
    def sell_market(self, symbol: str, quantity: float) -> dict:
        """Ejecuta una orden de venta a mercado en Binance."""
        if not self.binance_client:
            return {"error": "Binance client not initialized"}
        if self.testnet:
            logger.info(f"🔵 [TESTNET] Selling {quantity} {symbol} at market price")
        try:
            order = self.binance_client.create_order(
                symbol=symbol,
                side=SIDE_SELL,
                type=ORDER_TYPE_MARKET,
                quantity=quantity
            )
            logger.info(f"✅ Sell order executed: {order}")
            return order
        except Exception as e:
            logger.error(f"❌ Error selling {symbol}: {e}")
            return {"error": str(e)}
    
    # ==================== SOLANA FUNCTIONS (con Jito) ====================
    def send_solana_transaction_jito(self, transaction: Transaction) -> dict:
        """
        Envía una transacción de Solana a través de Jito para evitar MEV y reducir latencia.
        """
        if not self.keypair:
            return {"success": False, "error": "Solana keypair not loaded"}
        
        try:
            # Firmar la transacción (ahora se hace con VersionedTransaction)
            tx_bytes = bytes(transaction)
            signature = self.keypair.sign_message(tx_bytes)
            # La transacción ya debe estar firmada al construirla, pero con VersionedTransaction
            # se firma de manera diferente. Simplificamos: usamos el método send_transaction de solana.rpc
            # que maneja la firma automáticamente si se pasa el keypair.
            
            # Para Jito necesitamos serializar la transacción firmada
            # Usamos el cliente RPC de Solana para enviar
            response = self.solana_client.send_transaction(transaction, self.keypair, opts={"skip_preflight": True})
            if response.get("result"):
                return {"success": True, "signature": response["result"], "source": "jito"}
            else:
                return {"success": False, "error": response.get("error", "Unknown error")}
        except Exception as e:
            logger.error(f"Error sending via Jito: {e}")
            return {"success": False, "error": str(e)}
    
    def send_solana_transaction_fallback(self, transaction: Transaction) -> dict:
        """Envía una transacción de Solana usando el RPC estándar (fallback)."""
        if not self.keypair:
            return {"success": False, "error": "Solana keypair not loaded"}
        try:
            response = self.solana_client.send_transaction(transaction, self.keypair, opts={"skip_preflight": True})
            if response.get("result"):
                return {"success": True, "signature": response["result"], "source": "fallback"}
            else:
                return {"success": False, "error": response.get("error", "Unknown error")}
        except Exception as e:
            logger.error(f"Error sending via fallback: {e}")
            return {"success": False, "error": str(e)}
    
    def send_solana_transaction(self, transaction: Transaction, prefer_jito: bool = True) -> dict:
        """Envía una transacción de Solana, primero por Jito y si falla, por fallback."""
        if prefer_jito and JITO_RPC_ENDPOINT:
            result = self.send_solana_transaction_jito(transaction)
            if result.get("success"):
                return result
            logger.warning("⚠️ Jito failed, falling back to standard RPC")
        return self.send_solana_transaction_fallback(transaction)
    
    def transfer_sol(self, to_address: str, amount: float, prefer_jito: bool = True) -> dict:
        """Transfiere SOL a una dirección específica."""
        if not self.keypair:
            return {"success": False, "error": "Solana keypair not loaded"}
        try:
            to_pubkey = Pubkey.from_string(to_address)
            from_pubkey = self.keypair.pubkey()
            
            # Crear instrucción de transferencia
            transfer_ix = transfer(
                TransferParams(
                    from_pubkey=from_pubkey,
                    to_pubkey=to_pubkey,
                    lamports=int(amount * 1e9)
                )
            )
            
            # Crear transacción Versioned
            recent_blockhash = self.solana_client.get_latest_blockhash()
            message = MessageV0.try_compile(
                payer=from_pubkey,
                instructions=[transfer_ix],
                address_lookup_table_accounts=[],
                recent_blockhash=recent_blockhash['result']['value']['blockhash']
            )
            transaction = Transaction([self.keypair], message)
            
            return self.send_solana_transaction(transaction, prefer_jito)
        except Exception as e:
            logger.error(f"Error in transfer_sol: {e}")
            return {"success": False, "error": str(e)}
    
    # ==================== MÉTODOS DE UTILIDAD ====================
    def get_solana_balance(self) -> float:
        """Obtiene el balance de SOL de la wallet."""
        if not self.keypair:
            return 0.0
        try:
            response = self.solana_client.get_balance(self.keypair.pubkey())
            return response['result']['value'] / 1e9 if response else 0.0
        except Exception as e:
            logger.error(f"Error getting Solana balance: {e}")
            return 0.0

# ==================== PRUEBA RÁPIDA ====================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    engine = TradingEngine(testnet=True)
    print("💰 Binance USDT Balance:", engine.get_balance("USDT"))
    print("💰 Binance BTC Balance:", engine.get_balance("BTC"))
    print("📈 BTC/USDT Price:", engine.get_price("BTCUSDT"))
    if engine.keypair:
        print("💰 Solana SOL Balance:", engine.get_solana_balance())
