import asyncio
import time
import aiohttp
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TELEGRAM_TOKEN = "<توکن>"
POLL_INTERVAL = 20
WATCH_WALLETS = {}  # {address: {"chain":"sol" or "eth", "last_bal":0}}

async def fetch_dexscreener():
    url = "https://api.dexscreener.com/latest/dex/top"
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            return await r.json()

async def fetch_gmgn():
    url = "https://gmgn.ai/defi/quotation/v1/rank/sol/swaps/5m?orderby=smartmoney&direction=desc"
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            return await r.json()

async def check_wallet_activity(address):
    # فقط مثال برای Solana RPC
    rpc_url = "https://api.mainnet-beta.solana.com"
    payload = {
        "jsonrpc":"2.0","id":1,
        "method":"getConfirmedSignaturesForAddress2",
        "params":[address, {"limit":3}]
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(rpc_url,json=payload) as r:
            return await r.json()

async def monitor(app):
    while True:
        ds = await fetch_dexscreener()
        gmgn = await fetch_gmgn()

        # مثال ساده: توکن هایی با حجم بالا
        top = ds.get("pairs",[]) or ds.get("pairs",[])
        msg = "📊 DexScreener Top:\n"
        for t in top[:5]:
            msg += f"{t['baseToken']['symbol']} {t['priceUsd'][:6]} | {t['priceChange']['hour24']}\n"
       await app.bot.send_message(
    chat_id=CHAT_ID,
    text=msg
)


        # wallet activity
        for address in WATCH_WALLETS:
            act = await check_wallet_activity(address)
            if act.get("result"):
                await app.bot.send_message(<CHAT_ID>, f"📌 Activity in {address}: {act}")

        await asyncio.sleep(POLL_INTERVAL)

async def start(update:Update,ctx):
    await update.message.reply_text("بات روشن شد!")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.create_task(monitor(app))
    app.run_polling()

if __name__=="__main__":
    main()
