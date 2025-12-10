import sys
import os

sys.path.append(os.path.dirname(__file__))

import asyncio
from hyperdash_telegram_bot_mtproto_coinglass import main as bot_main

asyncio.run(bot_main())

