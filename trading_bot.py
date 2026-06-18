# -*- coding: utf-8 -*-
import os
import time
import json
import logging
import requests
import schedule
import threading
import asyncio
import feedparser
import re
from datetime import datetime, timedelta
from flask import Flask, request
from dotenv import load_dotenv
import mercadopago
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from whale_advanced import (
    obtener_alertas_bitcoin,
    obtener_alertas_ethereum,
    obtener_alertas_solana,
    obtener_alertas_polygon,
    obtener_alertas_arbitrum,
    analizar_alerta,
    analizar_con_ia
)
from trading_engine import TradingEngine
from supabase import create_client, Client

load_dotenv()

# ==================== CONFIGURACIÓN ====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN not found. Set it in .env")

MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN")
if not MP_ACCESS_TOKEN:
    raise ValueError("❌ MP_ACCESS_TOKEN not found in .env")

MP_WEBHOOK_URL = os.getenv("MP_WEBHOOK_URL")
BINANCE_REFERRAL_LINK = os.getenv("BINANCE_REFERRAL_LINK", "https://www.binance.com/en/register?ref=YOUR_CODE")

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== COINS ====================
COINS = [
    ("bitcoin", "BTC", "Bitcoin"),
    ("ethereum", "ETH", "Ethereum"),
    ("solana", "SOL", "Solana"),
    ("ripple", "XRP", "XRP"),
    ("binancecoin", "BNB", "BNB"),
    ("chainlink", "LINK", "Chainlink"),
    ("avalanche-2", "AVAX", "Avalanche")
]

# ==================== USER DATA ====================
USER_DATA = {}

def load_user_data():
    global USER_DATA
    try:
        with open("user_data.json", "r") as f:
            USER_DATA = json.load(f)
    except FileNotFoundError:
        USER_DATA = {}

def save_user_data():
    with open("user_data.json", "w") as f:
        json.dump(USER_DATA, f, indent=2, default=str)

load_user_data()

# ==================== SUPABASE ====================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    logger.warning("⚠️ SUPABASE_URL or SUPABASE_KEY not configured. Using local files.")
    supabase = None
else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("✅ Connected to Supabase")

SUBSCRIBERS_FILE = "subscribers.json"

# ==================== NIVELES ====================
LEVELS = {
    0: {
        "name": "Explorer",
        "emoji": "🧭",
        "commission": 0.005,
        "insignia": "🔰",
        "benefits": "14 days free, 3 alerts, trading access, whales, news",
        "active": False
    },
    1: {
        "name": "Trader",
        "emoji": "📊",
        "commission": 0.003,
        "insignia": "⚡",
        "benefits": "Full access, no subscription, reduced commission",
        "active": True
    },
    2: {
        "name": "Pro",
        "emoji": "⭐",
        "commission": 0.002,
        "insignia": "🌟",
        "benefits": "Subscription included, direct team access (priority)",
        "active": True
    },
    3: {
        "name": "Elite",
        "emoji": "👑",
        "commission": 0.002,
        "insignia": "🏆",
        "benefits": "Beta features, exclusive badge, vote on new features",
        "active": True
    }
}

# ==================== FUNCIONES DE SUSCRIPCIÓN ====================
def load_subscribers():
    if supabase:
        try:
            response = supabase.table("subscriptions").select("*").execute()
            if response.data:
                result = {}
                for row in response.data:
                    result[row["chat_id"]] = {
                        "plan": row.get("plan", "free"),
                        "start": row.get("start_date"),
                        "end": row.get("end_date"),
                        "active": row.get("active", True),
                        "fee": row.get("fee"),
                        "email": row.get("email"),
                        "trial_start": row.get("trial_start"),
                        "trial_end": row.get("trial_end"),
                        "deposit_level": row.get("deposit_level", 0),
                        "commission_rate": row.get("commission_rate", 0.005),
                        "insignia": row.get("insignia"),
                        "is_early_adopter": row.get("is_early_adopter", False)
                    }
                return result
            return {}
        except Exception as e:
            logger.error(f"Error loading from Supabase: {e}")
            try:
                with open(SUBSCRIBERS_FILE, "r") as f:
                    return json.load(f)
            except FileNotFoundError:
                return {}
    else:
        try:
            with open(SUBSCRIBERS_FILE, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

def save_subscribers(subscribers):
    if supabase:
        try:
            supabase.table("subscriptions").delete().neq("chat_id", "none").execute()
            for chat_id, data in subscribers.items():
                row = {
                    "chat_id": chat_id,
                    "plan": data.get("plan", "free"),
                    "start_date": data.get("start"),
                    "end_date": data.get("end"),
                    "active": data.get("active", True),
                    "fee": data.get("fee"),
                    "email": data.get("email"),
                    "trial_start": data.get("trial_start"),
                    "trial_end": data.get("trial_end"),
                    "deposit_level": data.get("deposit_level", 0),
                    "commission_rate": data.get("commission_rate", 0.005),
                    "insignia": data.get("insignia"),
                    "is_early_adopter": data.get("is_early_adopter", False)
                }
                supabase.table("subscriptions").insert(row).execute()
            logger.info("✅ Subscribers saved to Supabase")
        except Exception as e:
            logger.error(f"Error saving to Supabase: {e}")
            try:
                with open(SUBSCRIBERS_FILE, "w") as f:
                    json.dump(subscribers, f, indent=2, default=str)
            except Exception as e2:
                logger.error(f"Error saving locally: {e2}")
    else:
        try:
            with open(SUBSCRIBERS_FILE, "w") as f:
                json.dump(subscribers, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error saving locally: {e}")

def get_user_level(chat_id):
    subscribers = load_subscribers()
    data = subscribers.get(str(chat_id), {})
    level = data.get("deposit_level", 0)
    if level == 0:
        trial_end = data.get("trial_end")
        if trial_end:
            end = datetime.fromisoformat(trial_end)
            if end < datetime.now():
                data["active"] = False
                save_subscribers(subscribers)
                return -1
    return level

def get_user_commission(chat_id):
    level = get_user_level(chat_id)
    if level < 0:
        return None
    return LEVELS.get(level, LEVELS[0])["commission"]

def get_user_insignia(chat_id):
    level = get_user_level(chat_id)
    if level < 0:
        return "❌"
    return LEVELS.get(level, LEVELS[0])["insignia"]

def get_level_benefits(level):
    return LEVELS.get(level, LEVELS[0])["benefits"]

def start_trial(chat_id):
    subscribers = load_subscribers()
    if str(chat_id) not in subscribers:
        subscribers[str(chat_id)] = {}
    data = subscribers[str(chat_id)]
    if not data.get("trial_start"):
        data["trial_start"] = datetime.now().isoformat()
        data["trial_end"] = (datetime.now() + timedelta(days=14)).isoformat()
        data["deposit_level"] = 0
        data["commission_rate"] = 0.005
        data["insignia"] = "🔰"
        data["active"] = True
        save_subscribers(subscribers)
        return True
    return False

def calculate_plan_end(plan_key: str, start_date: datetime) -> datetime:
    if plan_key == "monthly":
        return start_date + timedelta(days=30)
    elif plan_key == "quarterly":
        return start_date + timedelta(days=90)
    elif plan_key == "yearly":
        return start_date + timedelta(days=365)
    else:
        return start_date + timedelta(days=30)

def is_premium(chat_id):
    subscribers = load_subscribers()
    data = subscribers.get(str(chat_id))
    if not data or not data.get("active", False):
        return False
    end_str = data.get("end")
    if end_str:
        end = datetime.fromisoformat(end_str)
        if end < datetime.now():
            data["active"] = False
            save_subscribers(subscribers)
            return False
    return True

def activate_premium(chat_id, plan_key):
    subscribers = load_subscribers()
    start = datetime.now()
    end = calculate_plan_end(plan_key, start)
    subscribers[str(chat_id)] = {
        "plan": plan_key,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "active": True,
        "deposit_level": 2,
        "commission_rate": 0.002,
        "insignia": "🌟"
    }
    save_subscribers(subscribers)
    logger.info(f"✅ Premium activated for {chat_id} with plan {plan_key} until {end}")
    send_telegram(int(chat_id), f"🎉 *Premium Activated!*\n\nPlan: *{plan_key.capitalize()}*\nValid until: {end.strftime('%d/%m/%Y')}\n\nThank you for your payment. You now have access to all Premium features.")
    return True

def get_user_email(chat_id):
    subscribers = load_subscribers()
    data = subscribers.get(str(chat_id), {})
    return data.get("email")

def set_user_email(chat_id, email):
    subscribers = load_subscribers()
    if str(chat_id) not in subscribers:
        subscribers[str(chat_id)] = {}
    subscribers[str(chat_id)]["email"] = email
    save_subscribers(subscribers)

# ==================== LEGAL TERMS ====================
TERMS_FILE = "terms_accepted.json"

def load_terms():
    try:
        with open(TERMS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_terms(terms):
    with open(TERMS_FILE, "w") as f:
        json.dump(terms, f, indent=2)

def has_accepted_terms(chat_id):
    terms = load_terms()
    return str(chat_id) in terms and terms[str(chat_id)] == True

async def terms_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
⚠️ *IMPORTANT LEGAL DISCLAIMER*

This bot is an *analysis and automation tool*. **IT IS NOT A FINANCIAL ADVISOR**.

- Alerts, reports, and generated data are *purely informational*.
- They do not constitute buy/sell/investment recommendations.
- Cryptocurrency trading involves *high risk* of total capital loss.
- Neither the bot creator nor its operators are responsible for financial losses arising from use of this tool.

By using this bot, you accept full responsibility for your own investment decisions.

Type `/accept` to confirm you have read and agree to these terms.
"""
    await update.message.reply_text(text, parse_mode="Markdown")

async def accept_terms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    terms = load_terms()
    terms[chat_id] = True
    save_terms(terms)
    start_trial(chat_id)
    await update.message.reply_text(
        "✅ *Welcome to CryptoArch Agent!*\n\n"
        "🧭 *You have 14 days FREE trial!*\n"
        "• Commission: 0.5%\n"
        "• Limited features (3 alerts)\n\n"
        "⚡ *Why CryptoArch Agent is different:*\n"
        "• Maestro, Banana Gun and Trojan charge 1% per trade.\n"
        "• We charge 0.2% fixed. That's 5x cheaper.\n"
        "• They execute fast. We make you think faster.\n"
        "• They copy traders. We copy whales with AI.\n\n"
        "To unlock full benefits, you have two options:\n"
        "1️⃣ *Deposit on Binance* using our referral link (no subscription):\n"
        f"👉 {BINANCE_REFERRAL_LINK}\n"
        "   • ≥ 50 USDT → Trader (0.3% comisión)\n"
        "   • ≥ 100 USDT → Pro (0.2% comisión, premium)\n"
        "   • ≥ 500 USDT → Elite (0.2% comisión, VIP)\n\n"
        "2️⃣ *Pay a subscription* (no deposit required):\n"
        "   • Use /pay to see plans (Pro level, 0.2% commission).\n\n"
        "Use /plan to see your current level.\n"
        "Use /activate to check your deposit level.\n\n"
        "💀 *Remember:* Maestro, Banana Gun and Trojan are 5x more expensive.\n"
        "You are already ahead.",
        parse_mode="Markdown"
    )
    await start(update, context)

# ==================== MARKET FUNCTIONS ====================
def get_all_prices():
    ids = ",".join([c[0] for c in COINS])
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.error(f"Price error: {e}")
    return {}

def get_coin_price_by_id(coin_id):
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code == 200:
            return r.json()[coin_id]["usd"]
    except:
        return None

def send_telegram(chat_id, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        logger.error(f"Error sending: {e}")

# ==================== PRICE ALERTS ====================
def check_alerts():
    for chat_id, data in USER_DATA.items():
        for alert in data.get("alerts", []):
            if not alert.get("active", True):
                continue
            coin_id = next((c[0] for c in COINS if c[1] == alert["coin"]), None)
            if not coin_id:
                continue
            price = get_coin_price_by_id(coin_id)
            if not price:
                continue
            condition = alert["condition"]
            target = alert["price"]
            if condition == ">" and price > target:
                send_telegram(int(chat_id), f"🚨 *ALERT* {alert['coin']}\nCurrent price: ${price:,.2f}\nExceeded ${target:,.2f}")
                alert["active"] = False
            elif condition == "<" and price < target:
                send_telegram(int(chat_id), f"🚨 *ALERT* {alert['coin']}\nCurrent price: ${price:,.2f}\nDropped below ${target:,.2f}")
                alert["active"] = False
    save_user_data()

# ==================== REPORTS ====================
def send_report(chat_id, report_type):
    prices = get_all_prices()
    if not prices:
        message = "⚠️ Could not retrieve report."
    else:
        changes = []
        for coin_id, symbol, name in COINS:
            if coin_id in prices:
                change = prices[coin_id].get('usd_24h_change', 0)
                changes.append((symbol, change))
        if changes:
            winner = max(changes, key=lambda x: x[1])
            loser = min(changes, key=lambda x: x[1])
        else:
            winner = loser = ("N/A", 0)

        message = f"📊 *{report_type.upper()} REPORT* 📊\n\n"
        for coin_id, symbol, name in COINS:
            if coin_id not in prices:
                continue
            data = prices[coin_id]
            price = data.get('usd', 0)
            change = data.get('usd_24h_change', 0)
            if price == 0:
                continue
            trend = "📈" if change > 0 else "📉" if change < 0 else "➡️"
            message += f"• *{symbol}*: ${price:,.0f} | {change:+.1f}% {trend}\n"
        message += f"\n🏆 *Daily winner:* {winner[0]} {winner[1]:+.1f}%\n"
        message += f"📉 *Daily loser:* {loser[0]} {loser[1]:+.1f}%\n"
        try:
            fg = requests.get('https://api.alternative.me/fng/').json()
            value = fg['data'][0]['value']
            classification = fg['data'][0]['value_classification']
            message += f"\n😨 *Fear & Greed:* {value}/100 ({classification})"
        except:
            pass
    send_telegram(chat_id, message)

def reschedule_reports():
    schedule.clear()
    schedule.every(60).seconds.do(check_alerts)
    for chat_id, data in USER_DATA.items():
        reports = data.get("reports", {})
        for report_type, hour in reports.items():
            if hour:
                schedule.every().day.at(hour).do(send_report, int(chat_id), report_type)
                logger.info(f"Scheduled {report_type} report at {hour} for chat {chat_id}")

# ==================== BOT HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not has_accepted_terms(chat_id):
        await terms_command(update, context)
        return

    level = get_user_level(chat_id)
    if level == -1:
        await update.message.reply_text(
            "⏰ *Your 14-day trial has expired!*\n\n"
            "To continue trading with reduced commissions, you have two options:\n\n"
            "1️⃣ *Deposit on Binance* using our referral link:\n"
            f"👉 {BINANCE_REFERRAL_LINK}\n"
            "   • Deposit ≥ 50 USDT → Trader (0.3% comisión)\n"
            "   • Deposit ≥ 100 USDT → Pro (0.2% + premium)\n"
            "   • Deposit ≥ 500 USDT → Elite (0.2% + VIP)\n\n"
            "2️⃣ *Pay a subscription* (no deposit required):\n"
            "   • Use /pay to activate premium.\n\n"
            "Choose the option that best suits you! 🚀",
            parse_mode="Markdown"
        )
        return

    subscribers = load_subscribers()
    data = subscribers.get(str(chat_id), {})
    if not data.get("trial_start") and level == 0:
        start_trial(chat_id)
        await update.message.reply_text(
            "🧭 *You have 14 days FREE trial!*\n"
            "• Commission: 0.5%\n"
            "• 3 alerts limit\n\n"
            "Upgrade with /activate to unlock full benefits.",
            parse_mode="Markdown"
        )

    keyboard = [
        [InlineKeyboardButton("📊 Market status", callback_data="status")],
        [InlineKeyboardButton("🔔 My alerts", callback_data="alerts_list")],
        [InlineKeyboardButton("➕ New alert", callback_data="new_alert_coin")],
        [InlineKeyboardButton("📅 Auto reports", callback_data="reports_config")],
        [InlineKeyboardButton("💰 My balance (Testnet)", callback_data="balance")],
        [InlineKeyboardButton("💎 My status", callback_data="premium")],
        [InlineKeyboardButton("💳 Activate Premium", callback_data="pay")],
        [InlineKeyboardButton("🐋 Whales (Free)", callback_data="whale")],
        [InlineKeyboardButton("📅 Plans", callback_data="plans")],
        [InlineKeyboardButton("📰 News", callback_data="news")],
        [InlineKeyboardButton("ℹ️ Coin info", callback_data="info")],
        [InlineKeyboardButton("🛒 Buy (testnet)", callback_data="buy")],
        [InlineKeyboardButton("💰 Sell (testnet)", callback_data="sell")],
        [InlineKeyboardButton("⚙️ Activate plan", callback_data="activate")],
        [InlineKeyboardButton("📋 My plan", callback_data="plan")],
        [InlineKeyboardButton("🤖 Auto trading", callback_data="rules")],
        [InlineKeyboardButton("⚡ Snipe", callback_data="snipe")],
        [InlineKeyboardButton("🎯 Sniper X", callback_data="sniper")],
        [InlineKeyboardButton("⚔️ Compare", callback_data="compare")],
        [InlineKeyboardButton("❓ Help", callback_data="help")]
    ]
    await update.message.reply_text("🤖 *CryptoArch Agent*\nChoose an option:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# ==================== CALLBACK HANDLER ====================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = update.effective_chat.id

    if data == "status":
        await show_status(query)
    elif data == "alerts_list":
        await show_alerts(query, chat_id)
    elif data == "new_alert_coin":
        await new_alert_coin(query, chat_id)
    elif data.startswith("new_alert_price_"):
        coin = data.split("_")[3]
        context.user_data["new_alert_coin"] = coin
        await new_alert_condition(query, coin, chat_id)
    elif data.startswith("new_alert_condition_"):
        cond = data.split("_")[3]
        context.user_data["new_alert_condition"] = cond
        await query.edit_message_text(f"💰 Enter target price for {context.user_data['new_alert_coin']} {cond}\nExample: 50000")
        context.user_data["awaiting_alert_price"] = True
    elif data.startswith("alert_toggle_"):
        idx = int(data.split("_")[2])
        toggle_alert(chat_id, idx)
        await show_alerts(query, chat_id)
    elif data.startswith("alert_delete_"):
        idx = int(data.split("_")[2])
        delete_alert(chat_id, idx)
        await show_alerts(query, chat_id)
    elif data == "reports_config":
        await reports_menu(query, chat_id)
    elif data.startswith("report_type_"):
        report_type = data.split("_")[2]
        context.user_data["report_type"] = report_type
        await query.edit_message_text(f"⏰ Enter time for {report_type.upper()} report (HH:MM, e.g. 08:30)")
        context.user_data["awaiting_report_time"] = True
    elif data == "help":
        await help_menu(query)
    elif data == "balance":
        try:
            engine = TradingEngine(testnet=True)
            usdt_balance = engine.get_balance("USDT")
            btc_balance = engine.get_balance("BTC")
            message = f"💰 *Testnet Balance*\nUSDT: ${usdt_balance:.2f}\nBTC: {btc_balance:.8f}\n\n⚠️ This is TESTNET balance (fake money). To trade real money, deposit on real Binance and use /activate."
            await query.edit_message_text(message, parse_mode="Markdown")
        except Exception as e:
            await query.edit_message_text(f"❌ Error: {e}. Check your Binance Testnet API keys in .env", parse_mode="Markdown")
    elif data == "premium":
        level = get_user_level(chat_id)
        if level >= 1:
            subscribers = load_subscribers()
            data_sub = subscribers.get(str(chat_id), {})
            plan = data_sub.get("plan", "free")
            end_str = data_sub.get("end")
            insignia = get_user_insignia(chat_id)
            commission = get_user_commission(chat_id)
            benefits = get_level_benefits(level)
            level_name = LEVELS[level]["name"]
            if end_str:
                end_date = datetime.fromisoformat(end_str).strftime("%d/%m/%Y")
                message = f"✨ *{insignia} {level_name}* ✨\n\n📅 *Valid until:* {end_date}\n💰 *Commission:* {commission*100:.1f}%\n🎁 *Benefits:* {benefits}\n\n✅ Real trading access\n✅ Reduced fee\n✅ Whale alerts"
            else:
                message = f"✨ *{insignia} {level_name}* ✨\n\n💰 *Commission:* {commission*100:.1f}%\n🎁 *Benefits:* {benefits}\n\n✅ Lifetime access\n✅ Whale alerts"
        elif level == 0:
            message = "🧭 *Explorer* (Trial)\n\n💰 Commission: 0.5%\n🎁 Benefits: 14 days free, 3 alerts, trading access\n\nUpgrade with /activate."
        else:
            message = "🔒 *FREE user*\n\nTo activate Premium, use /pay or /plans."
        await query.edit_message_text(message, parse_mode="Markdown")
    elif data == "whale":
        await whale_callback(update, context)
    elif data == "plans":
        text = """
📅 *Subscription plans* (prices in MXN, one‑time payment):

• *Monthly*: $190 / 30 days
• *Quarterly*: $540 / 90 days (save $30)
• *Yearly*: $1900 / 365 days (save $380)

To activate, type:
/pay monthly
/pay quarterly
/pay yearly

*After payment, your premium will be activated automatically.*
"""
        await query.edit_message_text(text, parse_mode="Markdown")
    elif data == "news":
        await query.edit_message_text("📰 *Fetching latest news...*", parse_mode="Markdown")
        sources = [
            "https://cointelegraph.com/rss",
            "https://cryptopotato.com/feed/",
            "https://news.google.com/rss/search?q=cryptocurrency&hl=en&gl=US&ceid=US:en"
        ]
        for url in sources:
            try:
                feed = feedparser.parse(url)
                if feed.entries:
                    message = "📰 *Latest crypto news*\n\n"
                    for entry in feed.entries[:5]:
                        title = entry.title
                        link = entry.link
                        message += f"• [{title}]({link})\n"
                    await query.edit_message_text(message, parse_mode="Markdown", disable_web_page_preview=True)
                    return
            except Exception as e:
                logger.warning(f"Error with source {url}: {e}")
                continue
        await query.edit_message_text("No news found at the moment. Try again later.", parse_mode="Markdown")
    elif data == "info":
        keyboard = [
            [InlineKeyboardButton("BTC", callback_data="info_coin_BTC")],
            [InlineKeyboardButton("ETH", callback_data="info_coin_ETH")],
            [InlineKeyboardButton("SOL", callback_data="info_coin_SOL")],
            [InlineKeyboardButton("XRP", callback_data="info_coin_XRP")],
            [InlineKeyboardButton("BNB", callback_data="info_coin_BNB")],
            [InlineKeyboardButton("LINK", callback_data="info_coin_LINK")],
            [InlineKeyboardButton("AVAX", callback_data="info_coin_AVAX")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu")]
        ]
        await query.edit_message_text("📈 *Select a coin for detailed info*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data.startswith("info_coin_"):
        symbol = data.split("_")[2]
        await show_coin_info(query, symbol)
    elif data == "buy":
        level = get_user_level(chat_id)
        if level == -1:
            await query.edit_message_text(
                "⏰ *Your trial has expired!*\n\n"
                "To continue trading, deposit on Binance with our referral link:\n"
                f"{BINANCE_REFERRAL_LINK}\n\n"
                "Or subscribe with /pay.",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text("⚠️ To buy, use the command:\n`/buy [amount] [symbol]`\nExample: `/buy 0.001 BTCUSDT`\n\nYou can also reply with YES after the confirmation.", parse_mode="Markdown")
    elif data == "sell":
        level = get_user_level(chat_id)
        if level == -1:
            await query.edit_message_text(
                "⏰ *Your trial has expired!*\n\n"
                "To continue trading, deposit on Binance with our referral link:\n"
                f"{BINANCE_REFERRAL_LINK}\n\n"
                "Or subscribe with /pay.",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text("⚠️ To sell, use the command:\n`/sell [amount] [symbol]`\nExample: `/sell 0.001 BTCUSDT`\n\nYou can also reply with YES after the confirmation.", parse_mode="Markdown")
    elif data == "activate":
        await activate_from_callback(query, chat_id)
    elif data == "plan":
        subscribers = load_subscribers()
        data_sub = subscribers.get(str(chat_id), {"plan": "free", "fee": None})
        fee = data_sub.get("fee", None)
        level = get_user_level(chat_id)
        if level >= 0:
            insignia = get_user_insignia(chat_id)
            commission = get_user_commission(chat_id)
            benefits = get_level_benefits(level)
            level_name = LEVELS[level]["name"]
            message = f"📋 *Your current level*\n\n{insignia} *{level_name}*\n💰 *Commission:* {commission*100:.1f}%\n🎁 *Benefits:* {benefits}\n\n"
            if fee:
                message += f"💰 Trade fee (testnet): {fee}%\n"
            else:
                message += "💰 No real trading.\n"
            if level == 3:
                message += "\n👑 *You are an ELITE member!*"
            else:
                message += f"\n*How to upgrade?*\n"
                message += f"1. Register on Binance using our link: {BINANCE_REFERRAL_LINK}\n"
                message += "2. Deposit the required amount:\n"
                message += "   • Trader: 50 USDT (0.3% fee)\n"
                message += "   • Pro: 100 USDT (0.2% fee + premium)\n"
                message += "   • Elite: 500 USDT (0.2% fee + VIP benefits)\n"
                message += "3. Run /activate to upgrade your level.\n"
        else:
            message = "⏰ *Trial expired.* Please deposit or subscribe to continue."
        await query.edit_message_text(message, parse_mode="Markdown")
    elif data == "copy_whale":
        await copy_whale_callback(update, context)
    elif data == "rules":
        await rules_menu(update, context)
    elif data == "snipe":
        await snipe_settings_menu(update, context)
    elif data == "sniper":
        await sniper(update, context)
    elif data == "compare":
        await compare(update, context)
    elif data == "menu":
        await start(update, context)
    else:
        await query.edit_message_text("❌ Invalid option.")

# ==================== FUNCIONES AUXILIARES ====================
async def show_status(query):
    prices = get_all_prices()
    if not prices:
        await query.edit_message_text("⚠️ Could not fetch data. Try again later.")
        return
    message = "📊 *LIVE MARKET STATUS*\n\n"
    for coin_id, symbol, name in COINS:
        if coin_id not in prices:
            continue
        data = prices[coin_id]
        price = data.get('usd', 0)
        change = data.get('usd_24h_change', 0)
        if price == 0:
            continue
        trend = "📈" if change > 0 else "📉" if change < 0 else "➡️"
        message += f"• *{symbol}*: ${price:,.0f} | {change:+.1f}% {trend}\n"
    try:
        fg = requests.get('https://api.alternative.me/fng/').json()
        value = fg['data'][0]['value']
        classification = fg['data'][0]['value_classification']
        message += f"\n😨 *Fear & Greed:* {value}/100 ({classification})"
    except:
        pass
    await query.edit_message_text(message, parse_mode="Markdown")

async def show_alerts(query, chat_id):
    data = USER_DATA.get
