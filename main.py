import json, logging, time, threading, requests
from telegram import Bot, Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# تنظیمات
TELEGRAM_BOT_TOKEN = "7762972292:AAEOjINaOiWzyJ0zJjrjjvtdTl6Wg51vCC8"

CHAT_ID = None
POLL_INTERVAL = 300
MIN_POSITION_VALUE_USD = 10

HYPERDASH_BASE = "https://hyperdash.info"
DEXSCREENER_API = "https://api.dexscreener.com/latest/dex/pairs/"
DEBANK_API = "https://api.debank.com/user/addr"

WALLETS_FILE = "wallets.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("whale_bot")


# ===== توابع مدیریت کیف پول =====
def load_wallets():
    try:
        with open(WALLETS_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_wallets(wallets):
    with open(WALLETS_FILE, "w") as f:
        json.dump(wallets, f, indent=2)

def add_wallet(addr):
    wallets = load_wallets()
    if addr not in wallets:
        wallets.append(addr)
        save_wallets(wallets)
        return True
    return False


# ===== دستورات تلگرام =====
def cmd_add(update: Update, context: CallbackContext):
    if len(context.args) < 1:
        update.message.reply_text("فرمت درست: /add <address>")
        return
    addr = context.args[0].lower()
    if add_wallet(addr):
        update.message.reply_text(f"✅ آدرس {addr} اضافه شد.")
    else:
        update.message.reply_text(f"⚠️ آدرس {addr} از قبل وجود دارد.")

def cmd_list(update: Update, context: CallbackContext):
    wallets = load_wallets()
    if wallets:
        update.message.reply_text("📜 کیف‌پول‌های دنبال‌شده:\n" + "\n".join(wallets))
    else:
        update.message.reply_text("❌ لیست خالی است.")


# ===== گرفتن سیگنال‌ها =====
def get_signal_hyperdash(addr):
    try:
        r = requests.get(f"{HYPERDASH_BASE}/trader/{addr}", timeout=15)
        if r.ok and "position" in r.text:
            return f"📊 سیگنال جدید از HyperDash برای {addr}"
    except Exception as e:
        logger.warning(f"HyperDash error {addr}: {e}")
    return None


def get_signal_dexscreener(addr):
    try:
        r = requests.get(f"{DEXSCREENER_API}{addr}", timeout=15)
        if r.ok and "pair" in r.text:
            return f"📈 سیگنال از DexScreener برای {addr}"
    except Exception as e:
        logger.warning(f"DexScreener error {addr}: {e}")
    return None


def get_signal_debank(addr):
    try:
        r = requests.get(f"{DEBANK_API}?addr={addr}", timeout=15)
        if r.ok and "data" in r.text:
            return f"💰 سیگنال از DeBank برای {addr}"
    except Exception as e:
        logger.warning(f"DeBank error {addr}: {e}")
    return None


# ===== بررسی سیگنال‌ها =====
def poll_wallet(bot, addr):
    for fn in [get_signal_hyperdash, get_signal_dexscreener, get_signal_debank]:
        sig = fn(addr)
        if sig:
            bot.send_message(chat_id=CHAT_ID or bot.get_me().id, text=sig)
            break


def poller(bot):
    while True:
        wallets = load_wallets()
        for w in wallets:
            poll_wallet(bot, w)
        time.sleep(POLL_INTERVAL)


# ===== اجرای اصلی =====
def main():
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("add", cmd_add, pass_args=True))
    dp.add_handler(CommandHandler("list", cmd_list))

    threading.Thread(target=poller, args=(bot,), daemon=True).start()
    updater.start_polling()
    print("✅ Bot running. Poll interval:", POLL_INTERVAL, "seconds")
    updater.idle()


if __name__ == "__main__":
    main()
