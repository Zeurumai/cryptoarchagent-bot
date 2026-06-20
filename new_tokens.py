import os
import json
import logging
import requests
from datetime import datetime, timedelta
from supabase import create_client, Client

logger = logging.getLogger(__name__)

# ==================== CONFIGURACIÓN ====================
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# ==================== INICIALIZACIÓN SEGURA DE SUPABASE ====================
supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        # Prueba rápida de conexión (opcional)
        # supabase.table("new_tokens").select("count").limit(1).execute()
        logger.info("✅ Supabase client initialized for new_tokens")
    except Exception as e:
        # Cambiado a WARNING para no ensuciar los logs con errores
        logger.warning(f"⚠️ Supabase connection failed in new_tokens: {e}. Using local storage.")
        supabase = None
else:
    logger.warning("⚠️ SUPABASE_URL or SUPABASE_KEY not set. New tokens will be stored locally.")

# ==================== ALMACENAMIENTO LOCAL (fallback) ====================
LOCAL_TOKENS_FILE = "new_tokens_cache.json"

def _load_local_tokens():
    try:
        with open(LOCAL_TOKENS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def _save_local_tokens(tokens):
    with open(LOCAL_TOKENS_FILE, "w") as f:
        json.dump(tokens, f, indent=2, default=str)

# ==================== FUNCIONES PRINCIPALES ====================

def scan_new_pools(limit: int = 10, min_liquidity: float = 5000) -> list:
    """
    Escanea nuevos pools en DEX (simulado). En producción, conectar a alguna API.
    """
    # Simulación: en realidad deberías usar DEX APIs (p. ej., DexScreener, Birdeye, etc.)
    sample_tokens = [
        {
            "address": "0x123...abc",
            "symbol": "NEW1",
            "name": "New Token 1",
            "chain": "ethereum",
            "liquidity_usd": 12000,
            "volume_24h": 50000,
            "price_usd": 0.05,
            "created_at": datetime.now().isoformat(),
            "buy_tax": 0,
            "sell_tax": 0,
            "holder_count": 150
        },
        {
            "address": "0x456...def",
            "symbol": "NEW2",
            "name": "New Token 2",
            "chain": "bsc",
            "liquidity_usd": 8000,
            "volume_24h": 30000,
            "price_usd": 0.02,
            "created_at": datetime.now().isoformat(),
            "buy_tax": 2,
            "sell_tax": 2,
            "holder_count": 80
        }
    ]
    filtered = [t for t in sample_tokens if t.get("liquidity_usd", 0) >= min_liquidity]
    return filtered[:limit]

def get_recent_tokens(limit: int = 10) -> list:
    if supabase:
        try:
            response = supabase.table("new_tokens").select("*").order("created_at", desc=True).limit(limit).execute()
            return response.data if response.data else []
        except Exception as e:
            logger.error(f"Error fetching tokens from Supabase: {e}")
            tokens = _load_local_tokens()
            return tokens[:limit] if tokens else []
    else:
        tokens = _load_local_tokens()
        return tokens[:limit] if tokens else []

def save_new_tokens(tokens: list):
    if not tokens:
        return
    if supabase:
        try:
            for token in tokens:
                existing = supabase.table("new_tokens").select("address").eq("address", token["address"]).execute()
                if not existing.data:
                    supabase.table("new_tokens").insert(token).execute()
            logger.info(f"✅ Saved {len(tokens)} new tokens to Supabase")
        except Exception as e:
            logger.error(f"Error saving tokens to Supabase: {e}")
            local = _load_local_tokens()
            existing_addresses = {t["address"] for t in local}
            for token in tokens:
                if token["address"] not in existing_addresses:
                    local.append(token)
            _save_local_tokens(local)
    else:
        local = _load_local_tokens()
        existing_addresses = {t["address"] for t in local}
        for token in tokens:
            if token["address"] not in existing_addresses:
                local.append(token)
        _save_local_tokens(local)

def format_token_message(token: dict) -> str:
    name = token.get("name", "Unknown")
    symbol = token.get("symbol", "???")
    address = token.get("address", "")
    chain = token.get("chain", "unknown")
    price = token.get("price_usd", 0)
    liquidity = token.get("liquidity_usd", 0)
    volume = token.get("volume_24h", 0)
    holders = token.get("holder_count", "?")
    msg = f"🪙 *{name} ({symbol})*\n"
    msg += f"   🔗 Chain: {chain.capitalize()}\n"
    msg += f"   💰 Price: ${price:.4f}\n"
    msg += f"   💧 Liquidity: ${liquidity:,.0f}\n"
    msg += f"   📊 24h Volume: ${volume:,.0f}\n"
    msg += f"   👥 Holders: {holders}\n"
    if token.get("buy_tax") or token.get("sell_tax"):
        msg += f"   💰 Buy Tax: {token.get('buy_tax', 0)}% | Sell Tax: {token.get('sell_tax', 0)}%\n"
    msg += f"   🆔 `{address[:8]}...{address[-6:]}`"
    return msg
