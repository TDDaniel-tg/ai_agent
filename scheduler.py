from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import config
from context import ctx
from db import get_vacancies_for_followup, get_setting, mark_followup_sent
from ai_client import generate_followup


scheduler = AsyncIOScheduler()


async def check_followups():
    days_str = get_setting("followup_days") or str(config.followup_days)
    try:
        days = int(days_str)
    except ValueError:
        days = config.followup_days

    vacancies = get_vacancies_for_followup(days)
    for v in vacancies:
        previous = ""
        if v["followup_sent"] > 0:
            previous = f"Previous follow-ups: {v['followup_sent']} times"

        followup_text = await generate_followup(v["text"], previous)
        if not followup_text:
            continue

        msg = (
            f"📨 Follow-up for vacancy #{v['id']}\n"
            f"Channel: {v['channel_title']}\n"
            f"Status: {v['status']}\n\n"
            f"Generated follow-up:\n{followup_text}"
        )
        await ctx.send_to_admin(msg)

        if v["sender_id"] and ctx.monitor_manager:
            sent = await ctx.monitor_manager.send_via_account(
                v["account_id"], v["sender_id"], followup_text
            )
            if sent:
                mark_followup_sent(v["id"])


def start_scheduler():
    scheduler.add_job(
        check_followups,
        IntervalTrigger(hours=12),
        id="check_followups",
        replace_existing=True,
    )
    scheduler.start()
    print("[Scheduler] Started")


def init_scheduler(_bot, _send_func):
    pass
