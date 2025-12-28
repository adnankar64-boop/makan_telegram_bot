import os
import asyncio
import aiohttp
import aiosqlite

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ================== CONFIG ==================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = int(os.environ["CHAT_ID"])  # حتماً ست شود

DB_FILE = "wallets.db"
POLL_INTERVAL = 20  # seconds

SOLANA_RPC = "https://api.mainnet-beta.solana.com"


# ================== DB ==================
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS wallets (
                address TEXT PRIMARY KEY,
                last_sig TEXT
            )
        """)
        await db.commit()


async def add_wallet(address: str):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT OR IGNORE INTO wallets VALUES (?, ?)",
            (address, None)
        )
        await db.commit()


async def get_wallets():
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute("SELECT address, last_sig FROM wallets")
        return await cur.fetchall()


async def update_last_sig(address: str, sig: str):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "UPDATE wallets SET last_sig=? WHERE address=?",
            (sig, address)
        )
        await db.commit()


# ================== SOLANA ==================
async def get_last_signature(address: str):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [address, {"limit": 1}]
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(SOLANA_RPC, json=payload) as resp:
            data = await resp.json()
            result = data.get("result")
            if not result:
                return None
            return result[0]["signature"]


# ================== BOT COMMANDS ==================
async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ Bot started\n\n"
        "➕ Add wallet:\n"
        "/addwallet WALLET_ADDRESS"
    )


async def addwallet_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("❌ Usage:\n/addwallet WALLET_ADDRESS")
        return

    address = ctx.args[0]
    await add_wallet(address)

    await update.message.reply_text(
        f"✅ Wallet added:\n{address}"
    )


# ================== MONITOR JOB ==================
async def monitor(context: ContextTypes.DEFAULT_TYPE):
    try:
        wallets = await get_wallets()

        for address, last_sig in wallets:
            sig = await get_last_signature(address)

            if sig and sig != last_sig:
                await update_last_sig(address, sig)

                await context.bot.send_message(
                    chat_id=CHAT_ID,
                    text=(
                        "🐋 WALLET ACTIVITY DETECTED\n\n"
                        f"Address:\n{address}\n\n"
                        f"Tx:\n{sig}"
                    )
                )

    except Exception as e:
        print("Monitor error:", e)


# ================== POST INIT ==================
async def post_init(app):
    await init_db()

    app.job_queue.run_repeating(
        monitor,
        interval=POLL_INTERVAL,
        first=5,
    )


# ================== MAIN ==================
def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN not set")

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("addwallet", addwallet_cmd))

    app.run_polling()


if __name__ == "__main__":
    main()
