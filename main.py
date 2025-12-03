# /app/main.py
import asyncio
from hyperdash_telegram_bot_mtproto_coinglass import main as bot_main

if __name__ == "__main__":
    asyncio.run(bot_main())
