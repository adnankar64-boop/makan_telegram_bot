# bot.py
import asyncio
import os
import time
import aiohttp
import aiosqlite

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")

GMGN_TREND_URL = "https://gmgn.ai/defi/quotation/v1/trending/sol"
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
DB_FILE = "bot_state.db"


def now_ts():
    return int(time.time())


# ---------- DB ----------
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id TEXT PRIMARY KEY,
                created_at INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sent_signals (
                key TEXT PRIMARY KEY,
                ts INTEGER
            )
        """)
        await db.commit()


async def add_user(chat_id):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users VALUES (?, ?)",
            (str(chat_id), now_ts())
        )
        await db.commit()


async def list_users():
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute("SELECT chat_id FROM users")
        rows = await cur.fetchall()
        return [int(r[0]) for r in rows]


async def signal_sent(key):
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute(
            "SELECT 1 FROM sent_signals WHERE key=?",
            (key,)
        )
        return await cur.fetchone() is not None


async def mark_signal(key):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT OR IGNORE INTO sent_signals VALUES (?, ?)",
            (key, now_ts())
        )
        await db.commit()


# ---------- Commands ----------
async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await add_user(update.effective_chat.id)
    await update.message.reply_text("✅ بات فعال شد")


async def trend_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    async with aiohttp.ClientSession() as s:
        async with s.get(GMGN_TREND_URL) as r:
            data = await r.json()

    items = data.get("data", [])[:5]
    msg = "\n".join(
        f"{i['symbol']} | 5m: {i['increaseRate_5m']}%"
        for i in items
    )
    await update.message.reply_text(msg)


# ---------- Background ----------
async def monitor_loop(app):
    await app.wait_until_ready()

    while True:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(GMGN_TREND_URL) as r:
                    data = await r.json()

            users = [int(ADMIN_CHAT_ID)] if ADMIN_CHAT_ID else await list_users()

            for it in data.get("data", [])[:10]:
                p5 = float(it.get("increaseRate_5m") or 0)
                if p5 >= 20:
                    key = f"{it['symbol']}_{int(now_ts()/60)}"
                    if await signal_sent(key):
                        continue

                    await mark_signal(key)

                    for u in users:
                        await app.bot.send_message(
                            u,
                            f"🚨 WHALE MOMENTUM\n{it['symbol']} | 5m: {p5}%"
                        )

        except Exception as e:
            print("monitor error:", e)

        await asyncio.sleep(POLL_INTERVAL)


# ---------- MAIN ----------
def main():
    asyncio.run(init_db())

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("trend", trend_cmd))

    app.create_task(monitor_loop(app))

    app.run_polling()
