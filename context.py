from typing import Callable, Optional


class BotContext:
    def __init__(self):
        self.bot = None
        self.application = None
        self.monitor_manager = None
        self._send_to_admin: Optional[Callable] = None

    def set_send_to_admin(self, func: Callable):
        self._send_to_admin = func

    async def send_to_admin(self, text: str):
        if self._send_to_admin:
            await self._send_to_admin(text)


ctx = BotContext()
