# whale_advanced.py - Datos reales de ballenas (BTC, ETH, BSC) con APIs gratuitas
import os
import requests
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ==================== CONFIGURACIÓN ====================
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")
BSCSCAN_API_KEY = os.getenv("BSCSCAN_API_KEY", "")

ETHERSCAN_API_URL = "https://api.etherscan.io/api"
BSCSCAN_API_URL = "https://api.bscscan.com/api"
BLOCKCHAIN_API_URL = "https://blockchain.info"

# ==================== BITCOIN (Blockchain.com - sin API key) ====================
def obtener_alertas_bitcoin(min_value_usd=50000, limit=3):
    try:
        url = f"{BLOCKCHAIN_API_URL}/unconfirmed-transactions?format=json"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        txs = data.get("txs", [])
        if not txs:
            logger.warning("No se encontraron transacciones no confirmadas en Blockchain.com")
            return []

        btc_usd_price = _get_btc_usd_price()
        if not btc_usd_price:
            btc_usd_price = 60000

        large_txs = []
        for tx in txs:
            total_btc = sum(out.get("value", 0) for out in tx.get("out", [])) / 100000000
            value_usd = total_btc * btc_usd_price
            if value_usd >= min_value_usd:
                large_txs.append({
                    "amount": total_btc,
                    "amount_usd": value_usd,
                    "symbol": "BTC",
                    "transaction_type": "transfer",
                    "description": f"Transacción BTC de {total_btc:.2f} BTC",
                    "hash": tx.get("hash", ""),
                    "timestamp": datetime.now().isoformat()
                })

        large_txs.sort(key=lambda x: x["amount_usd"], reverse=True)
        return large_txs[:limit]
    except Exception as e:
        logger.error(f"Error en Blockchain.com BTC: {e}")
        return []

def _get_btc_usd_price():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return r.json().get("bitcoin", {}).get("usd")
    except:
        pass
    return None

# ==================== ETHEREUM (Etherscan - con API key) ====================
def obtener_alertas_ethereum(min_value_usd=10000, limit=3):
    if not ETHERSCAN_API_KEY:
        logger.warning("Sin API key de Etherscan, no se pueden obtener datos de ETH.")
        return []

    try:
        eth_usd_price = _get_eth_usd_price()
        if not eth_usd_price:
            eth_usd_price = 1800

        # Usar la cuenta de la Fundación Ethereum como referencia
        address = "0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae"
        url = f"{ETHERSCAN_API_URL}?module=account&action=txlist&address={address}&sort=desc&apikey={ETHERSCAN_API_KEY}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "1":
            logger.warning(f"Etherscan no devolvió transacciones: {data.get('message')}")
            return []

        txs = data.get("result", [])
        large_txs = []
        for tx in txs[:50]:
            value_wei = int(tx.get("value", 0))
            if value_wei == 0:
                continue
            eth_amount = value_wei / 10**18
            value_usd = eth_amount * eth_usd_price
            if value_usd >= min_value_usd:
                large_txs.append({
                    "amount": eth_amount,
                    "amount_usd": value_usd,
                    "symbol": "ETH",
                    "transaction_type": "transfer",
                    "description": f"Transacción ETH de {eth_amount:.2f} ETH",
                    "hash": tx.get("hash", ""),
                    "from": tx.get("from", ""),
                    "to": tx.get("to", ""),
                    "timestamp": datetime.fromtimestamp(int(tx.get("timeStamp", 0))).isoformat()
                })

        large_txs.sort(key=lambda x: x["amount_usd"], reverse=True)
        return large_txs[:limit]
    except Exception as e:
        logger.error(f"Error en Etherscan ETH: {e}")
        return []

def _get_eth_usd_price():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return r.json().get("ethereum", {}).get("usd")
    except:
        pass
    return None

# ==================== BINANCE SMART CHAIN (BSCScan - con API key) ====================
def obtener_alertas_bsc(min_value_usd=5000, limit=3):
    if not BSCSCAN_API_KEY:
        logger.warning("Sin API key de BSCScan, no se pueden obtener datos de BSC.")
        return []

    try:
        bnb_usd_price = _get_bnb_usd_price()
        if not bnb_usd_price:
            bnb_usd_price = 600

        # Usar una cuenta conocida de BSC (PancakeSwap Router)
        address = "0x10ED43C718714eb63d5aA57B78B54704E256024E"
        url = f"{BSCSCAN_API_URL}?module=account&action=txlist&address={address}&sort=desc&apikey={BSCSCAN_API_KEY}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "1":
            logger.warning(f"BSCScan no devolvió transacciones: {data.get('message')}")
            return []

        txs = data.get("result", [])
        large_txs = []
        for tx in txs[:50]:
            value_wei = int(tx.get("value", 0))
            if value_wei == 0:
                continue
            bnb_amount = value_wei / 10**18
            value_usd = bnb_amount * bnb_usd_price
            if value_usd >= min_value_usd:
                large_txs.append({
                    "amount": bnb_amount,
                    "amount_usd": value_usd,
                    "symbol": "BNB",
                    "transaction_type": "transfer",
                    "description": f"Transacción BNB de {bnb_amount:.2f} BNB",
                    "hash": tx.get("hash", ""),
                    "from": tx.get("from", ""),
                    "to": tx.get("to", ""),
                    "timestamp": datetime.fromtimestamp(int(tx.get("timeStamp", 0))).isoformat()
                })

        large_txs.sort(key=lambda x: x["amount_usd"], reverse=True)
        return large_txs[:limit]
    except Exception as e:
        logger.error(f"Error en BSCScan BSC: {e}")
        return []

def _get_bnb_usd_price():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=binancecoin&vs_currencies=usd"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return r.json().get("binancecoin", {}).get("usd")
    except:
        pass
    return None

# ==================== FUNCIONES DE ANÁLISIS (comunes) ====================
def analizar_alerta(alert):
    try:
        amount = alert.get("amount", 0)
        value_usd = alert.get("amount_usd", 0)
        symbol = alert.get("symbol", "BTC")
        tx_type = alert.get("transaction_type", "transfer")

        emoji = "🐋" if tx_type == "transfer" else "🔄"
        desc = f"{amount:.2f} {symbol}"

        if value_usd > 10000000:
            sentimiento = "🚨 MUY GRANDE"
        elif value_usd > 1000000:
            sentimiento = "🔴 GRANDE"
        else:
            sentimiento = "🟡 MEDIANO"

        return emoji, desc, sentimiento, value_usd
    except Exception as e:
        logger.error(f"Error analizando alerta: {e}")
        return "❓", "Error", "DESCONOCIDO", 0

def analizar_con_ia(coin, amount, value_usd, tx_type, description):
    try:
        if value_usd > 10000000:
            return f"🚨 Movimiento masivo de {coin}. Posible acumulación institucional."
        elif value_usd > 1000000:
            return f"📊 Transacción significativa de {coin}. Probable movimiento de ballena."
        else:
            return f"📈 Movimiento moderado de {coin}. Seguimiento recomendado."
    except Exception as e:
        logger.error(f"Error en análisis IA: {e}")
        return None
