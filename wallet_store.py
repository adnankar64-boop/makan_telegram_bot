import sqlite3

conn = sqlite3.connect("wallets.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS wallets (
    address TEXT PRIMARY KEY,
    label TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")

conn.commit()


def add_wallet(address, label=""):
    cursor.execute(
        "INSERT OR IGNORE INTO wallets VALUES (?, ?)",
        (address, label)
    )
    conn.commit()


def remove_wallet(address):
    cursor.execute("DELETE FROM wallets WHERE address = ?", (address,))
    conn.commit()


def list_wallets():
    cursor.execute("SELECT * FROM wallets")
    return cursor.fetchall()


def set_threshold(value):
    cursor.execute(
        "INSERT OR REPLACE INTO settings VALUES ('threshold', ?)",
        (str(value),)
    )
    conn.commit()


def get_threshold():
    cursor.execute(
        "SELECT value FROM settings WHERE key='threshold'"
    )
    row = cursor.fetchone()
    return int(row[0]) if row else 50000
