import sys
import os

sys.path.append(os.path.dirname(__file__))

from hyperdash_telegram_bot_mtproto_coinglass import main as bot_main

# هیچ asyncio لازم نیست
bot_main()
