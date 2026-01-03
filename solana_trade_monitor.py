import asyncio
import requests

SOLANA_RPC = "https://api.mainnet-beta.solana.com"
CHECK_INTERVAL = 30
MIN_SOL = 1  # برای تست کم گذاشتم

last_signatures = {}

def rpc_call(method, params):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }
    r = requests.post(SOLANA_RPC, json=payload, timeout=10)
    return r.json().get("result")

def get_signatures(address):
    return rpc_call(
        "getSignaturesForAddress",
        [address, {"limit": 5}]
    ) or []

def get_transaction(sig):
    return rpc_call(
        "getTransaction",
        [sig, {"encoding": "jsonParsed"}]
    )

async def monitor(wallets, bot, chat_id):
    while True:
        for wallet in wallets():
            try:
                sigs = get_signatures(wallet)
                if not sigs:
                    continue

                sig = sigs[0]["signature"]
                if last_signatures.get(wallet) == sig:
                    continue

                last_signatures[wallet] = sig
                tx = get_transaction(sig)
                if not tx or not tx.get("meta"):
                    continue

                meta = tx["meta"]

                sol_change = (
                    meta["preBalances"][0] - meta["postBalances"][0]
                ) / 1e9

                if abs(sol_change) < MIN_SOL:
                    continue

                pre_tokens = {
                    t["mint"]: float(t["uiTokenAmount"]["uiAmount"] or 0)
                    for t in meta.get("preTokenBalances", [])
                }

                post_tokens = {
                    t["mint"]: float(t["uiTokenAmount"]["uiAmount"] or 0)
                    for t in meta.get("postTokenBalances", [])
                }

                for mint, post_amt in post_tokens.items():
                    pre_amt = pre_tokens.get(mint, 0)
                    diff = post_amt - pre_amt

                    if diff == 0:
                        continue

                    if sol_change > 0 and diff < 0:
                        action = "🔴 SELL"
                    elif sol_change < 0 and diff > 0:
                        action = "🟢 BUY"
                    else:
                        continue

                    text = (
                        f"{action} **Solana Trade**\n\n"
                        f"Wallet:\n`{wallet}`\n\n"
                        f"Token Mint:\n`{mint}`\n"
                        f"Token Amount: {abs(diff):,.2f}\n"
                        f"SOL Change: {abs(sol_change):.2f} SOL\n\n"
                        f"🔗 Links:\n"
                        f"Solscan: https://solscan.io/tx/{sig}\n"
                        f"GMGN: https://gmgn.ai/sol/token/{mint}\n"
                        f"HyperDash: https://hyperdash.info/solana/token/{mint}"
                    )

                    await bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode="Markdown"
                    )

            except Exception as e:
                print("Trade monitor error:", e)

        await asyncio.sleep(CHECK_INTERVAL)
