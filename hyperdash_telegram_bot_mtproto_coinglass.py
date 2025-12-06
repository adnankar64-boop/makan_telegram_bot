import os
import json
import time
import logging
import threading
import requests
from datetime import datetime

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes
)

# -----------------------------------
# LOGGING
# -----------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# -----------------------------------
# CONFIG
# -----------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
POLL_INTERVAL = 15
DATA_DIR = "data"
WALLETS_FILE = os.path.join(DATA_DIR, "wallets.json")
STATES_FILE = os.path.join(DATA_DIR, "states.json")

os.makedirs(DATA_DIR, exist_ok=True)

# -----------------------------------
# LOAD / SAVE
# -----------------------------------
def load_wallets():
    if not os.path.exists(WALLETS_FILE):
        return []
    with open(WALLETS_FILE) as f:
        return json.load(f)

def save_wallets(w):
    with open(WALLETS_FILE, "w") as f:
        json.dump(w, f, indent=2)

def load_states():
    if not os.path.exists(STATES_FILE):
        return {}
    with open(STATES_FILE) as f:
        return json.load(f)

def save_states(s):
    with open(STATES_FILE, "w") as f:
        json.dump(s, f, indent=2)

states = load_states()
authorized_chats = set()

# -----------------------------------
# SEND MESSAGE
# -----------------------------------
def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    })

# -----------------------------------
# API CALL (BSC مثال)
# -----------------------------------
def get_transactions(wallet):
    url = f"https://api.bscscan.com/api?module=account&action=txlist&address={wallet}&sort=desc"
    r = requests.get(url).json()

    if r.get("status") != "1":
        return []

    return r["result"][:5]

# -----------------------------------
# TX TYPE
# -----------------------------------
def detect_type(tx, wallet):
    f = tx["from"].lower()
    t = tx["to"].lower()
    wallet = wallet.lower()

    if f == wallet and t != wallet:
        return "SELL ❌"

    if t == wallet and f != wallet:
        return "BUY ✅"

    return "TRANSFER 🔄"

# -----------------------------------
# WALLET PROCESS
# -----------------------------------
def process_wallet(wallet):
    global states

    txs = get_transactions(wallet)

    if wallet not in states:
        states[wallet] = txs[0]["hash"] if txs else ""
        save_states(states)
        return []

    last = states[wallet]
    new_events = []

    for tx in txs:
        if tx["hash"] == last:
            break

        tx_type = detect_type(tx, wallet)

        msg = f"""
🔔 *تغییر جدید در کیف پول*
`{wallet}`

نوع: {tx_type}
هش: `{tx['hash']}`
زمان: {datetime.fromtimestamp(int(tx["timeStamp"]))}
"""
        new_events.append(msg)

    if txs:
        states[wallet] = txs[0]["hash"]
        save_states(states)

    return new_events

# -----------------------------------
# BACKGROUND POLLER THREAD
# -----------------------------------
def poller():
    while True:
        wallets = load_wallets()
        for w in wallets:
            try:
                events = process_wallet(w)
                for e in events:
                    for cid in authorized_chats:
                        send_message(cid, e)
            except Exception as ex:
                logger.error(ex)

        time.sleep(POLL_INTERVAL)

# -----------------------------------
# COMMANDS
# -----------------------------------
async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat.id
    authorized_chats.add(chat)

    if len(context.args) != 1:
        await update.message.reply_text("آدرس اشتباه است.")
        return

    wallet = context.args[0]
    wallets = load_wallets()

    if wallet not in wallets:
        wallets.append(wallet)
        save_wallets(wallets)

    await update.message.reply_text("✅ کیف پول اضافه شد.")

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat.id
    authorized_chats.add(chat)

    wallets = load_wallets()
    if not wallets:
        await update.message.reply_text("❌ هیچ کیف پولی ثبت نشده.")
    else:
        await update.message.reply_text("\n".join(wallets))

# -----------------------------------
# MAIN
# -----------------------------------
def main():
    # Thread برای مانیتورینگ کیف پول‌ها
    threading.Thread(target=poller, daemon=True).start()

    # Telegram App (نسخه جدید)
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("list", cmd_list))

    logger.info("Bot Started...")
    app.run_polling()

if __name__ == "__main__":
    main()
