# -*- coding: utf-8 -*-
import os
import json
import logging
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    create_client = None
    Client = None
    logger.warning("⚠️ Supabase library not installed. Using local storage only.")

supabase = None
if SUPABASE_AVAILABLE and SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("✅ Supabase client initialized for new_tokens")
    except Exception as e:
        logger.warning(f"⚠️ Supabase init failed: {e}. Using local storage.")
        supabase = None

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

def _fetch_geckoterminal(chain, limit=20):
    """Obtiene tokens de GeckoTerminal para una cadena específica"""
    tokens = []
    try:
        url = f"https://api.geckoterminal.com/api/v2/networks/{chain}/tokens?sort=created_at_desc&page[limit]={limit}"
        headers = {"Accept": "application/json"}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if 'data' in data:
                for item in data['data']:
                    attrs = item.get('attributes', {})
                    # Solo tokens con dirección válida
                    address = attrs.get('address', '')
                    if not address or len(address) < 10:
                        continue
                    
                    token = {
                        'name': attrs.get('name', 'Unknown'),
                        'symbol': attrs.get('symbol', '???'),
                        'address': address,
                        'chain': chain,
                        'price_usd': attrs.get('price_usd', '0'),
                        'volume_24h': attrs.get('volume_usd', {}).get('h24', '0'),
                        'market_cap': attrs.get('market_cap_usd', '0'),
                        'created_at': attrs.get('created_at', ''),
                        'buy_tax': attrs.get('buy_tax', '0'),
                        'sell_tax': attrs.get('sell_tax', '0'),
                        'holder_count': attrs.get('holder_count', '0')
                    }
                    tokens.append(token)
    except Exception as e:
        logger.error(f"Error fetching from GeckoTerminal {chain}: {e}")
    return tokens

def _fetch_dexscreener(chain, limit=10):
    """Fallback: Obtiene pares recientes de DexScreener para una cadena"""
    tokens = []
    try:
        # Mapeo de nombres de cadena para DexScreener
        chain_map = {
            'eth': 'ethereum',
            'bsc': 'bsc',
            'polygon': 'polygon',
            'arbitrum': 'arbitrum',
            'avalanche': 'avalanche'
        }
        chain_name = chain_map.get(chain, chain)
        url = f"https://api.dexscreener.com/latest/dex/search?q={chain_name}"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if 'pairs' in data:
                for pair in data['pairs'][:limit]:
                    base = pair.get('baseToken', {})
                    quote = pair.get('quoteToken', {})
                    # Solo tokens con dirección válida y que sean recientes
                    if not base.get('address'):
                        continue
                    
                    # Calcular antigüedad aproximada (los pares recientes tienen menos de 24h)
                    created = pair.get('pairCreatedAt', 0)
                    if created:
                        created_dt = datetime.fromtimestamp(created / 1000)
                        age_hours = (datetime.now() - created_dt).total_seconds() / 3600
                        if age_hours > 48:
                            continue
                    else:
                        continue
                    
                    token = {
                        'name': base.get('name', 'Unknown'),
                        'symbol': base.get('symbol', '???'),
                        'address': base.get('address', ''),
                        'chain': chain,
                        'price_usd': pair.get('priceUsd', '0'),
                        'volume_24h': pair.get('volume', {}).get('h24', '0'),
                        'market_cap': pair.get('marketCap', '0'),
                        'created_at': created_dt.isoformat() if created else '',
                        'buy_tax': '0',
                        'sell_tax': '0',
                        'holder_count': '0'
                    }
                    tokens.append(token)
    except Exception as e:
        logger.error(f"Error fetching from DexScreener {chain}: {e}")
    return tokens

def get_recent_tokens(limit=10):
    """Obtiene tokens reales recién creados de múltiples cadenas"""
    all_tokens = []
    chains = ['eth', 'bsc', 'polygon', 'arbitrum', 'avalanche']
    
    # Primero intentar GeckoTerminal (más completo)
    for chain in chains:
        tokens = _fetch_geckoterminal(chain, limit=15)
        if tokens:
            all_tokens.extend(tokens)
        else:
            # Fallback a DexScreener
            tokens = _fetch_dexscreener(chain, limit=5)
            all_tokens.extend(tokens)
    
    # Eliminar duplicados por dirección
    seen = set()
    unique_tokens = []
    for t in all_tokens:
        addr = t.get('address', '')
        if addr and addr not in seen:
            seen.add(addr)
            unique_tokens.append(t)
    
    # Ordenar por fecha de creación (más nuevos primero)
    unique_tokens.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return unique_tokens[:limit]

def scan_new_pools(limit=5, min_liquidity=5000):
    """Escanea pools nuevos para alertas automáticas"""
    tokens = get_recent_tokens(limit=limit * 2)
    filtered = []
    for t in tokens:
        try:
            liq = float(t.get('market_cap', '0'))
            if liq >= min_liquidity:
                filtered.append(t)
        except:
            continue
    return filtered[:limit]

def save_new_tokens(tokens):
    if not tokens:
        return
    if supabase is not None:
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

def format_token_message(token):
    name = token.get('name', 'Unknown')
    symbol = token.get('symbol', '???')
    address = token.get('address', '')
    chain = token.get('chain', 'unknown')
    price = token.get('price_usd', '0')
    volume = token.get('volume_24h', '0')
    market_cap = token.get('market_cap', '0')
    created = token.get('created_at', '')
    buy_tax = token.get('buy_tax', '0')
    sell_tax = token.get('sell_tax', '0')
    holders = token.get('holder_count', '0')
    
    created_time = "N/A"
    if created:
        try:
            dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
            created_time = dt.strftime('%d/%m/%Y %H:%M UTC')
        except:
            created_time = created
    
    if len(address) > 14:
        address_short = f"{address[:8]}...{address[-6:]}"
    else:
        address_short = address
    
    msg = (
        f"🪙 *{name} ({symbol})*\n"
        f"⛓️ Chain: {chain.upper()}\n"
        f"💰 Price: ${price}\n"
        f"📊 Volume 24h: ${volume}\n"
        f"🏦 Market Cap: ${market_cap}\n"
        f"📅 Created: {created_time}\n"
        f"🔗 Contract: `{address_short}`"
    )
    
    if buy_tax and buy_tax != '0':
        msg += f"\n   💰 Buy Tax: {buy_tax}%"
    if sell_tax and sell_tax != '0':
        msg += f"\n   💰 Sell Tax: {sell_tax}%"
    if holders and holders != '0':
        msg += f"\n   👥 Holders: {holders}"
    
    return msg
