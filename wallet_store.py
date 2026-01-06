import json
import os
from threading import Lock

FILE_PATH = "wallets.json"
_lock = Lock()


def _load():
    if not os.path.exists(FILE_PATH):
        return []

    try:
        with open(FILE_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return []


def _save(wallets):
    with open(FILE_PATH, "w") as f:
        json.dump(wallets, f, indent=2)


def add_wallet(address: str) -> bool:
    with _lock:
        wallets = _load()
        if address in wallets:
            return False
        wallets.append(address)
        _save(wallets)
        return True


def remove_wallet(address: str) -> bool:
    with _lock:
        wallets = _load()
        if address not in wallets:
            return False
        wallets.remove(address)
        _save(wallets)
        return True


def get_wallets():
    return _load()
