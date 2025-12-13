# bot.py
import asyncio
import os
import time
import aiohttp
import aiosqlite

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ---------------- CONFIG ----------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")  # اختیاری

# HyperDash / GMGN trending (Solana)
GMGN_TREND_URL = "https://gmgn.ai/defi/quotation/v1/trending/sol"

POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
DB_FILE = "bot_state.db"


def now_ts():
    return int(time.time())


# ---------------- DATABASE ----------------
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS wallets (
                chat_id TEXT,
                address TEXT,
                created_at INTEGER
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


# ---------------- COMMANDS ----------------
async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await add_user(update.effective_chat.id)
    await update.message.reply_text(
        "✅ HyperDash Whale Bot فعال شد\n\n"
        "📡 منبع سیگنال: HyperDash (GMGN)\n"
        "🚨 هشدار فقط روی مومنتوم غیرعادی\n\n"
        "دستورات:\n"
        "/trend\n"
        "/addwallet WALLET\n"
        "/listwallets"
    )


async def trend_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    async with aiohttp.ClientSession() as s:
        async with s.get(GMGN_TREND_URL, timeout=15) as r:
            data = await r.json()

    items = data.get("data", [])[:5]
    out = []

    for it in items:
        out.append(
            f"{it.get('symbol')} | "
            f"5m: {it.get('increaseRate_5m')}%"
        )

    await update.message.reply_text("📊 HyperDash Trending:\n" + "\n".join(out))


async def addwallet_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "❌ استفاده صحیح:\n/addwallet WALLET_ADDRESS"
        )
        return

    wallet = ctx.args[0]
    chat_id = str(update.effective_chat.id)

    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT INTO wallets VALUES (?, ?, ?)",
            (chat_id, wallet, now_ts())
        )
        await db.commit()

    await update.message.reply_text(f"✅ والت ذخیره شد:\n{wallet}")


async def listwallets_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute(
            "SELECT address FROM wallets WHERE chat_id=?",
            (chat_id,)
        )
        rows = await cur.fetchall()

    if not rows:
        await update.message.reply_text("📭 هیچ والتی ثبت نشده")
        return

    txt = "📒 Wallets:\n" + "\n".join(f"- {r[0]}" for r in rows)
    await update.message.reply_text(txt)


# ---------------- BACKGROUND MONITOR ----------------
async def monitor_loop(app):
    await app.wait_until_ready()
    print("🔁 HyperDash monitor started")

    while True:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(GMGN_TREND_URL, timeout=15) as r:
                    data = await r.json()

            items = data.get("data", [])
            users = [int(ADMIN_CHAT_ID)] if ADMIN_CHAT_ID else await list_users()

            for it in items[:10]:
                p5 = float(it.get("increaseRate_5m") or 0)

                # 🚨 Whale / Momentum filter
                if p5 >= 20:
                    key = f"{it.get('symbol')}_{int(now_ts()/60)}"
                    if await signal_sent(key):
                        continue

                    await mark_signal(key)

                    msg = (
                        "🚨 HYPERDASH WHALE SIGNAL\n\n"
                        f"Token: {it.get('symbol')}\n"
                        f"5m Momentum: {p5}%\n\n"
                        "Source: HyperDash"
                    )

                    for u in users:
                        await app.bot.send_message(u, msg)

        except Exception as e:
            print("monitor error:", e)

        await asyncio.sleep(POLL_INTERVAL)


# ---------------- MAIN ----------------
def main():
    if not TELEGRAM_TOKEN:
        print("ERROR: TELEGRAM_TOKEN required")
        return

    # دیتابیس (قبل از loop)
    asyncio.run(init_db())

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("trend", trend_cmd))
    app.add_handler(CommandHandler("addwallet", addwallet_cmd))
    app.add_handler(CommandHandler("listwallets", listwallets_cmd))

    # background task (روش صحیح)
    async def post_init(app):
        asyncio.create_task(monitor_loop(app))

    app.post_init = post_init

    # ❗️فقط این
    app.run_polling()
if __name__ == "__main__":
    main()
