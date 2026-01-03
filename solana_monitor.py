import asyncio
import time
import requests

SOLANA_RPC = "https://api.mainnet-beta.solana.com"
CHECK_INTERVAL = 30  # ثانیه
MIN_SOL = 50  # فیلتر نهنگ (50 SOL)

# ذخیره آخرین امضا
last_signatures = {}

def get_signatures(address):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [address, {"limit": 5}]
    }
    r = requests.post(SOLANA_RPC, json=payload, timeout=10)
    return r.json().get("result", [])

def get_transaction(signature):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [signature, {"encoding": "jsonParsed"}]
    }
    r = requests.post(SOLANA_RPC, json=payload, timeout=10)
    return r.json().get("result")

async def monitor(wallets, bot, chat_id):
    global last_signatures

    while True:
        for wallet in wallets():
            try:
                sigs = get_signatures(wallet)
                if not sigs:
                    continue

                latest_sig = sigs[0]["signature"]

                if last_signatures.get(wallet) == latest_sig:
                    continue

                last_signatures[wallet] = latest_sig
                tx = get_transaction(latest_sig)
                if not tx:
                    continue

                pre = tx["meta"]["preBalances"][0]
                post = tx["meta"]["postBalances"][0]
                diff = (pre - post) / 1e9

                if diff >= MIN_SOL:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"🐋 **Whale Alert (Solana)**\n\n"
                            f"Wallet:\n`{wallet}`\n\n"
                            f"Amount: {diff:.2f} SOL\n\n"
                            f"🔗 Solscan:\n"
                            f"https://solscan.io/tx/{latest_sig}"
                        ),
                        parse_mode="Markdown"
                    )

            except Exception as e:
                print("Monitor error:", e)

        await asyncio.sleep(CHECK_INTERVAL)
