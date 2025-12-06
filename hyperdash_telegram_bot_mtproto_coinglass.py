import os
import json
import time
import logging
import threading
import requests
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    Updater,
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

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR, exist_ok=True)

# -----------------------------------
# LOAD/SAVE HELPERS
# -----------------------------------
def load_wallets():
    if not os.path.exists(WALLETS_FILE):
        return []
    try:
        return json.load(open(WALLETS_FILE))
    except:
        return []

def save_wallets(w):
    json.dump(w, open(WALLETS_FILE, "w"), indent=2)

def load_states():
    if not os.path.exists(STATES_FILE):
        return {}
    try:
        return json.load(open(STATES_FILE))
    except:
        return {}

def save_states(s):
    json.dump(s, open(STATES_FILE, "w"), indent=2)

# -----------------------------------
# BOT COMMANDS (SYNC)
# -----------------------------------
authorized_chats = set()

def send_message_sync(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})

def cmd_add_sync(update: Update, context):
    chat_id = update.effective_chat.id
    authorized_chats.add(chat_id)

    if len(context.args) != 1:
        send_message_sync(chat_id, "⚠ آدرس کیف پول را صحیح وارد کنید.")
        return

    wallet = context.args[0]
    wallets = load_wallets()
    if wallet not in wallets:
        wallets.append(wallet)
        save_wallets(wallets)

    send_message_sync(chat_id, f"✅ کیف پول *{wallet}* اضافه شد.")

def cmd_remove_sync(update: Update, context):
    chat_id = update.effective_chat.id
    authorized_chats.add(chat_id)

    if len(context.args) != 1:
        send_message_sync(chat_id, "⚠ آدرس صحیح نیست.")
        return

    wallet = context.args[0]
    wallets = load_wallets()
    if wallet in wallets:
        wallets.remove(wallet)
        save_wallets(wallets)

    send_message_sync(chat_id, f"❌ {wallet} حذف شد.")

def cmd_list_sync(update: Update, context):
    chat_id = update.effective_chat.id
    authorized_chats.add(chat_id)

    wallets = load_wallets()
    if wallets:
        text = "📌 کیف پول‌های ثبت‌شده:\n" + "\n".join(f"- `{w}`" for w in wallets)
    else:
        text = "هیچ کیف پولی ثبت نشده."
    send_message_sync(chat_id, text)

def cmd_status_sync(update: Update, context):
    chat_id = update.effective_chat.id
    authorized_chats.add(chat_id)

    wallets = load_wallets()
    send_message_sync(chat_id, f"کیف پول‌ها: {wallets}")

# -----------------------------------
# WALLET POLLER
# -----------------------------------
def process_wallet(wallet):
    """
    اینجا باید منطق خواندن API و مقایسه وضعیت قرار گیرد.
    فعلاً فقط تست است.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return [f"🔔 تغییر جدید در کیف پول {wallet} — ⏱ {now}"]

def poller_thread():
    logger.info("Poller thread started.")
    while True:
        wallets = load_wallets()
        for w in wallets:
            try:
                events = process_wallet(w)
                for e in events:
                    for cid in authorized_chats:
                        send_message_sync(cid, e)
            except Exception as exc:
                logger.exception(f"Error processing {w}: {exc}")

        time.sleep(POLL_INTERVAL)

# -----------------------------------
# BOT STARTER
# -----------------------------------
def build_and_start_bot():
    logger.info("Starting bot...")

    # Poller thread
    t = threading.Thread(target=poller_thread, daemon=True)
    t.start()

    # Try using Application (v20+)
    try:
        app = Application.builder().token(BOT_TOKEN).build()

        async def wrap(fn):
            async def inner(update, context):
                fn(update, context)
            return inner

        app.add_handler(CommandHandler("add", lambda u, c: cmd_add_sync(u, c)))
        app.add_handler(CommandHandler("remove", lambda u, c: cmd_remove_sync(u, c)))
        app.add_handler(CommandHandler("list", lambda u, c: cmd_list_sync(u, c)))
        app.add_handler(CommandHandler("status", lambda u, c: cmd_status_sync(u, c)))

        app.run_polling()

    except:
        # fallback for old PTB 13.x
        updater = Updater(BOT_TOKEN, use_context=True)
        dp = updater.dispatcher

        dp.add_handler(CommandHandler("add", cmd_add_sync))
        dp.add_handler(CommandHandler("remove", cmd_remove_sync))
        dp.add_handler(CommandHandler("list", cmd_list_sync))
        dp.add_handler(CommandHandler("status", cmd_status_sync))

        updater.start_polling()
        updater.idle()

# -----------------------------------
# ENTRYPOINT
# -----------------------------------
def main():
    try:
        build_and_start_bot()
    except Exception as e:
        logger.exception(f"Fatal start error: {e}")

if __name__ == "__main__":
    main()
