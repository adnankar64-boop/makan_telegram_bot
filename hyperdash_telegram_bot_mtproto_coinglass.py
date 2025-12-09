# bot.py
import asyncio
import aiosqlite
import aiohttp
import os
import json
import time
from datetime import datetime, timezone

from telegram import __version__ as TGVER
from telegram import Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")  # REQUIRED
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")    # optional: برای ارسال اخطارها

# GMGN عمومی (مثال endpoints که سایت معمولاً استفاده می‌کند)
GMGN_TREND_URL = "https://gmgn.ai/defi/quotation/v1/trending/sol"
GMGN_SMARTMONEY = "https://gmgn.ai/defi/quotation/v1/smartmoney/{addr_or_token}"

# rate limits & intervals
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))  # ثانیه بین polling‌های GMGN
CACHE_TTL = 20  # ثانیه cache داخلی برای نتایج مشابه

DB_FILE = os.environ.get("DB_FILE", "bot_state.db")

# --- کمک‌کننده‌ها ---
def now_ts():
    return int(time.time())

# ساده‌ترین منطق سیگنال (قابل توسعست)
def compute_signal_from_trending(token_item):
    """
    token_item: dict from gmgn trending list
    بازمی‌گرداند: {"signal": "BUY"/"SELL"/"HOLD"/"WARN", "reason": "..."}
    قواعد نمونه:
      - اگر pct_change_5m > 15% و volume spike -> BUY (short)
      - اگر smart_money_out > 0 (قابلیت استفاده با داده smartmoney) -> SELL
    (تو باید پارامترها را بر اساس دیتا واقعی تعدیل کنی)
    """
    try:
        # نمونه: برخی فیلدها ممکنه نام‌های متفاوتی داشته باشن؛ امن بررسی کن
        p5 = float(token_item.get("increaseRate_5m", token_item.get("pct_5m", 0)) or 0)
        vol = float(token_item.get("volume", 0) or 0)
        age_hours = float(token_item.get("age_hours", 9999) or 9999)
    except Exception:
        p5, vol, age_hours = 0, 0, 9999

    # قوانین مثالی
    if p5 > 20 and vol > 10000 and age_hours < 24:
        return {"signal": "BUY", "reason": f"Rapid spike: {p5}% in 5m, vol {vol}"}
    if p5 < -20 and vol > 10000:
        return {"signal": "SELL", "reason": f"Crash: {p5}% in 5m"}
    return {"signal": "HOLD", "reason": f"no strong pattern ({p5}%, vol {vol})"}


# --- دیتابیس ساده (sqlite) ---
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id TEXT PRIMARY KEY,
                created_at INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS wallets (
                addr TEXT PRIMARY KEY,
                note TEXT,
                created_at INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sent_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT,
                payload TEXT,
                ts INTEGER
            )
        """)
        await db.commit()

async def add_user(chat_id):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT OR IGNORE INTO users(chat_id, created_at) VALUES (?, ?)", (str(chat_id), now_ts()))
        await db.commit()

async def list_users():
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute("SELECT chat_id FROM users")
        rows = await cur.fetchall()
        return [r[0] for r in rows]

async def add_wallet(addr, note=""):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT OR IGNORE INTO wallets(addr, note, created_at) VALUES (?, ?, ?)", (addr, note, now_ts()))
        await db.commit()

async def list_wallets():
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute("SELECT addr, note FROM wallets")
        rows = await cur.fetchall()
        return [{"addr": r[0], "note": r[1]} for r in rows]

async def remember_signal_once(key, payload):
    # برای جلوگیری از ارسال مکرر سیگنال مشابه
    async with aiosqlite.connect(DB_FILE) as db:
        cur = await db.execute("SELECT 1 FROM sent_signals WHERE key = ? AND ts > ?", (key, now_ts() - 3600))
        if await cur.fetchone():
            return False
        await db.execute("INSERT INTO sent_signals(key, payload, ts) VALUES (?, ?, ?)", (key, json.dumps(payload), now_ts()))
        await db.commit()
        return True

# --- دستورات تلگرام ---
async def start_cmd(update, context: ContextTypes.DEFAULT_TYPE):
    await add_user(update.effective_chat.id)
    await update.message.reply_text("سلام! من بات GMGN مانیتور هستم. /addwallet <address> /listwallets /trend")

async def addwallet_cmd(update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /addwallet <address> [note]")
        return
    addr = context.args[0].strip()
    note = " ".join(context.args[1:]) if len(context.args) > 1 else ""
    await add_wallet(addr, note)
    await update.message.reply_text(f"آدرس اضافه شد: {addr}")

async def listwallets_cmd(update, context: ContextTypes.DEFAULT_TYPE):
    w = await list_wallets()
    if not w:
        await update.message.reply_text("هیچ آدرسی ثبت نشده.")
        return
    lines = [f"{i+1}. {x['addr']} {('- '+x['note']) if x['note'] else ''}" for i, x in enumerate(w)]
    await update.message.reply_text("\n".join(lines))

async def trend_cmd(update, context: ContextTypes.DEFAULT_TYPE):
    # فوری یک رجوع GMGN و نمایش 5 ترند برتر
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(GMGN_TREND_URL, timeout=15) as r:
                data = await r.json()
        except Exception as e:
            await update.message.reply_text(f"خطا در واکشی GMGN: {e}")
            return
    items = data.get("data", []) if isinstance(data, dict) else []
    if not items:
        await update.message.reply_text("موردی یافت نشد.")
        return
    text_lines = []
    for t in items[:8]:
        sym = t.get("symbol") or t.get("tokenSymbol") or t.get("name") or "unknown"
        price = t.get("price") or t.get("lastPrice") or "?"
        p5 = t.get("increaseRate_5m") or t.get("pct_5m") or "-"
        text_lines.append(f"{sym} | price: {price} | 5m: {p5}")
    await update.message.reply_text("\n".join(text_lines))

# --- مانیتورینگ اصلی ---
class GMGNClient:
    def __init__(self, session):
        self.session = session
        self._cache = {}
    async def get_trending(self):
        key = "trending"
        now = now_ts()
        if key in self._cache and now - self._cache[key]["ts"] < CACHE_TTL:
            return self._cache[key]["data"]
        try:
            async with self.session.get(GMGN_TREND_URL, timeout=15) as r:
                data = await r.json()
        except Exception as e:
            data = {"error": str(e)}
        self._cache[key] = {"ts": now, "data": data}
        return data

    async def get_smartmoney(self, token_or_addr):
        url = GMGN_SMARTMONEY.format(addr_or_token=token_or_addr)
        key = f"sm_{token_or_addr}"
        now = now_ts()
        if key in self._cache and now - self._cache[key]["ts"] < CACHE_TTL:
            return self._cache[key]["data"]
        try:
            async with self.session.get(url, timeout=15) as r:
                data = await r.json()
        except Exception as e:
            data = {"error": str(e)}
        self._cache[key] = {"ts": now, "data": data}
        return data

async def monitor_loop(app):
    bot: Bot = app.bot
    async with aiohttp.ClientSession() as session:
        gm = GMGNClient(session)
        while True:
            try:
                trending = await gm.get_trending()
                items = trending.get("data", []) if isinstance(trending, dict) else []
                # iterate trending and compute simple signals
                for it in items[:20]:
                    sig = compute_signal_from_trending(it)
                    key = f"trend_{it.get('symbol','unk')}_{int(now_ts()/60)}"  # unique-ish per minute
                    if sig["signal"] in ("BUY", "SELL", "WARN"):
                        ok = await remember_signal_once(key, {"sym": it.get("symbol"), "sig": sig})
                        if ok:
                            text = f"GMGN Signal: {sig['signal']}\nSymbol: {it.get('symbol')}\nReason: {sig['reason']}\nPrice: {it.get('price')}\nTime: {datetime.now(timezone.utc).isoformat()}"
                            # send to admin or all users
                            recipients = [ADMIN_CHAT_ID] if ADMIN_CHAT_ID else await list_users()
                            for rcpt in recipients:
                                try:
                                    await bot.send_message(chat_id=int(rcpt), text=text)
                                except Exception:
                                    pass

                # monitor smart-money for watched wallets
                wallets = await list_wallets()
                for w in wallets:
                    addr = w["addr"]
                    sm = await gm.get_smartmoney(addr)
                    # اگر GMGN پاسخ داده که خریدهای قابل توجهی بوده -> اعلام
                    if isinstance(sm, dict):
                        # نمونه: بررسی یک فیلد فرضی 'top_buyers_count'
                        tbc = sm.get("top_buyers_count") or sm.get("buyers_count") or 0
                        try:
                            tbc = int(tbc)
                        except Exception:
                            tbc = 0
                        if tbc >= 3:
                            key = f"wallet_{addr}_{int(now_ts()/60)}"
                            ok = await remember_signal_once(key, {"addr": addr, "tbc": tbc})
                            if ok:
                                text = f"Wallet activity: {addr}\nSmart buyers: {tbc}\nNote: {w.get('note','')}"
                                recipients = [ADMIN_CHAT_ID] if ADMIN_CHAT_ID else await list_users()
                                for rcpt in recipients:
                                    try:
                                        await bot.send_message(chat_id=int(rcpt), text=text)
                                    except Exception:
                                        pass
            except Exception as e:
                # log (print)
                print("monitor loop exception:", e)

            await asyncio.sleep(POLL_INTERVAL)


# --- main ---
async def main():
    if not TELEGRAM_TOKEN:
        print("ERROR: TELEGRAM_TOKEN environment variable required.")
        return
    await init_db()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("addwallet", addwallet_cmd))
    app.add_handler(CommandHandler("listwallets", listwallets_cmd))
    app.add_handler(CommandHandler("trend", trend_cmd))

    # start monitor
    app.create_task(monitor_loop(app))
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
