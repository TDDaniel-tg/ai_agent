from aiohttp import web

from config import config


async def handle_ping(request):
    return web.Response(text="pong", content_type="text/plain")


async def handle_health(request):
    return web.json_response({"status": "ok", "service": "freelance-agent-bot"})


async def start_server():
    app = web.Application()
    app.router.add_get("/ping", handle_ping)
    app.router.add_get("/health", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.port)
    await site.start()
    print(f"[Server] Listening on 0.0.0.0:{config.port}")
    return runner
