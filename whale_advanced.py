# whale_advanced.py - Datos reales de ballenas (BTC, ETH, SOL, MATIC, ARB)
import os
import requests
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ==================== CONFIGURACIÓN ====================
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")

ETHERSCAN_API_URL = "https://api.etherscan.io/api"
POLYGONSCAN_API_URL = "https://api.polygonscan.com/api"
ARBISCAN_API_URL = "https://api.arbiscan.io/api"
HELIUS_API_URL = "https://api.helius.xyz/v0"
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
                tx_type = "transfer"
                description = f"BTC transaction of {total_btc:.2f} BTC"
                for out in tx.get("out", []):
                    addr = out.get("addr", "").lower()
                    if any(exchange in addr for exchange in ["binance", "coinbase", "kraken", "bitfinex"]):
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

# ==================== ETHEREUM (Etherscan) ====================
def obtener_alertas_ethereum(min_value_usd=10000, limit=3):
    if not ETHERSCAN_API_KEY:
        logger.warning("Etherscan API key missing. ETH whale data unavailable.")
        return []

    try:
        eth_usd_price = _get_eth_usd_price()
        if not eth_usd_price:
            eth_usd_price = 1800

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
                if any(exchange in to_addr for exchange in ["binance", "coinbase", "kraken"]):
                    tx_type = "exchange_in"
                    description = f"ETH moving to exchange: {eth_amount:.2f} ETH"
                elif "0x0000000000000000000000000000000000000000" in to_addr:
                    tx_type = "burn"
                    description = f"ETH burned: {eth_amount:.2f} ETH"
                if any(exchange in from_addr for exchange in ["binance", "coinbase", "kraken"]):
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

# ==================== SOLANA (Helius) ====================
def obtener_alertas_solana(min_value_usd=10000, limit=3):
    if not HELIUS_API_KEY:
        logger.warning("Helius API key missing. SOL whale data unavailable.")
        return []

    try:
        sol_usd_price = _get_sol_usd_price()
        if not sol_usd_price:
            sol_usd_price = 70

        # Usar endpoint de transacciones grandes de Helius
        url = f"{HELIUS_API_URL}/transactions?api-key={HELIUS_API_KEY}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if not data:
            logger.warning("No transactions found on Helius")
            return []

        large_txs = []
        for tx in data[:30]:
            # Parsear transacción de Solana
            sol_amount = tx.get("amount", 0) / 10**9  # SOL tiene 9 decimales
            value_usd = sol_amount * sol_usd_price
            if value_usd >= min_value_usd:
                tx_type = "transfer"
                description = f"SOL transaction of {sol_amount:.2f} SOL"
                # Identificar si es exchange (simplificado)
                if "exchange" in tx.get("description", "").lower():
                    tx_type = "exchange_out"
                    description = f"SOL moving to exchange: {sol_amount:.2f} SOL"
                large_txs.append({
                    "amount": sol_amount,
                    "amount_usd": value_usd,
                    "symbol": "SOL",
                    "transaction_type": tx_type,
                    "description": description,
                    "hash": tx.get("signature", ""),
                    "from": tx.get("source", "unknown"),
                    "to": tx.get("destination", "unknown"),
                    "timestamp": datetime.now().isoformat()
                })

        large_txs.sort(key=lambda x: x["amount_usd"], reverse=True)
        return large_txs[:limit]
    except Exception as e:
        logger.error(f"Error in Helius SOL: {e}")
        return []

def _get_sol_usd_price():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return r.json().get("solana", {}).get("usd")
    except:
        pass
    return None

# ==================== POLYGON (PolygonScan - V2) ====================
def obtener_alertas_polygon(min_value_usd=5000, limit=3):
    if not ETHERSCAN_API_KEY:
        logger.warning("Etherscan API key missing. MATIC whale data unavailable.")
        return []

    try:
        matic_usd_price = _get_matic_usd_price()
        if not matic_usd_price:
            matic_usd_price = 0.40

        address = "0x1a2a1c938ce3ec39b6d47113c7955baa9dd454f2"  # Binance Hot Wallet en Polygon
        url = f"{POLYGONSCAN_API_URL}?module=account&action=txlist&address={address}&sort=desc&apikey={ETHERSCAN_API_KEY}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "1":
            logger.warning(f"PolygonScan returned no transactions: {data.get('message')}")
            return []

        txs = data.get("result", [])
        large_txs = []
        for tx in txs[:30]:
            value_wei = int(tx.get("value", 0))
            if value_wei == 0:
                continue
            matic_amount = value_wei / 10**18
            value_usd = matic_amount * matic_usd_price
            if value_usd >= min_value_usd:
                from_addr = tx.get("from", "").lower()
                to_addr = tx.get("to", "").lower()
                tx_type = "transfer"
                description = f"MATIC transaction of {matic_amount:.2f} MATIC"
                if any(exchange in to_addr for exchange in ["binance", "coinbase"]):
                    tx_type = "exchange_in"
                    description = f"MATIC moving to exchange: {matic_amount:.2f} MATIC"
                large_txs.append({
                    "amount": matic_amount,
                    "amount_usd": value_usd,
                    "symbol": "MATIC",
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
        logger.error(f"Error in PolygonScan MATIC: {e}")
        return []

def _get_matic_usd_price():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=matic-network&vs_currencies=usd"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return r.json().get("matic-network", {}).get("usd")
    except:
        pass
    return None

# ==================== ARBITRUM (Arbiscan - V2) ====================
def obtener_alertas_arbitrum(min_value_usd=5000, limit=3):
    if not ETHERSCAN_API_KEY:
        logger.warning("Etherscan API key missing. ARB whale data unavailable.")
        return []

    try:
        arb_usd_price = _get_arb_usd_price()
        if not arb_usd_price:
            arb_usd_price = 0.60

        address = "0x1a2a1c938ce3ec39b6d47113c7955baa9dd454f2"  # Binance Hot Wallet en Arbitrum
        url = f"{ARBISCAN_API_URL}?module=account&action=txlist&address={address}&sort=desc&apikey={ETHERSCAN_API_KEY}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "1":
            logger.warning(f"Arbiscan returned no transactions: {data.get('message')}")
            return []

        txs = data.get("result", [])
        large_txs = []
        for tx in txs[:30]:
            value_wei = int(tx.get("value", 0))
            if value_wei == 0:
                continue
            arb_amount = value_wei / 10**18
            value_usd = arb_amount * arb_usd_price
            if value_usd >= min_value_usd:
                from_addr = tx.get("from", "").lower()
                to_addr = tx.get("to", "").lower()
                tx_type = "transfer"
                description = f"ARB transaction of {arb_amount:.2f} ARB"
                if any(exchange in to_addr for exchange in ["binance", "coinbase"]):
                    tx_type = "exchange_in"
                    description = f"ARB moving to exchange: {arb_amount:.2f} ARB"
                large_txs.append({
                    "amount": arb_amount,
                    "amount_usd": value_usd,
                    "symbol": "ARB",
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
        logger.error(f"Error in Arbiscan ARB: {e}")
        return []

def _get_arb_usd_price():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=arbitrum&vs_currencies=usd"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return r.json().get("arbitrum", {}).get("usd")
    except:
        pass
    return None

# ==================== FUNCIONES DE ANÁLISIS ====================
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
    try:
        coin = alert.get("symbol", "BTC")
        amount = alert.get("amount", 0)
        value_usd = alert.get("amount_usd", 0)
        tx_type = alert.get("transaction_type", "transfer")
        description = alert.get("description", "")

        is_exchange_in = tx_type == "exchange_in" or "exchange" in description.lower() and "to" in description.lower()
        is_exchange_out = tx_type == "exchange_out" or "exchange" in description.lower() and "from" in description.lower()

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

        else:
            if value_usd > 10000000:
                return f"🔄 Massive {coin} transfer between wallets. Whale reallocation."
            elif value_usd > 1000000:
                return f"🔄 Large {coin} wallet-to-wallet transfer. Neutral."
            else:
                return f"🔄 Moderate {coin} transfer. Likely internal movement."

    except Exception as e:
        logger.error(f"Error in AI analysis: {e}")
        return None
