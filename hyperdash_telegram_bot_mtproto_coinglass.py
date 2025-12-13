import os
import time
import threading
import requests
import sqlite3

from telegram.ext import Updater, CommandHandler

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GMGN_TREND_URL = "https://gmgn.ai/defi/quotation/v1/trending/sol"
DB_FILE = "bot_state.db"
POLL_INTERVAL = 30


def now_ts():
    return int(time.time())


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id TEXT PRIMARY KEY,
            created_at INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sent_signals (
            key TEXT PRIMARY KEY,
            ts INTEGER
        )
    """)
    conn.commit()
    conn.close()


def start_cmd(update, context):
    chat_id = str(update.effective_chat.id)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users VALUES (?, ?)", (chat_id, now_ts()))
    conn.commit()
    conn.close()

    update.message.reply_text("✅ HyperDash Whale Bot فعال شد")


def trend_cmd(update, context):
    r = requests.get(GMGN_TREND_URL, timeout=10).json()
    items = r.get("data", [])[:5]

    txt = "📊 HyperDash Trending:\n"
    for it in items:
        txt += f"{it.get('symbol')} | 5m: {it.get('increaseRate_5m')}%\n"

    update.message.reply_text(txt)


def monitor_loop(bot):
    while True:
        try:
            r = requests.get(GMGN_TREND_URL, timeout=10).json()
            items = r.get("data", [])

            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            users = [row[0] for row in c.execute("SELECT chat_id FROM users")]
            conn.close()

            for it in items[:10]:
                p5 = float(it.get("increaseRate_5m") or 0)
                if p5 >= 20:
                    msg = (
                        "🚨 HYPERDASH WHALE SIGNAL\n"
                        f"{it.get('symbol')} | 5m: {p5}%"
                    )
                    for u in users:
                        bot.send_message(chat_id=int(u), text=msg)

        except Exception as e:
            print("monitor error:", e)

        time.sleep(POLL_INTERVAL)


def main():
    init_db()

    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start_cmd))
    dp.add_handler(CommandHandler("trend", trend_cmd))

    threading.Thread(
        target=monitor_loop,
        args=(updater.bot,),
        daemon=True
    ).start()

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
