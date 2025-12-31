import requests
import time

SOLANA_RPC = "https://api.mainnet-beta.solana.com"

last_seen_signature = {}

def get_signatures(address, limit=5):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [address, {"limit": limit}]
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


def check_wallet(address):
    sigs = get_signatures(address)
    if not sigs:
        return None

    latest_sig = sigs[0]["signature"]

    if last_seen_signature.get(address) == latest_sig:
        return None

    last_seen_signature[address] = latest_sig
    tx = get_transaction(latest_sig)
    return tx
