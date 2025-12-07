# فایل: hyperdash_telegram_bot_mtproto_coinglass.py
# جایگزین کامل برای نسخه‌ی شما — سازگار با python-telegram-bot v20 (ApplicationBuilder)

import os
import json
import time
import logging
import threading
import requests
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ---------------- logging ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("signal_bot")

# ---------------- config (ENV) ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
COINGLASS_API_KEY = os.getenv("COINGLASS_API_KEY", "")  # مورد نیاز برای برخی endpoint های CoinGlass
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))  # فرکانس polling به ثانیه
DATA_DIR = os.getenv("DATA_DIR", "data")
os.makedirs(DATA_DIR, exist_ok=True)

WALLETS_FILE = os.path.join(DATA_DIR, "wallets.json")
STATES_FILE = os.path.join(DATA_DIR, "states.json")
AUTHORIZED_FILE = os.path.join(DATA_DIR, "authorized.json")

REQUEST_TIMEOUT = 12
COINGLASS_BASE = "https://open-api-v4.coinglass.com"  # docs: coinglass open api
HYPERLIQUID_BASE = "https://app.hyperliquid.xyz"      # docs exist for hyperliquid API
HYPERDASH_BASE = "https://hyperdash.info"             # hyperdash site (may need scraping)

# ---------------- persistence helpers ----------------
def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

wallets: List[str] = load_json(WALLETS_FILE, [])
states: Dict[str, Any] = load_json(STATES_FILE, {})
authorized_chats = set(load_json(AUTHORIZED_FILE, []))

def persist_wallets():
    save_json(WALLETS_FILE, wallets)

def persist_states():
    save_json(STATES_FILE, states)

def persist_auth():
    save_json(AUTHORIZED_FILE, list(authorized_chats))

# ---------------- http session ----------------
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "SignalBot/1.0"})

# ---------------- send message ----------------
def send_message(chat_id: int, text: str):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        SESSION.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})
    except Exception as e:
        logger.exception("send_message error: %s", e)

# ---------------- fetchers ----------------
# 1) CoinGlass: exchange assets (wallet holdings) and hyperliquid position endpoint
def fetch_coinglass(address: str) -> Optional[Dict[str, Any]]:
    if not COINGLASS_API_KEY:
        return None
    headers = {"CG-API-KEY": COINGLASS_API_KEY}
    try:
        # attempt exchange assets (holds USD balances per token)
        r = SESSION.get(f"{COINGLASS_BASE}/api/exchange/assets", params={"wallet_address": address}, headers=headers, timeout=REQUEST_TIMEOUT)
        if r.ok:
            j = r.json()
            tokens = {}
            usd_total = 0.0
            for item in j.get("data", []):
                sym = item.get("symbol") or item.get("coin")
                v = float(item.get("balance_usd") or 0)
                if sym:
                    tokens[sym] = tokens.get(sym, 0.0) + v
                    usd_total += v

            # try hyperliquid positions (if available on plan)
            positions = []
            try:
                r2 = SESSION.get(f"{COINGLASS_BASE}/api/hyperliquid/position", params={"user": address}, headers=headers, timeout=REQUEST_TIMEOUT)
                if r2.ok:
                    j2 = r2.json()
                    for it in (j2.get("data") or {}).get("list", []):
                        sym = it.get("symbol")
                        size = float(it.get("position_value_usd") or 0)
                        pos_size = float(it.get("position_size") or 0)
                        side = "long" if pos_size > 0 else "short" if pos_size < 0 else ""
                        if abs(size) > 0:
                            positions.append({"symbol": sym, "size_usd": abs(size), "side": side})
                            usd_total += abs(size)
            except Exception:
                logger.debug("coinglass hyperliquid positions failed for %s", address)

            return {"address": address, "tokens": tokens, "positions": positions, "usd_total": usd_total, "source": "coinglass"}
    except Exception:
        logger.debug("coinglass fetch failed for %s", address)
    return None

# 2) Hyperliquid leaderboard / positions (public API)
def fetch_hyperliquid(address: str) -> Optional[Dict[str, Any]]:
    """
    Try hyperliquid public API for positions or leaderboard entries.
    If the public API requires auth, this may need an API key — fallback: no data.
    """
    try:
        # example: Hyperliquid docs expose `/API` endpoints; here we attempt a leaderboard user lookup
        r = SESSION.get(f"{HYPERLIQUID_BASE}/API/v1/leaderboard?address={address}", timeout=REQUEST_TIMEOUT)
        if r.ok:
            j = r.json()
            # NOTE: adjust fields to actual response
            positions = []
            usd_total = 0.0
            for p in j.get("positions", []) if isinstance(j, dict) else []:
                sym = p.get("symbol")
                size = float(p.get("notional") or 0)
                side = "long" if p.get("isLong") else "short"
                if abs(size) >= 1:
                    positions.append({"symbol": sym, "size_usd": size, "side": side})
                    usd_total += abs(size)
            if positions:
                return {"address": address, "positions": positions, "tokens": {}, "usd_total": usd_total, "source": "hyperliquid"}
    except Exception:
        logger.debug("hyperliquid fetch failed for %s", address)
    return None

# 3) HyperDash (scrape trader page / trader-analysis)
def fetch_hyperdash(address: str) -> Optional[Dict[str, Any]]:
    """
    HyperDash doesn't always expose a documented public API; we attempt to fetch trader analysis page
    and extract JSON for positions or recent activity. This is fragile: prefer an official API or webhook.
    """
    try:
        r = SESSION.get(f"{HYPERDASH_BASE}/trader/{address}", timeout=REQUEST_TIMEOUT)
        if not r.ok:
            return None
        text = r.text
        # try to find a JSON snippet containing "positions"
        import re, json as _json
        m = re.search(r'"positions":(\[.*?\])', text, re.S)
        if m:
            arr = _json.loads(m.group(1))
            positions = []
            usd_total = 0.0
            for p in arr:
                sym = p.get("symbol") or p.get("market")
                size = float(p.get("notional") or p.get("size_usd") or 0)
                side = "long" if p.get("isLong") or p.get("side") == "long" else "short"
                if size > 0:
                    positions.append({"symbol": sym, "size_usd": size, "side": side})
                    usd_total += abs(size)
            if positions:
                return {"address": address, "positions": positions, "tokens": {}, "usd_total": usd_total, "source": "hyperdash"}
    except Exception:
        logger.debug("hyperdash fetch failed for %s", address)
    return None

# ---------------- Snapshot builder ----------------
def detect_and_build_snapshots(addr: str):
    """
    Try multiple fetchers. Return a normalized snapshot with keys:
    {address, usd_total, tokens: {SYM:usd}, positions: [{symbol, size_usd, side}], source}
    """
    for f in (fetch_coinglass, fetch_hyperliquid, fetch_hyperdash):
        try:
            r = f(addr)
            if r:
                r.setdefault("tokens", {})
                r.setdefault("positions", [])
                r.setdefault("usd_total", float(r.get("usd_total") or 0.0))
                return r
        except Exception:
            logger.debug("fetcher %s failed for %s", getattr(f, "__name__", str(f)), addr)
    return None

# ---------------- compare & generate events ----------------
def compare_and_generate_events(addr: str, snap: Dict[str, Any]):
    events = []
    prev = states.get(addr.lower(), {"tokens": {}, "positions": [], "usd_total": 0.0})

    prev_tokens = prev.get("tokens", {})
    now_tokens = snap.get("tokens", {})

    prev_positions = prev.get("positions", [])
    now_positions = snap.get("positions", [])

    prev_total = float(prev.get("usd_total") or 0)
    now_total = float(snap.get("usd_total") or 0)

    # tokens: new or changes (BUY/SELL by usd value)
    for tok in set(prev_tokens) | set(now_tokens):
        pv = float(prev_tokens.get(tok, 0))
        nv = float(now_tokens.get(tok, 0))
        if tok not in prev_tokens and nv > 0:
            events.append(f"📥 New token {tok}: ${nv:.2f}")
        elif tok in prev_tokens and nv == 0:
            events.append(f"🔴 Token removed {tok}: ${pv:.2f} -> 0")
        elif abs(nv - pv) > max(1.0, pv * 0.02):  # threshold
            if nv > pv:
                events.append(f"🟢 BUY {tok}: ${pv:.2f} -> ${nv:.2f}")
            else:
                events.append(f"🔴 SELL {tok}: ${pv:.2f} -> ${nv:.2f}")

    # balance change
    if abs(now_total - prev_total) > 5:
        events.append(f"ℹ️ Balance: ${prev_total:.2f} -> ${now_total:.2f}")

    # positions: open / increase / close
    prev_map = {(p.get("symbol"), p.get("side")): p for p in prev_positions}
    now_map = {(p.get("symbol"), p.get("side")): p for p in now_positions}

    # opened or increased
    for key, p in now_map.items():
        if key not in prev_map:
            events.append(f"⚡ OPEN {p.get('symbol')} {p.get('side')} ${p.get('size_usd',0):.0f}")
        else:
            old = float(prev_map[key].get("size_usd", 0))
            new = float(p.get("size_usd", 0))
            if new > old * 1.05:
                events.append(f"⚡ INCREASE {p.get('symbol')} {p.get('side')} ${old:.0f} -> ${new:.0f}")

    # closed
    for key, p in prev_map.items():
        if key not in now_map:
            events.append(f"⚡ CLOSE {p.get('symbol')} {p.get('side')} (${p.get('size_usd',0):.0f})")

    return events

# ---------------- process wallet and send signals ----------------
def process_wallet_sync(addr: str):
    snap = detect_and_build_snapshots(addr)
    if not snap:
        return
    events = compare_and_generate_events(addr, snap)

    # update state
    states[addr.lower()] = {
        "tokens": snap.get("tokens", {}),
        "positions": snap.get("positions", []),
        "usd_total": float(snap.get("usd_total", 0.0)),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    persist_states()

    # send
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for e in events:
        text = f"⚡ سیگنال — `{addr}`\n{e}\n⏱ {ts}"
        for cid in list(authorized_chats):
            send_message(cid, text)

# ---------------- poller ----------------
def poller_thread():
    logger.info("Poller started, interval %s sec", POLL_INTERVAL)
    while True:
        for w in wallets:
            try:
                process_wallet_sync(w)
            except Exception:
                logger.exception("poll error %s", w)
        time.sleep(POLL_INTERVAL)

# ---------------- Telegram handlers (async) ----------------
async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    authorized_chats.add(cid); persist_auth()

    if not context.args:
        await update.message.reply_text("Usage: /add <wallet_address>")
        return
    addr = context.args[0].strip().lower()
    if addr not in wallets:
        wallets.append(addr); persist_wallets()
    await update.message.reply_text(f"آدرس {addr} اضافه شد ✅")

async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    authorized_chats.add(cid); persist_auth()

    if not context.args:
        await update.message.reply_text("Usage: /remove <wallet_address>")
        return
    addr = context.args[0].strip().lower()
    if addr in wallets:
        wallets.remove(addr); persist_wallets()
        await update.message.reply_text(f"آدرس {addr} حذف شد ✅")
    else:
        await update.message.reply_text("آدرس یافت نشد.")

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    authorized_chats.add(cid); persist_auth()
    if wallets:
        await update.message.reply_text("فهرست کیف‌پول‌ها:\n" + "\n".join(wallets))
    else:
        await update.message.reply_text("هیچ آدرسی ثبت نشده.")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    authorized_chats.add(cid); persist_auth()
    await update.message.reply_text(f"Bot running. Poll interval: {POLL_INTERVAL}s. Wallets: {len(wallets)}")

# ---------------- start bot ----------------
def main():
    # start poller
    threading.Thread(target=poller_thread, daemon=True).start()

    # start telegram app
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("status", cmd_status))

    logger.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
