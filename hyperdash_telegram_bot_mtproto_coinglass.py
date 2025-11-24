import os
import json
import logging
import threading
import time
from datetime import datetime

import requests
from telegram import Update, Bot
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
)

# ---------------- Logging ---------------- #
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------- Load ENV ---------------- #
BOT_TOKEN = os.getenv("BOT_TOKEN")
COINGLASS_API_KEY = os.getenv("COINGLASS_API_KEY", "")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "300"))
MIN_POSITION_VALUE_USD = int(os.getenv("MIN_POSITION_VALUE_USD", "10"))

# ---------------- Data Files ---------------- #
def load_json(path, default):
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f)
        return default
    with open(path, "r") as f:
        return json.load(f)

wallets = load_json("wallets.json", [])
authorized_chats = load_json("authorized_chats.json", [])
state = load_json("state.json", {})

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

# ---------------- Helper ---------------- #
def check_wallet_positions(wallet):
    url = f"https://open-api.coinglass.com/public/v2/userPosition?address={wallet}"
    headers = {"coinglassSecret": COINGLASS_API_KEY}
    try:
        response = requests.get(url, headers=headers, timeout=10).json()
        return response
    except Exception as e:
        logger.error(f"Error fetching positions: {e}")
        return None

# ---------------- Telegram handlers ---------------- #
def start(update: Update, context: CallbackContext):
    update.message.reply_text("ربات فعال است. /addwallet و /listwallets را امتحان کن.")

def add_wallet(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("فرمت صحیح: /addwallet <address>")
        return
    wallet = context.args[0].strip()
    if wallet not in wallets:
        wallets.append(wallet)
        save_json("wallets.json", wallets)
        update.message.reply_text(f"کیف پول اضافه شد:\n{wallet}")
    else:
        update.message.reply_text("این کیف‌پول قبلاً ثبت شده.")

def list_wallets(update: Update, context: CallbackContext):
    if not wallets:
        update.message.reply_text("هیچ کیف‌پولی ثبت نشده.")
        return
    msg = "کیف‌پول‌های ثبت شده:\n" + "\n".join(wallets)
    update.message.reply_text(msg)

def help_cmd(update: Update, context: CallbackContext):
    update.message.reply_text(
        "/addwallet <addr>\n"
        "/listwallets\n"
        "/check\n"
    )

def check_now(update: Update, context: CallbackContext):
    do_check(context.bot)
    update.message.reply_text("چک انجام شد.")

# ---------------- Background checker ---------------- #
def do_check(bot: Bot):
    for chat_id in authorized_chats:
        for wallet in wallets:
            data = check_wallet_positions(wallet)
            if not data or "data" not in data:
                continue

            for pos in data["data"]:
                value = pos.get("value", 0)
                symbol = pos.get("symbol", "?")
                if value >= MIN_POSITION_VALUE_USD:
                    bot.send_message(
                        chat_id=chat_id,
                        text=f"📌 پوزیشن جدید:\n" 
                             f"💰 ارزش: {value}$\n"
                             f"🔹 نماد: {symbol}\n"
                             f"🏦 کیف‌پول: {wallet}"
                    )

def scheduler(bot: Bot):
    while True:
        time.sleep(POLL_INTERVAL)
        logger.info("Running scheduled check...")
        do_check(bot)

# ---------------- Main runner ---------------- #
def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is missing!")

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("addwallet", add_wallet))
    dp.add_handler(CommandHandler("listwallets", list_wallets))
    dp.add_handler(CommandHandler("help", help_cmd))
    dp.add_handler(CommandHandler("check", check_now))

    # Background thread
    thread = threading.Thread(target=scheduler, args=(updater.bot,), daemon=True)
    thread.start()

    logger.info("Bot is running...")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
