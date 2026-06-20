import os
import time
import logging
import requests
from datetime import datetime
from supabase import create_client, Client

logger = logging.getLogger(__name__)

# ==================== CONFIGURACIÓN ====================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GOPLUS_API_KEY = os.getenv("GOPLUS_API_KEY", "")
DEXSCREENER_API_URL = "https://api.dexscreener.com/latest/dex/search"

if SUPABASE_URL and SUPABASE_KEY:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    supabase = None
    logger.warning("⚠️ Supabase not configured for new_tokens. Using local storage.")

NEW_TOKENS_STORE = []

# ==================== CADENAS SOPORTADAS (8 cadenas) ====================
chains = [
    "ethereum",
    "bsc",
    "solana",
    "polygon",
    "arbitrum",
    "avalanche",
    "base",
    "optimism"
]

# ==================== FUNCIONES PRINCIPALES ====================

def fetch_new_pools(query: str = "?q=") -> list:
    """Obtiene pools de DEX Screener para una búsqueda."""
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
    """Filtra pools por liquidez y antigüedad."""
    filtered = []
    now = time.time()
    for pool in pools:
        liquidity = float(pool.get("liquidity", {}).get("usd", 0))
        if liquidity < min_liquidity:
            continue
        created_at = pool.get("pairCreatedAt", 0) / 1000
        if created_at > 0:
            age_minutes = (now - created_at) / 60
            if age_minutes > min_age_minutes:
                continue
        filtered.append(pool)
    return filtered

def check_token_security(contract_address: str, chain: str = "ethereum") -> dict:
    """Verifica la seguridad del token con GoPlus Labs."""
    if not GOPLUS_API_KEY:
        return {
            "risk_score": 0,
            "warnings": ["⚠️ No API key for security check"],
            "is_honeypot": False,
            "is_whitelist_only": False,
            "is_blacklisted": False,
            "can_sell": True,
            "liquidity_locked": True,
            "owner_renounced": False,
            "buy_tax": 0,
            "sell_tax": 0,
            "holder_count": 0,
            "owner_balance": 0
        }
    try:
        url = f"https://api.gopluslabs.io/api/v1/token_security/{chain}?contract_addresses={contract_address}"
        headers = {"X-API-Key": GOPLUS_API_KEY}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            logger.error(f"GoPlus API error: {response.status_code}")
            return {"risk_score": 0, "warnings": ["⚠️ Could not verify contract"]}
        
        data = response.json()
        if data.get("code") != 1:
            return {"risk_score": 0, "warnings": ["⚠️ Verification error"]}
        
        result = data.get("result", {})
        token_data = result.get(contract_address.lower(), {})
        
        # ===== CAMPOS DE SEGURIDAD =====
        is_honeypot = token_data.get("is_honeypot", False)
        is_whitelist_only = token_data.get("is_whitelist_only", False)
        is_blacklisted = token_data.get("is_blacklisted", False)
        liquidity_locked = token_data.get("liquidity_locked", False)
        owner_renounced = token_data.get("owner_renounced", False)
        buy_tax = float(token_data.get("buy_tax", 0))
        sell_tax = float(token_data.get("sell_tax", 0))
        owner_balance = token_data.get("owner_balance", 0)
        holder_count = int(token_data.get("holder_count", 0))
        
        # ===== CÁLCULO DE RIESGO =====
        risk_score = 0
        warnings = []
        
        if is_honeypot:
            risk_score += 40
            warnings.append("🚨 Honeypot detected (cannot sell)")
        if is_whitelist_only:
            risk_score += 30
            warnings.append("🚨 Whitelist only (cannot sell)")
        if is_blacklisted:
            risk_score += 20
            warnings.append("🚨 Blacklisted token")
        if not liquidity_locked:
            risk_score += 20
            warnings.append("⚠️ Liquidity not locked (rug pull risk)")
        if not owner_renounced:
            risk_score += 10
            warnings.append("⚠️ Owner not renounced (can modify contract)")
        if buy_tax > 10:
            risk_score += 10
            warnings.append(f"⚠️ High buy tax: {buy_tax}%")
        if sell_tax > 10:
            risk_score += 10
            warnings.append(f"⚠️ High sell tax: {sell_tax}%")
        try:
            owner_bal = float(owner_balance)
            if owner_bal > 5:
                risk_score += 10
                warnings.append(f"⚠️ Owner holds {owner_bal:.1f}% of supply")
        except:
            pass
        if holder_count < 100 and holder_count > 0:
            risk_score += 5
            warnings.append(f"⚠️ Only {holder_count} holders")
        
        return {
            "is_honeypot": is_honeypot,
            "is_whitelist_only": is_whitelist_only,
            "is_blacklisted": is_blacklisted,
            "can_sell": not is_honeypot and not is_whitelist_only and not is_blacklisted,
            "liquidity_locked": liquidity_locked,
            "owner_renounced": owner_renounced,
            "buy_tax": buy_tax,
            "sell_tax": sell_tax,
            "holder_count": holder_count,
            "owner_balance": owner_balance,
            "risk_score": min(100, risk_score),
            "warnings": warnings
        }
    except Exception as e:
        logger.error(f"Security check error: {e}")
        return {"risk_score": 0, "warnings": ["⚠️ Error verifying token"]}

def calculate_opportunity_score(token_data: dict) -> int:
    """
    Calcula un score de oportunidad (0-100) para un token.
    Basado en volumen, liquidez, holders, y cambios de precio.
    """
    score = 0
    
    # Factor 1: Volumen en 24h (máximo 30 puntos)
    volume = token_data.get("volume_24h", 0)
    if volume > 100000:
        score += 30
    elif volume > 50000:
        score += 20
    elif volume > 10000:
        score += 10
    
    # Factor 2: Liquidez (máximo 25 puntos)
    liquidity = token_data.get("liquidity_usd", 0)
    if liquidity > 50000:
        score += 25
    elif liquidity > 20000:
        score += 15
    elif liquidity > 5000:
        score += 5
    
    # Factor 3: Holders (máximo 20 puntos)
    holders = token_data.get("holder_count", 0)
    if holders > 500:
        score += 20
    elif holders > 200:
        score += 10
    elif holders > 50:
        score += 5
    
    # Factor 4: Cambio de precio en 24h (máximo 15 puntos)
    price_change = token_data.get("price_change_24h", 0)
    if price_change > 50:
        score += 15
    elif price_change > 20:
        score += 10
    elif price_change > 5:
        score += 5
    
    # Factor 5: Edad del token (máximo 10 puntos)
    # Tokens nuevos tienen más oportunidad de crecimiento
    age_hours = token_data.get("age_hours", 24)
    if age_hours < 1:
        score += 10
    elif age_hours < 6:
        score += 5
    
    return min(100, score)

def store_token(token_data: dict) -> bool:
    """Guarda el token en Supabase para evitar duplicados."""
    if supabase:
        try:
            existing = supabase.table("new_tokens").select("*").eq("pair_address", token_data["pair_address"]).execute()
            if existing.data:
                return False
            supabase.table("new_tokens").insert({
                "chain": token_data.get("chain", "ethereum"),
                "pair_address": token_data["pair_address"],
                "base_token": token_data.get("base_token", "UNKNOWN"),
                "quote_token": token_data.get("quote_token", "USDT"),
                "dex": token_data.get("dex", "unknown"),
                "liquidity_usd": token_data.get("liquidity_usd", 0),
                "price_usd": token_data.get("price_usd", 0),
                "price_change_24h": token_data.get("price_change_24h", 0),
                "volume_24h": token_data.get("volume_24h", 0),
                "age_hours": token_data.get("age_hours", 0),
                "risk_score": token_data.get("risk_score", 0),
                "opportunity_score": token_data.get("opportunity_score", 0),
                "buy_tax": token_data.get("buy_tax", 0),
                "sell_tax": token_data.get("sell_tax", 0),
                "holder_count": token_data.get("holder_count", 0),
                "warnings": token_data.get("warnings", []),
                "created_at": datetime.now().isoformat()
            }).execute()
            return True
        except Exception as e:
            logger.error(f"Error storing token: {e}")
    else:
        if token_data["pair_address"] not in [t["pair_address"] for t in NEW_TOKENS_STORE]:
            NEW_TOKENS_STORE.append(token_data)
            return True
    return False

def get_recent_tokens(limit: int = 10) -> list:
    """Obtiene los últimos tokens detectados."""
    if supabase:
        try:
            response = supabase.table("new_tokens").select("*").order("created_at", desc=True).limit(limit).execute()
            return response.data if response.data else []
        except Exception as e:
            logger.error(f"Error fetching recent tokens: {e}")
    return NEW_TOKENS_STORE[-limit:]

def scan_new_pools() -> list:
    """Escanea nuevos pools en todas las cadenas configuradas."""
    new_tokens = []
    for chain in chains:
        query = f"?q={chain}"
        pools = fetch_new_pools(query)
        if not pools:
            continue
        filtered = filter_new_pools(pools, min_liquidity=5000, min_age_minutes=30)
        for pool in filtered:
            base_token = pool.get("baseToken", {})
            quote_token = pool.get("quoteToken", {})
            
            # Calcular edad del token
            created_at = pool.get("pairCreatedAt", 0)
            age_hours = 0
            if created_at > 0:
                age_hours = (time.time() - (created_at / 1000)) / 3600
            
            token_data = {
                "chain": chain,
                "pair_address": pool.get("pairAddress", ""),
                "base_token": base_token.get("symbol", "UNKNOWN"),
                "quote_token": quote_token.get("symbol", "USDT"),
                "dex": pool.get("dexId", "unknown"),
                "liquidity_usd": pool.get("liquidity", {}).get("usd", 0),
                "price_usd": pool.get("priceUsd", 0),
                "price_change_24h": pool.get("priceChange", {}).get("h24", 0),
                "volume_24h": pool.get("volume", {}).get("h24", 0),
                "contract_address": base_token.get("address", ""),
                "age_hours": age_hours,
                "holder_count": 0,  # Se actualiza con GoPlus
                "buy_tax": 0,
                "sell_tax": 0,
                "risk_score": 0,
                "opportunity_score": 0,
                "warnings": []
            }
            
            if token_data["contract_address"]:
                # Análisis de seguridad con GoPlus
                security = check_token_security(token_data["contract_address"], chain)
                token_data.update(security)
                
                # Calcular score de oportunidad
                token_data["opportunity_score"] = calculate_opportunity_score(token_data)
                
                # Si es honeypot o riesgo alto, descartar
                if security.get("is_honeypot", False) or token_data["risk_score"] > 50:
                    continue
            
            # Guardar en base de datos
            if store_token(token_data):
                new_tokens.append(token_data)
    
    return new_tokens

def format_token_message(token: dict) -> str:
    """Formatea un token para mostrarlo en un mensaje de Telegram, incluyendo scores."""
    chain_emoji = {
        "ethereum": "⟠",
        "bsc": "🟡",
        "solana": "◎",
        "polygon": "🟣",
        "arbitrum": "🔵",
        "avalanche": "❄️",
        "base": "🟦",
        "optimism": "🔷"
    }
    emoji = chain_emoji.get(token.get("chain", "ethereum"), "🔗")
    
    # Emojis para los scores
    risk_emoji = "🟢" if token.get("risk_score", 0) < 20 else "🟡" if token.get("risk_score", 0) < 50 else "🔴"
    opp_emoji = "🟢" if token.get("opportunity_score", 0) > 70 else "🟡" if token.get("opportunity_score", 0) > 40 else "🔴"
    
    msg = f"{emoji} *{token['base_token']}* / *{token['quote_token']}*\n"
    msg += f"   💰 Liquidity: ${token.get('liquidity_usd', 0):,.0f}\n"
    msg += f"   💵 Price: ${token.get('price_usd', 0):,.6f}\n"
    msg += f"   📈 24h Change: {token.get('price_change_24h', 0):+.1f}%\n"
    msg += f"   🛡️ *Riesgo:* {risk_emoji} {token.get('risk_score', 0)}/100\n"
    msg += f"   🚀 *Oportunidad:* {opp_emoji} {token.get('opportunity_score', 0)}/100\n"
    
    if token.get("warnings"):
        for warn in token["warnings"][:2]:
            msg += f"   ⚠️ {warn}\n"
    msg += f"   🔗 Dex: {token.get('dex', 'unknown')}\n"
    if token.get("pair_address"):
        msg += f"   🆔 `{token['pair_address'][:10]}...`\n"
    if token.get("buy_tax") or token.get("sell_tax"):
        msg += f"   💰 Buy Tax: {token.get('buy_tax', 0)}% | Sell Tax: {token.get('sell_tax', 0)}%\n"
    if token.get("holder_count"):
        msg += f"   👥 Holders: {token.get('holder_count')}\n"
    if token.get("age_hours"):
        msg += f"   🕒 Edad: {token.get('age_hours', 0):.1f} horas\n"
    
    # Recomendación basada en scores
    if token.get("opportunity_score", 0) > 70 and token.get("risk_score", 0) < 30:
        msg += "\n✅ *RECOMENDACIÓN: COMPRA* - Alto potencial, bajo riesgo."
    elif token.get("opportunity_score", 0) > 50 and token.get("risk_score", 0) < 50:
        msg += "\n⚠️ *RECOMENDACIÓN: MONITORIZAR* - Potencial moderado."
    else:
        msg += "\n🔴 *RECOMENDACIÓN: EVITAR* - Alto riesgo o bajo potencial."
    
    return msg
