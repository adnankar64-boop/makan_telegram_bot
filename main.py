import os
import asyncio
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes
)
from telegram import Update

from wallet_store import (
    add_wallet,
    remove_wallet,
    get_wallets
)

# ================== ENV ==================
TOKEN = os.getenv("BOT_TOKEN")

SOLANA_RPC = os.getenv("SOLANA_RPC")  # https://api.mainnet-beta.solana.com
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
BSCSCAN_API_KEY = os.getenv("BSCSCAN_API_KEY")

# ================== COMMANDS ==================
async def addwallet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ آدرس کیف پول را وارد کن")
        return

    wallet = context.args[0]
    add_wallet(wallet)
    await update.message.reply_text(f"✅ Wallet اضافه شد:\n{wallet}")

async def removewallet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ آدرس کیف پول را وارد کن")
        return

    wallet = context.args[0]
    remove_wallet(wallet)
    await update.message.reply_text(f"🗑 Wallet حذف شد:\n{wallet}")

async def wallets_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallets = get_wallets()
    if not wallets:
        await update.message.reply_text("📭 هیچ کیف پولی ثبت نشده")
        return

    text = "📒 Wallets:\n\n" + "\n".join(wallets)
    await update.message.reply_text(text)

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallets = get_wallets()
    await update.message.reply_text(
        f"📊 Status\n\n"
        f"Wallets: {len(wallets)}\n"
        f"Network: Solana / ETH / BSC"
    )

# ================== MONITOR LOOP ==================
async def monitor_loop(app):
    await app.bot.send_message(
        chat_id=app.bot_data["admin_id"],
        text="🟢 Monitor started"
    )

    while True:
        wallets = get_wallets()

        for w in wallets:
            # 🔜 اینجا بعداً:
            # check_solana(w)
            # check_eth(w)
            # check_bsc(w)
            pass

        await asyncio.sleep(60)  # هر ۶۰ ثانیه

# ================== MAIN ==================
async def post_init(app):
    # اولین کسی که بات رو اجرا می‌کنه
    app.bot_data["admin_id"] = 123456789  # 👈 chat_id خودت

    asyncio.create_task(monitor_loop(app))

def main():
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("addwallet", addwallet_cmd))
    app.add_handler(CommandHandler("removewallet", removewallet_cmd))
    app.add_handler(CommandHandler("wallets", wallets_cmd))
    app.add_handler(CommandHandler("status", status_cmd))

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
