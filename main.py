import os
import threading
import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
)

from telegram_commands import (
    addwallet,
    removewallet,
    wallets,
    threshold,
    status,
)

from solana_trade_monitor import monitor


# ======================
# Fake HTTP Server (برای Render Free)
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
TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))

if not TOKEN:
    raise RuntimeError("❌ BOT_TOKEN is not set")

app = ApplicationBuilder().token(TOKEN).build()

# --- Commands ---
app.add_handler(CommandHandler("addwallet", addwallet))
app.add_handler(CommandHandler("removewallet", removewallet))
app.add_handler(CommandHandler("wallets", wallets))
app.add_handler(CommandHandler("setthreshold", threshold))
app.add_handler(CommandHandler("status", status))


# ======================
# Start Solana Trade Monitor
# ======================
async def start_trade_monitor(application):
    async def get_wallets():
        # والت‌ها از حافظه bot_data
        return application.bot_data.get("wallets", [])

    asyncio.create_task(
        monitor(
            wallets=get_wallets,
            bot=application.bot,
            chat_id=CHAT_ID,
        )
    )

app.post_init = start_trade_monitor


print("🤖 Bot is running (Render Free Mode + Solana Trade Monitor)...")
app.run_polling()
