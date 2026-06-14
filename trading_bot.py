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

load_dotenv()

# ==================== CONFIGURATION ====================
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

# ==================== USER DATA (alerts & reports) ====================
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

# ==================== SUBSCRIPTIONS & PLANS ====================
SUBSCRIBERS_FILE = "subscribers.json"

def load_subscribers():
    try:
        with open(SUBSCRIBERS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_subscribers(subscribers):
    with open(SUBSCRIBERS_FILE, "w") as f:
        json.dump(subscribers, f, indent=2, default=str)

def calculate_plan_end(plan: str, start_date: datetime) -> datetime:
    if plan == "monthly":
        return start_date + timedelta(days=30)
    elif plan == "quarterly":
        return start_date + timedelta(days=90)
    elif plan == "yearly":
        return start_date + timedelta(days=365)
    elif plan == "test":
        return start_date + timedelta(days=30)
    else:
        return start_date

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

def activate_premium(chat_id, plan):
    subscribers = load_subscribers()
    start = datetime.now()
    end = calculate_plan_end(plan, start)
    subscribers[str(chat_id)] = {
        "plan": plan,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "active": True
    }
    save_subscribers(subscribers)
    logger.info(f"✅ Premium activated for {chat_id} with plan {plan}")

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
    await update.message.reply_text(
        "✅ *Welcome to CryptoArch Agent!*\n\n"
        "You can now use the bot. Here are some suggestions:\n"
        "• Use /start to see the main menu.\n"
        "• Use /plans to view subscription plans.\n"
        "• Use /pay monthly (or quarterly, yearly, test) to activate Premium.\n"
        "• Use /whale to see whale movements (free).\n"
        "• Use /info BTC for detailed coin data.\n"
        "• Use /news for latest crypto news.\n"
        "• Use /balance to see Testnet balance.\n"
        "• Use /buy and /sell to trade on Testnet.\n"
        "• Use /activate to activate your plan based on Binance balance.\n"
        "• Use /plan to see your current plan.\n\n"
        "If you have questions, type /help.",
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

    keyboard = [
        [InlineKeyboardButton("📊 Market status", callback_data="status")],
        [InlineKeyboardButton("🔔 My alerts", callback_data="alerts_list")],
        [InlineKeyboardButton("➕ New alert", callback_data="new_alert_coin")],
        [InlineKeyboardButton("📅 Auto reports", callback_data="reports_config")],
        [InlineKeyboardButton("💰 My balance (Testnet)", callback_data="balance")],
        [InlineKeyboardButton("💎 My status (Premium)", callback_data="premium")],
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
        await balance(update, context)
    elif data == "premium":
        await premium(update, context)
    elif data == "pay":
        await query.edit_message_text(
            "❌ To activate Premium, use the /pay command followed by the plan.\n"
            "Example: /pay monthly\n\nTo see plans, use /plans"
        )
    elif data == "whale":
        await whale(update, context)
    elif data == "plans":
        await plans_command(update, context)
    elif data == "news":
        await news_command(update, context)
    elif data == "info":
        await info_command(update, context)
    elif data == "buy":
        await buy(update, context)
    elif data == "sell":
        await sell(update, context)
    elif data == "activate":
        await activate(update, context)
    elif data == "plan":
        await plan(update, context)
    elif data == "menu":
        await start(update, context)
    else:
        await query.edit_message_text("❌ Invalid option.")

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
/pay - Activate Premium (auto payment)
/plans - View subscription plans
/whale - Whale movements (free, with AI)
/info - Detailed coin info (e.g. /info BTC)
/news - Latest crypto news
/buy - Buy on Testnet (e.g. /buy 0.001 BTCUSDT)
/sell - Sell on Testnet (e.g. /sell 0.001 BTCUSDT)
/activate - Activate your plan based on Binance balance
/plan - Show your current plan
/terms - Legal disclaimer

*Custom alerts*
- Price above/below target
- Enable/disable alerts
- Delete alerts

*Auto reports*
- Schedule morning, midday, evening reports

*Real trading plans*
- Free: no real trading (only testnet)
- Starter: deposit 50 USDT → 0.3% fee
- Pro: deposit 100 USDT → 0.2% fee
- Lifetime: deposit 0.01 BTC or 500 USDT → 0.2% fee + benefits

⚠️ *Legal*: Not a financial advisor. Use /terms for details.
"""
    await query.edit_message_text(message, parse_mode="Markdown")

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
        await update.message.reply_text(f"❌ Error: {e}. Check your Binance Testnet API keys in .env")

async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if is_premium(chat_id):
        subscribers = load_subscribers()
        data = subscribers.get(str(chat_id), {})
        plan = data.get("plan", "monthly")
        end = data.get("end")
        if end:
            end_date = datetime.fromisoformat(end).strftime("%d/%m/%Y")
            message = f"✨ *You are PREMIUM* ✨\n\n📅 Plan: *{plan.capitalize()}*\n⏰ Valid until: {end_date}\n\n✅ Real trading access\n✅ Reduced fee 0.2%\n✅ Whale alerts"
        else:
            message = "✨ *You are PREMIUM* ✨\n\nPlan: *Lifetime*\n✅ Lifetime access\n✅ Whale alerts"
    else:
        message = "🔒 *FREE user*\n\nTo activate Premium, use /pay or /plans.\n💰 Plans from $190 MXN/month"
    await update.message.reply_text(message, parse_mode="Markdown")

async def plans_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
📅 *Subscription plans* (prices in MXN, fees included):

• *Monthly*: $190 / month
• *Quarterly*: $540 / quarter (save $30)
• *Yearly*: $1900 / year (save $380)
• *Test*: $10 / month (for testing)

To activate, type:
/pay monthly
/pay quarterly
/pay yearly
/pay test

*Includes whale alerts, AI analysis and more.*
"""
    await update.message.reply_text(text, parse_mode="Markdown")

# ==================== INFO & NEWS ====================
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

# ==================== PAYMENT COMMAND (WITH WEBHOOK SUPPORT) ====================
async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        await update.message.reply_text(
            "ℹ️ *Subscription plans*\n\n"
            "Use: `/pay monthly` (MXN 190/mes)\n"
            "Use: `/pay quarterly` (MXN 540/trimestre)\n"
            "Use: `/pay yearly` (MXN 1900/año)\n"
            "Use: `/pay test` (MXN 10/mes for testing)\n\n"
            "You will receive a payment link. After the first payment, the subscription will renew automatically.",
            parse_mode="Markdown"
        )
        return

    plan_key = args[0].lower()
    if plan_key == "monthly":
        amount = 190.00
        frequency = 1
        plan_name = "Monthly"
    elif plan_key == "quarterly":
        amount = 540.00
        frequency = 3
        plan_name = "Quarterly"
    elif plan_key == "yearly":
        amount = 1900.00
        frequency = 12
        plan_name = "Yearly"
    elif plan_key == "test":
        amount = 10.00
        frequency = 1
        plan_name = "Test"
    else:
        await update.message.reply_text("❌ Invalid plan. Use: monthly, quarterly, yearly, test")
        return

    # Email dinámico para evitar conflicto "payer and collector cannot be the same user"
    payer_email = f"user_{chat_id}@telegram.user"

    sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
    subscription_data = {
        "reason": f"CryptoArch Agent - {plan_name} Plan",
        "external_reference": str(chat_id),
        "payer_email": payer_email,
        "back_url": "https://t.me/CryptoArchTrading_bot",
        "auto_recurring": {
            "frequency": frequency,
            "frequency_type": "months",
            "transaction_amount": amount,
            "currency_id": "MXN"
        }
    }

    try:
        subscription_response = sdk.preapproval().create(subscription_data)
        print("🔍 Full Mercado Pago response:", subscription_response)
        if subscription_response.get("status") == 201:
            subscription = subscription_response["response"]
            payment_link = subscription.get("init_point")
            subscription_id = subscription.get("id")
            # Guardar subscription_id
            subscribers = load_subscribers()
            if str(chat_id) not in subscribers:
                subscribers[str(chat_id)] = {}
            subscribers[str(chat_id)]["subscription_id"] = subscription_id
            subscribers[str(chat_id)]["status"] = "pending"
            save_subscribers(subscribers)
            await update.message.reply_text(
                f"✅ *Subscription created successfully!*\n\n"
                f"🔗 [Click here to pay and activate]({payment_link})\n\n"
                f"After payment, your Premium will be activated automatically.\n"
                f"Future renewals will be automatic.",
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
        else:
            error_msg = subscription_response.get("response", {}).get("message", "Unknown error")
            await update.message.reply_text(f"❌ Error: {error_msg}")
    except Exception as e:
        logger.error(f"Error creating subscription: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

# ==================== WHALE ALERTS (AI) ====================
async def whale(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        message = update.callback_query.message
        await message.reply_text("🐋 *Fetching whale movements...*", parse_mode="Markdown")
        await update.callback_query.answer()
    else:
        message = update.message
        await message.reply_text("🐋 *Fetching whale movements...*", parse_mode="Markdown")

    btc_alerts, eth_alerts = await asyncio.gather(
        obtener_alertas_bitcoin(min_value_usd=50000, limit=3),
        obtener_alertas_ethereum(min_value_usd=10000, limit=3)
    )

    output = "📊 *RECENT WHALE MOVEMENTS*\n"
    output += "_The following data is informational only. Not investment advice._\n\n"

    if btc_alerts:
        output += "₿ *Bitcoin (BTC)*\n"
        for alert in btc_alerts:
            emoji, desc, sentiment, value = analizar_alerta(alert)
            output += f"{emoji} `{desc}`\n"
            output += f"   💰 Value: ${value:,.2f} USD | {sentiment}\n"
            ia_analysis = analizar_con_ia(
                coin="BTC",
                amount=alert["amount"],
                value_usd=alert["amount_usd"],
                tx_type=alert.get("transaction_type", "transfer"),
                description=alert["description"]
            )
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
            ia_analysis = analizar_con_ia(
                coin="ETH",
                amount=alert["amount"],
                value_usd=alert["amount_usd"],
                tx_type=alert.get("transaction_type", "transfer"),
                description=alert["description"]
            )
            if ia_analysis:
                output += f"   🧠 *AI:* {ia_analysis}\n"
            output += "\n"
    else:
        output += "⟠ *Ethereum (ETH)*\nNo significant movements recently.\n\n"

    output += "💡 *Note:* Accumulation/distribution analyses are automatic and should not be taken as buy/sell recommendations."
    await message.reply_text(output, parse_mode="Markdown")

# ==================== SIMULATED TRADING (TESTNET) ====================
async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await update.message.reply_text(f"🟢 *Confirm buy*\n{amount} {symbol} ≈ ${cost:.2f} USD\nReply with *YES* (uppercase) to execute on testnet.", parse_mode="Markdown")
        context.user_data["pending_order"] = {"type": "buy", "symbol": symbol, "amount": amount}
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await update.message.reply_text(f"🔴 *Confirm sell*\n{amount} {symbol} ≈ ${value:.2f} USD\nReply with *YES* (uppercase) to execute on testnet.", parse_mode="Markdown")
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
    engine = TradingEngine(testnet=True)
    if order["type"] == "buy":
        result = engine.buy_market(order["symbol"], order["amount"])
        if result:
            await update.message.reply_text(f"✅ Buy executed on testnet. ID: {result['orderId']}")
        else:
            await update.message.reply_text("❌ Buy failed.")
    elif order["type"] == "sell":
        result = engine.sell_market(order["symbol"], order["amount"])
        if result:
            await update.message.reply_text(f"✅ Sell executed on testnet. ID: {result['orderId']}")
        else:
            await update.message.reply_text("❌ Sell failed.")
    context.user_data.pop("pending_order", None)

# ==================== PLAN ACTIVATION (BASED ON REAL BALANCE) ====================
async def activate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        "🔍 *Checking your Binance balance...*\n\n"
        "⚠️ *IMPORTANT:* For the bot to trade with REAL money, you must:\n"
        "1. Have a real Binance account (not testnet).\n"
        "2. Deposit at least 50 USDT (or equivalent in BTC).\n"
        "3. Generate an API Key with trading permissions (no withdrawals) and link it to the bot.\n"
        "4. Run this command again.\n\n"
        f"👉 *Don't have an account?* Use our referral link (lifetime reduced fees):\n{BINANCE_REFERRAL_LINK}\n\n"
        "*(For now, the bot is in TESTNET mode, using fake money for you to practice)*",
        parse_mode="Markdown"
    )
    try:
        engine = TradingEngine(testnet=True)
        usdt_balance = engine.get_balance("USDT")
        btc_balance = engine.get_balance("BTC")
        if btc_balance >= 0.01 or usdt_balance >= 500:
            plan = "lifetime"
            fee = 0.2
        elif usdt_balance >= 100:
            plan = "pro"
            fee = 0.2
        elif usdt_balance >= 50:
            plan = "starter"
            fee = 0.3
        else:
            plan = "free"
            fee = None
        subscribers = load_subscribers()
        subscribers[str(chat_id)] = {
            "plan": plan,
            "fee": fee,
            "active": True if plan != "free" else False
        }
        save_subscribers(subscribers)
        message = f"✅ *Plan detected on TESTNET: {plan.upper()}*\n"
        if fee:
            message += f"💰 Trade fee (testnet): {fee}%\n"
        else:
            message += "💰 No real trading (testnet only).\n"
        message += f"📊 Detected balance (TESTNET): USDT ${usdt_balance:.2f}, BTC {btc_balance:.8f}\n\n"
        message += "🔐 To trade with REAL money, repeat this command after:\n"
        message += f"1. Register on Binance using our link: {BINANCE_REFERRAL_LINK}\n"
        message += "2. Deposit funds.\n"
        message += "3. Link your real API (change your .env to production)."
        await update.message.reply_text(message, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error checking balance: {e}\nMake sure your Binance Testnet API keys are correct in .env.")

async def plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    subscribers = load_subscribers()
    data = subscribers.get(str(chat_id), {"plan": "free", "fee": None})
    current_plan = data.get("plan", "free")
    fee = data.get("fee", None)
    message = f"📋 *Your current plan (based on TESTNET balance): {current_plan.upper()}*\n"
    if fee:
        message += f"💰 Trade fee (testnet): {fee}%\n"
    else:
        message += "💰 No real trading.\n"
    if current_plan == "lifetime":
        message += "\n✨ *You already have the best plan. Thanks for trusting CryptoArch Agent.*"
    else:
        message += f"\n*How to upgrade to REAL money plan?*\n"
        message += f"1. Register on Binance using our link: {BINANCE_REFERRAL_LINK}\n"
        message += "2. Deposit the required amount:\n"
        message += "   • Starter: 50 USDT (0.3% fee)\n"
        message += "   • Pro: 100 USDT (0.2% fee)\n"
        message += "   • Lifetime: 0.01 BTC or 500 USDT (0.2% fee + benefits)\n"
        message += "3. Generate an API Key (trading permissions, no withdrawals).\n"
        message += "4. Link it to the bot (edit your .env or use /setapi).\n"
        message += "5. Run /activate again.\n"
    await update.message.reply_text(message, parse_mode="Markdown")

# ==================== WEBHOOK ====================
if MP_WEBHOOK_URL:
    webhook_app = Flask(__name__)

    @webhook_app.route('/webhook', methods=['POST'])
    def webhook():
        data = request.json
        logger.info(f"📩 Webhook notification: {data}")
        try:
            # Payment notification (one-time payment)
            if data.get("type") == "payment":
                payment_id = data["data"]["id"]
                sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
                payment_response = sdk.payment().get(payment_id)
                payment_data = payment_response["response"]
                external_ref = payment_data.get("external_reference")
                status = payment_data.get("status")
                if status == "approved" and external_ref:
                    # external_reference is the chat_id (when using /pay command)
                    chat_id = external_ref
                    # Determine plan from subscription? For simplicity, activate with a default plan
                    # You could also store the plan when creating the subscription
                    plan = "premium"
                    activate_premium(chat_id, plan)
            # Subscription preapproval notification
            elif data.get("type") == "subscription_preapproval":
                subscription_id = data["data"]["id"]
                sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
                subscription_response = sdk.preapproval().get(subscription_id)
                subscription_data = subscription_response["response"]
                subscription_status = subscription_data.get("status")
                external_ref = subscription_data.get("external_reference")
                if subscription_status == "authorized" and external_ref:
                    chat_id = external_ref
                    plan = "premium"  # or extract from subscription_data
                    activate_premium(chat_id, plan)
            return "OK", 200
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return "Error", 500

    def run_webhook():
        webhook_app.run(host='0.0.0.0', port=5000)

# ==================== MAIN ====================
if __name__ == "__main__":
    if MP_WEBHOOK_URL:
        threading.Thread(target=run_webhook, daemon=True).start()
        logger.info("🔄 Webhook server started on port 5000")
    else:
        logger.info("⚠️ MP_WEBHOOK_URL not set. Webhook not started.")

    reschedule_reports()

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("premium", premium))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("plans", plans_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("whale", whale))
    app.add_handler(CommandHandler("terms", terms_command))
    app.add_handler(CommandHandler("accept", accept_terms))
    app.add_handler(CommandHandler("info", info_command))
    app.add_handler(CommandHandler("news", news_command))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("sell", sell))
    app.add_handler(CommandHandler("activate", activate))
    app.add_handler(CommandHandler("plan", plan))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text))

    def run_schedule():
        while True:
            schedule.run_pending()
            time.sleep(1)
    threading.Thread(target=run_schedule, daemon=True).start()

    logger.info("🚀 Trading bot started successfully")
    app.run_polling()
