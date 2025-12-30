from telegram import Update
from telegram.ext import ContextTypes
from wallet_store import add_wallet, remove_wallet, list_wallets, set_threshold, get_threshold


async def addwallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ آدرس کیف پول را وارد کن")
        return

    address = context.args[0]
    add_wallet(address)
    await update.message.reply_text(f"✅ Wallet اضافه شد:\n{address}")


async def removewallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def threshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = int(context.args[0])
    set_threshold(value)
    await update.message.reply_text(f"⚙️ Threshold تنظیم شد: ${value}")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = get_threshold()
    count = len(list_wallets())
    await update.message.reply_text(
        f"📊 Status\n\nWallets: {count}\nThreshold: ${t}"
    )
