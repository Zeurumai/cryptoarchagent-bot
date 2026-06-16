# whale_advanced.py - Datos reales de ballenas (BTC, ETH, BSC) con análisis mejorado
import os
import requests
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ==================== CONFIGURACIÓN ====================
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")
BSCSCAN_API_KEY = os.getenv("BSCSCAN_API_KEY", "")  # Opcional

ETHERSCAN_API_URL = "https://api.etherscan.io/api"
BSCSCAN_API_URL = "https://api.bscscan.com/api"
BLOCKCHAIN_API_URL = "https://blockchain.info"

# Lista de exchanges conocidos (para identificar movimientos)
EXCHANGE_ADDRESSES = [
    "binance", "coinbase", "kraken", "bitfinex", "huobi", "okx", "bybit",
    "gate.io", "kucoin", "crypto.com", "gemini", "bitstamp", "bittrex"
]

# ==================== BITCOIN (Blockchain.com - sin API key) ====================
def obtener_alertas_bitcoin(min_value_usd=50000, limit=3):
    try:
        url = f"{BLOCKCHAIN_API_URL}/unconfirmed-transactions?format=json"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        txs = data.get("txs", [])
        if not txs:
            logger.warning("No unconfirmed transactions found on Blockchain.com")
            return []

        btc_usd_price = _get_btc_usd_price()
        if not btc_usd_price:
            btc_usd_price = 60000

        large_txs = []
        for tx in txs[:50]:
            total_btc = sum(out.get("value", 0) for out in tx.get("out", [])) / 100000000
            value_usd = total_btc * btc_usd_price
            if value_usd >= min_value_usd:
                # Intentar identificar si es exchange o wallet fría
                tx_type = "transfer"
                description = f"BTC transaction of {total_btc:.2f} BTC"
                # Analizar direcciones de salida
                for out in tx.get("out", []):
                    addr = out.get("addr", "").lower()
                    if any(exchange in addr for exchange in EXCHANGE_ADDRESSES):
                        tx_type = "exchange_out"
                        description = f"BTC moving to exchange: {total_btc:.2f} BTC"
                        break
                large_txs.append({
                    "amount": total_btc,
                    "amount_usd": value_usd,
                    "symbol": "BTC",
                    "transaction_type": tx_type,
                    "description": description,
                    "hash": tx.get("hash", ""),
                    "from": "unknown",
                    "to": "unknown",
                    "timestamp": datetime.now().isoformat()
                })

        large_txs.sort(key=lambda x: x["amount_usd"], reverse=True)
        return large_txs[:limit]
    except Exception as e:
        logger.error(f"Error in Blockchain.com BTC: {e}")
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
        logger.warning("Etherscan API key missing. ETH whale data unavailable.")
        return []

    try:
        eth_usd_price = _get_eth_usd_price()
        if not eth_usd_price:
            eth_usd_price = 1800

        # Usar Binance Hot Wallet para más actividad
        address = "0x28C6c06298d514Db089934071355E5743bf21d60"
        url = f"{ETHERSCAN_API_URL}?module=account&action=txlist&address={address}&sort=desc&apikey={ETHERSCAN_API_KEY}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "1":
            logger.warning(f"Etherscan returned no transactions: {data.get('message')}")
            return []

        txs = data.get("result", [])
        large_txs = []
        for tx in txs[:30]:
            value_wei = int(tx.get("value", 0))
            if value_wei == 0:
                continue
            eth_amount = value_wei / 10**18
            value_usd = eth_amount * eth_usd_price
            if value_usd >= min_value_usd:
                from_addr = tx.get("from", "").lower()
                to_addr = tx.get("to", "").lower()
                tx_type = "transfer"
                description = f"ETH transaction of {eth_amount:.2f} ETH"
                # Analizar destino
                if any(exchange in to_addr for exchange in EXCHANGE_ADDRESSES):
                    tx_type = "exchange_in"
                    description = f"ETH moving to exchange: {eth_amount:.2f} ETH"
                elif "0x0000000000000000000000000000000000000000" in to_addr:
                    tx_type = "burn"
                    description = f"ETH burned: {eth_amount:.2f} ETH"
                # Analizar origen
                if any(exchange in from_addr for exchange in EXCHANGE_ADDRESSES):
                    tx_type = "exchange_out"
                    description = f"ETH moving from exchange: {eth_amount:.2f} ETH"
                large_txs.append({
                    "amount": eth_amount,
                    "amount_usd": value_usd,
                    "symbol": "ETH",
                    "transaction_type": tx_type,
                    "description": description,
                    "hash": tx.get("hash", ""),
                    "from": from_addr,
                    "to": to_addr,
                    "timestamp": datetime.fromtimestamp(int(tx.get("timeStamp", 0))).isoformat()
                })

        large_txs.sort(key=lambda x: x["amount_usd"], reverse=True)
        return large_txs[:limit]
    except Exception as e:
        logger.error(f"Error in Etherscan ETH: {e}")
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

# ==================== BINANCE SMART CHAIN (BSCScan - con API key, opcional) ====================
def obtener_alertas_bsc(min_value_usd=5000, limit=3):
    if not BSCSCAN_API_KEY:
        logger.warning("BSCScan API key missing. BSC whale data unavailable.")
        return []

    try:
        bnb_usd_price = _get_bnb_usd_price()
        if not bnb_usd_price:
            bnb_usd_price = 600

        address = "0x10ED43C718714eb63d5aA57B78B54704E256024E"  # PancakeSwap Router
        url = f"{BSCSCAN_API_URL}?module=account&action=txlist&address={address}&sort=desc&apikey={BSCSCAN_API_KEY}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "1":
            logger.warning(f"BSCScan returned no transactions: {data.get('message')}")
            return []

        txs = data.get("result", [])
        large_txs = []
        for tx in txs[:30]:
            value_wei = int(tx.get("value", 0))
            if value_wei == 0:
                continue
            bnb_amount = value_wei / 10**18
            value_usd = bnb_amount * bnb_usd_price
            if value_usd >= min_value_usd:
                from_addr = tx.get("from", "").lower()
                to_addr = tx.get("to", "").lower()
                tx_type = "transfer"
                description = f"BNB transaction of {bnb_amount:.2f} BNB"
                if any(exchange in to_addr for exchange in EXCHANGE_ADDRESSES):
                    tx_type = "exchange_in"
                    description = f"BNB moving to exchange: {bnb_amount:.2f} BNB"
                elif any(exchange in from_addr for exchange in EXCHANGE_ADDRESSES):
                    tx_type = "exchange_out"
                    description = f"BNB moving from exchange: {bnb_amount:.2f} BNB"
                large_txs.append({
                    "amount": bnb_amount,
                    "amount_usd": value_usd,
                    "symbol": "BNB",
                    "transaction_type": tx_type,
                    "description": description,
                    "hash": tx.get("hash", ""),
                    "from": from_addr,
                    "to": to_addr,
                    "timestamp": datetime.fromtimestamp(int(tx.get("timeStamp", 0))).isoformat()
                })

        large_txs.sort(key=lambda x: x["amount_usd"], reverse=True)
        return large_txs[:limit]
    except Exception as e:
        logger.error(f"Error in BSCScan BSC: {e}")
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

# ==================== FUNCIONES DE ANÁLISIS (MEJORADAS) ====================
def analizar_alerta(alert):
    try:
        amount = alert.get("amount", 0)
        value_usd = alert.get("amount_usd", 0)
        symbol = alert.get("symbol", "BTC")
        tx_type = alert.get("transaction_type", "transfer")

        emoji = "🐋" if tx_type == "transfer" else "🔄"
        desc = f"{amount:.2f} {symbol}"

        if value_usd > 10000000:
            sentiment = "🚨 VERY LARGE"
        elif value_usd > 1000000:
            sentiment = "🔴 LARGE"
        else:
            sentiment = "🟡 MEDIUM"

        return emoji, desc, sentiment, value_usd
    except Exception as e:
        logger.error(f"Error analyzing alert: {e}")
        return "❓", "Error", "UNKNOWN", 0

def analizar_con_ia(alert):
    """
    Análisis inteligente basado en tipo de transacción y contexto.
    """
    try:
        coin = alert.get("symbol", "BTC")
        amount = alert.get("amount", 0)
        value_usd = alert.get("amount_usd", 0)
        tx_type = alert.get("transaction_type", "transfer")
        description = alert.get("description", "")
        from_addr = alert.get("from", "")
        to_addr = alert.get("to", "")

        # Determinar tipo de movimiento
        is_exchange_in = tx_type == "exchange_in" or "exchange" in description.lower() and "to" in description.lower()
        is_exchange_out = tx_type == "exchange_out" or "exchange" in description.lower() and "from" in description.lower()
        is_cold_storage = "cold" in description.lower() or "wallet" in description.lower()

        # Análisis según el contexto
        if is_exchange_in:
            if value_usd > 10000000:
                return f"⚠️ Massive {coin} moving to exchange. Potential sell-off or distribution."
            elif value_usd > 1000000:
                return f"🔴 Large {coin} deposit to exchange. Possible selling pressure."
            else:
                return f"📉 Moderate {coin} to exchange. Monitor for potential dump."

        elif is_exchange_out:
            if value_usd > 10000000:
                return f"🚀 Massive {coin} withdrawn from exchange. Strong accumulation signal."
            elif value_usd > 1000000:
                return f"📈 Large {coin} withdrawal. Likely whale accumulation."
            else:
                return f"📊 Moderate {coin} withdrawal. Could be cold storage transfer."

        elif is_cold_storage:
            return f"🏦 {coin} moved to cold storage. Long-term hodl signal."

        else:
            # Transferencia entre carteras (neutral)
            if value_usd > 10000000:
                return f"🔄 Massive {coin} transfer between wallets. Whale reallocation."
            elif value_usd > 1000000:
                return f"🔄 Large {coin} wallet-to-wallet transfer. Neutral."
            else:
                return f"🔄 Moderate {coin} transfer. Likely internal movement."

    except Exception as e:
        logger.error(f"Error in AI analysis: {e}")
        return None
