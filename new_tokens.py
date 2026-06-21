import os
import json
import logging
from datetime import datetime

# ==================== IMPORTACIÓN SEGURA DE SUPABASE ====================
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    create_client = None
    Client = None
    logging.getLogger(__name__).warning("⚠️ Supabase library not installed. Using local storage only.")

logger = logging.getLogger(__name__)

# ==================== CONFIGURACIÓN ====================
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# ==================== INICIALIZACIÓN DE SUPABASE (SOLO SI ESTÁ DISPONIBLE) ====================
supabase = None
if SUPABASE_AVAILABLE and SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("✅ Supabase client initialized for new_tokens")
    except Exception as e:
        logger.warning(f"⚠️ Supabase init failed: {e}. Using local storage.")
        supabase = None
else:
    if not SUPABASE_AVAILABLE:
        logger.warning("⚠️ Supabase library not installed. Using local storage.")
    elif not SUPABASE_URL or not SUPABASE_KEY:
        logger.warning("⚠️ SUPABASE_URL or SUPABASE_KEY not set. Using local storage.")

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

def scan_new_pools(limit=10, min_liquidity=5000):
    """
    Escanea nuevos pools en DEX (simulado).
    En producción, reemplazar con llamada a DexScreener, Birdeye, etc.
    """
    # Datos de ejemplo (puedes reemplazar con API real)
    sample_tokens = [
        {
            "address": "0x123abc...",
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
            "address": "0x456def...",
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
    # Filtrar por liquidez mínima
    filtered = [t for t in sample_tokens if t.get("liquidity_usd", 0) >= min_liquidity]
    return filtered[:limit]

def get_recent_tokens(limit=10):
    """
    Obtiene tokens recientes desde Supabase si está disponible, sino desde local.
    """
    if supabase is not None:
        try:
            response = supabase.table("new_tokens").select("*").order("created_at", desc=True).limit(limit).execute()
            return response.data if response.data else []
        except Exception as e:
            logger.error(f"Error fetching tokens from Supabase: {e}")
            return _load_local_tokens()[:limit]
    else:
        return _load_local_tokens()[:limit]

def save_new_tokens(tokens):
    """
    Guarda tokens nuevos en Supabase si está disponible, sino en local.
    """
    if not tokens:
        return
    if supabase is not None:
        try:
            for token in tokens:
                # Evitar duplicados por address
                existing = supabase.table("new_tokens").select("address").eq("address", token["address"]).execute()
                if not existing.data:
                    supabase.table("new_tokens").insert(token).execute()
            logger.info(f"✅ Saved {len(tokens)} new tokens to Supabase")
        except Exception as e:
            logger.error(f"Error saving tokens to Supabase: {e}")
            # Guardar local
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

def format_token_message(token):
    """
    Formatea un token para mensaje de Telegram.
    """
    name = token.get("name", "Unknown")
    symbol = token.get("symbol", "???")
    address = token.get("address", "")
    chain = token.get("chain", "unknown")
    price = token.get("price_usd", 0)
    liquidity = token.get("liquidity_usd", 0)
    volume = token.get("volume_24h", 0)
    holders = token.get("holder_count", "?")
    buy_tax = token.get("buy_tax", 0)
    sell_tax = token.get("sell_tax", 0)
    
    msg = f"🪙 *{name} ({symbol})*\n"
    msg += f"   🔗 Chain: {chain.capitalize()}\n"
    msg += f"   💰 Price: ${price:.4f}\n"
    msg += f"   💧 Liquidity: ${liquidity:,.0f}\n"
    msg += f"   📊 24h Volume: ${volume:,.0f}\n"
    msg += f"   👥 Holders: {holders}\n"
    if buy_tax or sell_tax:
        msg += f"   💰 Buy Tax: {buy_tax}% | Sell Tax: {sell_tax}%\n"
    msg += f"   🆔 `{address[:8]}...{address[-6:]}`"
    return msg

# ==================== PRUEBA RÁPIDA ====================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    tokens = scan_new_pools()
    print(f"🔍 Tokens encontrados: {len(tokens)}")
    for t in tokens:
        print(format_token_message(t))
        print("-" * 40)
