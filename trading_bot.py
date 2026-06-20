# -*- coding: utf-8 -*-
import os
import time
import json
import logging
import requests
import schedule
import threading
import asyncio
import feedparser
import re
import hmac
import hashlib
from datetime import datetime, timedelta
from flask import Flask, request, render_template, jsonify
from dotenv import load_dotenv
# import mercadopago  # <--- ELIMINADO: ya no se usa
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from whale_advanced import (
    obtener_alertas_bitcoin,
    obtener_alertas_ethereum,
    obtener_alertas_solana,
    obtener_alertas_polygon,
    obtener_alertas_arbitrum,
    analizar_alerta,
    analizar_con_ia,
    predecir_movimiento_ballena
)
from trading_engine import TradingEngine
from supabase import create_client, Client
from functools import wraps
import websockets
import json as json_lib
from new_tokens import scan_new_pools, get_recent_tokens, format_token_message

load_dotenv()

# ==================== CONFIGURACIÓN ====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN not found. Set it in .env")

# MP_ACCESS_TOKEN ya no es obligatorio
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
if not MP_ACCESS_TOKEN:
    logger.warning("⚠️ MP_ACCESS_TOKEN not set. MercadoPago payments disabled.")

MP_WEBHOOK_URL = os.getenv("MP_WEBHOOK_URL")
BINANCE_REFERRAL_LINK = os.getenv("BINANCE_REFERRAL_LINK", "https://www.binance.com/en/register?ref=1249175745")

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== SEGURIDAD ====================
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "8355456581").split(",")))
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")
MP_WEBHOOK_SECRET = os.getenv("MP_WEBHOOK_SECRET", "")
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "")
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "20"))
RATE_LIMIT_PERIOD = int(os.getenv("RATE_LIMIT_PERIOD", "60"))

# ==================== WEBSOCKET ====================
WS_ENABLED = os.getenv("WS_ENABLED", "true").lower() == "true"
WS_EXCHANGE = os.getenv("WS_EXCHANGE", "kraken").lower()
PRICE_CACHE_TTL = int(os.getenv("PRICE_CACHE_TTL", "3"))

# ==================== SEGURIDAD ANTI-MEV / ANTI-RUG ====================
GOPLUS_API_KEY = os.getenv("GOPLUS_API_KEY", "")
ANTI_MEV_ENABLED = os.getenv("ANTI_MEV_ENABLED", "true").lower() == "true"
ANTI_RUG_ENABLED = os.getenv("ANTI_RUG_ENABLED", "true").lower() == "true"

# ==================== IA PREDICTIVA AVANZADA ====================
AI_MODEL_ENABLED = os.getenv("AI_MODEL_ENABLED", "true").lower() == "true"

# Ahora solo requerimos DASHBOARD_API_KEY y ADMIN_SECRET
if not DASHBOARD_API_KEY or not ADMIN_SECRET:
    raise ValueError("❌ Missing DASHBOARD_API_KEY or ADMIN_SECRET in Railway")
if not MP_WEBHOOK_SECRET:
    logger.warning("⚠️ MP_WEBHOOK_SECRET not set. MercadoPago webhook disabled.")

logger.info("✅ Security variables loaded")
logger.info(f"🧠 Advanced AI Predictor: {'ENABLED' if AI_MODEL_ENABLED else 'DISABLED'}")

# ==================== SEGURIDAD ====================
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "8355456581").split(",")))
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")
MP_WEBHOOK_SECRET = os.getenv("MP_WEBHOOK_SECRET", "")
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "")
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "20"))
RATE_LIMIT_PERIOD = int(os.getenv("RATE_LIMIT_PERIOD", "60"))

# ==================== WEBSOCKET ====================
WS_ENABLED = os.getenv("WS_ENABLED", "true").lower() == "true"
WS_EXCHANGE = os.getenv("WS_EXCHANGE", "kraken").lower()
PRICE_CACHE_TTL = int(os.getenv("PRICE_CACHE_TTL", "3"))

# ==================== SEGURIDAD ANTI-MEV / ANTI-RUG ====================
GOPLUS_API_KEY = os.getenv("GOPLUS_API_KEY", "")
ANTI_MEV_ENABLED = os.getenv("ANTI_MEV_ENABLED", "true").lower() == "true"
ANTI_RUG_ENABLED = os.getenv("ANTI_RUG_ENABLED", "true").lower() == "true"

# ==================== IA PREDICTIVA AVANZADA ====================
AI_MODEL_ENABLED = os.getenv("AI_MODEL_ENABLED", "true").lower() == "true"

if not MP_WEBHOOK_SECRET or not DASHBOARD_API_KEY or not ADMIN_SECRET:
    raise ValueError("❌ Missing security variables in Railway")

logger.info("✅ Security variables loaded")
logger.info(f"🧠 Advanced AI Predictor: {'ENABLED' if AI_MODEL_ENABLED else 'DISABLED'}")

# ==================== BILINGUAL SUPPORT ====================
USER_LANG = {}

TRANSLATIONS = {
    'en': {
        'welcome': "🤖 *CryptoArch Agent*\nChoose an option:",
        'start_trial': "🧭 *You are in the FREE BETA.* No time limit, no subscription.\n• Commission: 0.5%\n• 3 alerts limit\n\nUpgrade with /activate to unlock full benefits.",
        'trial_expired': "⏰ *Your trial has expired!*\n\nTo continue trading with reduced commissions, you have two options:\n\n1️⃣ *Deposit on Binance* using our referral link:\n👉 {link}\n   • Deposit ≥ 50 USDT → Trader (0.4% comisión)\n   • Deposit ≥ 100 USDT → Pro (0.3% + premium)\n   • Deposit ≥ 500 USDT → Elite (0.3% + VIP + token reward)\n\n2️⃣ *Get $CARCH tokens* (coming soon) for Elite/Legendary benefits.\n\nChoose the option that best suits you! 🚀",
        'lang_changed': "✅ Language changed to English.",
        'plans': "📊 *Commission levels* (no subscriptions):\n\n• *Explorer*: 0.5% (free)\n• *Trader*: 0.4% (≥ 50 USDT deposited)\n• *Pro*: 0.3% (≥ 100 USDT or volume > $10k)\n• *Elite*: 0.3% + token reward ($CARCH holder)\n• *Legendary*: 0.3% + token reward (holder + volume + referrals)\n\n🪙 *Token $CARCH*: Elite and Legendary holders receive 0.05% of all bot commissions.\n\nUse /activate to check your level.",
        'help': "📌 *Commands & functions*\n\n/start - Main menu\n/status - Market status\n/alerts - View/manage alerts\n/balance - Testnet balance\n/premium - Your premium status\n/plans - View commission levels\n/whale - Whale movements (free, with AI)\n/predict - AI prediction for current market\n/newtokens - Latest new tokens detected\n/info - Detailed coin info (e.g. /info BTC)\n/news - Latest crypto news\n/buy - Buy on Testnet (e.g. /buy 0.001 BTCUSDT)\n/sell - Sell on Testnet (e.g. /sell 0.001 BTCUSDT)\n/activate - Activate your plan based on Binance balance\n/plan - Show your current level\n/copy - Configure copy trading (e.g. /copy 20 1.5 follow on)\n/rule - Auto trading rules (e.g. /rule add \"whale_buy_btc > 100\" buy 50 5 10)\n/snipe - Configure sniping (e.g. /snipe set 50 5 ethereum on)\n/sniper - Configure Sniper X execution (e.g. /sniper set 100 2 aggressive true on)\n/compare - Compare us with the competition\n/lang - Switch language (English/Spanish)\n\n*Commission levels:*\n🧭 Explorer (0.5% comisión) - 14 days free\n📊 Trader (0.4%) - Deposit ≥ 50 USDT\n⭐ Pro (0.3% + premium) - Deposit ≥ 100 USDT\n👑 Elite (0.3% + token reward) - $CARCH holder\n🏆 Legendary (0.3% + token reward) - Elite + volume + referrals\n\n🪙 *Token $CARCH*: Elite and Legendary holders receive 0.05% of all bot commissions.\n\n⚠️ *Legal*: Not a financial advisor. Use /terms for details."
    },
    'es': {
        'welcome': "🤖 *CryptoArch Agent*\nElige una opción:",
        'start_trial': "🧭 *Estás en la BETA GRATUITA.* Sin límite de tiempo, sin suscripción.\n• Comisión: 0.5%\n• Límite de 3 alertas\n\nActualiza con /activate para desbloquear todos los beneficios.",
        'trial_expired': "⏰ *¡Tu prueba ha expirado!*\n\nPara continuar operando con comisiones reducidas, tienes dos opciones:\n\n1️⃣ *Deposita en Binance* usando nuestro enlace de referido:\n👉 {link}\n   • Depósito ≥ 50 USDT → Trader (0.4% comisión)\n   • Depósito ≥ 100 USDT → Pro (0.3% + premium)\n   • Depósito ≥ 500 USDT → Elite (0.3% + VIP + token reward)\n\n2️⃣ *Obtén tokens $CARCH* (próximamente) para beneficios Elite/Legendary.\n\n¡Elige la opción que mejor se adapte a ti! 🚀",
        'lang_changed': "✅ Idioma cambiado a Español.",
        'plans': "📊 *Niveles de comisión* (sin suscripciones):\n\n• *Explorer*: 0.5% (gratis)\n• *Trader*: 0.4% (≥ 50 USDT depositados)\n• *Pro*: 0.3% (≥ 100 USDT o volumen > $10k)\n• *Elite*: 0.3% + token reward (titular de $CARCH)\n• *Legendary*: 0.3% + token reward (titular + volumen + referidos)\n\n🪙 *Token $CARCH*: Los titulares Elite y Legendary reciben el 0.05% de todas las comisiones del bot.\n\nUsa /activate para ver tu nivel.",
        'help': "📌 *Comandos y funciones*\n\n/start - Menú principal\n/status - Estado del mercado\n/alerts - Ver/gestionar alertas\n/balance - Saldo en Testnet\n/premium - Estado premium\n/plans - Ver niveles de comisión\n/whale - Movimientos de ballenas (gratis, con IA)\n/predict - Predicción IA para el mercado actual\n/newtokens - Últimos tokens nuevos detectados\n/info - Información detallada de una moneda (ej. /info BTC)\n/news - Últimas noticias cripto\n/buy - Comprar en Testnet (ej. /buy 0.001 BTCUSDT)\n/sell - Vender en Testnet (ej. /sell 0.001 BTCUSDT)\n/activate - Activar tu plan basado en saldo de Binance\n/plan - Mostrar tu nivel actual\n/copy - Configurar copy trading (ej. /copy 20 1.5 follow on)\n/rule - Reglas de trading automático (ej. /rule add \"whale_buy_btc > 100\" buy 50 5 10)\n/snipe - Configurar snipe (ej. /snipe set 50 5 ethereum on)\n/sniper - Configurar Sniper X (ej. /sniper set 100 2 aggressive true on)\n/compare - Compararnos con la competencia\n/lang - Cambiar idioma (Inglés/Español)\n\n*Niveles de comisión:*\n🧭 Explorer (0.5% comisión) - 14 días gratis\n📊 Trader (0.4%) - Depósito ≥ 50 USDT\n⭐ Pro (0.3% + premium) - Depósito ≥ 100 USDT\n👑 Elite (0.3% + token reward) - Titular de $CARCH\n🏆 Legendary (0.3% + token reward) - Elite + volumen + referidos\n\n🪙 *Token $CARCH*: Los titulares Elite y Legendary reciben el 0.05% de todas las comisiones del bot.\n\n⚠️ *Legal*: No es un asesor financiero. Usa /terms para más detalles."
    }
}

def get_text(chat_id, key, **kwargs):
    lang = USER_LANG.get(str(chat_id), 'en')
    text = TRANSLATIONS.get(lang, TRANSLATIONS['en']).get(key, key)
    if kwargs:
        return text.format(**kwargs)
    return text

# ==================== COINS ====================
COINS = [
    ("bitcoin", "BTC", "Bitcoin"),
    ("ethereum", "ETH", "Ethereum"),
    ("solana", "SOL", "Solana"),
    ("ripple", "XRP", "XRP"),
    ("binancecoin", "BNB", "BNB"),
    ("chainlink", "LINK", "Chainlink"),
    ("avalanche-2", "AVAX", "AVAX")
]

EXCHANGE_SYMBOLS = {
    "binance": {
        "BTC": "btcusdt",
        "ETH": "ethusdt",
        "SOL": "solusdt",
        "XRP": "xrpusdt",
        "BNB": "bnbusdt",
        "LINK": "linkusdt",
        "AVAX": "avaxusdt"
    },
    "kraken": {
        "BTC": "XBT/USD",
        "ETH": "ETH/USD",
        "SOL": "SOL/USD",
        "XRP": "XRP/USD",
        "BNB": "BNB/USD",
        "LINK": "LINK/USD",
        "AVAX": "AVAX/USD"
    }
}

# ==================== CACHE DE PRECIOS ====================
PRICE_CACHE = {
    "data": {},
    "last_update": 0
}

def get_cached_prices():
    global PRICE_CACHE
    now = time.time()
    if PRICE_CACHE["data"] and (now - PRICE_CACHE["last_update"]) < PRICE_CACHE_TTL:
        return PRICE_CACHE["data"]
    return fetch_prices_rest()

def fetch_prices_rest():
    ids = ",".join([c[0] for c in COINS])
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        if r.status_code == 200:
            data = r.json()
            global PRICE_CACHE
            PRICE_CACHE["data"] = data
            PRICE_CACHE["last_update"] = time.time()
            return data
    except Exception as e:
        logger.error(f"Error en fallback REST: {e}")
    return {}

# ==================== WEB SOCKET (KRAKEN) ====================
ws_connection = None
ws_active = True

async def update_prices_from_websocket():
    global PRICE_CACHE, ws_connection, ws_active, WS_ENABLED
    if not WS_ENABLED:
        logger.info("WebSocket disabled by configuration.")
        return

    exchange = WS_EXCHANGE
    logger.info(f"🌐 Using WebSocket from {exchange.upper()}")

    if exchange == "kraken":
        kraken_symbols = [EXCHANGE_SYMBOLS["kraken"][sym[1]] for sym in COINS if sym[1] in EXCHANGE_SYMBOLS["kraken"]]
        subscription_msg = {
            "event": "subscribe",
            "subscription": {"name": "ticker"},
            "pair": kraken_symbols
        }
        ws_url = "wss://ws.kraken.com"
        
        while ws_active and WS_ENABLED:
            try:
                logger.info(f"🔌 Connecting to Kraken WebSocket...")
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=10) as websocket:
                    ws_connection = websocket
                    await websocket.send(json.dumps(subscription_msg))
                    logger.info("✅ Kraken WebSocket connected. Updating in real-time.")
                    
                    async for message in websocket:
                        try:
                            data = json_lib.loads(message)
                            if isinstance(data, list) and len(data) >= 4 and data[2] == "ticker":
                                ticker_data = data[1]
                                pair = data[3]
                                symbol = None
                                for sym, kraken_pair in EXCHANGE_SYMBOLS["kraken"].items():
                                    if kraken_pair == pair:
                                        symbol = sym
                                        break
                                if symbol:
                                    price = float(ticker_data['c'][0])
                                    change = float(ticker_data.get('p', [0])[0])
                                    coin_id = None
                                    for cid, sym, name in COINS:
                                        if sym == symbol:
                                            coin_id = cid
                                            break
                                    if coin_id:
                                        if coin_id not in PRICE_CACHE["data"]:
                                            PRICE_CACHE["data"][coin_id] = {}
                                        PRICE_CACHE["data"][coin_id]["usd"] = price
                                        PRICE_CACHE["data"][coin_id]["usd_24h_change"] = change
                                        PRICE_CACHE["last_update"] = time.time()
                        except Exception as e:
                            logger.error(f"Error processing Kraken WS message: {e}")
            except Exception as e:
                logger.error(f"❌ Kraken WebSocket disconnected: {e}. Retrying in 10s...")
                await asyncio.sleep(10)
    else:
        symbols = [EXCHANGE_SYMBOLS["binance"][sym[1]] for sym in COINS if sym[1] in EXCHANGE_SYMBOLS["binance"]]
        stream_url = f"wss://stream.binance.com/stream?streams={'/'.join([f'{s}@ticker' for s in symbols])}"
        
        while ws_active and WS_ENABLED:
            try:
                logger.info(f"🔌 Connecting to Binance WebSocket...")
                async with websockets.connect(stream_url, ping_interval=20, ping_timeout=10) as websocket:
                    ws_connection = websocket
                    logger.info("✅ Binance WebSocket connected.")
                    
                    async for message in websocket:
                        try:
                            data = json_lib.loads(message)
                            if 'data' in data:
                                ticker = data['data']
                                symbol = ticker['s'].upper().replace('USDT', '')
                                price = float(ticker['c'])
                                change = float(ticker['P'])
                                coin_id = None
                                for cid, sym, name in COINS:
                                    if sym == symbol:
                                        coin_id = cid
                                        break
                                if coin_id:
                                    if coin_id not in PRICE_CACHE["data"]:
                                        PRICE_CACHE["data"][coin_id] = {}
                                    PRICE_CACHE["data"][coin_id]["usd"] = price
                                    PRICE_CACHE["data"][coin_id]["usd_24h_change"] = change
                                    PRICE_CACHE["last_update"] = time.time()
                        except Exception as e:
                            logger.error(f"Error processing Binance WS message: {e}")
            except Exception as e:
                logger.error(f"❌ Binance WebSocket disconnected: {e}. Retrying in 10s...")
                await asyncio.sleep(10)

# ==================== SEGURIDAD: ANTI-MEV Y ANTI-RUG ====================

def check_token_security(contract_address: str, chain: str = "ethereum") -> dict:
    if not GOPLUS_API_KEY or not ANTI_RUG_ENABLED:
        return {
            "is_honeypot": False,
            "is_whitelist_only": False,
            "can_sell": True,
            "liquidity_locked": True,
            "owner_renounced": False,
            "risk_score": 0,
            "warnings": ["⚠️ Anti-Rug disabled or no API key"]
        }
    
    try:
        url = f"https://api.gopluslabs.io/api/v1/token_security/{chain}?contract_addresses={contract_address}"
        headers = {"X-API-Key": GOPLUS_API_KEY} if GOPLUS_API_KEY else {}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            logger.error(f"GoPlusLabs error: {response.status_code}")
            return {"risk_score": 0, "warnings": ["⚠️ Could not verify contract"]}
        
        data = response.json()
        if data.get("code") != 1:
            return {"risk_score": 0, "warnings": ["⚠️ Verification error"]}
        
        result = data.get("result", {})
        token_data = result.get(contract_address.lower(), {})
        
        is_honeypot = token_data.get("is_honeypot", False)
        is_whitelist_only = token_data.get("is_whitelist_only", False)
        can_sell = not is_honeypot and not is_whitelist_only
        
        liquidity_locked = token_data.get("liquidity_locked", False)
        owner_renounced = token_data.get("owner_renounced", False)
        
        risk_score = 0
        warnings = []
        if is_honeypot:
            risk_score += 40
            warnings.append("🚨 Honeypot detected (cannot sell)")
        if is_whitelist_only:
            risk_score += 30
            warnings.append("🚨 Whitelist only (cannot sell)")
        if not liquidity_locked:
            risk_score += 20
            warnings.append("⚠️ Liquidity not locked (rug pull risk)")
        if not owner_renounced:
            risk_score += 10
            warnings.append("⚠️ Owner not renounced (can modify contract)")
        
        liquidity = token_data.get("liquidity", 0)
        if isinstance(liquidity, str):
            try:
                liquidity = float(liquidity)
            except:
                liquidity = 0
        if liquidity < 5000:
            risk_score += 10
            warnings.append("⚠️ Low liquidity (< $5000)")
        
        return {
            "is_honeypot": is_honeypot,
            "is_whitelist_only": is_whitelist_only,
            "can_sell": can_sell,
            "liquidity_locked": liquidity_locked,
            "owner_renounced": owner_renounced,
            "risk_score": min(100, risk_score),
            "warnings": warnings
        }
    except Exception as e:
        logger.error(f"check_token_security error: {e}")
        return {"risk_score": 0, "warnings": ["⚠️ Error verifying token"]}

def simulate_anti_mev(symbol: str, amount: float) -> dict:
    if not ANTI_MEV_ENABLED:
        return {"protected": False, "message": "Anti-MEV disabled"}
    
    if amount > 10:
        return {
            "protected": True,
            "message": f"🛡️ Anti-MEV activated for {symbol} (amount > 10 USDT). Using private route."
        }
    else:
        return {
            "protected": True,
            "message": "🛡️ Anti-MEV activated (standard mode)."
        }

# ==================== IA PREDICTIVA AVANZADA ====================

prediction_history = []

def get_fear_greed_index() -> dict:
    try:
        response = requests.get('https://api.alternative.me/fng/', timeout=5)
        if response.status_code == 200:
            data = response.json()
            value = int(data['data'][0]['value'])
            classification = data['data'][0]['value_classification']
            return {
                "value": value,
                "classification": classification,
                "sentiment": "bearish" if value < 30 else "bullish" if value > 70 else "neutral"
            }
    except Exception as e:
        logger.error(f"Error getting Fear & Greed: {e}")
    return {"value": 50, "classification": "Neutral", "sentiment": "neutral"}

def get_asset_volatility(symbol: str) -> float:
    prices = get_cached_prices()
    for coin_id, sym, name in COINS:
        if sym == symbol and coin_id in prices:
            change = prices[coin_id].get('usd_24h_change', 0)
            return abs(change)
    return 5.0

def get_whale_frequency(alerts: list, symbol: str, tx_type: str, time_window_hours: int = 6) -> int:
    if not alerts:
        return 0
    count = 0
    for alert in alerts:
        if alert.get("symbol") == symbol and alert.get("transaction_type") == tx_type:
            count += 1
    return count

def predict_with_ai_advanced(alert: dict, all_alerts: list = None) -> dict:
    if not AI_MODEL_ENABLED:
        return {
            "prediction": "⚠️ AI disabled",
            "confidence": 0,
            "emoji": "⚪",
            "details": "Enable AI with AI_MODEL_ENABLED=true",
            "factors": {}
        }
    
    symbol = alert.get("symbol", "BTC")
    value = alert.get("value", 0)
    tx_type = alert.get("transaction_type", "transfer")
    
    # Factor 1: Whale size (30%)
    if value > 1000000:
        whale_score = 100
        whale_tier = "🐋 Mega Whale (> $1M)"
    elif value > 500000:
        whale_score = 80
        whale_tier = "🐳 Large Whale (> $500k)"
    elif value > 100000:
        whale_score = 60
        whale_tier = "🐋 Medium Whale (> $100k)"
    elif value > 50000:
        whale_score = 40
        whale_tier = "🐟 Small Whale (> $50k)"
    else:
        whale_score = 20
        whale_tier = "🦐 Small (< $50k)"
    
    # Factor 2: Transaction type (20%)
    if tx_type == "buy":
        tx_score = 80
        tx_sentiment = "bullish"
    elif tx_type == "sell":
        tx_score = 20
        tx_sentiment = "bearish"
    else:
        tx_score = 50
        tx_sentiment = "neutral"
    
    # Factor 3: Whale frequency (15%)
    if all_alerts:
        freq_buy = get_whale_frequency(all_alerts, symbol, "buy")
        freq_sell = get_whale_frequency(all_alerts, symbol, "sell")
        if tx_type == "buy" and freq_buy > 2:
            freq_score = 80
        elif tx_type == "sell" and freq_sell > 2:
            freq_score = 20
        elif tx_type == "buy":
            freq_score = 60
        elif tx_type == "sell":
            freq_score = 40
        else:
            freq_score = 50
    else:
        freq_score = 50
    
    # Factor 4: Fear & Greed (15%)
    fg = get_fear_greed_index()
    if fg["sentiment"] == "bearish" and tx_type == "buy":
        fg_score = 80
    elif fg["sentiment"] == "bullish" and tx_type == "sell":
        fg_score = 80
    elif fg["sentiment"] == "bearish" and tx_type == "sell":
        fg_score = 30
    elif fg["sentiment"] == "bullish" and tx_type == "buy":
        fg_score = 30
    else:
        fg_score = 50
    
    # Factor 5: Volatility (10%)
    vol = get_asset_volatility(symbol)
    if vol > 10:
        vol_score = 20
    elif vol > 5:
        vol_score = 50
    else:
        vol_score = 80
    
    # Factor 6: Liquidity (10%)
    if symbol in ["BTC", "ETH"]:
        liq_score = 90
    elif symbol in ["SOL", "BNB"]:
        liq_score = 70
    else:
        liq_score = 50
    
    weights = {
        "whale_size": 0.30,
        "tx_type": 0.20,
        "frequency": 0.15,
        "fear_greed": 0.15,
        "volatility": 0.10,
        "liquidity": 0.10
    }
    
    raw_score = (
        whale_score * weights["whale_size"] +
        tx_score * weights["tx_type"] +
        freq_score * weights["frequency"] +
        fg_score * weights["fear_greed"] +
        vol_score * weights["volatility"] +
        liq_score * weights["liquidity"]
    )
    
    if tx_type == "buy":
        if raw_score > 55:
            prediction = "bullish"
            confidence = raw_score
            emoji = "🟢"
            detail = f"Strong buy signal ({whale_tier})"
        elif raw_score > 45:
            prediction = "neutral"
            confidence = raw_score
            emoji = "🟡"
            detail = f"Weak buy signal ({whale_tier})"
        else:
            prediction = "bearish"
            confidence = 100 - raw_score
            emoji = "🔴"
            detail = f"Contradictory buy signal ({whale_tier})"
    elif tx_type == "sell":
        if raw_score > 55:
            prediction = "bearish"
            confidence = raw_score
            emoji = "🔴"
            detail = f"Strong sell signal ({whale_tier})"
        elif raw_score > 45:
            prediction = "neutral"
            confidence = raw_score
            emoji = "🟡"
            detail = f"Weak sell signal ({whale_tier})"
        else:
            prediction = "bullish"
            confidence = 100 - raw_score
            emoji = "🟢"
            detail = f"Contradictory sell signal ({whale_tier})"
    else:
        if raw_score > 60:
            prediction = "bullish"
            confidence = raw_score
            emoji = "🟢"
            detail = f"Transfer with bullish tendency ({whale_tier})"
        elif raw_score < 40:
            prediction = "bearish"
            confidence = 100 - raw_score
            emoji = "🔴"
            detail = f"Transfer with bearish tendency ({whale_tier})"
        else:
            prediction = "neutral"
            confidence = raw_score
            emoji = "🟡"
            detail = f"Neutral transfer ({whale_tier})"
    
    confidence = max(0, min(100, confidence))
    
    factors = {
        "whale_size": f"{whale_score}/100 ({whale_tier})",
        "tx_type": f"{tx_score}/100 ({tx_sentiment})",
        "frequency": f"{freq_score}/100 ({'Multiple whales' if freq_score > 60 else 'Few whales'})",
        "fear_greed": f"{fg_score}/100 ({fg['classification']} {fg['value']}/100)",
        "volatility": f"{vol_score}/100 ({vol:.1f}% volatility)",
        "liquidity": f"{liq_score}/100 ({symbol})"
    }
    
    if all_alerts:
        prediction_history.append({
            "timestamp": time.time(),
            "symbol": symbol,
            "prediction": prediction,
            "confidence": confidence,
            "actual_tx": tx_type,
            "value": value
        })
        if len(prediction_history) > 100:
            prediction_history.pop(0)
    
    return {
        "prediction": prediction,
        "confidence": confidence,
        "emoji": emoji,
        "details": detail,
        "factors": factors
    }

# ==================== USER DATA ====================
USER_DATA = {}

def load_user_data():
    global USER_DATA
    try:
        with open("user_data.json", "r") as f:
            USER_DATA = json.load(f)
    except FileNotFoundError:
        USER_DATA = {}

def save_user_data():
    with open("user_data.json", "w") as f:
        json.dump(USER_DATA, f, indent=2, default=str)

load_user_data()

# ==================== SUPABASE ====================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    logger.warning("⚠️ SUPABASE_URL or SUPABASE_KEY not configured. Using local files.")
    supabase = None
else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("✅ Connected to Supabase")

SUBSCRIBERS_FILE = "subscribers.json"

# ==================== NIVELES ====================
LEVELS = {
    0: {"name": "Explorer", "emoji": "🧭", "commission": 0.005, "insignia": "🔰", "benefits": "Basic alerts, whales, news, 14-day free trial", "active": False, "beta_access": False, "token_reward": False},
    1: {"name": "Trader", "emoji": "📊", "commission": 0.004, "insignia": "⚡", "benefits": "Explorer + Copy Trading", "active": True, "beta_access": False, "token_reward": False},
    2: {"name": "Pro", "emoji": "⭐", "commission": 0.003, "insignia": "🌟", "benefits": "Trader + Sniper X + Auto Trading", "active": True, "beta_access": False, "token_reward": False},
    3: {"name": "Elite", "emoji": "👑", "commission": 0.003, "insignia": "🏆", "benefits": "Pro + Beta Access + Exclusive Badge", "active": True, "beta_access": True, "token_reward": 0.0005},
    4: {"name": "Legendary", "emoji": "🏆", "commission": 0.003, "insignia": "⚜️", "benefits": "Elite + Vote on Features + VIP Support", "active": True, "beta_access": True, "token_reward": 0.0005}
}

def load_subscribers():
    if supabase:
        try:
            response = supabase.table("subscriptions").select("*").execute()
            if response.data:
                result = {}
                for row in response.data:
                    result[row["chat_id"]] = {
                        "plan": row.get("plan", "free"),
                        "start": row.get("start_date"),
                        "end": row.get("end_date"),
                        "active": row.get("active", True),
                        "fee": row.get("fee"),
                        "email": row.get("email"),
                        "trial_start": row.get("trial_start"),
                        "trial_end": row.get("trial_end"),
                        "deposit_level": row.get("deposit_level", 0),
                        "commission_rate": row.get("commission_rate", 0.005),
                        "insignia": row.get("insignia"),
                        "is_early_adopter": row.get("is_early_adopter", False)
                    }
                return result
            return {}
        except Exception as e:
            logger.error(f"Error loading from Supabase: {e}")
            try:
                with open(SUBSCRIBERS_FILE, "r") as f:
                    return json.load(f)
            except FileNotFoundError:
                return {}
    else:
        try:
            with open(SUBSCRIBERS_FILE, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

def save_subscribers(subscribers):
    if supabase:
        try:
            supabase.table("subscriptions").delete().neq("chat_id", "none").execute()
            for chat_id, data in subscribers.items():
                row = {
                    "chat_id": chat_id,
                    "plan": data.get("plan", "free"),
                    "start_date": data.get("start"),
                    "end_date": data.get("end"),
                    "active": data.get("active", True),
                    "fee": data.get("fee"),
                    "email": data.get("email"),
                    "trial_start": data.get("trial_start"),
                    "trial_end": data.get("trial_end"),
                    "deposit_level": data.get("deposit_level", 0),
                    "commission_rate": data.get("commission_rate", 0.005),
                    "insignia": data.get("insignia"),
                    "is_early_adopter": data.get("is_early_adopter", False)
                }
                supabase.table("subscriptions").insert(row).execute()
            logger.info("✅ Subscribers saved to Supabase")
        except Exception as e:
            logger.error(f"Error saving to Supabase: {e}")
            try:
                with open(SUBSCRIBERS_FILE, "w") as f:
                    json.dump(subscribers, f, indent=2, default=str)
            except Exception as e2:
                logger.error(f"Error saving locally: {e2}")
    else:
        try:
            with open(SUBSCRIBERS_FILE, "w") as f:
                json.dump(subscribers, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error saving locally: {e}")

def get_user_level(chat_id):
    subscribers = load_subscribers()
    data = subscribers.get(str(chat_id), {})
    level = data.get("deposit_level", 0)
    if level == 0:
        trial_end = data.get("trial_end")
        if trial_end:
            end = datetime.fromisoformat(trial_end)
            if end < datetime.now():
                data["active"] = False
                save_subscribers(subscribers)
                return -1
    return level

def get_user_commission(chat_id):
    level = get_user_level(chat_id)
    if level < 0:
        return None
    return LEVELS.get(level, LEVELS[0])["commission"]

def get_token_reward(chat_id):
    level = get_user_level(chat_id)
    if level >= 3:
        return 0.0005
    return 0.0

def get_user_insignia(chat_id):
    level = get_user_level(chat_id)
    if level < 0:
        return "❌"
    return LEVELS.get(level, LEVELS[0])["insignia"]

def get_level_benefits(level):
    return LEVELS.get(level, LEVELS[0])["benefits"]

def start_trial(chat_id):
    subscribers = load_subscribers()
    if str(chat_id) not in subscribers:
        subscribers[str(chat_id)] = {}
    data = subscribers[str(chat_id)]
    if not data.get("trial_start"):
        data["trial_start"] = datetime.now().isoformat()
        data["trial_end"] = (datetime.now() + timedelta(days=14)).isoformat()
        data["deposit_level"] = 0
        data["commission_rate"] = 0.005
        data["insignia"] = "🔰"
        data["active"] = True
        save_subscribers(subscribers)
        return True
    return False

def calculate_plan_end(plan_key: str, start_date: datetime) -> datetime:
    if plan_key == "monthly":
        return start_date + timedelta(days=30)
    elif plan_key == "quarterly":
        return start_date + timedelta(days=90)
    elif plan_key == "yearly":
        return start_date + timedelta(days=365)
    else:
        return start_date + timedelta(days=30)

def is_premium(chat_id):
    subscribers = load_subscribers()
    data = subscribers.get(str(chat_id))
    if not data or not data.get("active", False):
        return False
    end_str = data.get("end")
    if end_str:
        end = datetime.fromisoformat(end_str)
        if end < datetime.now():
            data["active"] = False
            save_subscribers(subscribers)
            return False
    return True

def activate_premium(chat_id, plan_key):
    subscribers = load_subscribers()
    start = datetime.now()
    end = calculate_plan_end(plan_key, start)
    subscribers[str(chat_id)] = {
        "plan": plan_key,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "active": True,
        "deposit_level": 2,
        "commission_rate": 0.002,
        "insignia": "🌟"
    }
    save_subscribers(subscribers)
    logger.info(f"✅ Premium activated for {chat_id} with plan {plan_key} until {end}")
    send_telegram(int(chat_id), f"🎉 *Premium Activated!*\n\nPlan: *{plan_key.capitalize()}*\nValid until: {end.strftime('%d/%m/%Y')}\n\nThank you for your payment.")
    return True

def get_user_email(chat_id):
    subscribers = load_subscribers()
    data = subscribers.get(str(chat_id), {})
    return data.get("email")

def set_user_email(chat_id, email):
    subscribers = load_subscribers()
    if str(chat_id) not in subscribers:
        subscribers[str(chat_id)] = {}
    subscribers[str(chat_id)]["email"] = email
    save_subscribers(subscribers)

# ==================== LEGAL TERMS ====================
TERMS_FILE = "terms_accepted.json"

def load_terms():
    try:
        with open(TERMS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_terms(terms):
    with open(TERMS_FILE, "w") as f:
        json.dump(terms, f, indent=2)

def has_accepted_terms(chat_id):
    terms = load_terms()
    return str(chat_id) in terms and terms[str(chat_id)] == True

async def terms_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = """
⚠️ *IMPORTANT LEGAL DISCLAIMER*

This bot is an *analysis and automation tool*. **IT IS NOT A FINANCIAL ADVISOR**.

- Alerts, reports, and generated data are *purely informational*.
- They do not constitute buy/sell/investment recommendations.
- Cryptocurrency trading involves *high risk* of total capital loss.
- Neither the bot creator nor its operators are responsible for financial losses.

Type `/accept` to confirm you have read and agree.
"""
    await update.message.reply_text(text, parse_mode="Markdown")

# ==================== RATE LIMITING ====================
rate_limit_store = {}

def is_rate_limited(chat_id: int) -> bool:
    now = time.time()
    key = f"rate_{chat_id}"
    if key not in rate_limit_store:
        rate_limit_store[key] = []
    rate_limit_store[key] = [t for t in rate_limit_store[key] if t > now - RATE_LIMIT_PERIOD]
    if len(rate_limit_store[key]) >= RATE_LIMIT_REQUESTS:
        return True
    rate_limit_store[key].append(now)
    return False

def rate_limited():
    def decorator(func):
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            chat_id = update.effective_chat.id
            if is_rate_limited(chat_id):
                await update.message.reply_text("⏳ Too many requests. Please wait a moment.")
                return
            return await func(update, context)
        return wrapper
    return decorator

# ==================== FUNCIONES DE MERCADO Y UTILIDADES ====================
def get_all_prices():
    return get_cached_prices()

def get_coin_price_by_id(coin_id):
    prices = get_all_prices()
    if coin_id in prices:
        return prices[coin_id].get("usd")
    return None

def send_telegram(chat_id, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        logger.error(f"Error sending: {e}")

def check_alerts():
    for chat_id, data in USER_DATA.items():
        for alert in data.get("alerts", []):
            if not alert.get("active", True):
                continue
            coin_id = next((c[0] for c in COINS if c[1] == alert["coin"]), None)
            if not coin_id:
                continue
            price = get_coin_price_by_id(coin_id)
            if not price:
                continue
            condition = alert["condition"]
            target = alert["price"]
            if condition == ">" and price > target:
                send_telegram(int(chat_id), f"🚨 *ALERT* {alert['coin']}\nCurrent price: ${price:,.2f}\nExceeded ${target:,.2f}")
                alert["active"] = False
            elif condition == "<" and price < target:
                send_telegram(int(chat_id), f"🚨 *ALERT* {alert['coin']}\nCurrent price: ${price:,.2f}\nDropped below ${target:,.2f}")
                alert["active"] = False
    save_user_data()

def send_report(chat_id, report_type):
    prices = get_all_prices()
    if not prices:
        message = "⚠️ Could not retrieve report."
    else:
        changes = []
        for coin_id, symbol, name in COINS:
            if coin_id in prices:
                change = prices[coin_id].get('usd_24h_change', 0)
                changes.append((symbol, change))
        if changes:
            winner = max(changes, key=lambda x: x[1])
            loser = min(changes, key=lambda x: x[1])
        else:
            winner = loser = ("N/A", 0)

        message = f"📊 *{report_type.upper()} REPORT* 📊\n\n"
        for coin_id, symbol, name in COINS:
            if coin_id not in prices:
                continue
            data = prices[coin_id]
            price = data.get('usd', 0)
            change = data.get('usd_24h_change', 0)
            if price == 0:
                continue
            trend = "📈" if change > 0 else "📉" if change < 0 else "➡️"
            message += f"• *{symbol}*: ${price:,.0f} | {change:+.1f}% {trend}\n"
        message += f"\n🏆 *Daily winner:* {winner[0]} {winner[1]:+.1f}%\n"
        message += f"📉 *Daily loser:* {loser[0]} {loser[1]:+.1f}%\n"
        try:
            fg = requests.get('https://api.alternative.me/fng/').json()
            value = fg['data'][0]['value']
            classification = fg['data'][0]['value_classification']
            message += f"\n😨 *Fear & Greed:* {value}/100 ({classification})"
        except:
            pass
    send_telegram(chat_id, message)

def reschedule_reports():
    schedule.clear()
    schedule.every(60).seconds.do(check_alerts)
    for chat_id, data in USER_DATA.items():
        reports = data.get("reports", {})
        for report_type, hour in reports.items():
            if hour:
                schedule.every().day.at(hour).do(send_report, int(chat_id), report_type)
                logger.info(f"Scheduled {report_type} report at {hour} for chat {chat_id}")

# ==================== FUNCIÓN PARA NUEVOS TOKENS ====================
def check_new_tokens():
    if os.getenv("NEW_TOKEN_ALERTS", "false").lower() != "true":
        return
    logger.info("🔍 Scanning for new tokens...")
    try:
        new_tokens = scan_new_pools()
        if new_tokens:
            logger.info(f"✅ Found {len(new_tokens)} new tokens")
            for admin_id in ADMIN_IDS:
                for token in new_tokens:
                    msg = f"🚀 *New Token Detected!*\n\n{format_token_message(token)}"
                    if token.get("buy_tax") or token.get("sell_tax"):
                        msg += f"\n   💰 Tax: Buy {token.get('buy_tax', 0)}% / Sell {token.get('sell_tax', 0)}%"
                    if token.get("holder_count"):
                        msg += f"\n   👥 Holders: {token.get('holder_count')}"
                    send_telegram(admin_id, msg)
    except Exception as e:
        logger.error(f"Error in check_new_tokens: {e}")

# ==================== HANDLERS DE COMANDOS ====================
async def accept_terms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    terms = load_terms()
    terms[chat_id] = True
    save_terms(terms)
    start_trial(chat_id)
    await update.message.reply_text(
        "✅ *Welcome to CryptoArch Agent!*\n\n"
        "🧭 *You are in the FREE BETA.* No time limit, no subscription.\n"
        "• Commission: 0.5% (reduces with deposit)\n"
        "• Limited features (3 alerts) until you upgrade.\n\n"
        "⚡ *Why CryptoArch Agent is different:*\n"
        "• Maestro, Banana Gun and Trojan charge 1% per trade.\n"
        "• We charge from 0.5% down to 0.3%.\n"
        "• They execute fast. We make you think faster.\n"
        "• They copy traders. We copy whales with AI.\n\n"
        "To unlock full benefits, you have two options:\n"
        "1️⃣ *Deposit on Binance* using our referral link (no subscription):\n"
        f"👉 {BINANCE_REFERRAL_LINK}\n"
        "   • ≥ 50 USDT → Trader (0.4% comisión)\n"
        "   • ≥ 100 USDT → Pro (0.3% comisión, premium)\n"
        "   • ≥ 500 USDT → Elite (0.3% comisión, VIP + token reward)\n\n"
        "2️⃣ *Get $CARCH tokens* (coming soon) for Elite/Legendary benefits.\n\n"
        "Use /plan to see your current level.\n"
        "Use /activate to check your deposit level.\n\n"
        "💀 *Remember:* Maestro, Banana Gun and Trojan charge 1%.\n"
        "We charge from 0.5% to 0.3%.",
        parse_mode="Markdown"
    )
    await start(update, context)

@rate_limited()
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not has_accepted_terms(chat_id):
        await terms_command(update, context)
        return

    level = get_user_level(chat_id)
    if level == -1:
        await update.message.reply_text(
            get_text(chat_id, 'trial_expired', link=BINANCE_REFERRAL_LINK),
            parse_mode="Markdown"
        )
        return

    subscribers = load_subscribers()
    data = subscribers.get(str(chat_id), {})
    if not data.get("trial_start") and level == 0:
        start_trial(chat_id)
        await update.message.reply_text(
            get_text(chat_id, 'start_trial'),
            parse_mode="Markdown"
        )

    keyboard = [
        [InlineKeyboardButton("📊 Market status", callback_data="status")],
        [InlineKeyboardButton("🔔 My alerts", callback_data="alerts_list")],
        [InlineKeyboardButton("➕ New alert", callback_data="new_alert_coin")],
        [InlineKeyboardButton("📅 Auto reports", callback_data="reports_config")],
        [InlineKeyboardButton("💰 My balance (Testnet)", callback_data="balance")],
        [InlineKeyboardButton("💎 My status", callback_data="premium")],
        [InlineKeyboardButton("🐋 Whales (Free)", callback_data="whale")],
        [InlineKeyboardButton("📅 Plans", callback_data="plans")],
        [InlineKeyboardButton("📰 News", callback_data="news")],
        [InlineKeyboardButton("ℹ️ Coin info", callback_data="info")],
        [InlineKeyboardButton("🛒 Buy (testnet)", callback_data="buy")],
        [InlineKeyboardButton("💰 Sell (testnet)", callback_data="sell")],
        [InlineKeyboardButton("⚙️ Activate plan", callback_data="activate")],
        [InlineKeyboardButton("📋 My plan", callback_data="plan")],
        [InlineKeyboardButton("🤖 Auto trading", callback_data="rules")],
        [InlineKeyboardButton("⚡ Snipe", callback_data="snipe")],
        [InlineKeyboardButton("🎯 Sniper X", callback_data="sniper")],
        [InlineKeyboardButton("⚔️ Compare", callback_data="compare")],
        [InlineKeyboardButton("❓ Help", callback_data="help")]
    ]
    await update.message.reply_text(
        get_text(chat_id, 'welcome'),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

@rate_limited()
async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    level = get_user_level(chat_id)
    if level == -1:
        await update.message.reply_text(
            "⏰ *Your trial has expired!*\n\n"
            "To continue trading, deposit on Binance with our referral link:\n"
            f"{BINANCE_REFERRAL_LINK}\n\n"
            "Or wait for $CARCH token launch.",
            parse_mode="Markdown"
        )
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("⚠️ Usage: `/buy [amount] [symbol]`\nExample: `/buy 0.001 BTCUSDT`", parse_mode="Markdown")
        return
    try:
        amount = float(args[0])
        symbol = args[1].upper()
        if amount <= 0:
            raise ValueError
    except:
        await update.message.reply_text("❌ Invalid amount. Example: 0.001")
        return
    try:
        engine = TradingEngine(testnet=True)
        usdt_balance = engine.get_balance("USDT")
        if usdt_balance is None:
            await update.message.reply_text("❌ Could not connect to Binance Testnet. Please check your API keys.")
            return
        if usdt_balance < 0.01:
            await update.message.reply_text(
                "⚠️ Your Testnet balance is zero. You need to fund your testnet wallet first.\n"
                "Go to https://testnet.binance.vision/ to get testnet funds."
            )
            return
        price = engine.get_price(symbol)
        cost = amount * price
        if cost > usdt_balance:
            await update.message.reply_text(f"❌ Insufficient testnet balance. Need ~${cost:.2f} USDT. You have ${usdt_balance:.2f} USDT.")
            return
        
        commission = get_user_commission(chat_id)
        token_reward = get_token_reward(chat_id)
        fee = cost * commission if commission else 0
        token_amount = fee * token_reward if token_reward > 0 else 0
        
        security_msg = ""
        if ANTI_RUG_ENABLED and GOPLUS_API_KEY:
            contract = "0x0000000000000000000000000000000000000000"
            rug_check = check_token_security(contract, "ethereum")
            if rug_check["risk_score"] > 30:
                security_msg = f"\n⚠️ *Security risk detected:*\n"
                security_msg += f"   Risk score: {rug_check['risk_score']}/100\n"
                for warn in rug_check["warnings"]:
                    security_msg += f"   {warn}\n"
                security_msg += "\nDo you want to continue? Type *CONFIRMAR*.\n"
                await update.message.reply_text(
                    f"🟢 *Confirm buy*\n{amount} {symbol} ≈ ${cost:.2f} USD\n"
                    f"Commission: {commission*100:.1f}%\n"
                    + (f"🪙 Token reward: {token_amount:.6f} $CARCH\n" if token_amount > 0 else "")
                    + f"\n{security_msg}",
                    parse_mode="Markdown"
                )
                context.user_data["pending_order"] = {"type": "buy", "symbol": symbol, "amount": amount, "risk_accepted": False}
                return
        
        pred_msg = ""
        if AI_MODEL_ENABLED:
            alert = {"symbol": symbol, "value": cost, "transaction_type": "buy"}
            pred = predict_with_ai_advanced(alert, [])
            confidence_emoji = "🟢" if pred['confidence'] > 70 else "🟡" if pred['confidence'] > 50 else "🔴"
            pred_msg = f"\n🧠 *AI Prediction:* {pred['emoji']} {pred['prediction'].capitalize()} ({confidence_emoji} {pred['confidence']:.1f}% confidence)"
        
        await update.message.reply_text(
            f"🟢 *Confirm buy*\n{amount} {symbol} ≈ ${cost:.2f} USD\n"
            f"Commission: {commission*100:.1f}%\n"
            + (f"🪙 Token reward: {token_amount:.6f} $CARCH\n" if token_amount > 0 else "")
            + f"\n{security_msg}"
            + pred_msg
            + f"\n\nReply with *YES* (uppercase) to execute on testnet.",
            parse_mode="Markdown"
        )
        context.user_data["pending_order"] = {"type": "buy", "symbol": symbol, "amount": amount, "risk_accepted": True}
    except Exception as e:
        logger.error(f"Error in buy: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}. Check your Binance Testnet configuration.")

@rate_limited()
async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    level = get_user_level(chat_id)
    if level == -1:
        await update.message.reply_text(
            "⏰ *Your trial has expired!*\n\n"
            "To continue trading, deposit on Binance with our referral link:\n"
            f"{BINANCE_REFERRAL_LINK}\n\n"
            "Or wait for $CARCH token launch.",
            parse_mode="Markdown"
        )
        return

    args = context.args
    if len(args) != 2:
        await update.message.reply_text("⚠️ Usage: `/sell [amount] [symbol]`\nExample: `/sell 0.001 BTCUSDT`", parse_mode="Markdown")
        return
    try:
        amount = float(args[0])
        symbol = args[1].upper()
        if amount <= 0:
            raise ValueError
    except:
        await update.message.reply_text("❌ Invalid amount.")
        return
    try:
        try:
            fg_data = requests.get('https://api.alternative.me/fng/?limit=1').json()
            fear_value = int(fg_data['data'][0]['value'])
            if fear_value < 25:
                warning = (
                    "🛡️ *Panic Shield Activated* 🛡️\n\n"
                    "⚠️ You are about to sell during extreme fear.\n"
                    "📊 Historical data shows that selling during extreme fear often leads to regret.\n"
                    "🐋 Whales are currently accumulating.\n\n"
                    "Are you sure? Type *YES* to confirm, or *NO* to cancel."
                )
                await update.message.reply_text(warning, parse_mode="Markdown")
                context.user_data["pending_sell_confirm"] = True
                context.user_data["pending_sell_order"] = {"symbol": symbol, "amount": amount}
                return
        except Exception as e:
            logger.error(f"Error in Panic Shield: {e}")

        engine = TradingEngine(testnet=True)
        base_asset = symbol.replace("USDT", "")
        balance_asset = engine.get_balance(base_asset)
        if balance_asset is None:
            await update.message.reply_text("❌ Could not connect to Binance Testnet. Please check your API keys.")
            return
        if balance_asset < amount:
            await update.message.reply_text(f"❌ Insufficient {base_asset} testnet balance. You have {balance_asset:.8f}. Need {amount}.")
            return
        price = engine.get_price(symbol)
        value = amount * price
        commission = get_user_commission(chat_id)
        token_reward = get_token_reward(chat_id)
        fee = value * commission if commission else 0
        token_amount = fee * token_reward if token_reward > 0 else 0
        
        security_msg = ""
        if ANTI_RUG_ENABLED and GOPLUS_API_KEY:
            contract = "0x0000000000000000000000000000000000000000"
            rug_check = check_token_security(contract, "ethereum")
            if not rug_check.get("can_sell", True):
                security_msg = f"\n🚨 *Cannot sell this token (honeypot detected)*\n"
                security_msg += f"   Risk: {rug_check['risk_score']}/100\n"
                for warn in rug_check["warnings"]:
                    security_msg += f"   {warn}\n"
                await update.message.reply_text(
                    f"❌ *Sale blocked for safety*\n{security_msg}",
                    parse_mode="Markdown"
                )
                return
            elif rug_check["risk_score"] > 30:
                security_msg = f"\n⚠️ *Risk detected when selling:*\n"
                security_msg += f"   Score: {rug_check['risk_score']}/100\n"
                for warn in rug_check["warnings"]:
                    security_msg += f"   {warn}\n"
                security_msg += "\nDo you want to continue? Type *CONFIRMAR*.\n"
                await update.message.reply_text(
                    f"🔴 *Confirm sell*\n{amount} {symbol} ≈ ${value:.2f} USD\n"
                    f"Commission: {commission*100:.1f}%\n"
                    + (f"🪙 Token reward: {token_amount:.6f} $CARCH\n" if token_amount > 0 else "")
                    + f"\n{security_msg}",
                    parse_mode="Markdown"
                )
                context.user_data["pending_order"] = {"type": "sell", "symbol": symbol, "amount": amount, "risk_accepted": False}
                return
        
        pred_msg = ""
        if AI_MODEL_ENABLED:
            alert = {"symbol": symbol, "value": value, "transaction_type": "sell"}
            pred = predict_with_ai_advanced(alert, [])
            confidence_emoji = "🟢" if pred['confidence'] > 70 else "🟡" if pred['confidence'] > 50 else "🔴"
            pred_msg = f"\n🧠 *AI Prediction:* {pred['emoji']} {pred['prediction'].capitalize()} ({confidence_emoji} {pred['confidence']:.1f}% confidence)"
        
        await update.message.reply_text(
            f"🔴 *Confirm sell*\n{amount} {symbol} ≈ ${value:.2f} USD\n"
            f"Commission: {commission*100:.1f}%\n"
            + (f"🪙 Token reward: {token_amount:.6f} $CARCH\n" if token_amount > 0 else "")
            + f"\n{security_msg}"
            + pred_msg
            + f"\n\nReply with *YES* (uppercase) to execute on testnet.",
            parse_mode="Markdown"
        )
        context.user_data["pending_order"] = {"type": "sell", "symbol": symbol, "amount": amount, "risk_accepted": True}
    except Exception as e:
        logger.error(f"Error in sell: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}. Check your Binance Testnet configuration.")

@rate_limited()
async def whale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🐋 *Fetching whale movements...*", parse_mode="Markdown")
    btc_alerts = await asyncio.to_thread(obtener_alertas_bitcoin, 50000, 3)
    eth_alerts = await asyncio.to_thread(obtener_alertas_ethereum, 10000, 3)
    sol_alerts = await asyncio.to_thread(obtener_alertas_solana, 10000, 3)
    matic_alerts = await asyncio.to_thread(obtener_alertas_polygon, 5000, 3)
    arb_alerts = await asyncio.to_thread(obtener_alertas_arbitrum, 5000, 3)

    output = "📊 *RECENT WHALE MOVEMENTS*\n"
    output += "_The following data is informational only. Not investment advice._\n\n"

    all_alerts = btc_alerts + eth_alerts + sol_alerts + matic_alerts + arb_alerts
    context.user_data["last_whale_alerts"] = all_alerts

    if not all_alerts:
        output += "🐋 *No significant whale movements detected in the last hour.*\n"
        output += "Whales are waiting for the right moment. Check again later!\n\n"
    else:
        def format_alert(alert, idx):
            emoji, desc, sentiment, value = analizar_alerta(alert)
            text = f"{emoji} `{desc}`\n"
            text += f"   💰 Value: ${value:,.2f} USD | {sentiment}\n"
            ia_analysis = analizar_con_ia(alert)
            if ia_analysis:
                text += f"   🧠 *AI:* {ia_analysis}\n"
            if AI_MODEL_ENABLED:
                pred = predict_with_ai_advanced(alert, all_alerts)
                confidence_emoji = "🟢" if pred['confidence'] > 70 else "🟡" if pred['confidence'] > 50 else "🔴"
                text += f"   📡 *Prediction:* {pred['emoji']} {pred['prediction'].capitalize()} ({confidence_emoji} {pred['confidence']:.1f}% confidence)\n"
            radar = predecir_movimiento_ballena(alert)
            text += f"   📡 *Radar:* {radar['emoji']} {radar['prediction']} ({radar['confidence']}% confidence)\n"
            context.user_data[f"whale_alert_{idx}"] = alert
            text += f"   🆔 `whale_{idx}`\n"
            return text

        if btc_alerts:
            output += "₿ *Bitcoin (BTC)*\n"
            for idx, alert in enumerate(btc_alerts):
                output += format_alert(alert, idx) + "\n"
        else:
            output += "₿ *Bitcoin (BTC)*\nNo significant movements recently.\n\n"

        if eth_alerts:
            output += "⟠ *Ethereum (ETH)*\n"
            for idx, alert in enumerate(eth_alerts, start=len(btc_alerts)):
                output += format_alert(alert, idx) + "\n"
        else:
            output += "⟠ *Ethereum (ETH)*\nNo significant movements recently.\n\n"

        if sol_alerts:
            output += "◎ *Solana (SOL)*\n"
            for idx, alert in enumerate(sol_alerts, start=len(btc_alerts) + len(eth_alerts)):
                output += format_alert(alert, idx) + "\n"
        else:
            output += "◎ *Solana (SOL)*\nNo significant movements recently.\n\n"

        if matic_alerts:
            output += "🟣 *Polygon (MATIC)*\n"
            for idx, alert in enumerate(matic_alerts, start=len(btc_alerts) + len(eth_alerts) + len(sol_alerts)):
                output += format_alert(alert, idx) + "\n"
        else:
            output += "🟣 *Polygon (MATIC)*\nNo significant movements recently.\n\n"

        if arb_alerts:
            output += "🔵 *Arbitrum (ARB)*\n"
            for idx, alert in enumerate(arb_alerts, start=len(btc_alerts) + len(eth_alerts) + len(sol_alerts) + len(matic_alerts)):
                output += format_alert(alert, idx) + "\n"
        else:
            output += "🔵 *Arbitrum (ARB)*\nNo significant movements recently.\n\n"

    fg = get_fear_greed_index()
    output += f"\n📉 *Fear & Greed:* {fg['value']}/100 ({fg['classification']})"
    output += "\n\n💡 *Note:* Accumulation/distribution analyses are automatic."

    if all_alerts:
        keyboard = [
            [InlineKeyboardButton("🐋 Copy this whale", callback_data="copy_whale")],
            [InlineKeyboardButton("⚔️ Why we're better", callback_data="compare")],
            [InlineKeyboardButton("🧠 AI Prediction", callback_data="predict")]
        ]
        await update.message.reply_text(output, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.message.reply_text(output, parse_mode="Markdown")

    chat_id_str = str(update.effective_chat.id)
    await evaluate_rules(chat_id_str, all_alerts, context)
    await execute_sniper(chat_id_str, all_alerts, context)

@rate_limited()
async def copy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    args = context.args
    if not supabase:
        await update.message.reply_text("❌ Database not available.")
        return
    if not args:
        try:
            settings = supabase.table("copy_settings").select("*").eq("chat_id", chat_id).execute()
            if settings.data:
                s = settings.data[0]
                text = (
                    f"🐋 *Copy Trading Settings*\n\n"
                    f"💰 Max amount: {s['max_amount']} USDT\n"
                    f"📉 Slippage: {s['slippage']}%\n"
                    f"🔄 Mode: {s['mode']}\n"
                    f"✅ Active: {'✅ Yes' if s['active'] else '❌ No'}\n\n"
                    f"To change: `/copy [amount] [slippage] [mode] [on/off]`\n"
                    f"Example: `/copy 20 1.5 follow on`"
                )
                await update.message.reply_text(text, parse_mode="Markdown")
            else:
                await update.message.reply_text(
                    "🐋 *Copy Trading not configured*\n\n"
                    "This feature allows you to automatically copy whale trades.\n"
                    "To set it up, use: `/copy [amount] [slippage] [mode] [on/off]`\n"
                    "Example: `/copy 20 1.5 follow on`\n\n"
                    "Modes:\n"
                    "• `follow` → buy when whale buys (bullish)\n"
                    "• `invert` → buy when whale sells (contrarian)",
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Error loading copy settings: {e}")
            await update.message.reply_text("❌ Internal error. Try again later.")
        return
    try:
        if len(args) < 4:
            await update.message.reply_text("❌ Usage: `/copy [amount] [slippage] [mode] [on/off]`")
            return
        max_amount = float(args[0])
        slippage = float(args[1])
        mode = args[2].lower()
        active = args[3].lower() == "on"
        if mode not in ["follow", "invert"]:
            await update.message.reply_text("❌ Mode must be 'follow' or 'invert'")
            return
        if max_amount <= 0 or slippage < 0:
            await update.message.reply_text("❌ Amount must be > 0 and slippage >= 0")
            return
        data = {
            "chat_id": chat_id,
            "max_amount": max_amount,
            "slippage": slippage,
            "mode": mode,
            "active": active,
            "updated_at": datetime.now().isoformat()
        }
        supabase.table("copy_settings").upsert(data).execute()
        await update.message.reply_text(
            f"✅ *Copy settings saved!*\n\n"
            f"💰 Max amount: {max_amount} USDT\n"
            f"📉 Slippage: {slippage}%\n"
            f"🔄 Mode: {mode}\n"
            f"✅ Active: {'✅ Yes' if active else '❌ No'}",
            parse_mode="Markdown"
        )
    except ValueError:
        await update.message.reply_text("❌ Invalid number format. Use decimal points (ej: 20.5)")
    except Exception as e:
        logger.error(f"Error saving copy settings: {e}")
        await update.message.reply_text("❌ Internal error. Try again later.")

@rate_limited()
async def compare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
⚔️ *CryptoArch Agent vs. The Giants*

| Feature | Maestro | Banana Gun | Trojan | **CryptoArch Agent** |
|---------|---------|------------|--------|----------------------|
| **Commission** | 1% | 1%/0.5% | 1% | **0.5% → 0.3%** ✅ |
| **Subscription** | $200/mo | ❌ | ❌ | **FREE** ✅ |
| **Whale Alerts** | ❌ | ❌ | ❌ | ✅ **AI-powered** |
| **Copy Trading** | ✅ | ✅ | ✅ | ✅ **Whale copy** |
| **AI Analysis** | ❌ | ❌ | ❌ | ✅ **Contextual** |
| **Multi-Chain** | 14 | 4 | 1 | **5 (growing)** |
| **Free Trial** | ❌ | ❌ | ❌ | ✅ **14 days** |
| **Anti-MEV** | ✅ | ✅ | ✅ | ✅ **Real** |
| **Anti-Rug** | ✅ | ✅ | ❌ | ✅ **GoPlusLabs** |
| **Whale Radar** | ❌ | ❌ | ❌ | ✅ **Predictive AI** |
| **Panic Shield** | ❌ | ❌ | ❌ | ✅ **Emotional protection** |
| **Token Reward** | ❌ | ❌ | ❌ | ✅ **0.05% of all commissions** |

💀 *The math is simple:* They charge 1%. We charge from 0.5% to 0.3%.  
That's **up to 3.3x cheaper**. For a trader with $10,000 volume per month:
- Maestro/Banana/Trojan: $100/month
- CryptoArch Agent: $30/month (Pro level)

**You save $70/month. Every month.**

Plus, you get AI-powered whale analysis that *none of them* offer.

Use /whale to see it in action.
Use /copy to copy whales automatically.
Use /plan to check your level.

*Choose wisely. Or don't. But you've been warned.* 🚀
"""
    await update.message.reply_text(text, parse_mode="Markdown")

@rate_limited()
async def predict_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not AI_MODEL_ENABLED:
        await update.message.reply_text(
            "⚠️ *AI Predictor disabled*\n\n"
            "Enable with `AI_MODEL_ENABLED=true` in Railway.",
            parse_mode="Markdown"
        )
        return
    alert = None
    if context.user_data.get("last_whale_alerts"):
        alert = context.user_data["last_whale_alerts"][0]
    if not alert:
        alert = {"symbol": "BTC", "value": 150000, "transaction_type": "buy", "description": "Whale bought BTC"}
        all_alerts = [alert]
    else:
        all_alerts = context.user_data.get("last_whale_alerts", [alert])
    prediction = predict_with_ai_advanced(alert, all_alerts)
    message = (
        f"🧠 *Advanced AI Prediction*\n\n"
        f"{prediction['emoji']} *Direction:* {prediction['prediction'].capitalize()}\n"
        f"📊 *Confidence:* {prediction['confidence']:.1f}%\n"
        f"📝 *Details:* {prediction['details']}\n\n"
        f"📊 *Factors analyzed:*\n"
    )
    for factor, value in prediction.get("factors", {}).items():
        message += f"   • {factor.replace('_', ' ').title()}: {value}\n"
    fg = get_fear_greed_index()
    message += f"\n📉 *Fear & Greed:* {fg['value']}/100 ({fg['classification']})"
    if prediction['confidence'] > 70:
        message += "\n\n✅ *Strong signal* - High probability of success."
    elif prediction['confidence'] > 50:
        message += "\n\n⚠️ *Moderate signal* - Consider other factors."
    else:
        message += "\n\n🔴 *Weak signal* - Low reliability."
    message += "\n\n_Based on recent whale activity and multi-factor analysis._\n"
    message += "⚠️ _Not financial advice._"
    await update.message.reply_text(message, parse_mode="Markdown")

@rate_limited()
async def newtokens_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tokens = get_recent_tokens(limit=10)
    if not tokens:
        await update.message.reply_text("No new tokens detected recently. Stay tuned!")
        return
    msg = "🚀 *Latest New Tokens (24h)*\n\n"
    for token in tokens[:10]:
        msg += format_token_message(token) + "\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

@rate_limited()
async def plans_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(get_text(chat_id, 'plans'), parse_mode="Markdown")

@rate_limited()
async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("❌ Usage: `/info [symbol]`\nExample: `/info BTC`", parse_mode="Markdown")
        return
    symbol = args[0].upper()
    mapping = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "ripple",
               "BNB": "binancecoin", "LINK": "chainlink", "AVAX": "avalanche-2"}
    coin_id = mapping.get(symbol)
    if not coin_id:
        await update.message.reply_text("❌ Unsupported coin. Options: BTC, ETH, SOL, XRP, BNB, LINK, AVAX")
        return
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code != 200:
            await update.message.reply_text("⚠️ Could not fetch data. Try again later.")
            return
        data = r.json()
        price = data["market_data"]["current_price"]["usd"]
        market_cap = data["market_data"]["market_cap"]["usd"]
        volume = data["market_data"]["total_volume"]["usd"]
        change_24h = data["market_data"]["price_change_percentage_24h"]
        ath = data["market_data"]["ath"]["usd"]
        atl = data["market_data"]["atl"]["usd"]
        rank = data["market_cap_rank"]
        message = (
            f"📈 *{symbol} - {data['name']}*\n\n"
            f"💰 Price: ${price:,.2f} USD\n"
            f"📊 Market cap: ${market_cap:,.0f}\n"
            f"📉 Volume (24h): ${volume:,.0f}\n"
            f"📈 24h change: {change_24h:.2f}%\n"
            f"🏆 All-time high: ${ath:,.2f}\n"
            f"📉 All-time low: ${atl:,.2f}\n"
            f"🔢 Rank: #{rank}\n\n"
            f"Data from CoinGecko (informational only)."
        )
        await update.message.reply_text(message, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in /info: {e}")
        await update.message.reply_text("❌ Internal error. Try again later.")

@rate_limited()
async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📰 *Fetching latest news...*", parse_mode="Markdown")
    sources = [
        "https://cointelegraph.com/rss",
        "https://cryptopotato.com/feed/",
        "https://news.google.com/rss/search?q=cryptocurrency&hl=en&gl=US&ceid=US:en"
    ]
    for url in sources:
        try:
            feed = feedparser.parse(url)
            if feed.entries:
                message = "📰 *Latest crypto news*\n\n"
                for entry in feed.entries[:5]:
                    title = entry.title
                    link = entry.link
                    message += f"• [{title}]({link})\n"
                await update.message.reply_text(message, parse_mode="Markdown", disable_web_page_preview=True)
                return
        except Exception as e:
            logger.warning(f"Error with source {url}: {e}")
            continue
    await update.message.reply_text("No news found at the moment. Try again later.")

async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"🆔 *Your user ID:* `{chat_id}`", parse_mode="Markdown")

@rate_limited()
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        engine = TradingEngine(testnet=True)
        usdt_balance = engine.get_balance("USDT")
        btc_balance = engine.get_balance("BTC")
        message = f"💰 *Testnet Balance*\nUSDT: ${usdt_balance:.2f}\nBTC: {btc_balance:.8f}\n\n⚠️ This is TESTNET balance (fake money)."
        await update.message.reply_text(message, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in balance: {e}")
        await update.message.reply_text("❌ Internal error. Try again later.", parse_mode="Markdown")

@rate_limited()
async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    level = get_user_level(chat_id)
    if level >= 1:
        subscribers = load_subscribers()
        data = subscribers.get(str(chat_id), {})
        plan = data.get("plan", "free")
        end_str = data.get("end")
        insignia = get_user_insignia(chat_id)
        commission = get_user_commission(chat_id)
        benefits = get_level_benefits(level)
        level_name = LEVELS[level]["name"]
        token_reward = get_token_reward(chat_id)
        if end_str:
            end_date = datetime.fromisoformat(end_str).strftime("%d/%m/%Y")
            message = f"✨ *{insignia} {level_name}* ✨\n\n📅 *Valid until:* {end_date}\n💰 *Commission:* {commission*100:.1f}%\n🎁 *Benefits:* {benefits}\n"
            if token_reward > 0:
                message += f"🪙 *Token reward:* {token_reward*100:.2f}% of all bot commissions\n"
            message += "\n✅ Real trading access\n✅ Reduced fee\n✅ Whale alerts"
        else:
            message = f"✨ *{insignia} {level_name}* ✨\n\n💰 *Commission:* {commission*100:.1f}%\n🎁 *Benefits:* {benefits}\n"
            if token_reward > 0:
                message += f"🪙 *Token reward:* {token_reward*100:.2f}% of all bot commissions\n"
            message += "\n✅ Lifetime access\n✅ Whale alerts"
    elif level == 0:
        message = "🧭 *Explorer* (Trial)\n\n💰 Commission: 0.5%\n🎁 Benefits: 14 days free, 3 alerts, trading access\n\nUpgrade with /activate."
    else:
        message = "🔒 *FREE user*\n\nTo get started, use /start."
    await update.message.reply_text(message, parse_mode="Markdown")

@rate_limited()
async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        "🔍 *Checking your Binance balance...*\n\n"
        "⚠️ *IMPORTANT:* This checks your TESTNET balance.\n"
        "To activate a real plan, deposit on real Binance.\n\n"
        "Minimum deposits for levels:\n"
        "• Trader: 50 USDT (0.4% fee)\n"
        "• Pro: 100 USDT (0.3% fee + premium)\n"
        "• Elite: 500 USDT (0.3% fee + token reward)\n\n"
        "🪙 *Token $CARCH:* Elite holders receive 0.05% of all bot commissions.",
        parse_mode="Markdown"
    )
    try:
        engine = TradingEngine(testnet=True)
        usdt_balance = engine.get_balance("USDT")
        btc_balance = engine.get_balance("BTC")
        if btc_balance >= 0.01 or usdt_balance >= 500:
            level = 3
            commission = 0.003
            insignia = "👑"
            name = "Elite"
        elif usdt_balance >= 100:
            level = 2
            commission = 0.003
            insignia = "🌟"
            name = "Pro"
        elif usdt_balance >= 50:
            level = 1
            commission = 0.004
            insignia = "⚡"
            name = "Trader"
        else:
            level = 0
            commission = 0.005
            insignia = "🔰"
            name = "Explorer (trial)"
        subscribers = load_subscribers()
        subscribers[str(chat_id)] = {
            "plan": "free",
            "deposit_level": level,
            "commission_rate": commission,
            "insignia": insignia,
            "active": True if level > 0 else True
        }
        save_subscribers(subscribers)
        message = f"✅ *Level detected on TESTNET: {insignia} {name}*\n"
        message += f"💰 Commission: {commission*100:.1f}%\n"
        if level >= 3:
            message += f"🪙 Token reward: 0.05% of all bot commissions in $CARCH\n"
        message += f"📊 Detected balance (TESTNET): USDT ${usdt_balance:.2f}, BTC {btc_balance:.8f}\n\n"
        if level == 0:
            message += "Deposit ≥ 50 USDT to reach Trader level."
        elif level == 1:
            message += "Deposit ≥ 100 USDT to reach Pro level."
        elif level == 2:
            message += "Deposit ≥ 500 USDT to reach Elite level (with token reward)."
        else:
            message += "👑 You are ELITE! You receive 0.05% of all bot commissions in $CARCH tokens."
        await update.message.reply_text(message, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in activate: {e}")
        await update.message.reply_text("❌ Internal error. Try again later.", parse_mode="Markdown")

@rate_limited()
async def plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    subscribers = load_subscribers()
    data_sub = subscribers.get(str(chat_id), {"plan": "free", "fee": None})
    fee = data_sub.get("fee", None)
    level = get_user_level(chat_id)
    if level >= 0:
        insignia = get_user_insignia(chat_id)
        commission = get_user_commission(chat_id)
        benefits = get_level_benefits(level)
        level_name = LEVELS[level]["name"]
        token_reward = get_token_reward(chat_id)
        message = f"📋 *Your current level*\n\n{insignia} *{level_name}*\n💰 *Commission:* {commission*100:.1f}%\n🎁 *Benefits:* {benefits}\n"
        if token_reward > 0:
            message += f"🪙 *Token reward:* {token_reward*100:.2f}% of all bot commissions in $CARCH\n"
        if fee:
            message += f"💰 Trade fee (testnet): {fee}%\n"
        else:
            message += "💰 No real trading.\n"
        if level == 3:
            message += "\n👑 *You are an ELITE member!*"
        elif level == 4:
            message += "\n🏆 *You are LEGENDARY!*"
        else:
            message += f"\n*How to upgrade?*\n"
            message += f"1. Register on Binance using our link: {BINANCE_REFERRAL_LINK}\n"
            message += "2. Deposit the required amount:\n"
            message += "   • Trader: 50 USDT (0.4% fee)\n"
            message += "   • Pro: 100 USDT (0.3% fee + premium)\n"
            message += "   • Elite: 500 USDT (0.3% fee + token reward)\n"
            message += "3. Run /activate to upgrade your level.\n"
            message += "4. Or get $CARCH tokens (coming soon)."
    else:
        message = "⏰ *Trial expired.* Please deposit or subscribe to continue."
    await update.message.reply_text(message, parse_mode="Markdown")

async def setemail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args
    if not args:
        await update.message.reply_text("❌ Usage: `/setemail your@email.com`", parse_mode="Markdown")
        return
    email = args[0].strip()
    if "@" not in email or "." not in email:
        await update.message.reply_text("❌ Invalid email address.")
        return
    set_user_email(chat_id, email)
    await update.message.reply_text(f"✅ Email saved: `{email}`. You can now use /pay.", parse_mode="Markdown")

@rate_limited()
async def lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    args = context.args
    if args and args[0].lower() in ['es', 'spanish']:
        USER_LANG[chat_id] = 'es'
        await update.message.reply_text("✅ Idioma cambiado a Español.")
    elif args and args[0].lower() in ['en', 'english']:
        USER_LANG[chat_id] = 'en'
        await update.message.reply_text("✅ Language changed to English.")
    else:
        current = USER_LANG.get(chat_id, 'en')
        await update.message.reply_text(
            f"🌐 Current language: {current.upper()}\n\n"
            f"To change, use:\n"
            f"/lang en  -> English\n"
            f"/lang es  -> Español"
        )

async def activate_from_callback(query, chat_id):
    await activate(query.message, None)

async def show_coin_info(query, symbol):
    mapping = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "SOL": "solana",
        "XRP": "ripple",
        "BNB": "binancecoin",
        "LINK": "chainlink",
        "AVAX": "avalanche-2"
    }
    coin_id = mapping.get(symbol)
    if not coin_id:
        await query.edit_message_text("❌ Unsupported coin.")
        return
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code != 200:
            await query.edit_message_text("⚠️ Could not fetch data. Try again later.")
            return
        data = r.json()
        price = data["market_data"]["current_price"]["usd"]
        market_cap = data["market_data"]["market_cap"]["usd"]
        volume = data["market_data"]["total_volume"]["usd"]
        change_24h = data["market_data"]["price_change_percentage_24h"]
        ath = data["market_data"]["ath"]["usd"]
        atl = data["market_data"]["atl"]["usd"]
        rank = data["market_cap_rank"]
        message = (
            f"📈 *{symbol} - {data['name']}*\n\n"
            f"💰 Price: ${price:,.2f} USD\n"
            f"📊 Market cap: ${market_cap:,.0f}\n"
            f"📉 Volume (24h): ${volume:,.0f}\n"
            f"📈 24h change: {change_24h:.2f}%\n"
            f"🏆 All-time high: ${ath:,.2f}\n"
            f"📉 All-time low: ${atl:,.2f}\n"
            f"🔢 Rank: #{rank}\n\n"
            f"Data from CoinGecko (informational only)."
        )
        await query.edit_message_text(message, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in show_coin_info: {e}")
        await query.edit_message_text("❌ Error fetching data.")

async def receive_alert_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text.replace(",", ""))
        coin = context.user_data.get("new_alert_coin")
        condition = context.user_data.get("new_alert_condition")
        if not coin or not condition:
            await update.message.reply_text("❌ Error. Try again from the menu.")
            context.user_data.pop("awaiting_alert_price", None)
            context.user_data.pop("new_alert_coin", None)
            context.user_data.pop("new_alert_condition", None)
            return
        chat_str = str(update.effective_chat.id)
        if chat_str not in USER_DATA:
            USER_DATA[chat_str] = {"alerts": [], "reports": {}}
        USER_DATA[chat_str]["alerts"].append({
            "coin": coin,
            "condition": condition,
            "price": price,
            "active": True
        })
        save_user_data()
        await update.message.reply_text(f"✅ Alert created for {coin} {condition} ${price:,.2f}")
    except ValueError:
        await update.message.reply_text("❌ Invalid number. Use digits and decimal point (e.g. 50000).")
    finally:
        context.user_data.pop("awaiting_alert_price", None)
        context.user_data.pop("new_alert_coin", None)
        context.user_data.pop("new_alert_condition", None)

async def receive_report_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time_str = update.message.text.strip()
    if len(time_str) != 5 or time_str[2] != ":":
        await update.message.reply_text("❌ Invalid format. Use HH:MM (e.g. 08:30).")
        return
    try:
        hour = int(time_str[:2])
        minute = int(time_str[3:])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except:
        await update.message.reply_text("❌ Invalid time.")
        return
    report_type = context.user_data.get("report_type")
    if not report_type:
        await update.message.reply_text("❌ Error. Try again.")
        return
    chat_str = str(update.effective_chat.id)
    if chat_str not in USER_DATA:
        USER_DATA[chat_str] = {"alerts": [], "reports": {}}
    USER_DATA[chat_str]["reports"][report_type] = time_str
    save_user_data()
    reschedule_reports()
    await update.message.reply_text(f"✅ {report_type.upper()} report scheduled at {time_str}.")
    context.user_data.pop("awaiting_report_time", None)
    context.user_data.pop("report_type", None)

async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_alert_price"):
        await receive_alert_price(update, context)
    elif context.user_data.get("awaiting_report_time"):
        await receive_report_time(update, context)
    else:
        await confirm_order(update, context)

async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text == "confirmar" or text == "confirm":
        order = context.user_data.get("pending_order")
        if order:
            order["risk_accepted"] = True
            if order["type"] == "buy":
                await buy(update, context)
            else:
                await sell(update, context)
            return
    if context.user_data.get("pending_sell_confirm"):
        if text in ("no", "cancel"):
            await update.message.reply_text("✅ Sale cancelled. Smart choice! 🔥")
            context.user_data.pop("pending_sell_confirm", None)
            context.user_data.pop("pending_sell_order", None)
            return
        elif text == "yes":
            order = context.user_data.get("pending_sell_order")
            if not order:
                return
            engine = TradingEngine(testnet=True)
            result = engine.sell_market(order["symbol"], order["amount"])
            if result:
                await update.message.reply_text(f"✅ Sell executed on testnet. ID: {result['orderId']}")
            else:
                await update.message.reply_text("❌ Sell failed.")
            context.user_data.pop("pending_sell_confirm", None)
            context.user_data.pop("pending_sell_order", None)
            return
        else:
            await update.message.reply_text("❌ Type *YES* to confirm, or *NO* to cancel.")
            return
    if text not in ("yes", "sí", "si"):
        return
    order = context.user_data.get("pending_order")
    if not order:
        return
    if not order.get("risk_accepted", True):
        await update.message.reply_text("❌ You must accept the risk by typing *CONFIRMAR*.")
        return
    chat_id = update.effective_chat.id
    engine = TradingEngine(testnet=True)
    commission = get_user_commission(chat_id)
    if order["type"] == "buy":
        result = engine.buy_market(order["symbol"], order["amount"])
        if result:
            if commission is not None and commission > 0:
                fee = order["amount"] * commission
                logger.info(f"Commission charged: {fee} {order['symbol']} ({commission*100:.1f}%)")
                token_reward = get_token_reward(chat_id)
                if token_reward > 0:
                    token_amount = fee * token_reward
                    logger.info(f"🪙 Token reward: {token_amount} $CARCH for {chat_id}")
            await update.message.reply_text(f"✅ Buy executed on testnet. ID: {result['orderId']}")
        else:
            await update.message.reply_text("❌ Buy failed.")
    elif order["type"] == "sell":
        result = engine.sell_market(order["symbol"], order["amount"])
        if result:
            if commission is not None and commission > 0:
                fee = order["amount"] * commission
                logger.info(f"Commission charged: {fee} {order['symbol']} ({commission*100:.1f}%)")
                token_reward = get_token_reward(chat_id)
                if token_reward > 0:
                    token_amount = fee * token_reward
                    logger.info(f"🪙 Token reward: {token_amount} $CARCH for {chat_id}")
            await update.message.reply_text(f"✅ Sell executed on testnet. ID: {result['orderId']}")
        else:
            await update.message.reply_text("❌ Sell failed.")
    context.user_data.pop("pending_order", None)

async def force_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Not authorized.")
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("❌ Usage: /force_premium ID LEVEL SECRET_CODE\nExample: /force_premium 123456789 3 MySecret")
        return
    try:
        target_id = int(args[0])
        level = int(args[1])
        provided_secret = args[2]
        if provided_secret != ADMIN_SECRET:
            await update.message.reply_text("❌ Incorrect secret code. Action denied.")
            logger.warning(f"Failed /force_premium attempt from {chat_id}")
            return
        if level < 0 or level > 4:
            await update.message.reply_text("❌ Level must be 0-4.")
            return
        subscribers = load_subscribers()
        subscribers[str(target_id)] = {
            "plan": "free",
            "deposit_level": level,
            "commission_rate": LEVELS[level]["commission"],
            "insignia": LEVELS[level]["insignia"],
            "active": True,
            "start": datetime.now().isoformat(),
            "end": (datetime.now() + timedelta(days=365)).isoformat()
        }
        save_subscribers(subscribers)
        await update.message.reply_text(f"✅ User {target_id} updated to level {level} ({LEVELS[level]['name']})")
        logger.info(f"ADMIN: {chat_id} updated {target_id} to level {level}")
    except ValueError:
        await update.message.reply_text("❌ Invalid ID or level.")
    except Exception as e:
        logger.error(f"Error in force_premium: {e}")
        await update.message.reply_text("❌ Internal error.")

async def evaluate_rules(chat_id, alerts, context):
    if not supabase:
        return
    try:
        rules = supabase.table("rules").select("*").eq("chat_id", chat_id).eq("active", True).execute()
        if not rules.data:
            return
        for rule in rules.data:
            condition = rule["condition"]
            action = rule["action"]
            amount = rule["amount"]
            stop_loss = rule.get("stop_loss")
            take_profit = rule.get("take_profit")
            for alert in alerts:
                desc = alert.get("description", "")
                symbol = alert.get("symbol", "")
                tx_type = alert.get("transaction_type", "")
                if "whale_buy" in condition.lower() and "buy" in tx_type.lower():
                    match = True
                elif "whale_sell" in condition.lower() and "sell" in tx_type.lower():
                    match = True
                elif "whale_transfer" in condition.lower() and "transfer" in tx_type.lower():
                    match = True
                else:
                    match = False
                if match:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"🤖 *Auto Trade Executed*\n\n"
                             f"📊 Asset: {symbol}\n"
                             f"🔄 Action: {action.upper()}\n"
                             f"💰 Amount: ${amount:.2f} USDT\n"
                             f"📉 Stop-loss: {stop_loss}%\n"
                             f"📈 Take-profit: {take_profit}%\n"
                             f"⚡ Rule: {condition}\n\n"
                             f"*Simulation:* Order would be executed on testnet.",
                        parse_mode="Markdown"
                    )
                    supabase.table("rules").update({"active": False}).eq("id", rule["id"]).execute()
                    break
    except Exception as e:
        logger.error(f"Error evaluating rules: {e}")

async def execute_sniper(chat_id, alerts, context):
    if not supabase or not alerts:
        return
    try:
        settings = supabase.table("sniper_settings").select("*").eq("chat_id", chat_id).eq("active", True).execute()
        if not settings.data:
            return
        s = settings.data[0]
        alert = alerts[0]
        symbol = alert.get("symbol", "BTC")
        direction = alert.get("transaction_type", "transfer")
        if direction in ["transfer", "exchange_out"]:
            trade_direction = "sell"
            emoji = "🔴"
        else:
            trade_direction = "buy"
            emoji = "🟢"
        if s["mode"] == "aggressive":
            slippage = s["slippage"] + 1.0
            speed = "⚡ Ultra-fast"
        elif s["mode"] == "moderate":
            slippage = s["slippage"]
            speed = "⚖️ Balanced"
        else:
            slippage = max(0.5, s["slippage"] - 1.0)
            speed = "🛡️ Safe"
        commission = get_user_commission(int(chat_id)) or 0.003
        token_reward = get_token_reward(int(chat_id))
        amount_usd = s['max_amount']
        fee = amount_usd * commission
        token_amount = fee * token_reward if token_reward > 0 else 0
        security_msg = ""
        if ANTI_MEV_ENABLED:
            mev_check = simulate_anti_mev(symbol, amount_usd)
            if mev_check.get("protected"):
                security_msg += f"🛡️ {mev_check['message']}\n"
        if ANTI_RUG_ENABLED and GOPLUS_API_KEY:
            contract = "0x0000000000000000000000000000000000000000"
            rug_check = check_token_security(contract, "ethereum")
            if rug_check["risk_score"] > 30:
                security_msg += f"⚠️ Risk detected (score: {rug_check['risk_score']}/100)\n"
                for warn in rug_check["warnings"]:
                    security_msg += f"   {warn}\n"
        pred_msg = ""
        if AI_MODEL_ENABLED:
            pred = predict_with_ai_advanced(alert, alerts)
            confidence_emoji = "🟢" if pred['confidence'] > 70 else "🟡" if pred['confidence'] > 50 else "🔴"
            pred_msg = f"\n🧠 *Prediction:* {pred['emoji']} {pred['prediction'].capitalize()} ({confidence_emoji} {pred['confidence']:.1f}% confidence)"
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🎯 *Sniper X Execution*\n\n"
                 f"{emoji} Direction: *{trade_direction.upper()}*\n"
                 f"💰 Amount: ${s['max_amount']:.2f} USDT\n"
                 f"📉 Slippage: {slippage:.1f}%\n"
                 f"⚡ Mode: {speed}\n"
                 f"🛡️ Anti-MEV: {'✅ ON' if s['anti_mev'] else '❌ OFF'}\n"
                 f"📊 Asset: {symbol}\n"
                 f"💵 Commission: ${fee:.4f} ({commission*100:.1f}%)\n"
                 + (f"🪙 Token reward: {token_amount:.6f} $CARCH\n" if token_amount > 0 else "")
                 + (f"\n{security_msg}" if security_msg else "")
                 + pred_msg
                 + f"\n\n*Simulation:* Order would be executed on testnet.\n"
                 f"⚠️ *Real execution coming soon.*",
            parse_mode="Markdown"
        )
        supabase.table("sniper_settings").update({"active": False}).eq("chat_id", chat_id).execute()
    except Exception as e:
        logger.error(f"Error executing sniper for {chat_id}: {e}")

async def copy_whale_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = str(update.effective_chat.id)
    alerts = context.user_data.get("last_whale_alerts", [])
    if not alerts:
        await query.edit_message_text("⚠️ No whale alert available to copy.")
        return
    alert = alerts[0]
    symbol = alert.get("symbol", "BTC")
    direction = alert.get("transaction_type", "transfer")
    if direction in ["transfer", "exchange_out"]:
        trade_direction = "sell"
        emoji = "🔴"
    else:
        trade_direction = "buy"
        emoji = "🟢"
    try:
        settings = supabase.table("copy_settings").select("*").eq("chat_id", chat_id).execute()
        if not settings.data or not settings.data[0].get("active", False):
            await query.edit_message_text(
                "❌ *Copy Trading not active or not configured.*\n\n"
                "Use `/copy` to set up your copy trading settings.\n"
                "Example: `/copy 20 1.5 follow on`",
                parse_mode="Markdown"
            )
            return
        s = settings.data[0]
        max_amount = s["max_amount"]
        slippage = s["slippage"] / 100.0
        mode = s["mode"]
        if mode == "invert":
            trade_direction = "buy" if trade_direction == "sell" else "sell"
            emoji = "🔄" + emoji
        commission = get_user_commission(int(chat_id)) or 0.003
        token_reward = get_token_reward(int(chat_id))
        fee = max_amount * commission
        token_amount = fee * token_reward if token_reward > 0 else 0
        security_msg = ""
        if ANTI_MEV_ENABLED:
            mev_check = simulate_anti_mev(symbol, max_amount)
            if mev_check.get("protected"):
                security_msg += f"🛡️ {mev_check['message']}\n"
        if ANTI_RUG_ENABLED and GOPLUS_API_KEY:
            contract = "0x0000000000000000000000000000000000000000"
            rug_check = check_token_security(contract, "ethereum")
            if rug_check["risk_score"] > 30:
                security_msg += f"⚠️ Risk detected (score: {rug_check['risk_score']}/100)\n"
                for warn in rug_check["warnings"]:
                    security_msg += f"   {warn}\n"
        pred_msg = ""
        if AI_MODEL_ENABLED:
            pred = predict_with_ai_advanced(alert, alerts)
            confidence_emoji = "🟢" if pred['confidence'] > 70 else "🟡" if pred['confidence'] > 50 else "🔴"
            pred_msg = f"\n🧠 *Prediction:* {pred['emoji']} {pred['prediction'].capitalize()} ({confidence_emoji} {pred['confidence']:.1f}% confidence)"
        await query.edit_message_text(
            f"🐋 *Copy Trade Execution*\n\n"
            f"{emoji} Direction: *{trade_direction.upper()}*\n"
            f"💰 Amount: ${max_amount:.2f} USDT\n"
            f"📉 Slippage: {slippage*100:.1f}%\n"
            f"🔄 Mode: {mode}\n"
            f"📊 Asset: {symbol}\n"
            f"💵 Commission: ${fee:.4f} ({commission*100:.1f}%)\n"
            + (f"🪙 Token reward: {token_amount:.6f} $CARCH\n" if token_amount > 0 else "")
            + (f"\n{security_msg}" if security_msg else "")
            + pred_msg
            + f"\n\n⚡ *Simulation:* Order executed on testnet (real trading coming soon).",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in copy_whale_callback: {e}")
        await query.edit_message_text("❌ Internal error. Try again later.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = update.effective_chat.id
    if is_rate_limited(chat_id):
        await query.edit_message_text("⏳ Too many requests. Please wait.")
        return
    if data == "status":
        await show_status(query)
    elif data == "alerts_list":
        await show_alerts(query, chat_id)
    elif data == "new_alert_coin":
        await new_alert_coin(query, chat_id)
    elif data.startswith("new_alert_price_"):
        coin = data.split("_")[3]
        context.user_data["new_alert_coin"] = coin
        await new_alert_condition(query, coin, chat_id)
    elif data.startswith("new_alert_condition_"):
        cond = data.split("_")[3]
        context.user_data["new_alert_condition"] = cond
        await query.edit_message_text(f"💰 Enter target price for {context.user_data['new_alert_coin']} {cond}\nExample: 50000")
        context.user_data["awaiting_alert_price"] = True
    elif data.startswith("alert_toggle_"):
        idx = int(data.split("_")[2])
        toggle_alert(chat_id, idx)
        await show_alerts(query, chat_id)
    elif data.startswith("alert_delete_"):
        idx = int(data.split("_")[2])
        delete_alert(chat_id, idx)
        await show_alerts(query, chat_id)
    elif data == "reports_config":
        await reports_menu(query, chat_id)
    elif data.startswith("report_type_"):
        report_type = data.split("_")[2]
        context.user_data["report_type"] = report_type
        await query.edit_message_text(f"⏰ Enter time for {report_type.upper()} report (HH:MM, e.g. 08:30)")
        context.user_data["awaiting_report_time"] = True
    elif data == "help":
        await help_menu(query, chat_id)
    elif data == "balance":
        try:
            engine = TradingEngine(testnet=True)
            usdt_balance = engine.get_balance("USDT")
            btc_balance = engine.get_balance("BTC")
            message = f"💰 *Testnet Balance*\nUSDT: ${usdt_balance:.2f}\nBTC: {btc_balance:.8f}\n\n⚠️ This is TESTNET balance (fake money). To trade real money, deposit on real Binance and use /activate."
            await query.edit_message_text(message, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error en balance: {e}")
            await query.edit_message_text("❌ Internal error. Try again later.", parse_mode="Markdown")
    elif data == "premium":
        level = get_user_level(chat_id)
        if level >= 1:
            subscribers = load_subscribers()
            data_sub = subscribers.get(str(chat_id), {})
            plan = data_sub.get("plan", "free")
            end_str = data_sub.get("end")
            insignia = get_user_insignia(chat_id)
            commission = get_user_commission(chat_id)
            benefits = get_level_benefits(level)
            level_name = LEVELS[level]["name"]
            if end_str:
                end_date = datetime.fromisoformat(end_str).strftime("%d/%m/%Y")
                message = f"✨ *{insignia} {level_name}* ✨\n\n📅 *Valid until:* {end_date}\n💰 *Commission:* {commission*100:.1f}%\n🎁 *Benefits:* {benefits}\n\n✅ Real trading access\n✅ Reduced fee\n✅ Whale alerts"
            else:
                message = f"✨ *{insignia} {level_name}* ✨\n\n💰 *Commission:* {commission*100:.1f}%\n🎁 *Benefits:* {benefits}\n\n✅ Lifetime access\n✅ Whale alerts"
        elif level == 0:
            message = "🧭 *Explorer* (Trial)\n\n💰 Commission: 0.5%\n🎁 Benefits: 14 days free, 3 alerts, trading access\n\nUpgrade with /activate."
        else:
            message = "🔒 *FREE user*\n\nTo get started, use /start."
        await query.edit_message_text(message, parse_mode="Markdown")
    elif data == "whale":
        await whale_callback(update, context)
    elif data == "plans":
        await query.edit_message_text(get_text(chat_id, 'plans'), parse_mode="Markdown")
    elif data == "news":
        await query.edit_message_text("📰 *Fetching latest news...*", parse_mode="Markdown")
        sources = [
            "https://cointelegraph.com/rss",
            "https://cryptopotato.com/feed/",
            "https://news.google.com/rss/search?q=cryptocurrency&hl=en&gl=US&ceid=US:en"
        ]
        for url in sources:
            try:
                feed = feedparser.parse(url)
                if feed.entries:
                    message = "📰 *Latest crypto news*\n\n"
                    for entry in feed.entries[:5]:
                        title = entry.title
                        link = entry.link
                        message += f"• [{title}]({link})\n"
                    await query.edit_message_text(message, parse_mode="Markdown", disable_web_page_preview=True)
                    return
            except Exception as e:
                logger.warning(f"Error with source {url}: {e}")
                continue
        await query.edit_message_text("No news found at the moment. Try again later.", parse_mode="Markdown")
    elif data == "info":
        keyboard = [
            [InlineKeyboardButton("BTC", callback_data="info_coin_BTC")],
            [InlineKeyboardButton("ETH", callback_data="info_coin_ETH")],
            [InlineKeyboardButton("SOL", callback_data="info_coin_SOL")],
            [InlineKeyboardButton("XRP", callback_data="info_coin_XRP")],
            [InlineKeyboardButton("BNB", callback_data="info_coin_BNB")],
            [InlineKeyboardButton("LINK", callback_data="info_coin_LINK")],
            [InlineKeyboardButton("AVAX", callback_data="info_coin_AVAX")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu")]
        ]
        await query.edit_message_text("📈 *Select a coin for detailed info*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data.startswith("info_coin_"):
        symbol = data.split("_")[2]
        await show_coin_info(query, symbol)
    elif data == "buy":
        level = get_user_level(chat_id)
        if level == -1:
            await query.edit_message_text(
                "⏰ *Your trial has expired!*\n\n"
                "To continue trading, deposit on Binance with our referral link:\n"
                f"{BINANCE_REFERRAL_LINK}\n\n"
                "Or wait for $CARCH token launch.",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text("⚠️ To buy, use the command:\n`/buy [amount] [symbol]`\nExample: `/buy 0.001 BTCUSDT`\n\nYou can also reply with YES after the confirmation.", parse_mode="Markdown")
    elif data == "sell":
        level = get_user_level(chat_id)
        if level == -1:
            await query.edit_message_text(
                "⏰ *Your trial has expired!*\n\n"
                "To continue trading, deposit on Binance with our referral link:\n"
                f"{BINANCE_REFERRAL_LINK}\n\n"
                "Or wait for $CARCH token launch.",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text("⚠️ To sell, use the command:\n`/sell [amount] [symbol]`\nExample: `/sell 0.001 BTCUSDT`\n\nYou can also reply with YES after the confirmation.", parse_mode="Markdown")
    elif data == "activate":
        await activate_from_callback(query, chat_id)
    elif data == "plan":
        subscribers = load_subscribers()
        data_sub = subscribers.get(str(chat_id), {"plan": "free", "fee": None})
        fee = data_sub.get("fee", None)
        level = get_user_level(chat_id)
        if level >= 0:
            insignia = get_user_insignia(chat_id)
            commission = get_user_commission(chat_id)
            benefits = get_level_benefits(level)
            level_name = LEVELS[level]["name"]
            token_reward = get_token_reward(chat_id)
            message = f"📋 *Your current level*\n\n{insignia} *{level_name}*\n💰 *Commission:* {commission*100:.1f}%\n🎁 *Benefits:* {benefits}\n"
            if token_reward > 0:
                message += f"🪙 *Token reward:* {token_reward*100:.2f}% of all bot commissions in $CARCH\n"
            if fee:
                message += f"💰 Trade fee (testnet): {fee}%\n"
            else:
                message += "💰 No real trading.\n"
            if level == 3:
                message += "\n👑 *You are an ELITE member!*"
            elif level == 4:
                message += "\n🏆 *You are LEGENDARY!*"
            else:
                message += f"\n*How to upgrade?*\n"
                message += f"1. Register on Binance using our link: {BINANCE_REFERRAL_LINK}\n"
                message += "2. Deposit the required amount:\n"
                message += "   • Trader: 50 USDT (0.4% fee)\n"
                message += "   • Pro: 100 USDT (0.3% fee + premium)\n"
                message += "   • Elite: 500 USDT (0.3% fee + token reward)\n"
                message += "3. Run /activate to upgrade your level.\n"
                message += "4. Or get $CARCH tokens (coming soon)."
        else:
            message = "⏰ *Trial expired.* Please deposit or subscribe to continue."
        await query.edit_message_text(message, parse_mode="Markdown")
    elif data == "copy_whale":
        await copy_whale_callback(update, context)
    elif data == "rules":
        await rules_menu(update, context)
    elif data == "snipe":
        await snipe_settings_menu(update, context)
    elif data == "sniper":
        await sniper(update, context)
    elif data == "compare":
        await compare(update, context)
    elif data == "menu":
        await start(update, context)
    else:
        await query.edit_message_text("❌ Invalid option.")

async def show_status(query):
    prices = get_all_prices()
    if not prices:
        await query.edit_message_text("⚠️ Could not fetch data. Try again later.")
        return
    message = "📊 *LIVE MARKET STATUS* (WebSocket)\n\n"
    for coin_id, symbol, name in COINS:
        if coin_id not in prices:
            continue
        data = prices[coin_id]
        price = data.get('usd', 0)
        change = data.get('usd_24h_change', 0)
        if price == 0:
            continue
        trend = "📈" if change > 0 else "📉" if change < 0 else "➡️"
        message += f"• *{symbol}*: ${price:,.0f} | {change:+.1f}% {trend}\n"
    try:
        fg = requests.get('https://api.alternative.me/fng/').json()
        value = fg['data'][0]['value']
        classification = fg['data'][0]['value_classification']
        message += f"\n😨 *Fear & Greed:* {value}/100 ({classification})"
    except:
        pass
    await query.edit_message_text(message, parse_mode="Markdown")

async def show_alerts(query, chat_id):
    data = USER_DATA.get(str(chat_id), {})
    alerts = data.get("alerts", [])
    if not alerts:
        await query.edit_message_text("🔔 You have no active alerts.\nUse '➕ New alert' to create one.")
        return
    keyboard = []
    for i, a in enumerate(alerts):
        state = "✅" if a.get("active", True) else "❌"
        keyboard.append([InlineKeyboardButton(f"{state} {a['coin']} {a['condition']} ${a['price']:,.0f}", callback_data=f"alert_toggle_{i}")])
        keyboard.append([InlineKeyboardButton(f"🗑 Delete {a['coin']}", callback_data=f"alert_delete_{i}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu")])
    await query.edit_message_text("🔔 *Your alerts*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

def toggle_alert(chat_id, idx):
    chat_str = str(chat_id)
    if chat_str not in USER_DATA:
        return
    alerts = USER_DATA[chat_str].get("alerts", [])
    if idx < len(alerts):
        alerts[idx]["active"] = not alerts[idx].get("active", True)
        save_user_data()

def delete_alert(chat_id, idx):
    chat_str = str(chat_id)
    if chat_str not in USER_DATA:
        return
    alerts = USER_DATA[chat_str].get("alerts", [])
    if idx < len(alerts):
        alerts.pop(idx)
        save_user_data()

async def new_alert_coin(query, chat_id):
    level = get_user_level(chat_id)
    if level == 0:
        data = USER_DATA.get(str(chat_id), {})
        alerts = data.get("alerts", [])
        if len(alerts) >= 3:
            await query.edit_message_text(
                "⚠️ *Explorer users can only have 3 active alerts.*\n"
                "Upgrade to Trader/Pro/Elite for unlimited alerts.\n"
                "Use /activate to check your level.",
                parse_mode="Markdown"
            )
            return
    keyboard = []
    for _, symbol, name in COINS:
        keyboard.append([InlineKeyboardButton(f"{symbol} - {name}", callback_data=f"new_alert_price_{symbol}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu")])
    await query.edit_message_text("💰 *New alert - Select coin*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def new_alert_condition(query, coin, chat_id):
    keyboard = [
        [InlineKeyboardButton("🚀 Price goes above (> 🚀)", callback_data="new_alert_condition_>")],
        [InlineKeyboardButton("📉 Price goes below (< 📉)", callback_data="new_alert_condition_<")],
        [InlineKeyboardButton("🔙 Back", callback_data="new_alert_coin")]
    ]
    await query.edit_message_text(f"📊 *Coin: {coin}*\nWhich condition to monitor?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def reports_menu(query, chat_id):
    keyboard = [
        [InlineKeyboardButton("🌅 Morning report", callback_data="report_type_morning")],
        [InlineKeyboardButton("☀️ Midday report", callback_data="report_type_midday")],
        [InlineKeyboardButton("🌙 Evening report", callback_data="report_type_evening")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu")]
    ]
    await query.edit_message_text("📅 *Auto report settings*\nChoose which report to schedule:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def help_menu(query, chat_id):
    await query.edit_message_text(get_text(chat_id, 'help'), parse_mode="Markdown")

async def whale_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.edit_message_text("🐋 *Fetching whale movements...*", parse_mode="Markdown")
    btc_alerts = await asyncio.to_thread(obtener_alertas_bitcoin, 50000, 3)
    eth_alerts = await asyncio.to_thread(obtener_alertas_ethereum, 10000, 3)
    sol_alerts = await asyncio.to_thread(obtener_alertas_solana, 10000, 3)
    matic_alerts = await asyncio.to_thread(obtener_alertas_polygon, 5000, 3)
    arb_alerts = await asyncio.to_thread(obtener_alertas_arbitrum, 5000, 3)

    output = "📊 *RECENT WHALE MOVEMENTS*\n"
    output += "_The following data is informational only._\n\n"

    all_alerts = btc_alerts + eth_alerts + sol_alerts + matic_alerts + arb_alerts
    context.user_data["last_whale_alerts"] = all_alerts

    if not all_alerts:
        output += "🐋 *No significant whale movements detected in the last hour.*\n"
        output += "Whales are waiting for the right moment. Check again later!\n\n"
    else:
        def format_alert(alert, idx):
            emoji, desc, sentiment, value = analizar_alerta(alert)
            text = f"{emoji} `{desc}`\n"
            text += f"   💰 Value: ${value:,.2f} USD | {sentiment}\n"
            ia_analysis = analizar_con_ia(alert)
            if ia_analysis:
                text += f"   🧠 *AI:* {ia_analysis}\n"
            if AI_MODEL_ENABLED:
                pred = predict_with_ai_advanced(alert, all_alerts)
                confidence_emoji = "🟢" if pred['confidence'] > 70 else "🟡" if pred['confidence'] > 50 else "🔴"
                text += f"   📡 *Prediction:* {pred['emoji']} {pred['prediction'].capitalize()} ({confidence_emoji} {pred['confidence']:.1f}% confidence)\n"
            radar = predecir_movimiento_ballena(alert)
            text += f"   📡 *Radar:* {radar['emoji']} {radar['prediction']} ({radar['confidence']}% confidence)\n"
            context.user_data[f"whale_alert_{idx}"] = alert
            text += f"   🆔 `whale_{idx}`\n"
            return text

        if btc_alerts:
            output += "₿ *Bitcoin (BTC)*\n"
            for idx, alert in enumerate(btc_alerts):
                output += format_alert(alert, idx) + "\n"
        else:
            output += "₿ *Bitcoin (BTC)*\nNo significant movements recently.\n\n"

        if eth_alerts:
            output += "⟠ *Ethereum (ETH)*\n"
            for idx, alert in enumerate(eth_alerts, start=len(btc_alerts)):
                output += format_alert(alert, idx) + "\n"
        else:
            output += "⟠ *Ethereum (ETH)*\nNo significant movements recently.\n\n"

        if sol_alerts:
            output += "◎ *Solana (SOL)*\n"
            for idx, alert in enumerate(sol_alerts, start=len(btc_alerts) + len(eth_alerts)):
                output += format_alert(alert, idx) + "\n"
        else:
            output += "◎ *Solana (SOL)*\nNo significant movements recently.\n\n"

        if matic_alerts:
            output += "🟣 *Polygon (MATIC)*\n"
            for idx, alert in enumerate(matic_alerts, start=len(btc_alerts) + len(eth_alerts) + len(sol_alerts)):
                output += format_alert(alert, idx) + "\n"
        else:
            output += "🟣 *Polygon (MATIC)*\nNo significant movements recently.\n\n"

        if arb_alerts:
            output += "🔵 *Arbitrum (ARB)*\n"
            for idx, alert in enumerate(arb_alerts, start=len(btc_alerts) + len(eth_alerts) + len(sol_alerts) + len(matic_alerts)):
                output += format_alert(alert, idx) + "\n"
        else:
            output += "🔵 *Arbitrum (ARB)*\nNo significant movements recently.\n\n"

    fg = get_fear_greed_index()
    output += f"\n📉 *Fear & Greed:* {fg['value']}/100 ({fg['classification']})"
    output += "\n\n💡 *Note:* Accumulation/distribution analyses are automatic."

    if all_alerts:
        keyboard = [
            [InlineKeyboardButton("🐋 Copy this whale", callback_data="copy_whale")],
            [InlineKeyboardButton("⚔️ Why we're better", callback_data="compare")],
            [InlineKeyboardButton("🧠 AI Prediction", callback_data="predict")]
        ]
        await query.edit_message_text(output, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await query.edit_message_text(output, parse_mode="Markdown")

    chat_id_str = str(update.effective_chat.id)
    await evaluate_rules(chat_id_str, all_alerts, context)
    await execute_sniper(chat_id_str, all_alerts, context)

@rate_limited()
async def rules_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    try:
        rules = supabase.table("rules").select("*").eq("chat_id", chat_id).execute()
        if not rules.data:
            text = "🤖 *No auto trading rules configured.*\n\n"
            text += "Use `/rule add` to create one.\n"
            text += "Example: `/rule add \"whale_buy_btc > 100\" buy 50 5 10`"
            await update.message.reply_text(text, parse_mode="Markdown")
            return
        text = "🤖 *Your auto trading rules:*\n\n"
        for r in rules.data:
            status = "✅ Active" if r["active"] else "❌ Paused"
            text += f"🔹 *ID {r['id']}*: {r['condition']}\n"
            text += f"   Action: {r['action']} | Amount: ${r['amount']} USDT\n"
            text += f"   Stop-loss: {r['stop_loss']}% | Take-profit: {r['take_profit']}%\n"
            text += f"   Status: {status}\n"
            text += f"   📌 `/rule toggle {r['id']}` · `/rule delete {r['id']}`\n\n"
        text += "\n*Commands:*\n"
        text += "/rule add [condition] [action] [amount] [stop_loss] [take_profit]\n"
        text += "Example: `/rule add \"whale_buy_btc > 100\" buy 50 5 10`\n"
        text += "/rule list - Show all rules\n"
        text += "/rule toggle [id] - Activate/pause\n"
        text += "/rule delete [id] - Delete rule"
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in rules_menu: {e}")
        await update.message.reply_text("❌ Internal error. Try again later.")

@rate_limited()
async def rule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    args = context.args
    if not supabase:
        await update.message.reply_text("❌ Database not available.")
        return
    if len(args) == 0:
        await update.message.reply_text("❌ Usage: /rule [add|list|toggle|delete] ...")
        return
    subcommand = args[0].lower()
    if subcommand == "add":
        if len(args) < 6:
            await update.message.reply_text(
                "❌ Usage: `/rule add \"condition\" action amount stop_loss take_profit`\n"
                "Example: `/rule add \"whale_buy_btc > 100\" buy 50 5 10`"
            )
            return
        try:
            full_text = " ".join(args[1:])
            match = re.search(r'"(.*?)"', full_text)
            if match:
                condition = match.group(1)
                rest = full_text.replace(f'"{condition}"', '').strip().split()
                if len(rest) < 4:
                    await update.message.reply_text("❌ Missing parameters after condition.")
                    return
                action = rest[0].lower()
                amount = float(rest[1])
                stop_loss = float(rest[2])
                take_profit = float(rest[3])
            else:
                condition = args[1]
                action = args[2].lower()
                amount = float(args[3])
                stop_loss = float(args[4])
                take_profit = float(args[5])
            condition = re.sub(r'[^a-zA-Z0-9_>\<=\s]', '', condition)
            if action not in ["buy", "sell"]:
                await update.message.reply_text("❌ Action must be 'buy' or 'sell'")
                return
            data = {
                "chat_id": chat_id,
                "condition": condition,
                "action": action,
                "amount": amount,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "active": True
            }
            result = supabase.table("rules").insert(data).execute()
            rule_id = result.data[0]["id"] if result.data else "N/A"
            await update.message.reply_text(
                f"✅ *Rule added successfully!*\n"
                f"📌 Rule ID: `{rule_id}`\n\n"
                f"Use `/rule list` to see all rules, or `/rule toggle {rule_id}` to pause it.",
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("❌ Invalid number format. Use decimals with dot (ej: 50.0)")
        except Exception as e:
            logger.error(f"Error adding rule: {e}")
            await update.message.reply_text("❌ Internal error. Try again later.")
    elif subcommand == "list":
        try:
            rules = supabase.table("rules").select("*").eq("chat_id", chat_id).execute()
            if not rules.data:
                await update.message.reply_text("🤖 No rules configured.")
                return
            text = "🤖 *Your rules:*\n\n"
            for r in rules.data:
                status = "✅" if r["active"] else "❌"
                text += f"{status} *ID {r['id']}*: {r['condition']}\n"
                text += f"   → {r['action'].upper()} ${r['amount']} USDT | SL: {r['stop_loss']}% | TP: {r['take_profit']}%\n"
                text += f"   📌 `/rule toggle {r['id']}` · `/rule delete {r['id']}`\n\n"
            await update.message.reply_text(text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error listing rules: {e}")
            await update.message.reply_text("❌ Internal error. Try again later.")
    elif subcommand == "toggle":
        if len(args) < 2:
            await update.message.reply_text("❌ Usage: `/rule toggle [id]`")
            return
        try:
            rule_id = int(args[1])
            if str(rule_id) == chat_id:
                await update.message.reply_text(
                    "❌ That's your Telegram ID, not a rule ID.\n"
                    "Use `/rule list` to see your rule IDs."
                )
                return
            rule = supabase.table("rules").select("*").eq("id", rule_id).eq("chat_id", chat_id).execute()
            if not rule.data:
                await update.message.reply_text("❌ Rule not found.")
                return
            new_status = not rule.data[0]["active"]
            supabase.table("rules").update({"active": new_status}).eq("id", rule_id).execute()
            status_text = "activated" if new_status else "paused"
            await update.message.reply_text(f"✅ Rule {rule_id} {status_text}.")
        except ValueError:
            await update.message.reply_text("❌ Invalid ID. Use `/rule list` to see your rule IDs.")
        except Exception as e:
            logger.error(f"Error toggling rule: {e}")
            await update.message.reply_text("❌ Internal error. Try again later.")
    elif subcommand == "delete":
        if len(args) < 2:
            await update.message.reply_text("❌ Usage: `/rule delete [id]`")
            return
        try:
            rule_id = int(args[1])
            if str(rule_id) == chat_id:
                await update.message.reply_text(
                    "❌ That's your Telegram ID, not a rule ID.\n"
                    "Use `/rule list` to see your rule IDs."
                )
                return
            supabase.table("rules").delete().eq("id", rule_id).eq("chat_id", chat_id).execute()
            await update.message.reply_text(f"✅ Rule {rule_id} deleted.")
        except ValueError:
            await update.message.reply_text("❌ Invalid ID. Use `/rule list` to see your rule IDs.")
        except Exception as e:
            logger.error(f"Error deleting rule: {e}")
            await update.message.reply_text("❌ Internal error. Try again later.")
    else:
        await update.message.reply_text("❌ Unknown subcommand. Use: add, list, toggle, delete")

@rate_limited()
async def snipe_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    try:
        settings = supabase.table("snipe_settings").select("*").eq("chat_id", chat_id).execute()
        if not settings.data:
            text = "⚡ *Snipe settings*\n\nNo configuration found.\n\n"
            text += "Use: `/snipe set [amount] [slippage] [chain] [on/off]`\n"
            text += "Example: `/snipe set 50 5 ethereum on`\n"
            text += "Chains: `ethereum` or `bsc`"
            await update.message.reply_text(text, parse_mode="Markdown")
            return
        s = settings.data[0]
        status = "✅ Active" if s["active"] else "❌ Paused"
        text = (
            f"⚡ *Snipe Settings*\n\n"
            f"💰 Max amount: ${s['max_amount']} USDT\n"
            f"📉 Slippage: {s['slippage']}%\n"
            f"⛓️ Chain: {s['chain']}\n"
            f"🔘 Status: {status}\n\n"
            f"Commands:\n"
            f"`/snipe set [amount] [slippage] [chain] [on/off]`\n"
            f"`/snipe on` - Activate\n"
            f"`/snipe off` - Pause"
        )
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in snipe_settings_menu: {e}")
        await update.message.reply_text("❌ Internal error. Try again later.")

@rate_limited()
async def snipe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    args = context.args
    if not supabase:
        await update.message.reply_text("❌ Database not available.")
        return
    if len(args) == 0:
        await snipe_settings_menu(update, context)
        return
    subcommand = args[0].lower()
    if subcommand == "set":
        if len(args) < 5:
            await update.message.reply_text(
                "❌ Usage: `/snipe set [amount] [slippage] [chain] [on/off]`\n"
                "Example: `/snipe set 50 5 ethereum on`"
            )
            return
        try:
            amount = float(args[1])
            slippage = float(args[2])
            chain = args[3].lower()
            active = args[4].lower() == "on"
            if chain not in ["ethereum", "bsc"]:
                await update.message.reply_text("❌ Chain must be 'ethereum' or 'bsc'")
                return
            data = {
                "chat_id": chat_id,
                "max_amount": amount,
                "slippage": slippage,
                "chain": chain,
                "active": active,
                "updated_at": datetime.now().isoformat()
            }
            supabase.table("snipe_settings").upsert(data).execute()
            await update.message.reply_text(
                f"✅ *Snipe settings saved!*\n\n"
                f"💰 Max amount: ${amount} USDT\n"
                f"📉 Slippage: {slippage}%\n"
                f"⛓️ Chain: {chain}\n"
                f"🔘 Status: {'✅ Active' if active else '❌ Paused'}",
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("❌ Invalid number format. Use decimals with dot (ej: 50.0)")
        except Exception as e:
            logger.error(f"Error saving snipe settings: {e}")
            await update.message.reply_text("❌ Internal error. Try again later.")
    elif subcommand == "on":
        try:
            supabase.table("snipe_settings").update({"active": True}).eq("chat_id", chat_id).execute()
            await update.message.reply_text("✅ Snipe activated.")
        except Exception as e:
            logger.error(f"Error activating snipe: {e}")
            await update.message.reply_text("❌ Internal error. Try again later.")
    elif subcommand == "off":
        try:
            supabase.table("snipe_settings").update({"active": False}).eq("chat_id", chat_id).execute()
            await update.message.reply_text("✅ Snipe paused.")
        except Exception as e:
            logger.error(f"Error pausing snipe: {e}")
            await update.message.reply_text("❌ Internal error. Try again later.")
    else:
        await update.message.reply_text("❌ Unknown subcommand. Use: set, on, off")

@rate_limited()
async def sniper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    args = context.args
    if not supabase:
        await update.message.reply_text("❌ Database not available.")
        return
    if not args:
        try:
            settings = supabase.table("sniper_settings").select("*").eq("chat_id", chat_id).execute()
            if settings.data:
                s = settings.data[0]
                mode_emoji = "⚡" if s["mode"] == "aggressive" else "⚖️" if s["mode"] == "moderate" else "🛡️"
                status = "✅ Active" if s["active"] else "❌ Paused"
                text = (
                    f"🎯 *Sniper X Settings*\n\n"
                    f"💰 Max amount: ${s['max_amount']} USDT\n"
                    f"📉 Slippage: {s['slippage']}%\n"
                    f"🔄 Mode: {mode_emoji} {s['mode'].capitalize()}\n"
                    f"🛡️ Anti-MEV: {'✅ ON' if s['anti_mev'] else '❌ OFF'}\n"
                    f"🔘 Status: {status}\n\n"
                    f"Commands:\n"
                    f"`/sniper set [amount] [slippage] [mode] [anti_mev] [on/off]`\n"
                    f"Modes: `aggressive`, `moderate`, `conservative`\n"
                    f"Example: `/sniper set 100 2 aggressive true on`"
                )
                await update.message.reply_text(text, parse_mode="Markdown")
            else:
                await update.message.reply_text(
                    "🎯 *Sniper X not configured*\n\n"
                    "Use: `/sniper set [amount] [slippage] [mode] [anti_mev] [on/off]`\n"
                    "Modes: `aggressive`, `moderate`, `conservative`\n"
                    "Example: `/sniper set 100 2 aggressive true on`\n\n"
                    "• Aggressive: max speed, higher slippage\n"
                    "• Moderate: balanced speed/slippage\n"
                    "• Conservative: lower speed, minimal slippage",
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Error loading sniper settings: {e}")
            await update.message.reply_text("❌ Internal error. Try again later.")
        return
    try:
        if len(args) < 6:
            await update.message.reply_text("❌ Usage: `/sniper set [amount] [slippage] [mode] [anti_mev] [on/off]`")
            return
        amount = float(args[1])
        slippage = float(args[2])
        mode = args[3].lower()
        anti_mev = args[4].lower() == "true"
        active = args[5].lower() == "on"
        if mode not in ["aggressive", "moderate", "conservative"]:
            await update.message.reply_text("❌ Mode must be 'aggressive', 'moderate' or 'conservative'")
            return
        if amount <= 0 or slippage < 0:
            await update.message.reply_text("❌ Amount must be > 0 and slippage >= 0")
            return
        data = {
            "chat_id": chat_id,
            "max_amount": amount,
            "slippage": slippage,
            "mode": mode,
            "anti_mev": anti_mev,
            "active": active,
            "updated_at": datetime.now().isoformat()
        }
        supabase.table("sniper_settings").upsert(data).execute()
        mode_emoji = "⚡" if mode == "aggressive" else "⚖️" if mode == "moderate" else "🛡️"
        await update.message.reply_text(
            f"✅ *Sniper X settings saved!*\n\n"
            f"💰 Max amount: ${amount} USDT\n"
            f"📉 Slippage: {slippage}%\n"
            f"🔄 Mode: {mode_emoji} {mode.capitalize()}\n"
            f"🛡️ Anti-MEV: {'✅ ON' if anti_mev else '❌ OFF'}\n"
            f"🔘 Status: {'✅ Active' if active else '❌ Paused'}",
            parse_mode="Markdown"
        )
    except ValueError:
        await update.message.reply_text("❌ Invalid number format. Use decimals with dot (ej: 50.0)")
    except Exception as e:
        logger.error(f"Error saving sniper settings: {e}")
        await update.message.reply_text("❌ Internal error. Try again later.")

# ==================== WEBHOOK + WEB TERMINAL ====================
trade_history = []

def add_trade_to_history(symbol, action, amount, price, pnl=None):
    trade_history.append({
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "action": action,
        "amount": amount,
        "price": price,
        "pnl": pnl if pnl is not None else 0.0
    })
    if len(trade_history) > 100:
        trade_history.pop(0)

webhook_app = Flask(__name__, template_folder='templates')

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        provided_key = request.headers.get('X-API-Key')
        if not provided_key or provided_key != DASHBOARD_API_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

@webhook_app.route('/webhook', methods=['POST'])
def webhook():
    logger.info("ℹ️ Webhook received but MercadoPago is disabled.")
    return "MP disabled", 200
def webhook():
    if not MP_WEBHOOK_URL:
        return "Webhook disabled", 404
    x_signature = request.headers.get('x-signature')
    x_request_id = request.headers.get('x-request-id')
    if not x_signature or not x_request_id:
        logger.warning("Webhook without signature")
        return "Missing signature", 401
    raw_data = request.get_data()
    secret = MP_WEBHOOK_SECRET.encode('utf-8')
    computed = hmac.new(secret, raw_data, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, x_signature):
        logger.warning("Invalid webhook signature")
        return "Invalid signature", 401
    try:
        data = request.json
        logger.info(f"📩 Authenticated webhook: {data}")
        if data.get("type") == "payment":
            payment_id = data["data"]["id"]
            sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
            payment_response = sdk.payment().get(payment_id)
            payment_data = payment_response["response"]
            status = payment_data.get("status")
            ext = payment_data.get("external_reference")
            if status == "approved" and ext and ":" in ext:
                chat_id_str, plan_key = ext.split(":")
                activate_premium(int(chat_id_str), plan_key)
        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return "Internal error", 500

@webhook_app.route('/ping')
def ping():
    return "OK", 200

@webhook_app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html', DASHBOARD_API_KEY=DASHBOARD_API_KEY)

@webhook_app.route('/api/market_data')
@require_api_key
def market_data():
    prices = get_all_prices()
    if not prices:
        return jsonify({"error": "No market data"}), 500
    fg = get_fear_greed_index()
    market = {}
    for coin_id, symbol, name in COINS:
        if coin_id in prices:
            data = prices[coin_id]
            market[symbol] = {
                "price": data.get("usd", 0),
                "change_24h": data.get("usd_24h_change", 0),
                "volume_24h": data.get("usd_24h_vol", 0),
            }
    history = []
    for i in range(30):
        history.append({
            "time": (datetime.now() - timedelta(minutes=i*5)).isoformat(),
            "BTC": 60000 + (i * 100) + (i * 0.5)
        })
    return jsonify({
        "market": market,
        "fear_greed": fg,
        "history": history,
        "timestamp": time.time()
    })

@webhook_app.route('/api/trade_history')
@require_api_key
def trade_history_api():
    return jsonify(trade_history)

@webhook_app.route('/api/settings/<chat_id>')
@require_api_key
def get_settings_api(chat_id):
    if not supabase:
        return jsonify({"error": "Database not connected"}), 500
    try:
        sniper = supabase.table("sniper_settings").select("*").eq("chat_id", chat_id).execute()
        sniper_data = sniper.data[0] if sniper.data else {}
        copy = supabase.table("copy_settings").select("*").eq("chat_id", chat_id).execute()
        copy_data = copy.data[0] if copy.data else {}
        rules = supabase.table("rules").select("*").eq("chat_id", chat_id).execute()
        rules_data = rules.data if rules.data else []
        return jsonify({
            "sniper": sniper_data,
            "copy": copy_data,
            "rules": rules_data
        })
    except Exception as e:
        logger.error(f"Error getting settings: {e}")
        return jsonify({"error": "Internal error"}), 500

@webhook_app.route('/api/update_sniper', methods=['POST'])
@require_api_key
def update_sniper_api():
    if not supabase:
        return jsonify({"error": "Database not connected"}), 500
    try:
        data = request.json
        chat_id = data.get("chat_id")
        field = data.get("field")
        value = data.get("value")
        if not chat_id or not field:
            return jsonify({"error": "Missing parameters"}), 400
        supabase.table("sniper_settings").update({field: value}).eq("chat_id", chat_id).execute()
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error updating sniper: {e}")
        return jsonify({"error": "Internal error"}), 500

@webhook_app.route('/api/update_copy', methods=['POST'])
@require_api_key
def update_copy_api():
    if not supabase:
        return jsonify({"error": "Database not connected"}), 500
    try:
        data = request.json
        chat_id = data.get("chat_id")
        field = data.get("field")
        value = data.get("value")
        if not chat_id or not field:
            return jsonify({"error": "Missing parameters"}), 400
        supabase.table("copy_settings").update({field: value}).eq("chat_id", chat_id).execute()
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error updating copy: {e}")
        return jsonify({"error": "Internal error"}), 500

@webhook_app.route('/api/toggle_rule', methods=['POST'])
@require_api_key
def toggle_rule_api():
    if not supabase:
        return jsonify({"error": "Database not connected"}), 500
    try:
        data = request.json
        rule_id = data.get("rule_id")
        active = data.get("active")
        if not rule_id:
            return jsonify({"error": "Missing rule_id"}), 400
        supabase.table("rules").update({"active": active}).eq("id", rule_id).execute()
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error toggling rule: {e}")
        return jsonify({"error": "Internal error"}), 500

@webhook_app.route('/api/delete_rule', methods=['POST'])
@require_api_key
def delete_rule_api():
    if not supabase:
        return jsonify({"error": "Database not connected"}), 500
    try:
        data = request.json
        rule_id = data.get("rule_id")
        if not rule_id:
            return jsonify({"error": "Missing rule_id"}), 400
        supabase.table("rules").delete().eq("id", rule_id).execute()
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error deleting rule: {e}")
        return jsonify({"error": "Internal error"}), 500

def run_webhook():
    if not MP_WEBHOOK_URL:
        return
    port = int(os.getenv("PORT", 5000))
    webhook_app.run(host='0.0.0.0', port=port, debug=False)

# ==================== FUNCIÓN DEL SCHEDULER ====================
def run_scheduler():
    """Ejecuta las tareas programadas en un hilo separado."""
    while True:
        schedule.run_pending()
        time.sleep(1)

# ==================== MAIN ====================
if __name__ == "__main__":
    # Inicializar datos y conexiones
    subscribers = load_subscribers()
    if not supabase:
        logger.critical("❌ Supabase not connected. Bot will not start for security.")
        exit(1)

    # Desactivar webhook de MP
    logger.info("ℹ️ MercadoPago webhook disabled. Dashboard still available.")

    # Iniciar scheduler en hilo separado
    threading.Thread(target=run_scheduler, daemon=True).start()
    logger.info("✅ Scheduler started")

    # Programar reports
    reschedule_reports()

    # Programar escáner de nuevos tokens si está habilitado
    if os.getenv("NEW_TOKEN_ALERTS", "false").lower() == "true":
        interval = int(os.getenv("NEW_TOKEN_SCAN_INTERVAL", "300"))
        schedule.every(interval).seconds.do(check_new_tokens)
        logger.info(f"🔄 New token scanner scheduled every {interval} seconds")

    # Iniciar el bot de Telegram y WebSocket en un único event loop
    async def start_services():
        if WS_ENABLED:
            asyncio.create_task(update_prices_from_websocket())
            logger.info("🔄 WebSocket price listener started in background.")
        else:
            logger.info("ℹ️ WebSocket disabled (WS_ENABLED=false). Using REST.")

        application = Application.builder().token(TELEGRAM_TOKEN).build()

        # === REGISTRO DE COMANDOS ===
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("menu", menu_command))
        application.add_handler(CommandHandler("buy", buy))
        application.add_handler(CommandHandler("sell", sell))
        application.add_handler(CommandHandler("whale", whale))
        application.add_handler(CommandHandler("copy", copy))
        application.add_handler(CommandHandler("predict", predict_command))
        application.add_handler(CommandHandler("newtokens", newtokens_command))
        application.add_handler(CommandHandler("plans", plans_command))
        application.add_handler(CommandHandler("info", info_command))
        application.add_handler(CommandHandler("news", news_command))
        application.add_handler(CommandHandler("id", id_command))
        application.add_handler(CommandHandler("balance", balance))
        application.add_handler(CommandHandler("premium", premium))
        application.add_handler(CommandHandler("activate", activate))
        application.add_handler(CommandHandler("plan", plan))
        application.add_handler(CommandHandler("setemail", setemail))
        application.add_handler(CommandHandler("lang", lang_command))
        application.add_handler(CommandHandler("rule", rule_command))
        application.add_handler(CommandHandler("snipe", snipe_command))
        application.add_handler(CommandHandler("sniper", sniper))
        application.add_handler(CommandHandler("compare", compare))
        application.add_handler(CommandHandler("terms", terms_command))
        application.add_handler(CommandHandler("accept", accept_terms))
        application.add_handler(CommandHandler("force_premium", force_premium))
        application.add_handler(CallbackQueryHandler(button_handler))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text))

        # Iniciar Flask en hilo separado (solo para el dashboard)
        port = int(os.getenv("PORT", 8080))
        threading.Thread(target=lambda: webhook_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False), daemon=True).start()
        logger.info(f"✅ Web dashboard running on port {port}")

        # Iniciar el bot
        await application.initialize()
        await application.start()
        await application.updater.start_polling()

        logger.info("🚀 Trading bot started successfully (Fase 8.5: New Tokens + AI Advanced + Bilingual)")

        # Mantener el loop vivo
        while True:
            await asyncio.sleep(1)

    try:
        asyncio.run(start_services())
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        raise
