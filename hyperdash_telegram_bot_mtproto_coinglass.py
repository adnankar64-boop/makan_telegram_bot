import os
import json
import time
import logging
import threading
import requests
from datetime import datetime

from telegram import Update
from telegram.ext import Updater, CommandHandler

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
# LOAD/SAVE
# -----------------------------------
def load_wallets():
    if not os.path.exists(WALLETS_FILE):
        return []
    return json.load(open(WALLETS_FILE))

def save_wallets(w):
    json.dump(w, open(WALLETS_FILE, "w"), indent=2)

def load_states():
    if not os.path.exists(STATES_FILE):
        return {}
    return json.load(open(STATES_FILE))

def save_states(s):
    json.dump(s, open(STATES_FILE, "w"), indent=2)

states = load_states()
authorized_chats = set()

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})


# -----------------------------------
# API CALL
# -----------------------------------
def get_transactions(wallet):
    """
    مثال API:
      از سایت BscScan یا EtherScan
    """

    url = f"https://api.bscscan.com/api?module=account&action=txlist&address={wallet}&sort=desc"
    r = requests.get(url).json()

    if r.get("status") != "1":
        return []

    return r["result"][:5]   # آخرین 5 تراکنش


# -----------------------------------
# TYPE DETECTOR
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
# POLLER
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
{wallet}

نوع: {tx_type}
هش: `{tx['hash']}`
زمان: {datetime.fromtimestamp(int(tx["timeStamp"]))}
"""
        new_events.append(msg)

    if txs:
        states[wallet] = txs[0]["hash"]
        save_states(states)

    return new_events


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
def cmd_add(update, context):
    chat = update.effective_chat.id
    authorized_chats.add(chat)

    if len(context.args) != 1:
        return send_message(chat, "آدرس اشتباه است.")

    wallet = context.args[0]
    wallets = load_wallets()

    if wallet not in wallets:
        wallets.append(wallet)
        save_wallets(wallets)

    send_message(chat, "کیف پول اضافه شد.")


def cmd_list(update, context):
    chat = update.effective_chat.id
    authorized_chats.add(chat)

    wallets = load_wallets()
    if not wallets:
        send_message(chat, "هیچ کیف پولی نیست.")
    else:
        send_message(chat, "\n".join(wallets))


# -----------------------------------
# START
# -----------------------------------
def main():
    t = threading.Thread(target=poller, daemon=True)
    t.start()

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("add", cmd_add))
    dp.add_handler(CommandHandler("list", cmd_list))

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
