# whale_advanced.py
import requests
import asyncio
import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

# ==================== BITCOIN ====================
def obtener_precio_btc_usd():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", timeout=5)
        if r.status_code == 200:
            return r.json()["bitcoin"]["usd"]
    except:
        pass
    return 60000

def obtener_ballenas_bitcoin(min_valor_usd=50000, limite=5):
    url = "https://blockchain.info/unconfirmed-transactions?format=json"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            txs = data.get("txs", [])
            ballenas = []
            precio_btc = obtener_precio_btc_usd()
            for tx in txs:
                btc_amount = sum(out.get("value", 0) for out in tx.get("out", [])) / 1e8
                valor_usd = btc_amount * precio_btc
                if valor_usd >= min_valor_usd:
                    ballenas.append({
                        "symbol": "BTC",
                        "amount": btc_amount,
                        "amount_usd": valor_usd,
                        "transaction_type": "transfer",
                        "description": f"Movimiento de {btc_amount:.2f} BTC (${valor_usd:,.0f} USD)",
                        "sentiment": "neutral"
                    })
                if len(ballenas) >= limite:
                    break
            return ballenas
    except Exception as e:
        print(f"Error Bitcoin: {e}")
    return []

# ==================== ETHEREUM ====================
def obtener_precio_eth_usd():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd", timeout=5)
        if r.status_code == 200:
            return r.json()["ethereum"]["usd"]
    except:
        pass
    return 1800

def obtener_ballenas_ethereum(min_valor_usd=10000, limite=5):
    api_key = os.getenv("ETHERSCAN_API_KEY")
    if not api_key:
        print("⚠️ Falta ETHERSCAN_API_KEY en .env. Usando datos de ejemplo.")
        return _ejemplo_eth()

    whale_address = "0x28C6c06298d514Db089934071355E5743bf21d60"
    url = f"https://api.etherscan.io/v2/api?chainid=1&module=account&action=txlist&address={whale_address}&startblock=0&endblock=99999999&sort=desc&apikey={api_key}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get("status") != "1":
            print("Etherscan error:", data.get("message"))
            return _ejemplo_eth()
        transacciones = data.get("result", [])
        ballenas = []
        precio_eth = obtener_precio_eth_usd()
        for tx in transacciones[:200]:
            value_wei = int(tx.get("value", "0"))
            if value_wei == 0:
                continue
            eth_amount = value_wei / 1e18
            valor_usd = eth_amount * precio_eth
            if valor_usd >= min_valor_usd:
                ballenas.append({
                    "symbol": "ETH",
                    "amount": eth_amount,
                    "amount_usd": valor_usd,
                    "transaction_type": "transfer",
                    "description": f"Movimiento de {eth_amount:.2f} ETH (${valor_usd:,.0f} USD)",
                    "sentiment": "neutral"
                })
            if len(ballenas) >= limite:
                break
        return ballenas
    except Exception as e:
        print(f"Error Ethereum: {e}")
        return _ejemplo_eth()

def _ejemplo_eth():
    return [
        {
            "symbol": "ETH",
            "amount": 15234.5,
            "amount_usd": 15234.5 * 1800,
            "transaction_type": "deposit",
            "description": "Ballena movió 15,234 ETH desde wallet fría a exchange (posible venta)",
            "sentiment": "bearish"
        },
        {
            "symbol": "ETH",
            "amount": 8750.2,
            "amount_usd": 8750.2 * 1800,
            "transaction_type": "withdrawal",
            "description": "Retiro de 8,750 ETH del exchange a wallet desconocida (acumulación)",
            "sentiment": "bullish"
        }
    ]

# ==================== IA CON GROQ ====================
groq_client = None
groq_api_key = os.getenv("GROQ_API_KEY")
if groq_api_key:
    groq_client = Groq(api_key=groq_api_key)

def analizar_con_ia(moneda, cantidad, valor_usd, tipo, descripcion):
    if not groq_client:
        return None
    prompt = f"""
Eres un analista de criptomonedas. Analiza esta transacción de ballena:

Moneda: {moneda}
Cantidad: {cantidad:.2f} {moneda}
Valor: ${valor_usd:,.2f} USD
Tipo: {tipo}
Descripción: {descripcion}

Responde en español, en menos de 80 caracteres, con formato:
[Sentimiento: ALCISTA/BAJISTA/NEUTRAL] - Breve razón.
Ejemplo: "ALCISTA - Retiro de exchange sugiere acumulación."
No des consejos de inversión.
"""
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=60
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error IA: {e}")
        return None

# ==================== FUNCIONES ASÍNCRONAS PARA EL BOT ====================
async def obtener_alertas_bitcoin(min_valor_usd=50000, limite=5):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, obtener_ballenas_bitcoin, min_valor_usd, limite)

async def obtener_alertas_ethereum(min_valor_usd=10000, limite=5):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, obtener_ballenas_ethereum, min_valor_usd, limite)

def analizar_alerta(alerta):
    desc = alerta.get("description", "Movimiento detectado")
    valor = alerta.get("amount_usd", 0)
    sentiment = alerta.get("sentiment", "neutral")
    if sentiment == "bullish":
        emoji = "🟢"
        texto = "Posible acumulación (investiga por tu cuenta)"
    elif sentiment == "bearish":
        emoji = "🔴"
        texto = "Posible distribución (investiga por tu cuenta)"
    else:
        emoji = "⚪"
        texto = "Neutral"
    desc_corta = desc[:100] + "..." if len(desc) > 100 else desc
    return emoji, desc_corta, texto, valor