from telegram import Update
from telegram.ext import ContextTypes
from wallet_store import add_wallet, remove_wallet, list_wallets


async def addwallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ آدرس کیف پول را وارد کن")
        return

    address = context.args[0]
    add_wallet(address)
    await update.message.reply_text(f"✅ Wallet اضافه شد:\n{address}")


async def removewallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return

    address = context.args[0]
    remove_wallet(address)
    await update.message.reply_text(f"🗑 Wallet حذف شد:\n{address}")


async def wallets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallets = list_wallets()
    if not wallets:
        await update.message.reply_text("📭 لیست کیف پول خالی است")
        return

    msg = "📒 Wallets:\n\n"
    for w in wallets:
        msg += f"- {w[0]}\n"

    await update.message.reply_text(msg)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallets = list_wallets()
    await update.message.reply_text(
        f"📊 Status\n\nWallets: {len(wallets)}\nNetwork: Solana"
    )
