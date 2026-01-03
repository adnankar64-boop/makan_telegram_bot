import json
import os

FILE = "wallets.json"

def load():
    if not os.path.exists(FILE):
        return []
    with open(FILE, "r") as f:
        return json.load(f)

def save(data):
    with open(FILE, "w") as f:
        json.dump(data, f)

def add_wallet(w):
    data = load()
    if w not in data:
        data.append(w)
        save(data)

def remove_wallet(w):
    data = load()
    if w in data:
        data.remove(w)
        save(data)

def get_wallets():
    return load()
