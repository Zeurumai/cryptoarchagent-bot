# new_tokens.py - Detección de nuevos proyectos y pools de liquidez
import os
import time
import logging
import requests
from datetime import datetime, timedelta
from supabase import create_client, Client

logger = logging.getLogger(__name__)

# Configuración
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
DEXSCREENER_API_URL = "https://api.dexscreener.com/latest/dex/search"

# Inicializar Supabase si está disponible
if SUPABASE_URL and SUPABASE_KEY:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    supabase = None
    logger.warning("⚠️ Supabase not configured for new_tokens. Using local storage.")

# Almacenamiento local (fallback)
NEW_TOKENS_STORE = []

# Última vez que se ejecutó el escaneo
last_scan_time = 0

def fetch_new_pools(query: str = "?q=") -> list:
    """
    Obtiene pools de DEX Screener para una búsqueda.
    Por defecto, busca "?q=" (todos los listados recientes).
    Podríamos hacer búsquedas específicas por símbolo o contrato.
    """
    try:
        url = f"{DEXSCREENER_API_URL}{query}"
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("pairs"):
                return data["pairs"]
        else:
            logger.error(f"DEX Screener error: {response.status_code}")
    except Exception as e:
        logger.error(f"Error fetching new pools: {e}")
    return []

def filter_new_pools(pools: list, min_liquidity: float = 5000, min_age_minutes: int = 30) -> list:
    """
    Filtra pools que cumplan:
    - Liquidez >= min_liquidity
    - Creados en los últimos min_age_minutes minutos
    - No son honeypot (según GoPlusLabs)
    """
    filtered = []
    now = time.time()
    for pool in pools:
        # Verificar que tenga datos de liquidez
        liquidity = float(pool.get("liquidity", {}).get("usd", 0))
        if liquidity < min_liquidity:
            continue
        
        # Verificar antigüedad (si el pool tiene timestamp de creación)
        # DEX Screener no siempre da timestamp, pero podemos usar el primer bloque o confiar en que es reciente
        # Por simplicidad, asumimos que los pools devueltos son recientes (últimos minutos)
        # Si tiene "creationTime", lo usamos; si no, asumimos que es reciente
        created_at = pool.get("pairCreatedAt", 0) / 1000  # en milisegundos
        if created_at > 0:
            age_minutes = (now - created_at) / 60
            if age_minutes > min_age_minutes:
                continue
        
        # Verificar seguridad (opcional, podemos hacerlo después)
        # Añadimos el pool a la lista filtrada
        filtered.append(pool)
    return filtered

def check_token_security(contract_address: str, chain: str = "ethereum") -> dict:
    """
    Reutiliza la función de trading_bot.py, pero la definimos aquí también por si acaso.
    """
    # Importamos la función desde trading_bot (si existe) o la implementamos.
    # Para no crear dependencia circular, la implementamos localmente.
    GOPLUS_API_KEY = os.getenv("GOPLUS_API_KEY", "")
    if not GOPLUS_API_KEY:
        return {"risk_score": 0, "warnings": ["⚠️ No API key for security check"]}
    try:
        url = f"https://api.gopluslabs.io/api/v1/token_security/{chain}?contract_addresses={contract_address}"
        headers = {"X-API-Key": GOPLUS_API_KEY}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("code") == 1:
                result = data.get("result", {})
                token_data = result.get(contract_address.lower(), {})
                is_honeypot = token_data.get("is_honeypot", False)
                liquidity_locked = token_data.get("liquidity_locked", False)
                owner_renounced = token_data.get("owner_renounced", False)
                risk_score = 0
                warnings = []
                if is_honeypot:
                    risk_score += 40
                    warnings.append("🚨 Honeypot detected")
                if not liquidity_locked:
                    risk_score += 20
                    warnings.append("⚠️ Liquidity not locked")
                if not owner_renounced:
                    risk_score += 10
                    warnings.append("⚠️ Owner not renounced")
                return {
                    "risk_score": min(100, risk_score),
                    "warnings": warnings,
                    "is_honeypot": is_honeypot
                }
    except Exception as e:
        logger.error(f"Security check error: {e}")
    return {"risk_score": 0, "warnings": []}

def store_token(token_data: dict):
    """
    Guarda el token en Supabase para evitar duplicados.
    """
    if supabase:
        try:
            # Verificar si ya existe
            existing = supabase.table("new_tokens").select("*").eq("pair_address", token_data["pair_address"]).execute()
            if existing.data:
                return False  # ya existe
            
            # Insertar
            supabase.table("new_tokens").insert({
                "chain": token_data.get("chain", "ethereum"),
                "pair_address": token_data["pair_address"],
                "base_token": token_data.get("base_token", {}).get("symbol", "UNKNOWN"),
                "quote_token": token_data.get("quote_token", {}).get("symbol", "USDT"),
                "dex": token_data.get("dexId", "unknown"),
                "liquidity_usd": token_data.get("liquidity", {}).get("usd", 0),
                "price_usd": token_data.get("price_usd", 0),
                "created_at": datetime.now().isoformat(),
                "risk_score": token_data.get("risk_score", 0),
                "warnings": token_data.get("warnings", [])
            }).execute()
            return True
        except Exception as e:
            logger.error(f"Error storing token: {e}")
    else:
        # Fallback local
        if token_data["pair_address"] not in [t["pair_address"] for t in NEW_TOKENS_STORE]:
            NEW_TOKENS_STORE.append(token_data)
            return True
    return False

def get_recent_tokens(limit: int = 10) -> list:
    """
    Obtiene los últimos tokens detectados.
    """
    if supabase:
        try:
            response = supabase.table("new_tokens").select("*").order("created_at", desc=True).limit(limit).execute()
            return response.data if response.data else []
        except Exception as e:
            logger.error(f"Error fetching recent tokens: {e}")
    return NEW_TOKENS_STORE[-limit:]

def scan_new_pools() -> list:
    """
    Escanea nuevos pools en todas las cadenas configuradas.
    Retorna una lista de tokens nuevos detectados.
    """
    chains = ["ethereum", "bsc", "solana", "polygon", "arbitrum"]
    new_tokens = []
    for chain in chains:
        # DEX Screener no soporta búsqueda por cadena fácilmente, pero podemos buscar por nombre de cadena en la URL
        # Ejemplo: ?q=ethereum
        query = f"?q={chain}"
        pools = fetch_new_pools(query)
        if not pools:
            continue
        filtered = filter_new_pools(pools, min_liquidity=5000, min_age_minutes=30)
        for pool in filtered:
            # Extraer información relevante
            base_token = pool.get("baseToken", {})
            quote_token = pool.get("quoteToken", {})
            token_data = {
                "chain": chain,
                "pair_address": pool.get("pairAddress", ""),
                "base_token": base_token.get("symbol", "UNKNOWN"),
                "quote_token": quote_token.get("symbol", "USDT"),
                "dex": pool.get("dexId", "unknown"),
                "liquidity": pool.get("liquidity", {}).get("usd", 0),
                "price_usd": pool.get("priceUsd", 0),
                "contract_address": base_token.get("address", ""),
            }
            # Verificar seguridad
            if token_data["contract_address"]:
                security = check_token_security(token_data["contract_address"], chain)
                token_data["risk_score"] = security.get("risk_score", 0)
                token_data["warnings"] = security.get("warnings", [])
                # Si es honeypot o riesgo alto, lo descartamos
                if security.get("is_honeypot", False) or token_data["risk_score"] > 50:
                    continue
            # Guardar
            if store_token(token_data):
                new_tokens.append(token_data)
    return new_tokens

def format_token_message(token: dict) -> str:
    """
    Formatea un token para mostrarlo en un mensaje de Telegram.
    """
    chain_emoji = {
        "ethereum": "⟠",
        "bsc": "🟡",
        "solana": "◎",
        "polygon": "🟣",
        "arbitrum": "🔵"
    }
    emoji = chain_emoji.get(token.get("chain", "ethereum"), "🔗")
    risk_emoji = "🟢" if token.get("risk_score", 0) < 20 else "🟡" if token.get("risk_score", 0) < 50 else "🔴"
    msg = f"{emoji} *{token['base_token']}* / *{token['quote_token']}*\n"
    msg += f"   💰 Liquidity: ${token.get('liquidity_usd', 0):,.0f}\n"
    msg += f"   💵 Price: ${token.get('price_usd', 0):,.6f}\n"
    msg += f"   🛡️ Risk: {risk_emoji} {token.get('risk_score', 0)}/100\n"
    if token.get("warnings"):
        for warn in token["warnings"][:2]:
            msg += f"   ⚠️ {warn}\n"
    msg += f"   🔗 Dex: {token.get('dex', 'unknown')}\n"
    if token.get("pair_address"):
        msg += f"   🆔 `{token['pair_address'][:10]}...`\n"
    return msg
