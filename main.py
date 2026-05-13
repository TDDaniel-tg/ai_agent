import asyncio
import logging
import os
import signal

from config import config
from context import ctx
from db import init_db
from monitor import MonitorManager
from bot import create_bot, on_vacancy_found
from scheduler import start_scheduler, init_scheduler
from server import start_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("Starting Freelance Agent Bot...")

    os.makedirs(config.session_dir, exist_ok=True)

    init_db()
    logger.info("Database initialized")

    await start_server()
    logger.info("Web server started")

    bot_app = create_bot()
    ctx.application = bot_app
    ctx.bot = bot_app.bot

    monitor_mgr = MonitorManager(on_vacancy=on_vacancy_found)
    ctx.monitor_manager = monitor_mgr

    init_scheduler(bot_app.bot, ctx.send_to_admin)
    start_scheduler()

    await monitor_mgr.start_all()
    logger.info(f"Monitoring {len(monitor_mgr.monitors)} accounts")

    ping_url = config.ping_url or os.getenv("RENDER_EXTERNAL_URL", "")
    if ping_url:
        from scheduler import scheduler
        from apscheduler.triggers.interval import IntervalTrigger

        async def keepalive_ping():
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    await session.get(f"{ping_url}/ping", timeout=10)
                    logger.debug("Keepalive ping sent")
            except Exception as e:
                logger.warning(f"Keepalive ping failed: {e}")

        scheduler.add_job(
            keepalive_ping,
            IntervalTrigger(minutes=10),
            id="keepalive_ping",
            replace_existing=True,
        )
        logger.info(f"Keepalive ping configured for {ping_url}")

    await bot_app.initialize()
    await bot_app.start()
    await bot_app.updater.start_polling(allowed_updates=["message", "callback_query"])
    logger.info("Bot started polling")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)
    await stop_event.wait()

    logger.info("Shutting down...")
    await monitor_mgr.stop_all()
    await bot_app.updater.stop()
    await bot_app.stop()
    await bot_app.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
