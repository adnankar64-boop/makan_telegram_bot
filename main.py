import sys
import os
import asyncio

sys.path.append(os.path.dirname(__file__))

from hyperdash_telegram_bot_mtproto_coinglass import main as bot_main

asyncio.run(bot_main())
