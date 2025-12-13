# bot.py
import os
import time
import json
import asyncio
import aiohttp
import aiosqlite

from telegram import Bot, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")

GMGN_TREND_URL = "https://gmgn.ai/defi/quotation/v1/trending/sol"

POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
DB_FILE = "bot_state.db"


def now_ts():
    return int(time.time())


# ================= DATABASE =================
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id TEXT PRIMARY KEY
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
            "INSERT OR IGNORE INTO users(chat_id) VALUES (?)",
            (str(chat_id),)
        )
        await db.commit()


async def list_users():
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute("SELECT chat_id FROM users")
        rows = await cur.fetchall()
        return [int(r[0]) for r in rows]


async def remember_signal_once(key):
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute(
            "SELECT 1 FROM sent_signals WHERE key=? AND ts>?",
            (key, now_ts() - 3600)
        )
        if await cur.fetchone():
            return False

        await db.execute(
            "INSERT INTO sent_signals(key, ts) VALUES (?, ?)",
            (key, now_ts())
        )
        await db.commit()
        return True


# ================= COMMANDS =================
async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await add_user(update.effective_chat.id)
    await update.message.reply_text("🤖 GMGN Whale Monitor فعال شد")


async def trend_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    async with aiohttp.ClientSession() as s:
        async with s.get(GMGN_TREND_URL, timeout=15) as r:
            data = await r.json()

    items = data.get("data", [])
    msg = []

    for t in items[:5]:
        msg.append(
            f"{t.get('symbol')} | price: {t.get('price')} | 5m: {t.get('increaseRate_5m')}"
        )

    await update.message.reply_text("\n".join(msg))


# ================= BACKGROUND JOB =================
async def monitor_job(ctx: ContextTypes.DEFAULT_TYPE):
    bot: Bot = ctx.application.bot

    async with aiohttp.ClientSession() as session:
        async with session.get(GMGN_TREND_URL, timeout=15) as r:
            data = await r.json()

    items = data.get("data", [])
    users = [int(ADMIN_CHAT_ID)] if ADMIN_CHAT_ID else await list_users()

    for it in items[:10]:
        try:
            p5 = float(it.get("increaseRate_5m", 0) or 0)
        except:
            continue

        if p5 > 20:
            key = f"{it.get('symbol')}_{int(now_ts() / 60)}"

            if not await remember_signal_once(key):
                continue

            text = (
                f"🚀 BUY SIGNAL\n\n"
                f"Token: {it.get('symbol')}\n"
                f"5m Change: {p5}%\n"
                f"Price: {it.get('price')}"
            )

            for u in users:
                await bot.send_message(u, text)


# ================= MAIN =================
def main():
    if not TELEGRAM_TOKEN:
        print("ERROR: TELEGRAM_TOKEN required")
        return

    asyncio.run(init_db())

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("trend", trend_cmd))

    app.job_queue.run_repeating(
        monitor_job,
        interval=POLL_INTERVAL,
        first=10
    )

    print("✅ Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
