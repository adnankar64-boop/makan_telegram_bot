"""
Compatibility Telegram signal bot:
- Works with python-telegram-bot v20+ (Application) if available
- Falls back to v13 (Updater) if Application is not present
- Watches wallets via CoinGlass / DeBank / DexScreener / HyperDash
- Detects buys/sells/balance changes/positions and stores state to disk
- Reads config from ENV
"""

import sys
import os
import json
import logging
import time
import threading
import requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Set

# اضافه کردن مسیر ریشه (در صورت نیاز)
sys.path.append(os.path.dirname(__file__))

# Try to import modern PTB Application; otherwise fall back to Updater
USE_APPLICATION = False
try:
    # v20+ imports
    from telegram import Bot, Update
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        ContextTypes,
        filters,
    )
    USE_APPLICATION = True
except Exception:
    # fallback imports for older PTB (v13)
    from telegram import Bot, Update
    from telegram.ext import Updater, CommandHandler, MessageHandler, Filters

# ---------------- CONFIG (from ENV) ----------------
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
    raise RuntimeError("BOT_TOKEN environment variable is not set. Aborting.")

# ---------------- logging ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("signal_bot")

# ---------------- HTTP session ----------------
def make_session(proxies: Optional[dict] = None) -> requests.Session:
    s = requests.Session()
    retries = requests.adapters.Retry(total=3, backoff_factor=1, status_forcelist=(500, 502, 503, 504))
    adapter = requests.adapters.HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=50)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    if proxies:
        s.proxies.update(proxies)
    s.headers.update({"User-Agent": "SignalBot/1.0"})
    return s

PROXIES_REQUESTS = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else {}
SESSION = make_session(PROXIES_REQUESTS)

# ---------------- Telegram Bot object ----------------
bot = Bot(token=BOT_TOKEN)

# ---------------- storage helpers ----------------
def _read_json(path: str, default: Any):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:
        logger.debug(f"read_json {path} failed: {e}")
        return default

def _write_json(path: str, data: Any):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"write_json {path} failed: {e}")

def load_wallets() -> List[str]:
    data = _read_json(WALLETS_FILE, [])
    if isinstance(data, list):
        return [w.lower() for w in data]
    return []

def save_wallets(wallets: List[str]):
    _write_json(WALLETS_FILE, wallets)

def load_authorized_chats() -> Set[int]:
    data = _read_json(AUTHORIZED_CHATS_FILE, [])
    try:
        return set(int(x) for x in data)
    except Exception:
        return set()

def save_authorized_chats(chats: Set[int]):
    _write_json(AUTHORIZED_CHATS_FILE, list(chats))

# ---------------- state ----------------
state: Dict[str, Any] = _read_json(STATE_FILE, {})

def save_state():
    _write_json(STATE_FILE, state)

def get_wallet_state(addr: str) -> Dict[str, Any]:
    return state.get(addr.lower(), {"tokens": {}, "positions": [], "usd_total": 0.0})

def set_wallet_state(addr: str, snap: Dict[str, Any]):
    state[addr.lower()] = snap
    save_state()

# ---------------- authorization ----------------
authorized_chats: Set[int] = load_authorized_chats()

def authorize_chat(chat_id: int):
    if chat_id not in authorized_chats:
        authorized_chats.add(chat_id)
        save_authorized_chats(authorized_chats)
    return True

# ---------------- Helper: safe send message (works for both versions) ----------------
def send_message_sync(chat_id: int, text: str):
    try:
        bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        logger.exception("send_message failed: %s", e)

# helper to reply either via update.message.reply_text (preferred) or bot.send_message
def send_reply(update: Update, text: str):
    try:
        if hasattr(update, "message") and update.message:
            # For v20 Update.message.reply_text is coroutine — but in this wrapper we try to call
            # .reply_text synchronously if available; else fallback to bot.send_message
            try:
                # if reply_text is a coroutine (v20), call bot.send_message to avoid awaiting here
                reply = update.message.reply_text
                # If it's coroutine function, it'll be callable but returns coroutine — handle safely:
                res = reply(text)
                # if res is coroutine, ignore (we're in sync context); fallback to bot.send_message
                if hasattr(res, "__await__"):
                    send_message_sync(update.effective_chat.id, text)
            except Exception:
                # fallback
                cid = update.effective_chat.id if update.effective_chat else None
                if cid:
                    send_message_sync(cid, text)
        else:
            cid = update.effective_chat.id if update.effective_chat else None
            if cid:
                send_message_sync(cid, text)
    except Exception:
        try:
            cid = update.effective_chat.id
            send_message_sync(cid, text)
        except Exception:
            logger.exception("send_reply failed")

# ---------------- helpers for extracting args ----------------
def extract_first_arg_from_update(update: Update, context) -> Optional[str]:
    # Try context.args first (works for both versions)
    args = getattr(context, "args", None)
    if args:
        return str(args[0]).strip().lower()
    # Fall back to splitting message text
    try:
        text = ""
        if hasattr(update, "message") and update.message and update.message.text:
            text = update.message.text
        elif update.effective_message and update.effective_message.text:
            text = update.effective_message.text
        parts = text.split()
        if len(parts) >= 2:
            return parts[1].strip().lower()
    except Exception:
        pass
    return None

# ---------------- Telegram command handlers (synchronous, compatible) ----------------
def cmd_add_sync(update: Update, context):
    try:
        chat_id = update.effective_chat.id
    except Exception:
        return

    authorize_chat(chat_id)
    addr = extract_first_arg_from_update(update, context)
    if not addr:
        send_reply(update, "Usage: /add <wallet_address>")
        return
    wallets = load_wallets()
    if addr in wallets:
        send_reply(update, "آدرس قبلا وجود دارد.")
    else:
        wallets.append(addr)
        save_wallets(wallets)
        send_reply(update, f"آدرس {addr} اضافه شد ✅")

def cmd_remove_sync(update: Update, context):
    try:
        chat_id = update.effective_chat.id
    except Exception:
        return
    authorize_chat(chat_id)
    addr = extract_first_arg_from_update(update, context)
    if not addr:
        send_reply(update, "Usage: /remove <wallet_address>")
        return
    wallets = load_wallets()
    if addr in wallets:
        wallets.remove(addr)
        save_wallets(wallets)
        send_reply(update, f"آدرس {addr} حذف شد ✅")
    else:
        send_reply(update, "آدرس یافت نشد.")

def cmd_list_sync(update: Update, context):
    try:
        chat_id = update.effective_chat.id
    except Exception:
        return
    authorize_chat(chat_id)
    wallets = load_wallets()
    txt = "فهرست کیف‌پول‌ها:\n" + ("\n".join(wallets) if wallets else "هیچ آدرسی ثبت نشده.")
    send_reply(update, txt)

def cmd_status_sync(update: Update, context):
    try:
        chat_id = update.effective_chat.id
    except Exception:
        return
    authorize_chat(chat_id)
    wallets = load_wallets()
    send_reply(update, f"Bot running.\nInterval: {POLL_INTERVAL}s\nWallets: {len(wallets)}")

# ---------------- Fetchers (CoinGlass / Debank / DexScreener / HyperDash) ----------------
DEXSCREENER_API = "https://api.dexscreener.com/latest/dex/search?q="
DEBANK_API = "https://api.debank.com/user/total_balance?id="
COINGLASS_BASE = "https://open-api-v4.coinglass.com"
HYPERDASH_BASE = "https://hyperdash.info"

def fetch_from_dexscreener_addr(address: str) -> Optional[Dict[str, Any]]:
    try:
        r = SESSION.get(DEXSCREENER_API + address, timeout=REQUEST_TIMEOUT)
        j = r.json()
        pairs = j.get("pairs") or []
        tokens = {}
        for p in pairs:
            base = (p.get("baseToken") or {}).get("symbol")
            if not base:
                continue
            liquidity = float((p.get("liquidity") or {}).get("usd") or 0)
            tokens[base] = tokens.get(base, 0.0) + liquidity
        if tokens:
            return {"address": address, "tokens": tokens, "source": "dexscreener", "usd_total": sum(tokens.values())}
    except Exception:
        logger.debug("dexscreener fetch failed for %s", address)
    return None

def fetch_from_debank(address: str) -> Optional[Dict[str, Any]]:
    try:
        r = SESSION.get(DEBANK_API + address, timeout=REQUEST_TIMEOUT)
        j = r.json()
        total = float(((j.get("data") or {}).get("total_usd_value")) or 0)
        assets = (j.get("data") or {}).get("wallet_asset_list") or []

        tokens = {}
        for a in assets:
            sym = a.get("symbol") or a.get("name")
            price = float(a.get("price") or 0)
            amt = float(a.get("amount") or 0)
            if sym:
                tokens[sym] = tokens.get(sym, 0) + price * amt

        return {
            "address": address,
            "usd_total": total,
            "tokens": tokens,
            "positions": [],
            "source": "debank",
        }
    except Exception:
        logger.debug("debank fetch failed for %s", address)
        return None

def fetch_from_coinglass(address: str) -> Optional[Dict[str, Any]]:
    if not COINGLASS_API_KEY:
        return None
    headers = {"CG-API-KEY": COINGLASS_API_KEY}

    tokens = {}
    usd_total = 0.0
    positions = []

    try:
        # exchange assets
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
                if sym:
                    tokens[sym] = tokens.get(sym, 0) + v
                    usd_total += v

        # futures positions (best-effort)
        try:
            r2 = SESSION.get(
                f"{COINGLASS_BASE}/api/hyperliquid/position",
                params={"user": address},
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            if r2.ok:
                j2 = r2.json()
                for item in (j2.get("data") or {}).get("list", []):
                    sym = item.get("symbol")
                    size = float(item.get("position_value_usd") or 0)
                    pos_size = float(item.get("position_size") or 0)
                    side = "long" if pos_size > 0 else "short" if pos_size < 0 else ""
                    if abs(size) >= MIN_POSITION_VALUE_USD:
                        positions.append({"symbol": sym, "size_usd": abs(size), "side": side})
                        usd_total += abs(size)
        except Exception:
            logger.debug("coinglass positions fetch failed for %s", address)

        return {
            "address": address,
            "usd_total": usd_total,
            "tokens": tokens,
            "positions": positions,
            "source": "coinglass",
        }
    except Exception:
        logger.debug("coinglass fetch failed for %s", address)
        return None

def fetch_from_hyperdash(address: str) -> Optional[Dict[str, Any]]:
    try:
        r = SESSION.get(f"{HYPERDASH_BASE}/trader/{address}", timeout=REQUEST_TIMEOUT)
        if not r.ok:
            return None

        text = r.text
        import re
        m = re.search(r'"positions":(\[.*?\])', text)
        if not m:
            return None

        arr = json.loads(m.group(1))
        positions = []

        for p in arr:
            symbol = p.get("symbol") or p.get("market")
            size = float(p.get("notional") or 0)
            side = "long" if p.get("isLong") else "short"
            if size >= MIN_POSITION_VALUE_USD:
                positions.append({"symbol": symbol, "size_usd": size, "side": side})

        if positions:
            return {"address": address, "positions": positions, "source": "hyperdash", "usd_total": sum(p["size_usd"] for p in positions)}
    except Exception:
        logger.debug("hyperdash fetch failed for %s", address)
    return None

# ---------------- Snapshot detection ----------------
def detect_and_build_snapshots(addr: str) -> Optional[Dict[str, Any]]:
    for f in (
        fetch_from_coinglass,
        fetch_from_debank,
        fetch_from_dexscreener_addr,
        fetch_from_hyperdash,
    ):
        try:
            r = f(addr)
            if r:
                # normalize keys
                r.setdefault("tokens", {})
                r.setdefault("positions", [])
                r.setdefault("usd_total", float(r.get("usd_total") or 0.0))
                return r
        except Exception:
            logger.debug("fetcher %s failed for %s", getattr(f, "__name__", str(f)), addr)
    return None

# ---------------- Compare states → Events ----------------
def compare_and_generate_events(addr: str, snap: Dict[str, Any]) -> List[str]:
    events: List[str] = []
    prev = get_wallet_state(addr)

    prev_tokens = prev.get("tokens", {})
    now_tokens = snap.get("tokens", {})

    prev_positions = prev.get("positions", [])
    now_positions = snap.get("positions", [])

    prev_total = float(prev.get("usd_total") or 0)
    now_total = float(snap.get("usd_total") or 0)

    # token events - new tokens
    for tok in now_tokens:
        if tok not in prev_tokens:
            events.append(f"📥 New token: {tok} → ${float(now_tokens[tok]):.2f}")

    # token changes
    for tok in set(prev_tokens) | set(now_tokens):
        pv = float(prev_tokens.get(tok, 0))
        nv = float(now_tokens.get(tok, 0))
        if abs(nv - pv) < 1:
            continue
        if nv > pv:
            events.append(f"🟢 BUY {tok}: ${pv:.2f} → ${nv:.2f}")
        elif nv < pv:
            events.append(f"🔴 SELL {tok}: ${pv:.2f} → ${nv:.2f}")

    # balance change
    if abs(now_total - prev_total) > 5:
        events.append(f"ℹ️ Balance: ${prev_total:.2f} → ${now_total:.2f}")

    # positions: opens / increases / closes
    prev_map = {(p.get("symbol"), p.get("side")): p for p in prev_positions}

    for p in now_positions:
        key = (p.get("symbol"), p.get("side"))
        if key not in prev_map:
            events.append(f"⚡ OPEN {p.get('symbol')} {p.get('side')} ${p.get('size_usd', 0):.0f}")
        else:
            old = float(prev_map[key].get("size_usd", 0))
            new = float(p.get("size_usd", 0))
            if new > old * 1.05:
                events.append(f"⚡ INCREASE {p.get('symbol')} {p.get('side')} ${old:.0f} → ${new:.0f}")

    for pp in prev_positions:
        # check if this previous position still exists in now_positions
        exists = any((p.get("symbol") == pp.get("symbol") and p.get("side") == pp.get("side")) for p in now_positions)
        if not exists:
            events.append(f"⚡ CLOSE {pp.get('symbol')} {pp.get('side')} (${pp.get('size_usd', 0):.0f})")

    return events

# ---------------- sending signals ----------------
def send_signal_sync(text: str):
    """Send to all authorized chats (synchronous)."""
    for cid in list(authorized_chats):
        try:
            send_message_sync(cid, text)
        except Exception as e:
            logger.error(f"send to {cid} failed: {e}")

# ---------------- poller thread (synchronous) ----------------
def process_wallet_sync(addr: str):
    snap = detect_and_build_snapshots(addr)
    if not snap:
        return
    events = compare_and_generate_events(addr, snap)

    new_state = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "usd_total": float(snap.get("usd_total") or 0.0),
        "tokens": snap.get("tokens", {}),
        "positions": snap.get("positions", []),
    }
    set_wallet_state(addr, new_state)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for e in events:
        send_signal_sync(f"⚡ سیگنال — `{addr}`\n{e}\n⏱ {ts}")

def poller_thread():
    logger.info("Poller thread started, interval %s seconds", POLL_INTERVAL)
    while True:
        wallets = load_wallets()
        for w in wallets:
            try:
                process_wallet_sync(w)
            except Exception:
                logger.exception("poll error %s", w)
        time.sleep(POLL_INTERVAL)

# ---------------- start/registration ----------------
def build_and_start_bot():
    """
    Build handlers and start bot depending on available PTB version.
    """
    # Handlers (use sync functions; compatible with v13 and v20 via wrappers)
    handlers = [
        ("add", cmd_add_sync),
        ("remove", cmd_remove_sync),
        ("list", cmd_list_sync),
        ("status", cmd_status_sync),
    ]

    # Start poller thread
    t = threading.Thread(target=poller_thread, daemon=True)
    t.start()

    if USE_APPLICATION:
        logger.info("Using python-telegram-bot v20+ (Application)")
        app = Application.builder().token(BOT_TOKEN).build()

        # v20 expects async callbacks; wrap sync handlers in small async wrappers
        import asyncio

        def make_async_wrapper(sync_fn):
            async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
                try:
                    # Call sync function — it may block briefly; acceptable for light commands.
                    sync_fn(update, context)
                except Exception:
                    logger.exception("handler error")
            return wrapper

        for cmd, fn in handlers:
            app.add_handler(CommandHandler(cmd, make_async_wrapper(fn)))

        # start the application
        app.run_polling()
    else:
        logger.info("Using python-telegram-bot v13 Updater fallback")
        updater = Updater(token=BOT_TOKEN, use_context=True)
        dp = updater.dispatcher

        for cmd, fn in handlers:
            dp.add_handler(CommandHandler(cmd, fn))

        # start polling
        updater.start_polling()
        updater.idle()

# ---------------- entrypoint ----------------
if __name__ == "__main__":
    try:
        build_and_start_bot()
    except KeyboardInterrupt:
        logger.info("Shutting down by user request")
    except Exception:
        logger.exception("Fatal error starting bot")
