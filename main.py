import asyncio

from solana_trade_monitor import monitor


from solana_monitor import monitor
from wallet_store import list_wallets

import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

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

# ======================
# Fake HTTP Server
# ======================
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_fake_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()

threading.Thread(target=run_fake_server, daemon=True).start()

# ======================
# Telegram Bot
# ======================
TOKEN = os.getenv("TELEGRAM_TOKEN")

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("addwallet", addwallet))
app.add_handler(CommandHandler("removewallet", removewallet))
app.add_handler(CommandHandler("wallets", wallets))
app.add_handler(CommandHandler("setthreshold", threshold))
app.add_handler(CommandHandler("status", status))

print("🤖 Bot is running (Render Free Mode)...")
app.run_polling()
