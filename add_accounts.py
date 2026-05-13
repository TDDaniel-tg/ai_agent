import asyncio
import os
import sqlite3

from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.getenv("API_ID") or input("Default API ID: ") or "0")
API_HASH = os.getenv("API_HASH") or input("Default API Hash: ") or ""
DB_PATH = os.getenv("DB_PATH", "freelance_bot.db")


def save_account(phone, session_string, api_id, api_hash):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        conn.execute(
            "INSERT INTO accounts (phone, session_string, api_id, api_hash) VALUES (?, ?, ?, ?)",
            (phone, session_string, api_id, api_hash),
        )
        conn.commit()
        print(f"  ✅ Saved to DB: {phone}")
    except Exception as e:
        print(f"  ❌ DB error: {e}")
    finally:
        conn.close()


async def add_one(phone, api_id, api_hash):
    print(f"\n{'='*50}")
    print(f"📱 Adding: {phone}")
    print(f"{'='*50}")
    client = TelegramClient(StringSession(), api_id, api_hash)
    try:
        await client.start(phone=phone)
        me = await client.get_me()
        print(f"  ✅ Logged in as: {me.first_name or me.phone}")
        session_str = client.session.save()
        save_account(phone, session_str, api_id, api_hash)
        await client.disconnect()
        return True
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False


async def main():
    print("╔══════════════════════════════════════╗")
    print("║   Batch Account Adder for TG Bot     ║")
    print("╚══════════════════════════════════════╝")

    api_id = API_ID
    api_hash = API_HASH

    if not api_id or not api_hash:
        api_id = int(input("\nAPI ID (default 33602848): ") or "33602848")
        api_hash = input("API Hash (default cb92faf81dc604d584dff18e9a12a4e8): ") or "cb92faf81dc604d584dff18e9a12a4e8"

    phones_input = input("\nPhone numbers (space-separated, e.g. +996772362646 +996555123456):\n> ")
    phones = phones_input.strip().split()

    if not phones:
        print("No phones provided.")
        return

    print(f"\nWill add {len(phones)} account(s). Let's go!\n")

    for i, phone in enumerate(phones, 1):
        print(f"\n--- Account {i}/{len(phones)} ---")
        success = await add_one(phone.strip(), api_id, api_hash)
        if not success:
            print("  Skipping to next...")

    print(f"\n{'='*50}")
    print(f"✅ Done! Added {len(phones)} accounts.")
    print("Restart the bot to apply: python3 main.py")


if __name__ == "__main__":
    asyncio.run(main())
