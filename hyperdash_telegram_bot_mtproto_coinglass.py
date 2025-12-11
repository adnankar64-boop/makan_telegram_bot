# bot.py
import asyncio
import aiosqlite
import aiohttp
import os
import json
import time
from datetime import datetime, timezone

from telegram import Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")

GMGN_TREND_URL = "https://gmgn.ai/defi/quotation/v1/trending/sol"
GMGN_SMARTMONEY = "https://gmgn.ai/defi/quotation/v1/smartmoney/{addr_or_token}"

POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))
CACHE_TTL = 20
DB_FILE = os.environ.get("DB_FILE", "bot_state.db")

def now_ts():
    return int(time.time())

# --- Database ---
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id TEXT PRIMARY KEY,
                created_at INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS wallets (
                addr TEXT PRIMARY KEY,
                note TEXT,
                created_at INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sent_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT,
                payload TEXT,
                ts INTEGER
            )
        """)
        await db.commit()

async def add_user(chat_id):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT OR IGNORE INTO users VALUES (?, ?)", (str(chat_id), now_ts()))
        await db.commit()

async def list_users():
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute("SELECT chat_id FROM users")
        rows = await cur.fetchall()
        return [x[0] for x in rows]

async def add_wallet(addr, note=""):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT OR IGNORE INTO wallets VALUES (?, ?, ?)", (addr, note, now_ts()))
        await db.commit()

async def list_wallets():
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute("SELECT addr, note FROM wallets")
        rows = await cur.fetchall()
        return [{"addr": r[0], "note": r[1]} for r in rows]

async def remember_signal_once(key, payload):
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute("SELECT 1 FROM sent_signals WHERE key=? AND ts>?", (key, now_ts()-3600))
        if await cur.fetchone():
            return False
        await db.execute("INSERT INTO sent_signals(key,payload,ts) VALUES(?,?,?)",
                         (key, json.dumps(payload), now_ts()))
        await db.commit()
        return True

# --- Commands ---
async def start_cmd(update, ctx):
    await add_user(update.effective_chat.id)
    await update.message.reply_text("سلام! بات GMGN آماده است.")

async def addwallet_cmd(update, ctx):
    if not ctx.args:
        return await update.message.reply_text("Usage: /addwallet <address> [note]")
    addr = ctx.args[0]
    note = " ".join(ctx.args[1:]) if len(ctx.args) > 1 else ""
    await add_wallet(addr, note)
    await update.message.reply_text("Wallet added.")

async def listwallets_cmd(update, ctx):
    ws = await list_wallets()
    if not ws:
        return await update.message.reply_text("No wallets stored.")
    txt = "\n".join([f"- {w['addr']} {w['note']}" for w in ws])
    await update.message.reply_text(txt)

async def trend_cmd(update, ctx):
    async with aiohttp.ClientSession() as s:
        try:
            async with s.get(GMGN_TREND_URL, timeout=15) as r:
                data = await r.json()
        except Exception as e:
            return await update.message.reply_text(str(e))

    items = data.get("data", [])
    out = []
    for t in items[:5]:
        sym = t.get("symbol", "?")
        price = t.get("price", "?")
        p5 = t.get("increaseRate_5m", "?")
        out.append(f"{sym} | {price} | 5m: {p5}")
    await update.message.reply_text("\n".join(out))

# --- Background Loop (executed via JobQueue) ---
async def monitor_job(ctx):
    bot: Bot = ctx.application.bot

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(GMGN_TREND_URL, timeout=15) as r:
                trending = await r.json()
        except:
            return

    items = trending.get("data", [])
    users = [ADMIN_CHAT_ID] if ADMIN_CHAT_ID else await list_users()

    for it in items[:10]:
        p5 = float(it.get("increaseRate_5m", 0) or 0)
        if p5 > 20:
            key = f"trend_{it.get('symbol')}_{int(now_ts()/60)}"
            if await remember_signal_once(key, it):
                txt = f"Signal BUY: {it.get('symbol')} | 5m: {p5}"
                for u in users:
                    if u:
                        await bot.send_message(int(u), txt)

# --- main (SYNC!) ---
def main():
    if not TELEGRAM_TOKEN:
        print("ERROR: TELEGRAM_TOKEN environment variable required.")
        return

    # DB init must run inside event loop -> use asyncio.run
    asyncio.run(init_db())

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("addwallet", addwallet_cmd))
    app.add_handler(CommandHandler("listwallets", listwallets_cmd))
    app.add_handler(CommandHandler("trend", trend_cmd))

    # background job every POLL_INTERVAL sec
    app.job_queue.run_repeating(monitor_job, interval=POLL_INTERVAL, first=5)

    app.run_polling()

if __name__ == "__main__":
    main()
