import os
import json
import time
import logging
import threading
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
POLL_INTERVAL = 15

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

WALLETS_FILE = f"{DATA_DIR}/wallets.json"
STATES_FILE = f"{DATA_DIR}/states.json"

def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        return json.load(open(path))
    except:
        return default

def save_json(path, data):
    json.dump(data, open(path, "w"), indent=2)

wallets = load_json(WALLETS_FILE, [])
states = load_json(STATES_FILE, {})
authorized = set()

def send_message(cid, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": cid, "text": text, "parse_mode": "Markdown"})

def get_txs(wallet):
    url = f"https://api.bscscan.com/api?module=account&action=txlist&address={wallet}&sort=desc"
    r = requests.get(url).json()
    if r.get("status") != "1":
        return []
    return r["result"][:5]

def detect(tx, wallet):
    w = wallet.lower()
    f = tx["from"].lower()
    t = tx["to"].lower()
    if f == w and t != w:
        return "❌ SELL"
    if t == w and f != w:
        return "🟢 BUY"
    return "🔄 TRANSFER"

def process_wallet(wallet):
    global states
    txs = get_txs(wallet)

    if wallet not in states:
        states[wallet] = txs[0]["hash"] if txs else ""
        save_json(STATES_FILE, states)
        return []

    last = states[wallet]
    new_events = []

    for tx in txs:
        if tx["hash"] == last:
            break

        ttype = detect(tx, wallet)
        msg = f"""
🔔 *New Transaction*
`{wallet}`
Type: {ttype}
Hash: `{tx['hash']}`
Time: {datetime.fromtimestamp(int(tx["timeStamp"]))}
"""
        new_events.append(msg)

    if txs:
        states[wallet] = txs[0]["hash"]
        save_json(STATES_FILE, states)

    return new_events

def poller():
    logger.info("Poller started...")
    while True:
        for w in wallets:
            try:
                events = process_wallet(w)
                for e in events:
                    for cid in authorized:
                        send_message(cid, e)
            except Exception as ex:
                logger.error("Poll error: %s", ex)
        time.sleep(POLL_INTERVAL)

async def cmd_start(update, ctx):
    authorized.add(update.effective_chat.id)
    await update.message.reply_text("ربات فعال شد ✔️")

async def cmd_add(update, ctx):
    cid = update.effective_chat.id
    authorized.add(cid)

    if len(ctx.args) != 1:
        await update.message.reply_text("❌ آدرس اشتباه است.")
        return

    w = ctx.args[0]
    if w not in wallets:
        wallets.append(w)
        save_json(WALLETS_FILE, wallets)

    await update.message.reply_text(f"کیف پول ثبت شد:\n`{w}`")

async def cmd_list(update, ctx):
    authorized.add(update.effective_chat.id)
    if not wallets:
        await update.message.reply_text("❌ هیچ کیف پولی وجود ندارد.")
    else:
        await update.message.reply_text("\n".join(wallets))

def main():
    threading.Thread(target=poller, daemon=True).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("list", cmd_list))

    logger.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
