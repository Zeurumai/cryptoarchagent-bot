def predecir_movimiento_ballena(alert):
    """
    Predice la intención de la ballena basándose en patrones históricos.
    """
    try:
        amount = alert.get("amount", 0)
        value_usd = alert.get("amount_usd", 0)
        tx_type = alert.get("transaction_type", "transfer")
        description = alert.get("description", "")

        # Variables de predicción
        confidence = 0
        prediction = ""

        # 1. Análisis de cantidad
        if value_usd > 10000000:
            confidence += 30
        elif value_usd > 1000000:
            confidence += 15

        # 2. Análisis de tipo de transacción
        if "exchange" in description.lower():
            if "to exchange" in description.lower():
                confidence += 25  # Venta probable
                prediction = "possible distribution (sell-off)"
            elif "from exchange" in description.lower():
                confidence += 20  # Compra probable
                prediction = "possible accumulation (buy)"
            else:
                confidence += 10
                prediction = "neutral (transfer)"

        # 3. Análisis de volumen (puedes ampliarlo con datos históricos)
        if "withdrawal" in description.lower():
            confidence += 15
            if prediction:
                prediction += " & withdrawal"
            else:
                prediction = "withdrawal from exchange (potential accumulation)"

        # 4. Normalización
        confidence = min(confidence, 100)

        # Si la confianza es baja, usamos un análisis más genérico
        if confidence < 30:
            prediction = "uncertain (monitor closely)"

        # Añadir emoji según predicción
        emoji_pred = "🚀" if "accumulation" in prediction or "buy" in prediction else "⚠️" if "sell" in prediction or "distribution" in prediction else "🔄"

        return {
            "prediction": prediction,
            "confidence": confidence,
            "emoji": emoji_pred
        }
    except Exception as e:
        logger.error(f"Error predicting whale movement: {e}")
        return {
            "prediction": "error analyzing",
            "confidence": 0,
            "emoji": "❌"
        }
