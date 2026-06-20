import os
import time
import logging
import requests
from datetime import datetime
from supabase import create_client, Client

logger = logging.getLogger(__name__)

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
last_scan_time = 0

# ==================== CADENAS SOPORTADAS (ACTUALIZADO) ====================
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

def fetch_new_pools(query: str = "?q=") -> list:
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
    if not GOPLUS_API_KEY:
        return {"risk_score": 0, "warnings": ["⚠️ No API key for security check"]}
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
        
        is_honeypot = token_data.get("is_honeypot", False)
        is_whitelist_only = token_data.get("is_whitelist_only", False)
        is_blacklisted = token_data.get("is_blacklisted", False)
        liquidity_locked = token_data.get("liquidity_locked", False)
        owner_renounced = token_data.get("owner_renounced", False)
        buy_tax = float(token_data.get("buy_tax", 0))
        sell_tax = float(token_data.get("sell_tax", 0))
        owner_balance = token_data.get("owner_balance", 0)
        holder_count = int(token_data.get("holder_count", 0))
        
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
            "risk_score": min(100, risk_score),
            "warnings": warnings
        }
    except Exception as e:
        logger.error(f"Security check error: {e}")
        return {"risk_score": 0, "warnings": ["⚠️ Error verifying token"]}

def store_token(token_data: dict) -> bool:
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
                "created_at": datetime.now().isoformat(),
                "risk_score": token_data.get("risk_score", 0),
                "warnings": token_data.get("warnings", [])
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
    if supabase:
        try:
            response = supabase.table("new_tokens").select("*").order("created_at", desc=True).limit(limit).execute()
            return response.data if response.data else []
        except Exception as e:
            logger.error(f"Error fetching recent tokens: {e}")
    return NEW_TOKENS_STORE[-limit:]

def scan_new_pools() -> list:
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
            token_data = {
                "chain": chain,
                "pair_address": pool.get("pairAddress", ""),
                "base_token": base_token.get("symbol", "UNKNOWN"),
                "quote_token": quote_token.get("symbol", "USDT"),
                "dex": pool.get("dexId", "unknown"),
                "liquidity_usd": pool.get("liquidity", {}).get("usd", 0),
                "price_usd": pool.get("priceUsd", 0),
                "contract_address": base_token.get("address", ""),
            }
            if token_data["contract_address"]:
                security = check_token_security(token_data["contract_address"], chain)
                token_data["risk_score"] = security.get("risk_score", 0)
                token_data["warnings"] = security.get("warnings", [])
                token_data["buy_tax"] = security.get("buy_tax", 0)
                token_data["sell_tax"] = security.get("sell_tax", 0)
                token_data["holder_count"] = security.get("holder_count", 0)
                if security.get("is_honeypot", False) or token_data["risk_score"] > 50:
                    continue
            if store_token(token_data):
                new_tokens.append(token_data)
    return new_tokens

def format_token_message(token: dict) -> str:
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
    if token.get("buy_tax") or token.get("sell_tax"):
        msg += f"   💰 Buy Tax: {token.get('buy_tax', 0)}% | Sell Tax: {token.get('sell_tax', 0)}%\n"
    if token.get("holder_count"):
        msg += f"   👥 Holders: {token.get('holder_count')}\n"
    return msg
