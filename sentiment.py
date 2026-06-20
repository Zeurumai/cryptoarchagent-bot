import os
import re
import logging
import requests
import time
from datetime import datetime, timedelta
from textblob import TextBlob
import json

logger = logging.getLogger(__name__)

# ==================== CONFIGURACIÓN ====================
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")
TWITTER_API_URL = "https://api.twitter.com/2/tweets/search/recent"

# ==================== FUNCIONES PRINCIPALES ====================

def fetch_tweets(query: str, max_results: int = 10) -> list:
    """
    Obtiene tweets recientes usando la API de Twitter v2.
    Si no hay token, usa el scraper de Nitter (alternativa gratuita).
    """
    tweets = []
    
    # Opción 1: API de Twitter (recomendada)
    if TWITTER_BEARER_TOKEN:
        try:
            headers = {"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}
            params = {
                "query": query,
                "max_results": max_results,
                "tweet.fields": "public_metrics,created_at",
                "sort_order": "recency"
            }
            response = requests.get(TWITTER_API_URL, headers=headers, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if "data" in data:
                    tweets = data["data"]
                    logger.info(f"✅ Obtenidos {len(tweets)} tweets de Twitter API")
                    return tweets
            else:
                logger.warning(f"⚠️ Error en Twitter API: {response.status_code}")
        except Exception as e:
            logger.error(f"Error en fetch_tweets (Twitter API): {e}")
    
    # Opción 2: Scraper de Nitter (gratuito, sin token)
    try:
        # Usar una instancia pública de Nitter (puede cambiar)
        nitter_url = "https://nitter.net/search?f=tweets&q="
        response = requests.get(f"{nitter_url}{query}", headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if response.status_code == 200:
            # Parseo básico con regex (Nitter es HTML)
            import re
            text_pattern = r'<div class="tweet-content media-body">(.*?)</div>'
            matches = re.findall(text_pattern, response.text, re.DOTALL)
            for match in matches[:max_results]:
                clean_text = re.sub(r'<[^>]+>', '', match).strip()
                tweets.append({"text": clean_text, "public_metrics": {"like_count": 0, "retweet_count": 0}})
            logger.info(f"✅ Obtenidos {len(tweets)} tweets de Nitter")
            return tweets
    except Exception as e:
        logger.error(f"Error en Nitter scraper: {e}")
    
    # Fallback: datos simulados (solo para pruebas)
    logger.warning("⚠️ No se pudieron obtener tweets reales. Usando datos simulados.")
    return [
        {"text": f"I love {query}! To the moon! 🚀", "public_metrics": {"like_count": 10, "retweet_count": 5}},
        {"text": f"{query} is a scam, be careful!", "public_metrics": {"like_count": 2, "retweet_count": 1}},
        {"text": f"Just bought more {query}!", "public_metrics": {"like_count": 7, "retweet_count": 3}}
    ]

def analyze_sentiment(text: str) -> dict:
    """
    Analiza el sentimiento de un texto usando TextBlob.
    Retorna: polaridad (-1 a 1), subjetividad (0 a 1), clasificación.
    """
    blob = TextBlob(text)
    polarity = blob.sentiment.polarity  # -1 (negativo) a 1 (positivo)
    subjectivity = blob.sentiment.subjectivity  # 0 (objetivo) a 1 (subjetivo)
    
    # Clasificación
    if polarity > 0.3:
        classification = "bullish"
    elif polarity < -0.3:
        classification = "bearish"
    else:
        classification = "neutral"
    
    return {
        "polarity": polarity,
        "subjectivity": subjectivity,
        "classification": classification
    }

def get_sentiment_score(tweets: list) -> dict:
    """
    Calcula el score de sentimiento global a partir de una lista de tweets.
    """
    if not tweets:
        return {"score": 0, "classification": "neutral", "tweet_count": 0, "velocity": 0, "engagement": 0}
    
    polarities = []
    engagement_total = 0
    
    for tweet in tweets:
        text = tweet.get("text", "")
        # Limpiar texto (quitar URLs, menciones, etc.)
        text = re.sub(r'http\S+|@\w+|#', '', text)
        
        # Análisis de sentimiento
        sentiment = analyze_sentiment(text)
        polarities.append(sentiment["polarity"])
        
        # Engagement (likes + retweets)
        metrics = tweet.get("public_metrics", {})
        engagement = metrics.get("like_count", 0) + metrics.get("retweet_count", 0) * 2
        engagement_total += engagement
    
    # Promedio de polaridad
    avg_polarity = sum(polarities) / len(polarities) if polarities else 0
    
    # Clasificación global
    if avg_polarity > 0.2:
        classification = "bullish"
    elif avg_polarity < -0.2:
        classification = "bearish"
    else:
        classification = "neutral"
    
    # Velocidad de tweets (tweets por hora)
    # Para simplificar, usamos el número de tweets como proxy
    velocity = len(tweets) / 1  # por ahora, por minuto
    
    # Engagement promedio por tweet
    avg_engagement = engagement_total / len(tweets) if tweets else 0
    
    return {
        "score": avg_polarity * 100,  # -100 a 100
        "classification": classification,
        "tweet_count": len(tweets),
        "velocity": velocity,
        "engagement": avg_engagement
    }

def analyze_token_sentiment(token_symbol: str) -> dict:
    """
    Función principal para analizar el sentimiento de un token.
    """
    # Construir query de búsqueda (múltiples variantes)
    queries = [
        f"${token_symbol}",
        f"{token_symbol} crypto",
        f"#{token_symbol}"
    ]
    all_tweets = []
    for query in queries:
        tweets = fetch_tweets(query, max_results=5)
        all_tweets.extend(tweets)
        time.sleep(0.5)  # Pequeña pausa para no sobrecargar
    
    # Eliminar duplicados (por texto)
    seen_texts = set()
    unique_tweets = []
    for tweet in all_tweets:
        text = tweet.get("text", "")
        if text not in seen_texts:
            seen_texts.add(text)
            unique_tweets.append(tweet)
    
    # Calcular sentimiento global
    sentiment = get_sentiment_score(unique_tweets)
    sentiment["query_used"] = queries[0]  # Para depuración
    
    return sentiment
