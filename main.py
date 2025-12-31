import os
import asyncio
from telegram.ext import ApplicationBuilder, CommandHandler

from telegram_commands import (
    addwallet,
    removewallet,
    wallets,
    status
)

from wallet_store import list_wallets
from solana_tracker import check_wallet
from alerts import send_alert

TOKEN = os.getenv("BOT_TOKEN")


async def solana_monitor():
    while True:
        wallets_list = list_wallets()

        for w in wallets_list:
            address = w[0]

            # فیلتر ساده آدرس Solana
            if len(address) < 32:
                continue

            sig = check_wallet(address)
            if sig:
                send_alert(
                    f"🐋 Solana Whale Alert\n\n"
                    f"Wallet:\n{address}\n\n"
                    f"New transaction detected"
                )

        await asyncio.sleep(45)


async def on_startup(app):
    asyncio.create_task(solana_monitor())


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("addwallet", addwallet))
    app.add_handler(CommandHandler("removewallet", removewallet))
    app.add_handler(CommandHandler("wallets", wallets))
    app.add_handler(CommandHandler("status", status))

    app.post_init = on_startup

    print("🤖 Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
