import json
import os

WALLET_FILE = "wallets.json"

def _load():
    if not os.path.exists(WALLET_FILE):
        return []
    with open(WALLET_FILE, "r") as f:
        return json.load(f)

def _save(data):
    with open(WALLET_FILE, "w") as f:
        json.dump(data, f, indent=2)

def add_wallet(address: str):
    wallets = _load()
    if address not in wallets:
        wallets.append(address)
        _save(wallets)
        return True
    return False

def remove_wallet(address: str):
    wallets = _load()
    if address in wallets:
        wallets.remove(address)
        _save(wallets)
        return True
    return False

def list_wallets():
    return _load()
