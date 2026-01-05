from telegram import Update
from telegram.ext import ContextTypes

from wallet_store import add_wallet, remove_wallet, get_wallets

async def addwallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ آدرس وارد نشده")
        return

    wallet = context.args[0]
    if add_wallet(context, wallet):
        await update.message.reply_text(f"✅ Wallet اضافه شد:\n{wallet}")
    else:
        await update.message.reply_text("⚠️ Wallet قبلاً وجود دارد")

async def removewallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ آدرس وارد نشده")
        return

    wallet = context.args[0]
    if remove_wallet(context, wallet):
        await update.message.reply_text(f"🗑 Wallet حذف شد:\n{wallet}")
    else:
        await update.message.reply_text("⚠️ Wallet پیدا نشد")

async def wallets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallets = get_wallets(context)
    if not wallets:
        await update.message.reply_text("📭 هیچ Walletای ثبت نشده")
        return

    await update.message.reply_text(
        "📌 Wallets:\n\n" + "\n".join(wallets)
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallets = get_wallets(context)
    await update.message.reply_text(
        f"📊 Status\n"
        f"Wallets: {len(wallets)}\n"
        f"Network: Solana"
    )
