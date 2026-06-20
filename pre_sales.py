import requests
import time
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

PUMPFUN_API = "https://frontend-api.pump.fun/coins"

def get_new_pump_tokens(limit=20, min_mcap=5000):
    """Obtiene tokens de Pump.fun ordenados por fecha de creación."""
    try:
        response = requests.get(PUMPFUN_API, params={"limit": limit, "sort": "created_at"}, timeout=10)
        if response.status_code == 200:
            data = response.json()
            tokens = []
            for token in data:
                if token.get("market_cap", 0) >= min_mcap:
                    tokens.append({
                        "symbol": token.get("symbol", "UNKNOWN"),
                        "name": token.get("name", "Unknown"),
                        "address": token.get("mint", ""),
                        "market_cap": token.get("market_cap", 0),
                        "volume_24h": token.get("volume_24h", 0),
                        "holder_count": token.get("holder_count", 0),
                        "created_at": token.get("created_at", ""),
                        "creator": token.get("creator", "")
                    })
            return tokens
    except Exception as e:
        logger.error(f"Error fetching pump.fun tokens: {e}")
    return []
