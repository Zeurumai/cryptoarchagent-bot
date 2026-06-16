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
from datetime import datetime, timedelta
from flask import Flask, request
from dotenv import load_dotenv
import mercadopago
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from whale_advanced import obtener_alertas_bitcoin, obtener_alertas_ethereum, analizar_alerta, analizar_con_ia
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
        "commission": 0.5,
        "insignia": "🔰",
        "benefits": "14 days free, 3 alerts, trading access, whales, news",
        "active": False
    },
    1: {
        "name": "Trader",
        "emoji": "📊",
        "commission": 0.3,
        "insignia": "⚡",
        "benefits": "Full access, no subscription, reduced commission",
        "active": True
    },
    2: {
        "name": "Pro",
        "emoji": "⭐",
        "commission": 0.2,
        "insignia": "🌟",
        "benefits": "Subscription included, direct team access (priority)",
        "active": True
    },
    3: {
        "name": "Elite",
        "emoji": "👑",
        "commission": 0.2,
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
                        "commission_rate": row.get("commission_rate", 0.5),
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
                    "commission_rate": data.get("commission_rate", 0.5),
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
        data["commission_rate"] = 0.5
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
    elif plan_key == "test":
        return start_date + timedelta(days=7)
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
        "commission_rate": 0.2,
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
        "To unlock full benefits:\n"
        "• Deposit ≥ 50 USDT → Trader (0.3% comisión)\n"
        "• Deposit ≥ 100 USDT → Pro (0.2% comisión, premium)\n"
        "• Deposit ≥ 500 USDT → Elite (0.2% comisión, VIP)\n\n"
        "Use /plan to see your current level.\n"
        "Use /activate to check your deposit level.",
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
        await whale_callback(query)
    elif data == "plans":
        text = """
📅 *Subscription plans* (prices in MXN, one‑time payment):

• *Test*: $10 / 7 days
• *Monthly*: $190 / 30 days
• *Quarterly*: $540 / 90 days (save $30)
• *Yearly*: $1900 / 365 days (save $380)

To activate, type:
/pay test
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
    data = USER_DATA.get(str(chat_id), {})
    alerts = data.get("alerts", [])
    if not alerts:
        await query.edit_message_text("🔔 You have no active alerts.\nUse '➕ New alert' to create one.")
        return
    keyboard = []
    for i, a in enumerate(alerts):
        state = "✅" if a.get("active", True) else "❌"
        keyboard.append([InlineKeyboardButton(f"{state} {a['coin']} {a['condition']} ${a['price']:,.0f}", callback_data=f"alert_toggle_{i}")])
        keyboard.append([InlineKeyboardButton(f"🗑 Delete {a['coin']}", callback_data=f"alert_delete_{i}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu")])
    await query.edit_message_text("🔔 *Your alerts*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

def toggle_alert(chat_id, idx):
    chat_str = str(chat_id)
    if chat_str not in USER_DATA:
        return
    alerts = USER_DATA[chat_str].get("alerts", [])
    if idx < len(alerts):
        alerts[idx]["active"] = not alerts[idx].get("active", True)
        save_user_data()

def delete_alert(chat_id, idx):
    chat_str = str(chat_id)
    if chat_str not in USER_DATA:
        return
    alerts = USER_DATA[chat_str].get("alerts", [])
    if idx < len(alerts):
        alerts.pop(idx)
        save_user_data()

async def new_alert_coin(query, chat_id):
    level = get_user_level(chat_id)
    if level == 0:
        data = USER_DATA.get(str(chat_id), {})
        alerts = data.get("alerts", [])
        if len(alerts) >= 3:
            await query.edit_message_text(
                "⚠️ *Explorer users can only have 3 active alerts.*\n"
                "Upgrade to Trader/Pro/Elite for unlimited alerts.\n"
                "Use /activate to check your level.",
                parse_mode="Markdown"
            )
            return
    keyboard = []
    for _, symbol, name in COINS:
        keyboard.append([InlineKeyboardButton(f"{symbol} - {name}", callback_data=f"new_alert_price_{symbol}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu")])
    await query.edit_message_text("💰 *New alert - Select coin*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def new_alert_condition(query, coin, chat_id):
    keyboard = [
        [InlineKeyboardButton("🚀 Price goes above (> 🚀)", callback_data="new_alert_condition_>")],
        [InlineKeyboardButton("📉 Price goes below (< 📉)", callback_data="new_alert_condition_<")],
        [InlineKeyboardButton("🔙 Back", callback_data="new_alert_coin")]
    ]
    await query.edit_message_text(f"📊 *Coin: {coin}*\nWhich condition to monitor?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_alert_price"):
        await receive_alert_price(update, context)
    elif context.user_data.get("awaiting_report_time"):
        await receive_report_time(update, context)
    else:
        await confirm_order(update, context)

async def receive_alert_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text.replace(",", ""))
        coin = context.user_data.get("new_alert_coin")
        condition = context.user_data.get("new_alert_condition")
        if not coin or not condition:
            await update.message.reply_text("❌ Error. Try again from the menu.")
            return
        chat_str = str(update.effective_chat.id)
        if chat_str not in USER_DATA:
            USER_DATA[chat_str] = {"alerts": [], "reports": {}}
        USER_DATA[chat_str]["alerts"].append({
            "coin": coin,
            "condition": condition,
            "price": price,
            "active": True
        })
        save_user_data()
        await update.message.reply_text(f"✅ Alert created for {coin} {condition} ${price:,.2f}")
    except ValueError:
        await update.message.reply_text("❌ Invalid number. Use digits and decimal point (e.g. 50000).")
    finally:
        context.user_data.pop("awaiting_alert_price", None)
        context.user_data.pop("new_alert_coin", None)
        context.user_data.pop("new_alert_condition", None)

async def receive_report_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time_str = update.message.text.strip()
    if len(time_str) != 5 or time_str[2] != ":":
        await update.message.reply_text("❌ Invalid format. Use HH:MM (e.g. 08:30).")
        return
    try:
        hour = int(time_str[:2])
        minute = int(time_str[3:])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except:
        await update.message.reply_text("❌ Invalid time.")
        return
    report_type = context.user_data.get("report_type")
    if not report_type:
        await update.message.reply_text("❌ Error. Try again.")
        return
    chat_str = str(update.effective_chat.id)
    if chat_str not in USER_DATA:
        USER_DATA[chat_str] = {"alerts": [], "reports": {}}
    USER_DATA[chat_str]["reports"][report_type] = time_str
    save_user_data()
    reschedule_reports()
    await update.message.reply_text(f"✅ {report_type.upper()} report scheduled at {time_str}.")
    context.user_data.pop("awaiting_report_time", None)
    context.user_data.pop("report_type", None)

async def reports_menu(query, chat_id):
    keyboard = [
        [InlineKeyboardButton("🌅 Morning report", callback_data="report_type_morning")],
        [InlineKeyboardButton("☀️ Midday report", callback_data="report_type_midday")],
        [InlineKeyboardButton("🌙 Evening report", callback_data="report_type_evening")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu")]
    ]
    await query.edit_message_text("📅 *Auto report settings*\nChoose which report to schedule:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def help_menu(query):
    message = """
📌 *Commands & functions*

/start - Main menu
/status - Market status
/alerts - View/manage alerts
/balance - Testnet balance
/premium - Your premium status
/pay - Activate Premium (one‑time payment)
/plans - View subscription plans
/whale - Whale movements (free, with AI)
/info - Detailed coin info (e.g. /info BTC)
/news - Latest crypto news
/buy - Buy on Testnet (e.g. /buy 0.001 BTCUSDT)
/sell - Sell on Testnet (e.g. /sell 0.001 BTCUSDT)
/activate - Activate your plan based on Binance balance
/plan - Show your current level

*Benefits by level:*
🧭 Explorer (0.5% comisión) - 14 days free
📊 Trader (0.3%) - Deposit ≥ 50 USDT
⭐ Pro (0.2% + premium) - Deposit ≥ 100 USDT
👑 Elite (0.2% + VIP) - Deposit ≥ 500 USDT

⚠️ *Legal*: Not a financial advisor. Use /terms for details.
"""
    await query.edit_message_text(message, parse_mode="Markdown")

# ==================== WHALE FUNCTIONS ====================
async def whale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🐋 *Fetching whale movements...*", parse_mode="Markdown")
    
    btc_alerts = await asyncio.to_thread(obtener_alertas_bitcoin, 50000, 3)
    eth_alerts = await asyncio.to_thread(obtener_alertas_ethereum, 10000, 3)
    
    output = "📊 *RECENT WHALE MOVEMENTS*\n"
    output += "_The following data is informational only. Not investment advice._\n\n"
    
    if btc_alerts:
        output += "₿ *Bitcoin (BTC)*\n"
        for alert in btc_alerts:
            emoji, desc, sentiment, value = analizar_alerta(alert)
            output += f"{emoji} `{desc}`\n"
            output += f"   💰 Value: ${value:,.2f} USD | {sentiment}\n"
            ia_analysis = analizar_con_ia(alert)
            if ia_analysis:
                output += f"   🧠 *AI:* {ia_analysis}\n"
            output += "\n"
    else:
        output += "₿ *Bitcoin (BTC)*\nNo significant movements recently.\n\n"
    
    if eth_alerts:
        output += "⟠ *Ethereum (ETH)*\n"
        for alert in eth_alerts:
            emoji, desc, sentiment, value = analizar_alerta(alert)
            output += f"{emoji} `{desc}`\n"
            output += f"   💰 Value: ${value:,.2f} USD | {sentiment}\n"
            ia_analysis = analizar_con_ia(alert)
            if ia_analysis:
                output += f"   🧠 *AI:* {ia_analysis}\n"
            output += "\n"
    else:
        output += "⟠ *Ethereum (ETH)*\nNo significant movements recently.\n\n"
    
    output += "💡 *Note:* Accumulation/distribution analyses are automatic and should not be taken as buy/sell recommendations."
    await update.message.reply_text(output, parse_mode="Markdown")

async def whale_callback(query):
    await query.edit_message_text("🐋 *Fetching whale movements...*", parse_mode="Markdown")
    
    btc_alerts = await asyncio.to_thread(obtener_alertas_bitcoin, 50000, 3)
    eth_alerts = await asyncio.to_thread(obtener_alertas_ethereum, 10000, 3)
    
    output = "📊 *RECENT WHALE MOVEMENTS*\n"
    output += "_The following data is informational only. Not investment advice._\n\n"
    
    if btc_alerts:
        output += "₿ *Bitcoin (BTC)*\n"
        for alert in btc_alerts:
            emoji, desc, sentiment, value = analizar_alerta(alert)
            output += f"{emoji} `{desc}`\n"
            output += f"   💰 Value: ${value:,.2f} USD | {sentiment}\n"
            ia_analysis = analizar_con_ia(alert)
            if ia_analysis:
                output += f"   🧠 *AI:* {ia_analysis}\n"
            output += "\n"
    else:
        output += "₿ *Bitcoin (BTC)*\nNo significant movements recently.\n\n"
    
    if eth_alerts:
        output += "⟠ *Ethereum (ETH)*\n"
        for alert in eth_alerts:
            emoji, desc, sentiment, value = analizar_alerta(alert)
            output += f"{emoji} `{desc}`\n"
            output += f"   💰 Value: ${value:,.2f} USD | {sentiment}\n"
            ia_analysis = analizar_con_ia(alert)
            if ia_analysis:
                output += f"   🧠 *AI:* {ia_analysis}\n"
            output += "\n"
    else:
        output += "⟠ *Ethereum (ETH)*\nNo significant movements recently.\n\n"
    
    output += "💡 *Note:* Accumulation/distribution analyses are automatic and should not be taken as buy/sell recommendations."
    await query.edit_message_text(output, parse_mode="Markdown")

async def show_coin_info(query, symbol):
    mapping = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "ripple",
               "BNB": "binancecoin", "LINK": "chainlink", "AVAX": "avalanche-2"}
    coin_id = mapping.get(symbol)
    if not coin_id:
        await query.edit_message_text("❌ Unsupported coin.")
        return
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code != 200:
            await query.edit_message_text("⚠️ Could not fetch data. Try again later.")
            return
        data = r.json()
        price = data["market_data"]["current_price"]["usd"]
        market_cap = data["market_data"]["market_cap"]["usd"]
        volume = data["market_data"]["total_volume"]["usd"]
        change_24h = data["market_data"]["price_change_percentage_24h"]
        ath = data["market_data"]["ath"]["usd"]
        atl = data["market_data"]["atl"]["usd"]
        rank = data["market_cap_rank"]
        message = (
            f"📈 *{symbol} - {data['name']}*\n\n"
            f"💰 Price: ${price:,.2f} USD\n"
            f"📊 Market cap: ${market_cap:,.0f}\n"
            f"📉 Volume (24h): ${volume:,.0f}\n"
            f"📈 24h change: {change_24h:.2f}%\n"
            f"🏆 All-time high: ${ath:,.2f}\n"
            f"📉 All-time low: ${atl:,.2f}\n"
            f"🔢 Rank: #{rank}\n\n"
            f"Data from CoinGecko (informational only)."
        )
        await query.edit_message_text(message, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in info callback: {e}")
        await query.edit_message_text("❌ Error fetching data.")

async def activate_from_callback(query, chat_id):
    await query.edit_message_text(
        "🔍 *Checking your Binance balance...*\n\n"
        "⚠️ *IMPORTANT:* This checks your TESTNET balance.\n"
        "To activate a real plan, deposit on real Binance.\n\n"
        "Minimum deposits for levels:\n"
        "• Trader: 50 USDT (0.3% fee)\n"
        "• Pro: 100 USDT (0.2% fee + premium)\n"
        "• Elite: 500 USDT (0.2% fee + VIP benefits)",
        parse_mode="Markdown"
    )
    try:
        engine = TradingEngine(testnet=True)
        usdt_balance = engine.get_balance("USDT")
        btc_balance = engine.get_balance("BTC")
        if btc_balance >= 0.01 or usdt_balance >= 500:
            level = 3
            commission = 0.2
            insignia = "👑"
            name = "Elite"
        elif usdt_balance >= 100:
            level = 2
            commission = 0.2
            insignia = "🌟"
            name = "Pro"
        elif usdt_balance >= 50:
            level = 1
            commission = 0.3
            insignia = "⚡"
            name = "Trader"
        else:
            level = 0
            commission = 0.5
            insignia = "🔰"
            name = "Explorer (trial)"
        subscribers = load_subscribers()
        subscribers[str(chat_id)] = {
            "plan": "free",
            "deposit_level": level,
            "commission_rate": commission,
            "insignia": insignia,
            "active": True if level > 0 else True
        }
        save_subscribers(subscribers)
        message = f"✅ *Level detected on TESTNET: {insignia} {name}*\n"
        message += f"💰 Commission: {commission*100:.1f}%\n"
        message += f"📊 Detected balance (TESTNET): USDT ${usdt_balance:.2f}, BTC {btc_balance:.8f}\n\n"
        if level == 0:
            message += "Deposit ≥ 50 USDT to reach Trader level."
        elif level == 1:
            message += "Deposit ≥ 100 USDT to reach Pro level."
        elif level == 2:
            message += "Deposit ≥ 500 USDT to reach Elite level."
        else:
            message += "👑 You are ELITE! Congratulations."
        await query.edit_message_text(message, parse_mode="Markdown")
    except Exception as e:
        await query.edit_message_text(f"❌ Error checking balance: {e}\nMake sure your Binance Testnet API keys are correct in .env.", parse_mode="Markdown")

# ==================== COMMANDS ====================
async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"🆔 *Your user ID:* `{chat_id}`", parse_mode="Markdown")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        engine = TradingEngine(testnet=True)
        usdt_balance = engine.get_balance("USDT")
        btc_balance = engine.get_balance("BTC")
        message = f"💰 *Testnet Balance*\nUSDT: ${usdt_balance:.2f}\nBTC: {btc_balance:.8f}\n\n⚠️ This is TESTNET balance (fake money). To trade real money, deposit on real Binance and use /activate."
        await update.message.reply_text(message, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}. Check your Binance Testnet API keys in .env", parse_mode="Markdown")

async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    level = get_user_level(chat_id)
    if level >= 1:
        subscribers = load_subscribers()
        data = subscribers.get(str(chat_id), {})
        plan = data.get("plan", "free")
        end_str = data.get("end")
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
    await update.message.reply_text(message, parse_mode="Markdown")

async def plans_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
📅 *Subscription plans* (prices in MXN, one‑time payment):

• *Test*: $10 / 7 days
• *Monthly*: $190 / 30 days
• *Quarterly*: $540 / 90 days (save $30)
• *Yearly*: $1900 / 365 days (save $380)

To activate, type:
/pay test
/pay monthly
/pay quarterly
/pay yearly

*After payment, your premium will be activated automatically.*
"""
    await update.message.reply_text(text, parse_mode="Markdown")

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("❌ Usage: `/info [symbol]`\nExample: `/info BTC`", parse_mode="Markdown")
        return
    symbol = args[0].upper()
    mapping = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "XRP": "ripple",
               "BNB": "binancecoin", "LINK": "chainlink", "AVAX": "avalanche-2"}
    coin_id = mapping.get(symbol)
    if not coin_id:
        await update.message.reply_text("❌ Unsupported coin. Options: BTC, ETH, SOL, XRP, BNB, LINK, AVAX")
        return
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code != 200:
            await update.message.reply_text("⚠️ Could not fetch data. Try again later.")
            return
        data = r.json()
        price = data["market_data"]["current_price"]["usd"]
        market_cap = data["market_data"]["market_cap"]["usd"]
        volume = data["market_data"]["total_volume"]["usd"]
        change_24h = data["market_data"]["price_change_percentage_24h"]
        ath = data["market_data"]["ath"]["usd"]
        atl = data["market_data"]["atl"]["usd"]
        rank = data["market_cap_rank"]
        message = (
            f"📈 *{symbol} - {data['name']}*\n\n"
            f"💰 Price: ${price:,.2f} USD\n"
            f"📊 Market cap: ${market_cap:,.0f}\n"
            f"📉 Volume (24h): ${volume:,.0f}\n"
            f"📈 24h change: {change_24h:.2f}%\n"
            f"🏆 All-time high: ${ath:,.2f}\n"
            f"📉 All-time low: ${atl:,.2f}\n"
            f"🔢 Rank: #{rank}\n\n"
            f"Data from CoinGecko (informational only)."
        )
        await update.message.reply_text(message, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in /info: {e}")
        await update.message.reply_text("❌ Error fetching data.")

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📰 *Fetching latest news...*", parse_mode="Markdown")
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
                await update.message.reply_text(message, parse_mode="Markdown", disable_web_page_preview=True)
                return
        except Exception as e:
            logger.warning(f"Error with source {url}: {e}")
            continue
    await update.message.reply_text("No news found at the moment. Try again later.")

async def setemail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args
    if not args:
        await update.message.reply_text("❌ Usage: `/setemail your@email.com`", parse_mode="Markdown")
        return
    email = args[0].strip()
    if "@" not in email or "." not in email:
        await update.message.reply_text("❌ Invalid email address.")
        return
    set_user_email(chat_id, email)
    await update.message.reply_text(f"✅ Email saved: `{email}`. You can now use /pay.", parse_mode="Markdown")

# ==================== PAYMENT COMMAND ====================
async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args

    user_email = get_user_email(chat_id)
    if not user_email:
        await update.message.reply_text(
            "❌ Please set your email first using `/setemail your@email.com`.\n"
            "This email will be used for the payment receipt.",
            parse_mode="Markdown"
        )
        return

    if not args:
        await update.message.reply_text(
            "ℹ️ *One‑time payment plans*\n\n"
            "Use: `/pay test` (MXN 10, 7 days)\n"
            "Use: `/pay monthly` (MXN 190, 30 days)\n"
            "Use: `/pay quarterly` (MXN 540, 90 days)\n"
            "Use: `/pay yearly` (MXN 1900, 365 days)\n\n"
            "You will receive a payment link. After payment, your Premium will be activated automatically.",
            parse_mode="Markdown"
        )
        return

    plan_key = args[0].lower()
    if plan_key == "test":
        amount = 10.00
        days = 7
        plan_name = "Test (7 days)"
    elif plan_key == "monthly":
        amount = 190.00
        days = 30
        plan_name = "Monthly"
    elif plan_key == "quarterly":
        amount = 540.00
        days = 90
        plan_name = "Quarterly"
    elif plan_key == "yearly":
        amount = 1900.00
        days = 365
        plan_name = "Yearly"
    else:
        await update.message.reply_text("❌ Invalid plan. Use: test, monthly, quarterly, yearly")
        return

    sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
    preference_data = {
        "items": [{
            "title": f"CryptoArch Agent - {plan_name} Plan",
            "quantity": 1,
            "currency_id": "MXN",
            "unit_price": amount
        }],
        "external_reference": f"{chat_id}:{plan_key}",
        "payer": {"email": user_email},
        "back_urls": {
            "success": "https://t.me/CryptoArchTrading_bot",
            "failure": "https://t.me/CryptoArchTrading_bot"
        },
        "auto_return": "approved",
        "notification_url": MP_WEBHOOK_URL
    }

    try:
        response = sdk.preference().create(preference_data)
        logger.info(f"MercadoPago response: {response}")
        if response.get("status") == 201:
            payment_link = response["response"]["init_point"]
            await update.message.reply_text(
                f"✅ *Payment generated for {plan_name} plan*\n\n"
                f"🔗 [Click here to pay ${amount} MXN]({payment_link})\n\n"
                f"After payment, your Premium will be activated for {days} days.\n"
                f"Renewal is not automatic – you will be notified before expiration.",
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
        else:
            error_msg = response.get("message", "Unknown error")
            await update.message.reply_text(f"❌ Error creating payment: {error_msg}")
    except Exception as e:
        logger.error(f"Error in /pay: {e}")
        await update.message.reply_text("❌ Internal error. Try again later.")

# ==================== TRADING TESTNET ====================
async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    level = get_user_level(chat_id)
    if level == -1:
        await update.message.reply_text(
            "⏰ *Your trial has expired!*\n\n"
            "To continue trading, deposit on Binance with our referral link:\n"
            f"{BINANCE_REFERRAL_LINK}\n\n"
            "Or subscribe with /pay.",
            parse_mode="Markdown"
        )
        return

    args = context.args
    if len(args) != 2:
        await update.message.reply_text("⚠️ Usage: `/buy [amount] [symbol]`\nExample: `/buy 0.001 BTCUSDT`", parse_mode="Markdown")
        return
    try:
        amount = float(args[0])
        symbol = args[1].upper()
        if amount <= 0:
            raise ValueError
    except:
        await update.message.reply_text("❌ Invalid amount. Example: 0.001")
        return
    try:
        engine = TradingEngine(testnet=True)
        usdt_balance = engine.get_balance("USDT")
        price = engine.get_price(symbol)
        cost = amount * price
        if cost > usdt_balance:
            await update.message.reply_text(f"❌ Insufficient testnet balance. Need ~${cost:.2f} USDT. You have ${usdt_balance:.2f} USDT.")
            return
        commission = get_user_commission(chat_id)
        await update.message.reply_text(f"🟢 *Confirm buy*\n{amount} {symbol} ≈ ${cost:.2f} USD\nReply with *YES* (uppercase) to execute on testnet.\nCommission: {commission*100:.1f}%", parse_mode="Markdown")
        context.user_data["pending_order"] = {"type": "buy", "symbol": symbol, "amount": amount}
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    level = get_user_level(chat_id)
    if level == -1:
        await update.message.reply_text(
            "⏰ *Your trial has expired!*\n\n"
            "To continue trading, deposit on Binance with our referral link:\n"
            f"{BINANCE_REFERRAL_LINK}\n\n"
            "Or subscribe with /pay.",
            parse_mode="Markdown"
        )
        return

    args = context.args
    if len(args) != 2:
        await update.message.reply_text("⚠️ Usage: `/sell [amount] [symbol]`\nExample: `/sell 0.001 BTCUSDT`", parse_mode="Markdown")
        return
    try:
        amount = float(args[0])
        symbol = args[1].upper()
        if amount <= 0:
            raise ValueError
    except:
        await update.message.reply_text("❌ Invalid amount.")
        return
    try:
        engine = TradingEngine(testnet=True)
        base_asset = symbol.replace("USDT", "")
        balance_asset = engine.get_balance(base_asset)
        if balance_asset < amount:
            await update.message.reply_text(f"❌ Insufficient {base_asset} testnet balance. You have {balance_asset:.8f}. Need {amount}.")
            return
        price = engine.get_price(symbol)
        value = amount * price
        commission = get_user_commission(chat_id)
        await update.message.reply_text(f"🔴 *Confirm sell*\n{amount} {symbol} ≈ ${value:.2f} USD\nReply with *YES* (uppercase) to execute on testnet.\nCommission: {commission*100:.1f}%", parse_mode="Markdown")
        context.user_data["pending_order"] = {"type": "sell", "symbol": symbol, "amount": amount}
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text not in ("yes", "sí", "si"):
        return
    order = context.user_data.get("pending_order")
    if not order:
        return
    chat_id = update.effective_chat.id
    engine = TradingEngine(testnet=True)
    commission = get_user_commission(chat_id)
    if order["type"] == "buy":
        result = engine.buy_market(order["symbol"], order["amount"])
        if result:
            if commission is not None and commission > 0:
                fee = order["amount"] * commission
                logger.info(f"Commission charged: {fee} {order['symbol']} ({commission*100:.1f}%)")
            await update.message.reply_text(f"✅ Buy executed on testnet. ID: {result['orderId']}")
        else:
            await update.message.reply_text("❌ Buy failed.")
    elif order["type"] == "sell":
        result = engine.sell_market(order["symbol"], order["amount"])
        if result:
            if commission is not None and commission > 0:
                fee = order["amount"] * commission
                logger.info(f"Commission charged: {fee} {order['symbol']} ({commission*100:.1f}%)")
            await update.message.reply_text(f"✅ Sell executed on testnet. ID: {result['orderId']}")
        else:
            await update.message.reply_text("❌ Sell failed.")
    context.user_data.pop("pending_order", None)

# ==================== ACTIVATE / PLAN ====================
async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        "🔍 *Checking your Binance balance...*\n\n"
        "⚠️ *IMPORTANT:* This checks your TESTNET balance.\n"
        "To activate a real plan, deposit on real Binance.\n\n"
        "Minimum deposits for levels:\n"
        "• Trader: 50 USDT (0.3% fee)\n"
        "• Pro: 100 USDT (0.2% fee + premium)\n"
        "• Elite: 500 USDT (0.2% fee + VIP benefits)",
        parse_mode="Markdown"
    )
    try:
        engine = TradingEngine(testnet=True)
        usdt_balance = engine.get_balance("USDT")
        btc_balance = engine.get_balance("BTC")
        if btc_balance >= 0.01 or usdt_balance >= 500:
            level = 3
            commission = 0.2
            insignia = "👑"
            name = "Elite"
        elif usdt_balance >= 100:
            level = 2
            commission = 0.2
            insignia = "🌟"
            name = "Pro"
        elif usdt_balance >= 50:
            level = 1
            commission = 0.3
            insignia = "⚡"
            name = "Trader"
        else:
            level = 0
            commission = 0.5
            insignia = "🔰"
            name = "Explorer (trial)"
        subscribers = load_subscribers()
        subscribers[str(chat_id)] = {
            "plan": "free",
            "deposit_level": level,
            "commission_rate": commission,
            "insignia": insignia,
            "active": True if level > 0 else True
        }
        save_subscribers(subscribers)
        message = f"✅ *Level detected on TESTNET: {insignia} {name}*\n"
        message += f"💰 Commission: {commission*100:.1f}%\n"
        message += f"📊 Detected balance (TESTNET): USDT ${usdt_balance:.2f}, BTC {btc_balance:.8f}\n\n"
        if level == 0:
            message += "Deposit ≥ 50 USDT to reach Trader level."
        elif level == 1:
            message += "Deposit ≥ 100 USDT to reach Pro level."
        elif level == 2:
            message += "Deposit ≥ 500 USDT to reach Elite level."
        else:
            message += "👑 You are ELITE! Congratulations."
        await update.message.reply_text(message, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error checking balance: {e}\nMake sure your Binance Testnet API keys are correct in .env.", parse_mode="Markdown")

async def plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
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
    await update.message.reply_text(message, parse_mode="Markdown")

# ==================== ADMIN COMMAND ====================
ADMIN_IDS = [8355456581]  # Tu ID de Telegram

async def force_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Not authorized.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /force_premium ID LEVEL (0-3)")
        return
    try:
        target_id = int(args[0])
        level = int(args[1])
        if level < 0 or level > 3:
            await update.message.reply_text("Level must be 0-3.")
            return
        subscribers = load_subscribers()
        subscribers[str(target_id)] = {
            "plan": "free",
            "deposit_level": level,
            "commission_rate": LEVELS[level]["commission"],
            "insignia": LEVELS[level]["insignia"],
            "active": True,
            "start": datetime.now().isoformat(),
            "end": (datetime.now() + timedelta(days=365)).isoformat()
        }
        save_subscribers(subscribers)
        await update.message.reply_text(f"✅ User {target_id} set to level {level} ({LEVELS[level]['name']})")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# ==================== WEBHOOK ====================
if MP_WEBHOOK_URL:
    webhook_app = Flask(__name__)

    @webhook_app.route('/webhook', methods=['POST'])
    def webhook():
        data = request.json
        logger.info(f"📩 Webhook notification: {data}")
        try:
            if data.get("type") == "payment":
                payment_id = data["data"]["id"]
                sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
                payment_response = sdk.payment().get(payment_id)
                payment_data = payment_response["response"]
                external_ref = payment_data.get("external_reference")
                status = payment_data.get("status")
                if status == "approved" and external_ref:
                    parts = external_ref.split(":")
                    if len(parts) == 2:
                        chat_id_str, plan_key = parts
                        chat_id = int(chat_id_str)
                        activate_premium(chat_id, plan_key)
            return "OK", 200
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return "Error", 500

    def run_webhook():
        port = int(os.getenv("PORT", 5000))
        webhook_app.run(host='0.0.0.0', port=port)

# ==================== MAIN ====================
if __name__ == "__main__":
    # Asignar nivel Elite al admin (8355456581) al iniciar
    subscribers = load_subscribers()
    admin_id = str(8355456581)
    if admin_id not in subscribers or subscribers[admin_id].get("deposit_level", 0) < 3:
        subscribers[admin_id] = {
            "plan": "free",
            "deposit_level": 3,
            "commission_rate": 0.2,
            "insignia": "👑",
            "active": True,
            "start": datetime.now().isoformat(),
            "end": (datetime.now() + timedelta(days=365)).isoformat()
        }
        save_subscribers(subscribers)
        logger.info("👑 Admin set to ELITE level (0.2% commission)")

    if MP_WEBHOOK_URL:
        threading.Thread(target=run_webhook, daemon=True).start()
        logger.info("🔄 Webhook server started on port 5000 (or PORT env)")
    else:
        logger.info("⚠️ MP_WEBHOOK_URL not set. Webhook not started.")

    reschedule_reports()

    app = Application.builder().tok
