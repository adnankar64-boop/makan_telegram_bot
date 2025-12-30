import os
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler
)

from telegram_commands import (
    addwallet,
    removewallet,
    wallets,
    threshold,
    status
)

TOKEN = os.getenv("BOT_TOKEN")

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("addwallet", addwallet))
app.add_handler(CommandHandler("removewallet", removewallet))
app.add_handler(CommandHandler("wallets", wallets))
app.add_handler(CommandHandler("setthreshold", threshold))
app.add_handler(CommandHandler("status", status))

print("🤖 Bot is running...")
app.run_polling()
