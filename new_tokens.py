import os
import json
import logging
from datetime import datetime
from supabase import create_client, Client

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# Inicialización segura
supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        # Prueba simple de conexión (opcional)
        logger.info("✅ Supabase client initialized for new_tokens")
    except Exception as e:
        logger.warning(f"⚠️ Supabase init failed: {e}. Using local storage.")
        supabase = None
else:
    logger.warning("⚠️ SUPABASE_URL or SUPABASE_KEY not set. Using local storage.")

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

def scan_new_pools(limit=10, min_liquidity=5000):
    # Simulación; reemplaza con API real si quieres
    sample = [
        {"address": "0x123...", "symbol": "NEW1", "name": "New Token 1",
         "chain": "ethereum", "liquidity_usd": 12000, "volume_24h": 50000,
         "price_usd": 0.05, "created_at": datetime.now().isoformat(),
         "buy_tax": 0, "sell_tax": 0, "holder_count": 150}
    ]
    return [t for t in sample if t.get("liquidity_usd", 0) >= min_liquidity][:limit]

def get_recent_tokens(limit=10):
    if supabase:
        try:
            resp = supabase.table("new_tokens").select("*").order("created_at", desc=True).limit(limit).execute()
            return resp.data if resp.data else []
        except Exception:
            return _load_local_tokens()[:limit]
    return _load_local_tokens()[:limit]

def save_new_tokens(tokens):
    if not tokens:
        return
    if supabase:
        try:
            for t in tokens:
                existing = supabase.table("new_tokens").select("address").eq("address", t["address"]).execute()
                if not existing.data:
                    supabase.table("new_tokens").insert(t).execute()
            logger.info(f"✅ Saved {len(tokens)} new tokens to Supabase")
        except Exception as e:
            logger.error(f"Error saving tokens: {e}")
            _save_local_tokens(_load_local_tokens() + tokens)
    else:
        _save_local_tokens(_load_local_tokens() + tokens)

def format_token_message(token):
    return (f"🪙 *{token.get('name', 'Unknown')} ({token.get('symbol', '???')})*\n"
            f"   🔗 Chain: {token.get('chain', 'unknown').capitalize()}\n"
            f"   💰 Price: ${token.get('price_usd', 0):.4f}\n"
            f"   💧 Liquidity: ${token.get('liquidity_usd', 0):,.0f}\n"
            f"   👥 Holders: {token.get('holder_count', '?')}\n"
            f"   🆔 `{token.get('address', '')[:8]}...{token.get('address', '')[-6:]}`")
