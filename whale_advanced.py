# whale_advanced.py - Versión con logs para depuración
import os
import requests
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")

def obtener_alertas_bitcoin(min_value_usd=50000, limit=3):
    logger.info("🔍 Buscando ballenas BTC...")
    try:
        url = "https://blockchain.info/unconfirmed-transactions?format=json"
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            logger.error(f"Blockchain.com error: {response.status_code}")
            return []
        
        data = response.json()
        txs = data.get("txs", [])
        if not txs:
            logger.warning("No hay transacciones no confirmadas")
            return []
        
        btc_usd_price = 60000  # fallback
        try:
            price_url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
            r = requests.get(price_url, timeout=5)
            if r.status_code == 200:
                btc_usd_price = r.json().get("bitcoin", {}).get("usd", 60000)
        except:
            pass
        
        large_txs = []
        for tx in txs[:50]:
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
        logger.info(f"✅ {len(large_txs)} ballenas BTC encontradas")
        return large_txs[:limit]
    except Exception as e:
        logger.error(f"Error en BTC: {e}")
        return []

def obtener_alertas_ethereum(min_value_usd=10000, limit=3):
    logger.info("🔍 Buscando ballenas ETH...")
    if not ETHERSCAN_API_KEY:
        logger.warning("Sin API key de Etherscan")
        return []
    
    try:
        eth_usd_price = 1800
        try:
            price_url = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"
            r = requests.get(price_url, timeout=5)
            if r.status_code == 200:
                eth_usd_price = r.json().get("ethereum", {}).get("usd", 1800)
        except:
            pass
        
        # Usar dirección de Binance Hot Wallet (más actividad)
        address = "0x28C6c06298d514Db089934071355E5743bf21d60"
        url = f"https://api.etherscan.io/api?module=account&action=txlist&address={address}&sort=desc&apikey={ETHERSCAN_API_KEY}"
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            logger.error(f"Etherscan error: {response.status_code}")
            return []
        
        data = response.json()
        if data.get("status") != "1":
            logger.warning(f"Etherscan no devolvió transacciones: {data.get('message')}")
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
        logger.info(f"✅ {len(large_txs)} ballenas ETH encontradas")
        return large_txs[:limit]
    except Exception as e:
        logger.error(f"Error en ETH: {e}")
        return []

def obtener_alertas_bsc(min_value_usd=5000, limit=3):
    logger.info("🔍 Buscando ballenas BSC...")
    if not ETHERSCAN_API_KEY:
        logger.warning("Sin API key de BSC (usa Etherscan)")
        return []
    
    try:
        bnb_usd_price = 600
        try:
            price_url = "https://api.coingecko.com/api/v3/simple/price?ids=binancecoin&vs_currencies=usd"
            r = requests.get(price_url, timeout=5)
            if r.status_code == 200:
                bnb_usd_price = r.json().get("binancecoin", {}).get("usd", 600)
        except:
            pass
        
        # Usar dirección de Binance Hot Wallet en BSC
        address = "0x8894E0a0c962CB723c1976a4421c95949bE2D4E3"
        url = f"https://api.bscscan.com/api?module=account&action=txlist&address={address}&sort=desc&apikey={ETHERSCAN_API_KEY}"
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            logger.error(f"BSCScan error: {response.status_code}")
            return []
        
        data = response.json()
        if data.get("status") != "1":
            logger.warning(f"BSCScan no devolvió transacciones: {data.get('message')}")
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
        logger.info(f"✅ {len(large_txs)} ballenas BSC encontradas")
        return large_txs[:limit]
    except Exception as e:
        logger.error(f"Error en BSC: {e}")
        return []

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
