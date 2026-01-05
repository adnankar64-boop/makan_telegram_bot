def get_wallets(context):
    return context.bot_data.setdefault("wallets", [])

def add_wallet(context, address: str):
    wallets = get_wallets(context)
    if address not in wallets:
        wallets.append(address)
        return True
    return False

def remove_wallet(context, address: str):
    wallets = get_wallets(context)
    if address in wallets:
        wallets.remove(address)
        return True
    return False
