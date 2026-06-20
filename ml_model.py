import os
import logging
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_squared_error, r2_score

logger = logging.getLogger(__name__)

# ==================== CONFIGURACIÓN ====================
MODEL_PATH = "models/token_predictor.pkl"
SCALER_PATH = "models/scaler.pkl"

# ==================== GENERACIÓN DE DATOS SINTÉTICOS (para entrenamiento inicial) ====================

def generate_synthetic_data(n_samples=10000):
    """
    Genera datos sintéticos para entrenar el modelo inicial.
    En producción, estos datos serán reemplazados por datos reales históricos.
    """
    np.random.seed(42)
    
    # Características: [volumen_24h, liquidez, holders, edad_horas, cambio_precio_24h]
    X = np.random.rand(n_samples, 5)
    
    # Escalar características a rangos realistas
    X[:, 0] = X[:, 0] * 200000  # volumen: 0 - 200k
    X[:, 1] = X[:, 1] * 100000  # liquidez: 0 - 100k
    X[:, 2] = X[:, 2] * 1000    # holders: 0 - 1000
    X[:, 3] = X[:, 3] * 72      # edad: 0 - 72 horas
    X[:, 4] = (X[:, 4] - 0.5) * 100  # cambio: -50% a +50%
    
    # Crear variable objetivo: crecimiento en 24h (0-200%)
    # Simular relación: más volumen + liquidez + holders + cambio positivo = mayor crecimiento
    y = (
        X[:, 0] * 0.3 / 100000 +      # volumen contribuye
        X[:, 1] * 0.25 / 100000 +     # liquidez contribuye
        X[:, 2] * 0.2 / 1000 +        # holders contribuye
        (X[:, 4] + 50) * 0.5 / 100 +  # cambio de precio contribuye
        np.random.normal(0, 0.1)      # ruido
    )
    y = np.clip(y * 200, 0, 200)  # escalar a 0-200% y recortar
    
    return X, y

# ==================== ENTRENAMIENTO DEL MODELO ====================

def train_model(X=None, y=None):
    """
    Entrena el modelo con datos proporcionados o genera datos sintéticos.
    Guarda el modelo y el scaler en la carpeta 'models/'.
    """
    if X is None or y is None:
        logger.info("No se proporcionaron datos. Generando datos sintéticos para entrenamiento inicial...")
        X, y = generate_synthetic_data()
    
    # Dividir en entrenamiento y prueba
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    # Escalar características
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # Entrenar modelo
    model = RandomForestRegressor(
        n_estimators=100,
        max_depth=10,
        min_samples_split=5,
        min_samples_leaf=2,
        random_state=42,
        n_jobs=-1
    )
    model.fit(X_train_scaled, y_train)
    
    # Evaluar modelo
    y_pred = model.predict(X_test_scaled)
    mse = mean_squared_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)
    
    logger.info(f"✅ Modelo entrenado. MSE: {mse:.4f}, R²: {r2:.4f}")
    
    # Guardar modelo y scaler
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    joblib.dump(scaler, SCALER_PATH)
    logger.info(f"✅ Modelo guardado en {MODEL_PATH}")
    logger.info(f"✅ Scaler guardado en {SCALER_PATH}")
    
    return model, scaler

# ==================== CARGA DEL MODELO ====================

def load_model():
    """
    Carga el modelo entrenado y el scaler.
    Si no existen, entrena uno nuevo con datos sintéticos.
    """
    try:
        model = joblib.load(MODEL_PATH)
        scaler = joblib.load(SCALER_PATH)
        logger.info("✅ Modelo y scaler cargados correctamente.")
        return model, scaler
    except FileNotFoundError:
        logger.warning("⚠️ Modelo no encontrado. Entrenando uno nuevo...")
        model, scaler = train_model()
        return model, scaler

# ==================== PREDICCIÓN ====================

def predict_growth(token_data: dict) -> dict:
    """
    Predice el crecimiento potencial de un token basado en sus características.
    
    Args:
        token_data (dict): Diccionario con las características del token:
            - volume_24h (float): Volumen en las últimas 24h
            - liquidity_usd (float): Liquidez en USD
            - holder_count (int): Número de holders
            - age_hours (float): Edad del token en horas
            - price_change_24h (float): Cambio de precio en 24h (%)
    
    Returns:
        dict: {
            "prediction": float,  # Crecimiento esperado en % (0-200)
            "confidence": float,  # Confianza de la predicción (0-1)
            "recommendation": str  # "BUY", "WAIT", "AVOID"
        }
    """
    try:
        model, scaler = load_model()
    except Exception as e:
        logger.error(f"Error cargando modelo: {e}")
        # Fallback: predicción basada en heurística simple
        return fallback_prediction(token_data)
    
    # Extraer características en el orden correcto
    try:
        features = np.array([[
            token_data.get("volume_24h", 0),
            token_data.get("liquidity_usd", 0),
            token_data.get("holder_count", 0),
            token_data.get("age_hours", 24),
            token_data.get("price_change_24h", 0)
        ]])
    except Exception as e:
        logger.error(f"Error preparando características: {e}")
        return fallback_prediction(token_data)
    
    # Escalar y predecir
    try:
        features_scaled = scaler.transform(features)
        prediction = model.predict(features_scaled)[0]
    except Exception as e:
        logger.error(f"Error en predicción: {e}")
        return fallback_prediction(token_data)
    
    # Calcular confianza basada en la desviación estándar de los árboles
    try:
        predictions = [tree.predict(features_scaled)[0] for tree in model.estimators_]
        std_dev = np.std(predictions)
        # Confianza inversamente proporcional a la desviación estándar
        confidence = max(0, min(1, 1 - (std_dev / 50)))  # 50% de desviación = 0 confianza
    except:
        confidence = 0.5  # Valor por defecto
    
    # Redondear predicción
    prediction = max(0, min(200, prediction))  # Limitar entre 0 y 200%
    
    # Recomendación basada en predicción y confianza
    if prediction > 50 and confidence > 0.6:
        recommendation = "BUY"
    elif prediction > 20 and confidence > 0.4:
        recommendation = "WAIT"
    else:
        recommendation = "AVOID"
    
    return {
        "prediction": prediction,
        "confidence": confidence,
        "recommendation": recommendation,
        "details": {
            "std_dev": std_dev if 'std_dev' in locals() else 0,
            "features": features.tolist()
        }
    }

# ==================== FALLBACK HEURÍSTICO (si el modelo falla) ====================

def fallback_prediction(token_data: dict) -> dict:
    """
    Predicción basada en heurística simple cuando el modelo no está disponible.
    """
    volume = token_data.get("volume_24h", 0)
    liquidity = token_data.get("liquidity_usd", 0)
    holders = token_data.get("holder_count", 0)
    age = token_data.get("age_hours", 24)
    change = token_data.get("price_change_24h", 0)
    
    # Heurística simple
    score = 0
    if volume > 50000:
        score += 30
    elif volume > 10000:
        score += 15
    if liquidity > 20000:
        score += 25
    elif liquidity > 5000:
        score += 10
    if holders > 200:
        score += 20
    elif holders > 50:
        score += 10
    if change > 20:
        score += 15
    elif change > 5:
        score += 5
    if age < 6:
        score += 10
    elif age < 24:
        score += 5
    
    prediction = min(100, score)  # Normalizar a 0-100%
    confidence = 0.5  # Confianza baja por ser heurística
    
    if prediction > 60:
        recommendation = "BUY"
    elif prediction > 30:
        recommendation = "WAIT"
    else:
        recommendation = "AVOID"
    
    return {
        "prediction": prediction,
        "confidence": confidence,
        "recommendation": recommendation,
        "details": {
            "fallback": True,
            "score": score
        }
    }

# ==================== REENTRENAMIENTO CON DATOS REALES ====================

def retrain_with_real_data(df: pd.DataFrame):
    """
    Reentrena el modelo con datos reales históricos.
    
    Args:
        df (pd.DataFrame): DataFrame con columnas:
            - volume_24h, liquidity_usd, holder_count, age_hours, price_change_24h, growth_24h (target)
    """
    X = df[["volume_24h", "liquidity_usd", "holder_count", "age_hours", "price_change_24h"]].values
    y = df["growth_24h"].values
    
    train_model(X, y)
    logger.info("✅ Modelo reentrenado con datos reales.")

# ==================== EJEMPLO DE USO (si se ejecuta directamente) ====================

if __name__ == "__main__":
    # Configurar logging básico para pruebas
    logging.basicConfig(level=logging.INFO)
    
    # Probar carga y predicción
    print("🧠 Probando modelo de predicción...")
    
    # Datos de ejemplo para un token realista
    test_token = {
        "volume_24h": 75000,
        "liquidity_usd": 45000,
        "holder_count": 350,
        "age_hours": 2.5,
        "price_change_24h": 35.0
    }
    
    prediction = predict_growth(test_token)
    print("\n📊 Resultado de predicción:")
    print(f"  - Predicción de crecimiento: {prediction['prediction']:.2f}%")
    print(f"  - Confianza: {prediction['confidence']:.2f}")
    print(f"  - Recomendación: {prediction['recommendation']}")
    print(f"  - Detalles: {prediction.get('details', {})}")
