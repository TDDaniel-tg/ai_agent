import asyncio
import re
from typing import Callable, Optional

from telethon import TelegramClient, events
from telethon.tl.types import Message

from config import config
from db import get_channels, get_accounts, get_setting, save_vacancy, add_channel
from ai_client import analyze_vacancy, classify_channel


class AccountMonitor:
    def __init__(self, account: dict, on_vacancy: Callable):
        self.account = account
        self.on_vacancy = on_vacancy
        self.client: Optional[TelegramClient] = None
        self._running = False
        self._handlers = []

    async def start(self):
        self._running = True
        acc = self.account
        self.client = TelegramClient(
            session=f"{config.session_dir}/{acc['phone']}",
            api_id=acc["api_id"],
            api_hash=acc["api_hash"],
        )
        await self.client.start()
        me = await self.client.get_me()
        print(f"[Monitor] Account {me.phone or acc['phone']} connected")

        channels = get_channels(acc["id"])
        for ch in channels:
            await self._monitor_channel(ch["channel_link"])

    async def _monitor_channel(self, channel_link: str):
        try:
            entity = await self.client.get_input_entity(channel_link)
            if not entity:
                print(f"[Monitor] Cannot resolve {channel_link}")
                return

            @self.client.on(events.NewMessage(chats=entity))
            async def handler(event):
                await self._handle_message(event.message)

            self._handlers.append(handler)
        except Exception as e:
            print(f"[Monitor] Error monitoring {channel_link}: {e}")

    async def _handle_message(self, message: Message):
        text = message.text or message.caption or ""
        if not text:
            return

        is_vacancy, score, summary, budget = await analyze_vacancy(text)
        if not is_vacancy:
            return

        min_budget_str = get_setting("min_budget")
        if min_budget_str and budget:
            try:
                min_budget = float(min_budget_str)
                amounts = [float(x) for x in re.findall(r'[\d,.]+', budget.replace(",", "")) if float(x) > 0]
                if amounts and max(amounts) < min_budget:
                    print(f"[Monitor] Skipping low-budget vacancy: {budget}")
                    return
            except ValueError:
                pass

        vid = save_vacancy(
            account_id=self.account["id"],
            channel_title=message.chat.title if hasattr(message.chat, "title") else "",
            message_id=message.id,
            sender_id=message.sender_id,
            text=text,
            score=score,
            summary=summary,
            budget_info=budget,
        )
        if vid:
            print(f"[Monitor] New vacancy #{vid} (score={score:.2f}) from {getattr(message.chat, 'title', 'unknown')}")
            await self.on_vacancy(vid, self.account)

    async def stop(self):
        self._running = False
        for h in self._handlers:
            self.client.remove_event_handler(h)
        if self.client:
            await self.client.disconnect()

    async def scan_dialogs(self, min_score: float = 0.3) -> list:
        if not self.client:
            return []
        dialogs = await self.client.get_dialogs(limit=200)
        results = []
        for dlg in dialogs:
            if not dlg.is_channel:
                continue
            title = dlg.title or ""
            about = getattr(dlg.entity, "about", "") if hasattr(dlg.entity, "about") else ""
            is_job, score, category = await classify_channel(title, about)
            if is_job and score >= min_score:
                results.append({
                    "id": dlg.id,
                    "title": title,
                    "username": dlg.entity.username if hasattr(dlg.entity, "username") else "",
                    "score": score,
                    "category": category,
                })
                print(f"[Scan] {title} — {category} ({score:.2f})")
        results.sort(key=lambda r: r["score"], reverse=True)
        return results

    async def send_message(self, chat_id, text):
        if self.client:
            await self.client.send_message(chat_id, text)

    async def get_entity(self, chat_id):
        if self.client:
            return await self.client.get_entity(chat_id)


class MonitorManager:
    def __init__(self, on_vacancy: Callable):
        self.on_vacancy = on_vacancy
        self.monitors: dict[int, AccountMonitor] = {}

    async def start_all(self):
        accounts = get_accounts()
        for acc in accounts:
            if acc["is_active"]:
                await self.add_monitor(acc)

    async def add_monitor(self, account: dict):
        if len(self.monitors) >= config.max_accounts:
            print(f"[Monitor] Max {config.max_accounts} accounts reached")
            return
        monitor = AccountMonitor(account, self.on_vacancy)
        self.monitors[account["id"]] = monitor
        asyncio.create_task(monitor.start())

    async def remove_monitor(self, account_id: int):
        if account_id in self.monitors:
            await self.monitors[account_id].stop()
            del self.monitors[account_id]

    async def restart_all(self):
        await self.stop_all()
        await self.start_all()

    async def stop_all(self):
        for m in self.monitors.values():
            await m.stop()
        self.monitors.clear()

    def get_monitor(self, account_id: int) -> Optional[AccountMonitor]:
        return self.monitors.get(account_id)

    async def send_via_account(self, account_id: int, chat_id, text: str) -> bool:
        monitor = self.monitors.get(account_id)
        if monitor:
            await monitor.send_message(chat_id, text)
            return True
        return False
