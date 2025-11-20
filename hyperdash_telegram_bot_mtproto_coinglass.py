# hyperdash_telegram_bot_mtproto_coinglass.py
"""
Telegram signal bot:
- Watches wallets (on-chain + exchange via CoinGlass/DeBank/DexScreener)
- Detects: buys, sells, balance changes, new token, futures positions open/close
- Stores state to disk (state.json) and sends signals to authorized Telegram chats

Designed for polling (not webhook). Reads secrets from ENV.
"""

import os
import json
import time
import logging
import threading
import math
from typing import Any, Dict, List, Optional, Set
from datetime import datetime, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from telegram import Bot, Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from telegram.utils.request import Request
from telegram.error import TelegramError

# ---------------- CONFIG (from ENV) ----------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
COINGLASS_API_KEY = os.environ.get("COINGLASS_API_KEY", "")
PROXY_URL = os.environ.get("PROXY_URL", "")  # if you use a proxy, set e.g. socks5h://...
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
    retries = Retry(total=3, backoff_factor=1, status_forcelist=(500,502,503,504))
    adapter = HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=50)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    if proxies:
        s.proxies.update(proxies)
    s.headers.update({"User-Agent": "SignalBot/1.0"})
    return s

PROXIES_REQUESTS = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else {}
SESSION = make_session(PROXIES_REQUESTS)

# ---------------- Telegram init ----------------
request_obj = Request(proxy_url=PROXY_URL, connect_timeout=10.0, read_timeout=15.0) if PROXY_URL else Request(connect_timeout=10.0, read_timeout=15.0)
bot = Bot(token=BOT_TOKEN, request=request_obj)
updater = Updater(bot=bot, use_context=True)
dispatcher = updater.dispatcher

# ---------------- storage helpers ----------------
def _read_json(path: str, default: Any):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:
        logger.debug("read_json %s failed: %s", path, e)
        return default

def _write_json(path: str, data: Any):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error("write_json %s failed: %s", path, e)

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
# Structure:
# {
#   "<wallet>": {
#       "updated_at": "...",
#       "usd_total": 123.45,
#       "tokens": {"TOKEN": amount, ...},
#       "positions": [{"symbol":..., "size_usd":..., "side":...}, ...]
#    }, ...
# }
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

# ---------------- Telegram command handlers ----------------
def cmd_add(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    authorize_chat(chat_id)
    if not context.args:
        update.message.reply_text("Usage: /add <wallet_address>")
        return
    addr = context.args[0].strip().lower()
    wallets = load_wallets()
    if addr in wallets:
        update.message.reply_text("آدرس قبلا وجود دارد.")
    else:
        wallets.append(addr)
        save_wallets(wallets)
        update.message.reply_text(f"آدرس {addr} اضافه شد ✅")

def cmd_remove(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    authorize_chat(chat_id)
    if not context.args:
        update.message.reply_text("Usage: /remove <wallet_address>")
        return
    addr = context.args[0].strip().lower()
    wallets = load_wallets()
    if addr in wallets:
        wallets.remove(addr)
        save_wallets(wallets)
        update.message.reply_text(f"آدرس {addr} حذف شد ✅")
    else:
        update.message.reply_text("آدرس یافت نشد.")

def cmd_list(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    authorize_chat(chat_id)
    wallets = load_wallets()
    update.message.reply_text("فهرست کیف‌پول‌ها:\n" + ("\n".join(wallets) if wallets else "هیچ آدرسی ثبت نشده."))

def cmd_status(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    authorize_chat(chat_id)
    wallets = load_wallets()
    update.message.reply_text(f"Bot running. Poll interval: {POLL_INTERVAL}s\nFollowed wallets: {len(wallets)}")

def cmd_test(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    authorize_chat(chat_id)
    if not context.args:
        update.message.reply_text("Usage: /test <wallet_address>")
        return
    addr = context.args[0].strip().lower()
    update.message.reply_text(f"Testing {addr} — checking sources...")
    # Run single fetch cycle for this wallet and report which sources returned data
    results = []
    try:
        p = fetch_from_coinglass(addr)
        results.append(("CoinGlass", bool(p)))
    except Exception as e:
        results.append(("CoinGlass", f"err:{e}"))
    try:
        d = fetch_from_debank(addr)
        results.append(("DeBank", bool(d)))
    except Exception as e:
        results.append(("DeBank", f"err:{e}"))
    try:
        ds = fetch_from_dexscreener_addr(addr)
        results.append(("DexScreener", bool(ds)))
    except Exception as e:
        results.append(("DexScreener", f"err:{e}"))
    text = "\n".join(f"{k}: {v}" for k, v in results)
    update.message.reply_text("Test results:\n" + text)

dispatcher.add_handler(CommandHandler("add", cmd_add, pass_args=True))
dispatcher.add_handler(CommandHandler("remove", cmd_remove, pass_args=True))
dispatcher.add_handler(CommandHandler("list", cmd_list))
dispatcher.add_handler(CommandHandler("status", cmd_status))
dispatcher.add_handler(CommandHandler("test", cmd_test, pass_args=True))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, lambda u, c: None))

# ---------------- fetchers ----------------
# Note: APIs change over time. These functions try a few endpoints and return normalized snapshots.
DEXSCREENER_API = "https://api.dexscreener.com/latest/dex/search?q="
DEBANK_API = "https://api.debank.com/user/total_balance?id="
COINGLASS_BASE = "https://open-api-v4.coinglass.com"
HYPERDASH_BASE = "https://hyperdash.info"

def fetch_from_dexscreener_addr(address: str) -> Optional[Dict[str, Any]]:
    """
    Dexscreener search for address; returns list of token-like entries with liquidity (usd)
    """
    try:
        r = SESSION.get(DEXSCREENER_API + address, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        j = r.json()
        pairs = j.get("pairs") or []
        tokens = {}
        for p in pairs:
            base = (p.get("baseToken") or {}).get("symbol")
            if not base:
                continue
            try:
                liquidity = float((p.get("liquidity") or {}).get("usd") or 0)
            except Exception:
                liquidity = 0
            tokens[base] = tokens.get(base, 0.0) + liquidity
        if tokens:
            return {"address": address, "tokens": tokens, "source": "dexscreener"}
    except Exception as e:
        logger.debug("dexscreener err %s", e)
    return None

def fetch_from_debank(address: str) -> Optional[Dict[str, Any]]:
    """
    Try DeBank total and assets if available.
    """
    try:
        r = SESSION.get(DEBANK_API + address, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        j = r.json()
        total = float(((j.get("data") or {}).get("total_usd_value")) or 0)
        # try to get token breakdown if present
        tokens = {}
        assets = (j.get("data") or {}).get("wallet_asset_list") or []
        for a in assets:
            sym = a.get("symbol") or a.get("name")
            try:
                bal_usd = float(a.get("price", 0) * a.get("amount", 0))
            except Exception:
                bal_usd = 0
            if sym:
                tokens[sym] = bal_usd
        if total >= 0:
            return {"address": address, "usd_total": total, "tokens": tokens, "source": "debank"}
    except Exception as e:
        logger.debug("debank err %s", e)
    return None

def fetch_from_coinglass(address: str) -> Optional[Dict[str, Any]]:
    """
    Use CoinGlass endpoints:
    - /api/exchange/assets -> exchange balances (wallet tokens)
    - /api/hyperliquid/position -> futures positions (if hyperliquid)
    Return a combined snapshot: usd_total, tokens map, positions list
    """
    if not COINGLASS_API_KEY:
        return None
    headers = {"CG-API-KEY": COINGLASS_API_KEY, "Accept": "application/json"}
    tokens = {}
    usd_total = 0.0
    positions = []
    try:
        # exchange assets
        url_ex = f"{COINGLASS_BASE}/api/exchange/assets"
        r = SESSION.get(url_ex, params={"wallet_address": address}, headers=headers, timeout=REQUEST_TIMEOUT)
        if r.ok:
            j = r.json()
            if j.get("code") in (0, "0") and j.get("data"):
                for item in j.get("data", []):
                    sym = item.get("symbol") or item.get("assets_name")
                    try:
                        bal_usd = float(item.get("balance_usd") or item.get("balance") or 0)
                    except Exception:
                        bal_usd = 0
                    if sym:
                        tokens[sym] = tokens.get(sym, 0.0) + bal_usd
                        usd_total += bal_usd
        # hyperliquid / futures positions
        url_hl = f"{COINGLASS_BASE}/api/hyperliquid/position"
        r2 = SESSION.get(url_hl, params={"user": address}, headers=headers, timeout=REQUEST_TIMEOUT)
        if r2.ok:
            j2 = r2.json()
            if j2.get("code") in (0, "0") and j2.get("data"):
                lst = j2["data"].get("list") or []
                for item in lst:
                    sym = item.get("symbol") or item.get("asset") or item.get("market")
                    try:
                        pos_val = float(item.get("position_value_usd") or item.get("notional") or 0)
                    except Exception:
                        pos_val = 0
                    side = "long" if float(item.get("position_size") or 0) > 0 else "short" if float(item.get("position_size") or 0) < 0 else "unknown"
                    if pos_val and abs(pos_val) >= MIN_POSITION_VALUE_USD:
                        positions.append({"symbol": sym, "size_usd": abs(pos_val), "side": side})
                        usd_total += abs(pos_val)
        if tokens or positions or usd_total:
            return {"address": address, "usd_total": usd_total, "tokens": tokens, "positions": positions, "source": "coinglass"}
    except Exception as e:
        logger.debug("coinglass err %s", e)
    return None

def fetch_from_hyperdash(address: str) -> Optional[Dict[str, Any]]:
    """
    Try to scrape HyperDash trader page to extract positions (best-effort).
    """
    try:
        url = f"{HYPERDASH_BASE}/trader/{address}"
        r = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        if r.ok and r.text:
            # try to find JSON in __NEXT_DATA__ or window.__INITIAL_STATE__
            import re, json as _json
            m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>', r.text, re.S)
            if m:
                try:
                    data = _json.loads(m.group(1))
                    # navigate to trader positions if possible
                    trader = data.get("props", {}).get("pageProps", {}).get("trader")
                    if trader:
                        positions = []
                        raw_positions = trader.get("positions") or []
                        if isinstance(raw_positions, dict):
                            raw_positions = list(raw_positions.values())
                        for p in raw_positions:
                            try:
                                symbol = p.get("symbol") or p.get("asset") or p.get("market")
                                size_usd = float(p.get("notional") or p.get("sizeUsd") or p.get("size") or 0)
                                side = p.get("side") or ("long" if p.get("isLong") else "short" if p.get("isShort") else "")
                                if size_usd >= MIN_POSITION_VALUE_USD:
                                    positions.append({"symbol": symbol, "size_usd": size_usd, "side": side})
                            except Exception:
                                continue
                        if positions:
                            return {"address": address, "positions": positions, "source": "hyperdash"}
                except Exception:
                    pass
    except Exception as e:
        logger.debug("hyperdash err %s", e)
    return None

# ---------------- detection logic ----------------
def detect_and_build_snapshots(addr: str) -> Optional[Dict[str, Any]]:
    """
    Try multiple sources in priority order and return a unified snapshot:
    {
      "address": addr,
      "usd_total": float,
      "tokens": {SYMBOL: usd_value or amount_based_metric},
      "positions": [{symbol, size_usd, side}, ...],
      "source": "..."
    }
    """
    # Try CoinGlass (exchange + futures) first if available
    cg = fetch_from_coinglass(addr)
    if cg:
        return cg
    # Then DeBank
    db = fetch_from_debank(addr)
    if db:
        return db
    # Dexscreener (liquidity view)
    ds = fetch_from_dexscreener_addr(addr)
    if ds:
        return ds
    # HyperDash (trader positions)
    hd = fetch_from_hyperdash(addr)
    if hd:
        return hd
    return None

def compare_and_generate_events(addr: str, snap: Dict[str, Any]) -> List[str]:
    """
    Compare snap with previous state and generate human-readable event strings.
    """
    events: List[str] = []
    prev = get_wallet_state(addr)
    prev_tokens = prev.get("tokens", {}) or {}
    prev_positions = prev.get("positions", []) or []
    prev_total = float(prev.get("usd_total") or 0.0)

    now_tokens = snap.get("tokens", {}) or {}
    now_positions = snap.get("positions", []) or []
    now_total = float(snap.get("usd_total") or 0.0)

    # 1) New token detection (token present now but not before)
    for tok, val in now_tokens.items():
        if tok not in prev_tokens and (val or 0) >= MIN_POSITION_VALUE_USD:
            events.append(f"📥 New token detected: {tok} — approx ${val:.2f} (source: {snap.get('source')})")

    # 2) Buy / Sell detection via per-token delta
    # We interpret increase in USD value as buy, decrease as sell (best-effort)
    for tok in set(list(prev_tokens.keys()) + list(now_tokens.keys())):
        prev_val = float(prev_tokens.get(tok) or 0)
        now_val = float(now_tokens.get(tok) or 0)
        # ignore tiny noise
        if abs(now_val - prev_val) < max(1.0, 0.02 * max(prev_val, now_val)):
            continue
        if now_val > prev_val:
            # buy (or received)
            events.append(f"🟢 BUY detected: {tok} increased ${prev_val:.2f} → ${now_val:.2f} (wallet: {addr}, src: {snap.get('source')})")
        else:
            # sell (or transferred out)
            # if now_val is near zero and prev_val was significant -> token sold/removed
            events.append(f"🔴 SELL detected: {tok} decreased ${prev_val:.2f} → ${now_val:.2f} (wallet: {addr}, src: {snap.get('source')})")

    # 3) Balance change overall
    if abs(now_total - prev_total) >= max(5.0, 0.05 * max(1.0, prev_total)):
        events.append(f"ℹ️ Balance change: ${prev_total:.2f} → ${now_total:.2f} (diff ${now_total - prev_total:+.2f}) (src: {snap.get('source')})")

    # 4) Futures positions: open/close/size change/direction change
    # Build map of prev positions by (symbol, side)
    prev_map = { (p.get("symbol"), (p.get("side") or "").lower()): p for p in prev_positions }
    for p in now_positions:
        sym = p.get("symbol")
        side = (p.get("side") or "").lower()
        size = float(p.get("size_usd") or 0)
        key = (sym, side)
        if key not in prev_map and size >= MIN_POSITION_VALUE_USD:
            events.append(f"⚡ Position OPEN: {sym} {side.upper()} ${size:.0f} (src: {snap.get('source')})")
        else:
            prev_size = float(prev_map.get(key, {}).get("size_usd") or 0)
            if size > prev_size * 1.05 and size >= MIN_POSITION_VALUE_USD:
                events.append(f"⚡ Position INCREASE: {sym} {side.upper()} ${prev_size:.0f} → ${size:.0f} (src: {snap.get('source')})")

    # detect closed positions: existed before but not present now (by symbol+side)
    for pp in prev_positions:
        key = (pp.get("symbol"), (pp.get("side") or "").lower())
        found = False
        for p in now_positions:
            if p.get("symbol") == key[0] and (p.get("side") or "").lower() == key[1]:
                found = True
                break
        if not found:
            events.append(f"⚡ Position CLOSED: {key[0]} {key[1].upper()} (was ${pp.get('size_usd'):.0f}) (src: {snap.get('source')})")

    return events

# ---------------- sending signals ----------------
def send_signal_to_chats(text: str):
    if not authorized_chats:
        logger.info("No authorized chats set; signal would be: %s", text)
        return
    for cid in list(authorized_chats):
        try:
            bot.send_message(chat_id=cid, text=text, parse_mode="Markdown")
        except TelegramError as e:
            logger.error("send to %s failed: %s", cid, e)

# ---------------- poll & process ----------------
def process_wallet(addr: str):
    try:
        snap = detect_and_build_snapshots(addr)
        if not snap:
            logger.debug("No data for %s", addr)
            return
        events = compare_and_generate_events(addr, snap)
        # update state always (so changes are tracked next time)
        new_state = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "usd_total": float(snap.get("usd_total") or 0.0),
            "tokens": snap.get("tokens", {}),
            "positions": snap.get("positions", [])
        }
        set_wallet_state(addr, new_state)
        if events:
            ts = datetime.now(timezone.utc).astimezone().isoformat()
            for e in events:
                text = f"⚡ سیگنال — کیف‌پول: `{addr}`\n{e}\n_source: {snap.get('source','unknown')}\n_time: {ts}_"
                logger.info("SIGNAL: %s", text)
                send_signal_to_chats(text)
    except Exception as ex:
        logger.error("process_wallet %s error: %s", addr, ex)

def poller_thread():
    logger.info("Poller started. Interval %s seconds", POLL_INTERVAL)
    while True:
        wallets = load_wallets()
        if not wallets:
            logger.info("Polling wallets... count=0")
        for w in wallets:
            try:
                process_wallet(w)
            except Exception as e:
                logger.error("poll error %s: %s", w, e)
        time.sleep(POLL_INTERVAL)

# ---------------- start ----------------
def main():
    # start poller
    threading.Thread(target=poller_thread, daemon=True).start()
    logger.info("Starting bot polling ...")
    # start telegram polling (blocking)
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
