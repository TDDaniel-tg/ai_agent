from telethon import TelegramClient
from telethon.sessions import StringSession
import asyncio

API_ID = 33602848
API_HASH = "cb92faf81dc604d584dff18e9a12a4e8"

async def main():
    phone = input("Phone (+996772362646): ") or "+996772362646"
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.start(phone=phone)
    me = await client.get_me()
    print(f"\n✅ Logged in as: {me.phone}")
    session_string = client.session.save()
    print(f"\n🔑 Session string (copy this):\n{session_string}")
    await client.disconnect()

asyncio.run(main())
