from telegram import Bot
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

bot = Bot(token=BOT_TOKEN)

def send_alert(text):
    bot.send_message(chat_id=CHAT_ID, text=text)
