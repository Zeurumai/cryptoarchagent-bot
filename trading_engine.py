import os
import json
import base58
import requests
import logging
from solana.rpc.api import Client
from solana.transaction import Transaction
from solders.keypair import Keypair
from solders.commitment_config import CommitmentLevel
from solders.signature import Signature
from solders.system_program import TransferParams, transfer
from solders.pubkey import Pubkey
from solders.token.associated import get_associated_token_address
from solders.token.constants import TOKEN_PROGRAM_ID
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
            # Firmar la transacción
            transaction.sign(self.keypair)
            serialized_tx = base58.b58encode(transaction.serialize()).decode('utf-8')
            
            # Construir payload para Jito
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendTransaction",
                "params": [
                    serialized_tx,
                    {
                        "encoding": "base58",
                        "skipPreflight": True,
                        "maxRetries": 0
                    }
                ]
            }
            
            # Enviar a Jito
            response = requests.post(JITO_RPC_ENDPOINT, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
            if response.status_code == 200:
                result = response.json()
                if "result" in result:
                    return {"success": True, "signature": result["result"], "source": "jito"}
                else:
                    return {"success": False, "error": result.get("error", "Unknown error")}
            else:
                return {"success": False, "error": f"HTTP {response.status_code}"}
        except Exception as e:
            logger.error(f"Error sending via Jito: {e}")
            return {"success": False, "error": str(e)}
    
    def send_solana_transaction_fallback(self, transaction: Transaction) -> dict:
        """
        Envía una transacción de Solana usando el RPC estándar (fallback).
        """
        if not self.keypair:
            return {"success": False, "error": "Solana keypair not loaded"}
        try:
            transaction.sign(self.keypair)
            signature = self.solana_client.send_transaction(transaction, self.keypair, opts={"skip_preflight": True})
            return {"success": True, "signature": str(signature), "source": "fallback"}
        except Exception as e:
            logger.error(f"Error sending via fallback: {e}")
            return {"success": False, "error": str(e)}
    
    def send_solana_transaction(self, transaction: Transaction, prefer_jito: bool = True) -> dict:
        """
        Envía una transacción de Solana, primero por Jito y si falla, por fallback.
        """
        if prefer_jito and JITO_RPC_ENDPOINT:
            result = self.send_solana_transaction_jito(transaction)
            if result.get("success"):
                return result
            logger.warning("⚠️ Jito failed, falling back to standard RPC")
        return self.send_solana_transaction_fallback(transaction)
    
    def transfer_sol(self, to_address: str, amount: float, prefer_jito: bool = True) -> dict:
        """
        Transfiere SOL a una dirección específica.
        """
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
                    lamports=int(amount * 1e9)  # SOL a lamports
                )
            )
            
            # Crear transacción
            transaction = Transaction().add(transfer_ix)
            transaction.recent_blockhash = self.solana_client.get_recent_blockhash()['result']['value']['blockhash']
            transaction.fee_payer = from_pubkey
            
            return self.send_solana_transaction(transaction, prefer_jito)
        except Exception as e:
            logger.error(f"Error in transfer_sol: {e}")
            return {"success": False, "error": str(e)}
    
    def transfer_spl_token(self, token_address: str, to_address: str, amount: float, prefer_jito: bool = True) -> dict:
        """
        Transfiere un token SPL a una dirección específica.
        """
        if not self.keypair:
            return {"success": False, "error": "Solana keypair not loaded"}
        try:
            from_pubkey = self.keypair.pubkey()
            to_pubkey = Pubkey.from_string(to_address)
            token_mint = Pubkey.from_string(token_address)
            
            # Obtener cuentas de token asociadas
            from_token_account = get_associated_token_address(from_pubkey, token_mint)
            to_token_account = get_associated_token_address(to_pubkey, token_mint)
            
            # Crear instrucción de transferencia de token SPL
            from solders.token.instructions import transfer_checked
            transfer_ix = transfer_checked(
                token_program_id=TOKEN_PROGRAM_ID,
                source=from_token_account,
                mint=token_mint,
                dest=to_token_account,
                owner=from_pubkey,
                amount=int(amount * 1e9),  # Ajustar según decimales del token
                decimals=9  # Asumimos 9 decimales (ajustar según token)
            )
            
            transaction = Transaction().add(transfer_ix)
            transaction.recent_blockhash = self.solana_client.get_recent_blockhash()['result']['value']['blockhash']
            transaction.fee_payer = from_pubkey
            
            return self.send_solana_transaction(transaction, prefer_jito)
        except Exception as e:
            logger.error(f"Error in transfer_spl_token: {e}")
            return {"success": False, "error": str(e)}
    
    # ==================== MÉTODOS DE UTILIDAD ====================
    def get_solana_balance(self) -> float:
        """Obtiene el balance de SOL de la wallet."""
        if not self.keypair:
            return 0.0
        try:
            balance = self.solana_client.get_balance(self.keypair.pubkey())
            return balance['result']['value'] / 1e9 if balance else 0.0
        except Exception as e:
            logger.error(f"Error getting Solana balance: {e}")
            return 0.0
    
    def get_spl_token_balance(self, token_address: str) -> float:
        """Obtiene el balance de un token SPL en la wallet."""
        if not self.keypair:
            return 0.0
        try:
            token_mint = Pubkey.from_string(token_address)
            token_account = get_associated_token_address(self.keypair.pubkey(), token_mint)
            balance = self.solana_client.get_token_account_balance(token_account)
            return balance['result']['value']['uiAmount'] if balance else 0.0
        except Exception as e:
            logger.error(f"Error getting SPL token balance: {e}")
            return 0.0

# ==================== PRUEBA RÁPIDA (si se ejecuta directamente) ====================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    engine = TradingEngine(testnet=True)
    
    # Probar conexión a Binance
    print("💰 Binance USDT Balance:", engine.get_balance("USDT"))
    print("💰 Binance BTC Balance:", engine.get_balance("BTC"))
    
    # Probar precio de BTC
    print("📈 BTC/USDT Price:", engine.get_price("BTCUSDT"))
    
    # Si hay keypair de Solana, probar balance
    if engine.keypair:
        print("💰 Solana SOL Balance:", engine.get_solana_balance())
