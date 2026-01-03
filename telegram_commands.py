from telegram import Update
from telegram.ext import ContextTypes

from wallet_store import add_wallet, remove_wallet, list_wallets

async def addwallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ آدرس کیف پول وارد نشده")
        return

    wallet = context.args[0]
    if add_wallet(wallet):
        await update.message.reply_text(f"✅ Wallet اضافه شد:\n{wallet}")
    else:
        await update.message.reply_text("⚠️ این Wallet قبلاً اضافه شده")

async def removewallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ آدرس کیف پول وارد نشده")
        return

    wallet = context.args[0]
    if remove_wallet(wallet):
        await update.message.reply_text(f"🗑 Wallet حذف شد:\n{wallet}")
    else:
        await update.message.reply_text("⚠️ Wallet پیدا نشد")

async def wallets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallets = list_wallets()
    if not wallets:
        await update.message.reply_text("📭 هیچ Walletای ثبت نشده")
        return

    text = "📌 Wallets:\n\n" + "\n".join(wallets)
    await update.message.reply_text(text)

async def threshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ℹ️ Threshold فعلاً ثابت است")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallets = list_wallets()
    await update.message.reply_text(
        f"📊 Status\n"
        f"Wallets: {len(wallets)}\n"
        f"Network: Solana"
    )
