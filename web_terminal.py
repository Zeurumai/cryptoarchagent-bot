# web_terminal.py - Web Terminal para CryptoArch Agent
import os
import json
from flask import Flask, render_template, request, jsonify, session
from supabase import create_client, Client
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Configuración de Supabase (usando las mismas variables que en trading_bot.py)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    logger.error("❌ SUPABASE_URL or SUPABASE_KEY not configured.")
    supabase = None
else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("✅ Connected to Supabase")

# ==================== RUTAS ====================
@app.route('/dashboard')
def dashboard():
    """Página principal del dashboard."""
    # Por ahora, usamos un chat_id fijo (el tuyo) para pruebas. Luego se añadirá autenticación.
    chat_id = "8355456581"
    return render_template('dashboard.html', chat_id=chat_id)

@app.route('/api/stats/<chat_id>')
def get_stats(chat_id):
    """API para obtener estadísticas del usuario."""
    if not supabase:
        return jsonify({"error": "Database not connected"}), 500

    try:
        # Obtener datos del usuario
        stats = supabase.table("user_stats").select("*").eq("chat_id", chat_id).execute()
        if not stats.data:
            # Si no hay estadísticas, crear un registro por defecto
            default_stats = {
                "chat_id": chat_id,
                "total_trades": 0,
                "win_rate": 0.0,
                "pnl": 0.0,
                "legendary_mode": False
            }
            supabase.table("user_stats").insert(default_stats).execute()
            return jsonify(default_stats)

        return jsonify(stats.data[0])
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/settings/<chat_id>')
def get_settings(chat_id):
    """API para obtener la configuración del usuario."""
    if not supabase:
        return jsonify({"error": "Database not connected"}), 500

    try:
        # Obtener configuración de Sniper X
        sniper = supabase.table("sniper_settings").select("*").eq("chat_id", chat_id).execute()
        sniper_data = sniper.data[0] if sniper.data else {}

        # Obtener configuración de Copy Trading
        copy = supabase.table("copy_settings").select("*").eq("chat_id", chat_id).execute()
        copy_data = copy.data[0] if copy.data else {}

        return jsonify({
            "sniper": sniper_data,
            "copy": copy_data
        })
    except Exception as e:
        logger.error(f"Error getting settings: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/update_sniper', methods=['POST'])
def update_sniper():
    """API para actualizar la configuración de Sniper X."""
    if not supabase:
        return jsonify({"error": "Database not connected"}), 500

    try:
        data = request.json
        chat_id = data.get("chat_id")
        field = data.get("field")
        value = data.get("value")

        if not chat_id or not field:
            return jsonify({"error": "Missing parameters"}), 400

        # Actualizar en Supabase
        supabase.table("sniper_settings").update({field: value}).eq("chat_id", chat_id).execute()

        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error updating sniper: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/update_copy', methods=['POST'])
def update_copy():
    """API para actualizar la configuración de Copy Trading."""
    if not supabase:
        return jsonify({"error": "Database not connected"}), 500

    try:
        data = request.json
        chat_id = data.get("chat_id")
        field = data.get("field")
        value = data.get("value")

        if not chat_id or not field:
            return jsonify({"error": "Missing parameters"}), 400

        # Actualizar en Supabase
        supabase.table("copy_settings").update({field: value}).eq("chat_id", chat_id).execute()

        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error updating copy: {e}")
        return jsonify({"error": str(e)}), 500

# ==================== MAIN ====================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    app.run(host='0.0.0.0', port=port, debug=True)