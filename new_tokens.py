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

def _fetch_dexscreener(chain, limit=10):
    """Obtiene tokens reales de DexScreener (fuente principal)"""
    tokens = []
    try:
        chain_map = {
            'eth': 'ethereum',
            'bsc': 'bsc',
            'polygon': 'polygon',
            'arbitrum': 'arbitrum',
            'avalanche': 'avalanche'
        }
        chain_name = chain_map.get(chain, chain)
        url = f"https://api.dexscreener.com/latest/dex/search?q={chain_name}"
        logger.info(f"🌐 Fetching DexScreener {chain}")
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if 'pairs' in data:
                for pair in data['pairs'][:limit]:
                    # Verificar que tenga baseToken válido
                    base = pair.get('baseToken', {})
                    if not base.get('address') or not base.get('name'):
                        continue
                    
                    # Verificar que tenga precio
                    price = pair.get('priceUsd', '0')
                    if price == '0' or price is None:
                        continue
                    
                    # Obtener fecha de creación
                    created = pair.get('pairCreatedAt', 0)
                    created_dt = None
                    if created:
                        created_dt = datetime.fromtimestamp(created / 1000)
                        # Filtrar tokens con más de 7 días
                        age_hours = (datetime.now() - created_dt).total_seconds() / 3600
                        if age_hours > 168:  # 7 días
                            continue
                    
                    token = {
                        'name': base.get('name', 'Unknown'),
                        'symbol': base.get('symbol', '???'),
                        'address': base.get('address', ''),
                        'chain': chain,
                        'price_usd': price,
                        'volume_24h': str(pair.get('volume', {}).get('h24', '0')),
                        'market_cap': str(pair.get('marketCap', '0')),
                        'created_at': created_dt.isoformat() if created_dt else '',
                        'buy_tax': '0',
                        'sell_tax': '0',
                        'holder_count': '0'
                    }
                    tokens.append(token)
                
                logger.info(f"✅ DexScreener {chain}: {len(tokens)} tokens encontrados")
            else:
                logger.warning(f"⚠️ DexScreener {chain}: no 'pairs' en la respuesta")
        else:
            logger.warning(f"⚠️ DexScreener {chain} HTTP {response.status_code}")
    except Exception as e:
        logger.error(f"❌ Error DexScreener {chain}: {e}")
    return tokens

def get_sample_tokens():
    """Tokens de muestra para cuando no hay datos reales"""
    return [
        {
            'name': 'Sample Token 1',
            'symbol': 'SMP1',
            'address': '0x1234567890abcdef1234567890abcdef12345678',
            'chain': 'eth',
            'price_usd': '0.0123',
            'volume_24h': '150000',
            'market_cap': '500000',
            'created_at': datetime.now().isoformat(),
            'buy_tax': '0',
            'sell_tax': '0',
            'holder_count': '250'
        },
        {
            'name': 'Sample Token 2',
            'symbol': 'SMP2',
            'address': '0xabcdef1234567890abcdef1234567890abcdef12',
            'chain': 'bsc',
            'price_usd': '0.0045',
            'volume_24h': '80000',
            'market_cap': '120000',
            'created_at': datetime.now().isoformat(),
            'buy_tax': '2',
            'sell_tax': '2',
            'holder_count': '80'
        }
    ]

def get_recent_tokens(limit=10):
    """Obtiene tokens reales recién creados de múltiples cadenas (DexScreener)"""
    logger.info("🔍 Búsqueda de nuevos tokens en DexScreener...")
    all_tokens = []
    chains = ['eth', 'bsc', 'polygon', 'arbitrum', 'avalanche']
    
    for chain in chains:
        tokens = _fetch_dexscreener(chain, limit=15)
        all_tokens.extend(tokens)
    
    # Eliminar duplicados por dirección
    seen = set()
    unique = []
    for t in all_tokens:
        addr = t.get('address', '')
        if addr and addr not in seen:
            seen.add(addr)
            unique.append(t)
    
    # Ordenar por fecha de creación (más nuevos primero)
    unique.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    result = unique[:limit]
    
    # Si no hay tokens reales, devolver muestra
    if not result:
        logger.warning("⚠️ No se encontraron tokens reales, usando muestra")
        result = get_sample_tokens()
    
    logger.info(f"✅ Devolviendo {len(result)} tokens")
    return result

def scan_new_pools(limit=5, min_liquidity=5000):
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
