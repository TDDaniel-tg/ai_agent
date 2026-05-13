import html
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
)

from config import config
from context import ctx
from db import (
    get_accounts,
    add_account,
    delete_account,
    get_channels,
    add_channel,
    remove_channel,
    get_vacancies_by_status,
    get_vacancy,
    update_vacancy_status,
    get_setting,
    set_setting,
)
from ai_client import generate_response

# Conversation states
PHONE, API_ID, API_HASH, SESSION_STRING = range(4)
SETTING_KEY, SETTING_VALUE = range(10, 12)
CHANNEL_ACCOUNT, CHANNEL_LINK = range(20, 22)


def escape(text: str) -> str:
    return html.escape(text or "")


def _vacancy_keyboard(vid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Generate Response", callback_data=f"respond_{vid}"),
            InlineKeyboardButton("⏭ Skip", callback_data=f"skip_{vid}"),
        ],
        [
            InlineKeyboardButton("📋 Sent", callback_data=f"status_{vid}_sent"),
            InlineKeyboardButton("💬 Replied", callback_data=f"status_{vid}_replied"),
            InlineKeyboardButton("✅ Done", callback_data=f"status_{vid}_closed"),
        ],
    ])


async def _send_to_admin(text: str, keyboard: Optional[InlineKeyboardMarkup] = None):
    if config.admin_user_id:
        await ctx.bot.send_message(
            chat_id=config.admin_user_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )


ctx.set_send_to_admin(_send_to_admin)


async def start(update: Update, context):
    await update.message.reply_text(
        "🤖 <b>Freelance Agent Bot</b>\n\n"
        "I monitor Telegram channels for freelance vacancies and help you respond.\n\n"
        "<b>Commands:</b>\n"
        "/accounts — Manage your Telegram accounts\n"
        "/add_account — Add a new account\n"
        "/scan ACCOUNT_ID — Auto-scan account for job channels\n"
        "/channels — View/manage channel subscriptions\n"
        "/pipeline — View your lead pipeline\n"
        "/settings — View/change settings\n"
        "/mode — Toggle auto/manual mode\n"
        "/cancel — Cancel current operation",
        parse_mode=ParseMode.HTML,
    )


async def scan_cmd(update: Update, context):
    args = context.args
    if not args:
        accounts = get_accounts()
        if not accounts:
            await update.message.reply_text("No accounts. Add one with /add_account first.")
            return
        lines = ["<b>Usage:</b> /scan ACCOUNT_ID\n\n<b>Your accounts:</b>"]
        for a in accounts:
            lines.append(f"ID {a['id']}: {escape(a['phone'])}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        return

    try:
        account_id = int(args[0])
    except ValueError:
        await update.message.reply_text("Invalid account ID.")
        return

    if not ctx.monitor_manager:
        await update.message.reply_text("Monitor not initialized.")
        return

    monitor = ctx.monitor_manager.get_monitor(account_id)
    if not monitor:
        await update.message.reply_text(f"Account {account_id} is not active.")
        return

    await update.message.reply_text("🔍 Scanning dialogs for job channels... This may take a minute.")
    results = await monitor.scan_dialogs()

    if not results:
        await update.message.reply_text("No job-related channels found. Try increasing scan range or add channels manually.")
        return

    kb = []
    msg = f"<b>Found {len(results)} job/freelance channels:</b>\n\n"
    for r in results[:15]:
        link = f"@{r['username']}" if r["username"] else f"ID {r['id']}"
        msg += f"• {escape(r['title'])} ({link}) — {r['category']} ({r['score']:.0%})\n"
        kb.append([InlineKeyboardButton(
            f"📌 {r['title'][:30]}",
            callback_data=f"scan_sub_{account_id}_{r['id']}_{r['title']}"
        )])

    kb.append([InlineKeyboardButton("✅ Subscribe All", callback_data=f"scan_all_{account_id}")])
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def scan_subscribe_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    parts = data.split("_")
    # scan_sub_{account_id}_{channel_id}_{title}
    account_id = int(parts[2])
    channel_title = "_".join(parts[4:])
    channel_id = int(parts[3])
    link = channel_id
    # Try to get username from monitor
    monitor = ctx.monitor_manager.get_monitor(account_id) if ctx.monitor_manager else None
    if monitor and monitor.client:
        try:
            entity = await monitor.client.get_entity(channel_id)
            if hasattr(entity, "username") and entity.username:
                link = f"@{entity.username}"
        except Exception:
            pass

    add_channel(account_id, str(link), channel_title)
    await query.edit_message_reply_text(f"✅ Subscribed to {channel_title}")
    if ctx.monitor_manager:
        await ctx.monitor_manager.restart_all()


async def scan_subscribe_all_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    account_id = int(parts[2])

    if not ctx.monitor_manager:
        return

    monitor = ctx.monitor_manager.get_monitor(account_id)
    if not monitor:
        return

    await query.edit_message_reply_text("⏳ Subscribing to all channels...")
    results = await monitor.scan_dialogs()
    count = 0
    for r in results:
        try:
            link = f"@{r['username']}" if r["username"] else str(r["id"])
            add_channel(account_id, link, r["title"])
            count += 1
        except Exception:
            pass
    await query.edit_message_reply_text(f"✅ Subscribed to {count} channels!")
    if ctx.monitor_manager:
        await ctx.monitor_manager.restart_all()


async def accounts_cmd(update: Update, context):
    accounts = get_accounts()
    if not accounts:
        await update.message.reply_text("No accounts added. Use /add_account to add one.")
        return

    lines = ["<b>Your Accounts:</b>"]
    for a in accounts:
        status = "✅ Active" if a["is_active"] else "❌ Inactive"
        ch_count = len(get_channels(a["id"]))
        lines.append(
            f"ID {a['id']}: {escape(a['phone'])} — {status} — {ch_count} channels"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def add_account_start(update: Update, context):
    await update.message.reply_text(
        "Let's add a new account. First, send me the <b>phone number</b> in international format:\n"
        "Example: <code>+1234567890</code>",
        parse_mode=ParseMode.HTML,
    )
    return PHONE


async def add_account_phone(update: Update, context):
    context.user_data["acc_phone"] = update.message.text.strip()
    await update.message.reply_text("Now send me the <b>API ID</b> (from my.telegram.org):", parse_mode=ParseMode.HTML)
    return API_ID


async def add_account_api_id(update: Update, context):
    try:
        context.user_data["acc_api_id"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Invalid API ID. Must be a number. Try again or /cancel.")
        return API_ID
    await update.message.reply_text("Now send me the <b>API Hash</b>:", parse_mode=ParseMode.HTML)
    return API_HASH


async def add_account_api_hash(update: Update, context):
    context.user_data["acc_api_hash"] = update.message.text.strip()
    await update.message.reply_text(
        "Lastly, send me the <b>session string</b>.\n\n"
        "Generate it with Telethon:\n"
        "<code>from telethon import TelegramClient\n"
        "client = TelegramClient('session', API_ID, API_HASH)\n"
        "await client.start()\n"
        "print(client.session.save())</code>",
        parse_mode=ParseMode.HTML,
    )
    return SESSION_STRING


async def add_account_session(update: Update, context):
    phone = context.user_data["acc_phone"]
    api_id = context.user_data["acc_api_id"]
    api_hash = context.user_data["acc_api_hash"]
    session_string = update.message.text.strip()

    accounts = get_accounts()
    if len(accounts) >= config.max_accounts:
        await update.message.reply_text(f"Maximum {config.max_accounts} accounts reached.")
        return ConversationHandler.END

    try:
        add_account(phone, session_string, api_id, api_hash)
        await update.message.reply_text(f"✅ Account <code>{escape(phone)}</code> added!", parse_mode=ParseMode.HTML)
        if ctx.monitor_manager:
            accounts = get_accounts()
            for a in accounts:
                if a["phone"] == phone:
                    await ctx.monitor_manager.add_monitor(a)
                    break
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {escape(str(e))}", parse_mode=ParseMode.HTML)

    return ConversationHandler.END


async def cancel(update: Update, context):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


async def channels_cmd(update: Update, context):
    accounts = get_accounts()
    if not accounts:
        await update.message.reply_text("No accounts. Add one with /add_account first.")
        return

    lines = ["<b>Channel subscriptions:</b>"]
    for a in accounts:
        lines.append(f"\n📱 <code>{escape(a['phone'])}</code> (ID {a['id']}):")
        channels = get_channels(a["id"])
        if not channels:
            lines.append("  No channels monitored")
        else:
            for ch in channels:
                title = escape(ch["channel_title"] or ch["channel_link"])
                lines.append(f"  • {title} (ID {ch['id']})")
    lines.append("\nAdd: /add_channel ACCOUNT_ID LINK")
    lines.append("Remove: /remove_channel CHANNEL_ID")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def add_channel_cmd(update: Update, context):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /add_channel ACCOUNT_ID CHANNEL_LINK")
        return
    try:
        account_id = int(args[0])
        link = args[1].strip()
        add_channel(account_id, link)
        await update.message.reply_text(f"✅ Channel <code>{escape(link)}</code> added to account {account_id}!", parse_mode=ParseMode.HTML)
        if ctx.monitor_manager:
            await ctx.monitor_manager.restart_all()
    except ValueError:
        await update.message.reply_text("Invalid account ID")


async def remove_channel_cmd(update: Update, context):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /remove_channel CHANNEL_ID")
        return
    try:
        ch_id = int(args[0])
        remove_channel(ch_id)
        await update.message.reply_text(f"Channel {ch_id} removed.")
        if ctx.monitor_manager:
            await ctx.monitor_manager.restart_all()
    except ValueError:
        await update.message.reply_text("Invalid channel ID")


async def pipeline_cmd(update: Update, context):
    status_filter = context.args[0] if context.args else None
    valid_statuses = ["new", "sent", "replied", "working", "closed", "skipped"]
    if status_filter and status_filter not in valid_statuses:
        await update.message.reply_text(f"Invalid status. Valid: {', '.join(valid_statuses)}")
        return

    vacancies = get_vacancies_by_status(status_filter)
    if not vacancies:
        await update.message.reply_text("No vacancies found." + (f" with status '{status_filter}'" if status_filter else ""))
        return

    lines = [f"<b>Pipeline{' (' + status_filter + ')' if status_filter else ''}:</b>"]
    for v in vacancies[:20]:
        lines.append(
            f"\n#{v['id']} | {escape(v['channel_title'])} | Score: {v['ai_score']:.2f} | {v['status']}\n"
            f"{escape(v['ai_summary'][:150])}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def settings_cmd(update: Update, context):
    settings = {
        "auto_mode": get_setting("auto_mode"),
        "stack": get_setting("stack"),
        "about_me": get_setting("about_me"),
        "min_budget": get_setting("min_budget"),
        "followup_days": get_setting("followup_days"),
    }
    mode = "🤖 Auto" if settings["auto_mode"] == "1" else "👤 Manual"
    lines = [
        "<b>Settings:</b>",
        f"Mode: {mode}",
        f"Min budget: {escape(settings['min_budget'] or 'Not set')} USD",
        f"Follow-up days: {escape(settings['followup_days'] or '3')}",
        f"\n<b>Stack:</b>",
        f"<code>{escape((settings['stack'] or '')[:200])}</code>",
        f"\n<b>About:</b>",
        f"<code>{escape((settings['about_me'] or '')[:200])}</code>",
        "\n<b>Change:</b>",
        "/set <key> <value>",
        "Keys: stack, about_me, min_budget, followup_days",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def set_setting_cmd(update: Update, context):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /set <key> <value>")
        return
    key = args[0]
    value = " ".join(args[1:])
    valid_keys = ["stack", "about_me", "min_budget", "followup_days"]
    if key not in valid_keys:
        await update.message.reply_text(f"Invalid key. Valid: {', '.join(valid_keys)}")
        return

    if key == "followup_days":
        try:
            int(value)
        except ValueError:
            await update.message.reply_text("followup_days must be a number")
            return

    set_setting(key, value)
    await update.message.reply_text(f"✅ Setting '{key}' updated!")


async def mode_cmd(update: Update, context):
    current = get_setting("auto_mode")
    new = "1" if current != "1" else "0"
    set_setting("auto_mode", new)
    mode_label = "🤖 Auto" if new == "1" else "👤 Manual"
    await update.message.reply_text(f"Mode switched to {mode_label}")


async def vacancy_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("respond_"):
        vid = int(data.split("_")[1])
        await handle_respond(query, vid)
    elif data.startswith("skip_"):
        vid = int(data.split("_")[1])
        update_vacancy_status(vid, "skipped")
        await query.edit_message_reply_text(
            query.message.text + "\n\n⏭ Skipped", parse_mode=ParseMode.HTML
        )
    elif data.startswith("status_"):
        parts = data.split("_")
        vid = int(parts[1])
        status = parts[2]
        update_vacancy_status(vid, status)
        await query.edit_message_reply_text(
            query.message.text + f"\n\n📌 Status: {status}", parse_mode=ParseMode.HTML
        )


async def handle_respond(query, vid: int):
    vacancy = get_vacancy(vid)
    if not vacancy:
        await query.edit_message_reply_text("Vacancy not found.")
        return

    await query.edit_message_reply_text(
        query.message.text + "\n\n⏳ Generating response...", parse_mode=ParseMode.HTML
    )

    response_text = await generate_response(vacancy["text"])
    if not response_text:
        await query.edit_message_reply_text(
            query.message.text + "\n\n❌ Failed to generate response", parse_mode=ParseMode.HTML
        )
        return

    msg = (
        f"<b>Generated Response for #{vid}:</b>\n\n"
        f"{escape(response_text)}"
    )

    auto_mode = get_setting("auto_mode") == "1"
    if auto_mode and vacancy["sender_id"]:
        sent = await ctx.monitor_manager.send_via_account(
            vacancy["account_id"], vacancy["sender_id"], response_text
        )
        if sent:
            update_vacancy_status(vid, "sent")
            msg += "\n\n✅ <b>Auto-sent via Telegram!</b>"
        else:
            msg += "\n\n⚠️ Could not send (account offline)"
    else:
        kb = None
        if not auto_mode and vacancy["sender_id"]:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✈️ Send Manually", callback_data=f"send_{vid}")]
            ])
        msg += "\n\n📋 Copy the response above and send manually."
        update_vacancy_status(vid, "sent")

    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=msg,
        parse_mode=ParseMode.HTML,
    )


async def send_manually_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    vid = int(query.data.split("_")[1])
    vacancy = get_vacancy(vid)
    if not vacancy:
        await query.edit_message_reply_text("Vacancy not found.")
        return

    # Re-generate and send
    response_text = await generate_response(vacancy["text"])
    if not response_text:
        await query.edit_message_reply_text("Failed to generate response.")
        return

    if vacancy["sender_id"]:
        sent = await ctx.monitor_manager.send_via_account(
            vacancy["account_id"], vacancy["sender_id"], response_text
        )
        if sent:
            update_vacancy_status(vid, "sent")
            await query.edit_message_reply_text(
                f"✅ Response sent for vacancy #{vid}!", parse_mode=ParseMode.HTML
            )
        else:
            await query.edit_message_reply_text("⚠️ Could not send (account offline).")
    else:
        await query.edit_message_reply_text("No sender ID available.")


async def on_vacancy_found(vid: int, account: dict):
    """Called by MonitorManager when a new vacancy is found."""
    vacancy = get_vacancy(vid)
    if not vacancy:
        return

    msg = (
        f"🔔 <b>New Vacancy #{vid}</b>\n"
        f"📢 Channel: {escape(vacancy['channel_title'])}\n"
        f"📱 Account: {escape(account['phone'])}\n"
        f"⭐ Score: {vacancy['ai_score']:.2f}/1.0\n"
        f"💰 Budget: {escape(vacancy['budget_info'] or 'Not specified')}\n\n"
        f"<b>Summary:</b>\n{escape(vacancy['ai_summary'][:500])}"
    )

    await _send_to_admin(msg, keyboard=_vacancy_keyboard(vid))

    # Auto-respond if score is high enough and auto mode
    auto_mode = get_setting("auto_mode") == "1"
    if auto_mode and vacancy["ai_score"] >= 0.6:
        response_text = await generate_response(vacancy["text"])
        if response_text and vacancy["sender_id"]:
            sent = await ctx.monitor_manager.send_via_account(
                account["id"], vacancy["sender_id"], response_text
            )
            if sent:
                update_vacancy_status(vid, "sent")
                await _send_to_admin(
                    f"🤖 <b>Auto-responded to vacancy #{vid}</b>\n\n{escape(response_text[:300])}"
                )


def create_bot() -> Application:
    application = Application.builder().token(config.bot_token).build()

    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("accounts", accounts_cmd))
    application.add_handler(CommandHandler("channels", channels_cmd))
    application.add_handler(CommandHandler("add_channel", add_channel_cmd))
    application.add_handler(CommandHandler("remove_channel", remove_channel_cmd))
    application.add_handler(CommandHandler("pipeline", pipeline_cmd))
    application.add_handler(CommandHandler("settings", settings_cmd))
    application.add_handler(CommandHandler("set", set_setting_cmd))
    application.add_handler(CommandHandler("mode", mode_cmd))
    application.add_handler(CommandHandler("cancel", cancel))

    # Add account conversation
    add_acc_conv = ConversationHandler(
        entry_points=[CommandHandler("add_account", add_account_start)],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_phone)],
            API_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_api_id)],
            API_HASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_api_hash)],
            SESSION_STRING: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_account_session)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(add_acc_conv)

    # Scan
    application.add_handler(CommandHandler("scan", scan_cmd))
    application.add_handler(CallbackQueryHandler(scan_subscribe_callback, pattern=r"^scan_sub_\d+_\d+_"))
    application.add_handler(CallbackQueryHandler(scan_subscribe_all_callback, pattern=r"^scan_all_\d+$"))

    # Callbacks
    application.add_handler(CallbackQueryHandler(vacancy_callback, pattern=r"^(respond|skip|status)_"))
    application.add_handler(CallbackQueryHandler(send_manually_callback, pattern=r"^send_"))

    return application
