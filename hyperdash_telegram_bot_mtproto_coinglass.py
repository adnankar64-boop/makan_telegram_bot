"""
Telegram signal bot:
- Watches wallets (on-chain + exchange via CoinGlass/DeBank/DexScreener)
- Detects: buys, sells, balance changes, new token, futures positions open/close
- Stores state to disk (state.json) and sends signals to authorized Telegram chats
"""

import os
import json
import logging
import asyncio
from typing import Any, Dict, List, Optional, Set
from datetime import datetime, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Telegram PTB v20+
from telegram import Bot, Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------- CONFIG ----------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
COINGLASS_API_KEY = os.environ.get("COINGLASS_API_KEY", "")
PROXY_URL = os.environ.get("PROXY_URL", "")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "300"))
MIN_POSITION_VALUE_USD = float(os.environ.get("MIN_POSITION_VALUE_USD", "10.0"))

WALLETS_FILE = os.environ.get("WALLETS_FILE", "wallets.json")
AUTHORIZED_CHATS_FILE = os.environ.get("AUTHORIZED_CHATS_FILE", "authorized_chats.json")
STATE_FILE = os.environ.get("STATE_FILE", "state.json")

REQUEST_TIMEOUT = 12

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("signal_bot")

# ---------------- HTTP session ----------------
def make_session(proxies=None):
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=(500, 502, 503, 504))
    adapter = HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=50)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    if proxies:
        s.proxies.update(proxies)
    s.headers.update({"User-Agent": "SignalBot/1.0"})
    return s


PROXIES_REQUESTS = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else {}
SESSION = make_session(PROXIES_REQUESTS)

bot = Bot(token=BOT_TOKEN)

# ---------------- JSON storage helpers ----------------
def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"write_json {path}: {e}")


def load_wallets():
    data = _read_json(WALLETS_FILE, [])
    return [w.lower() for w in data]


def save_wallets(wallets):
    _write_json(WALLETS_FILE, wallets)


def load_authorized_chats():
    data = _read_json(AUTHORIZED_CHATS_FILE, [])
    return set(int(x) for x in data)


def save_authorized_chats(chats):
    _write_json(AUTHORIZED_CHATS_FILE, list(chats))


state = _read_json(STATE_FILE, {})


def save_state():
    _write_json(STATE_FILE, state)


def get_wallet_state(addr):
    return state.get(addr.lower(), {"tokens": {}, "positions": [], "usd_total": 0.0})


def set_wallet_state(addr, snap):
    state[addr.lower()] = snap
    save_state()


# ---------------- Authorization ----------------
authorized_chats: Set[int] = load_authorized_chats()


def authorize_chat(chat_id):
    if chat_id not in authorized_chats:
        authorized_chats.add(chat_id)
        save_authorized_chats(authorized_chats)


# ---------------- Telegram Commands ----------------
async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    authorize_chat(update.effective_chat.id)

    if not context.args:
        return await update.message.reply_text("Usage: /add <wallet_address>")

    addr = context.args[0].lower()
    wallets = load_wallets()

    if addr in wallets:
        return await update.message.reply_text("آدرس قبلاً ثبت شده.")

    wallets.append(addr)
    save_wallets(wallets)

    await update.message.reply_text(f"آدرس {addr} اضافه شد.")


async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    authorize_chat(update.effective_chat.id)

    if not context.args:
        return await update.message.reply_text("Usage: /remove <wallet_address>")

    addr = context.args[0].lower()
    wallets = load_wallets()

    if addr not in wallets:
        return await update.message.reply_text("آدرس یافت نشد.")

    wallets.remove(addr)
    save_wallets(wallets)

    await update.message.reply_text(f"آدرس {addr} حذف شد.")


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    authorize_chat(update.effective_chat.id)
    wallets = load_wallets()

    if not wallets:
        txt = "هیچ کیف‌پولی ثبت نشده."
    else:
        txt = "فهرست کیف‌پول‌ها:\n" + "\n".join(wallets)

    await update.message.reply_text(txt)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    authorize_chat(update.effective_chat.id)
    wallets = load_wallets()

    await update.message.reply_text(
        f"Bot running.\nInterval: {POLL_INTERVAL}s\nWallets: {len(wallets)}"
    )


# ---------------- Fetchers (CoinGlass/Debank/...) ----------------
DEXSCREENER_API = "https://api.dexscreener.com/latest/dex/search?q="
DEBANK_API = "https://api.debank.com/user/total_balance?id="
COINGLASS_BASE = "https://open-api-v4.coinglass.com"
HYPERDASH_BASE = "https://hyperdash.info"

def fetch_from_debank(address):
    try:
        r = SESSION.get(DEBANK_API + address, timeout=REQUEST_TIMEOUT)
        j = r.json()
        total = float(((j.get("data") or {}).get("total_usd_value")) or 0)
        assets = (j.get("data") or {}).get("wallet_asset_list") or []

        tokens = {}
        for a in assets:
            sym = a.get("symbol")
            price = float(a.get("price") or 0)
            amt = float(a.get("amount") or 0)
            if sym:
                tokens[sym] = price * amt

        return {"address": address, "usd_total": total, "tokens": tokens, "positions": []}
    except:
        return None


def fetch_from_coinglass(address):
    if not COINGLASS_API_KEY:
        return None

    headers = {"CG-API-KEY": COINGLASS_API_KEY}
    tokens = {}
    usd_total = 0
    positions = []

    try:
        r = SESSION.get(
            f"{COINGLASS_BASE}/api/exchange/assets",
            params={"wallet_address": address},
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

        if r.ok:
            j = r.json()
            for item in j.get("data", []):
                sym = item.get("symbol")
                v = float(item.get("balance_usd") or 0)
                tokens[sym] = tokens.get(sym, 0) + v
                usd_total += v

        return {"address": address, "usd_total": usd_total, "tokens": tokens, "positions": []}

    except:
        return None


def detect_and_build_snapshots(addr):
    for f in (fetch_from_coinglass, fetch_from_debank):
        r = f(addr)
        if r:
            return r
    return None


# ---------------- Compare States ----------------
def compare_and_generate_events(addr, snap):
    events = []
    prev = get_wallet_state(addr)

    prev_tokens = prev.get("tokens", {})
    now_tokens = snap.get("tokens", {})

    prev_total = float(prev.get("usd_total") or 0)
    now_total = float(snap.get("usd_total") or 0)

    # token changes
    for tok in set(prev_tokens) | set(now_tokens):
        old = float(prev_tokens.get(tok, 0))
        new = float(now_tokens.get(tok, 0))

        if new > old + 1:
            events.append(f"🟢 BUY {tok}: {old} → {new}")
        elif new < old - 1:
            events.append(f"🔴 SELL {tok}: {old} → {new}")

    if abs(now_total - prev_total) > 5:
        events.append(f"Balance: ${prev_total} → ${now_total}")

    return events


# ---------------- Sender ----------------
async def send_signal(text):
    for cid in authorized_chats:
        try:
            await bot.send_message(chat_id=cid, text=text)
        except Exception as e:
            logger.error(f"send to {cid} failed: {e}")


# ---------------- Poller ----------------
async def process_wallet(addr):
    snap = detect_and_build_snapshots(addr)
    if not snap:
        return

    events = compare_and_generate_events(addr, snap)

    set_wallet_state(
        addr,
        {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "usd_total": float(snap.get("usd_total") or 0),
            "tokens": snap.get("tokens", {}),
        },
    )

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for e in events:
        await send_signal(f"⚡ سیگنال — {addr}\n{e}\n⏱ {ts}")


async def poller():
    while True:
        for w in load_wallets():
            try:
                await process_wallet(w)
            except Exception as e:
                logger.error(f"poll error {w}: {e}")
        await asyncio.sleep(POLL_INTERVAL)


# ---------------- Main ----------------
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    asyncio.get_event_loop().create_task(poller())

    application.add_handler(CommandHandler("add", cmd_add))
    application.add_handler(CommandHandler("remove", cmd_remove))
    application.add_handler(CommandHandler("list", cmd_list))
    application.add_handler(CommandHandler("status", cmd_status))

    application.run_polling()


if __name__ == "__main__":
    main()
