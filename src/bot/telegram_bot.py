import logging
from telegram import BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from src.core.config import settings

from src.bot.handlers import (
    start_command,
    chatid_command,
    today_command,
    orders_command,
    top_command,
    pending_command,
    check_sheets_command,
    button_handler,
    handle_message,
    generate_invite_command,
    join_command,
    add_mod_command,
    ban_command,
    unban_command,
    list_mod_command,
    weekly_command,
    monthly_command,
    growth_command,
    alerts_command
)

logger = logging.getLogger(__name__)

async def post_init(application: Application) -> None:
    await application.bot.set_my_commands([
        BotCommand("start", "Open Main Menu"),
        BotCommand("chatid", "Get Telegram Chat ID"),
    ])
    logger.info("Native telegram menu setup complete.")

async def create_bot_application() -> Application:
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    
    # Core/Admin Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("chatid", chatid_command))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("weekly", weekly_command))
    app.add_handler(CommandHandler("monthly", monthly_command))
    app.add_handler(CommandHandler("growth", growth_command))
    app.add_handler(CommandHandler("alerts", alerts_command))
    app.add_handler(CommandHandler("orders", orders_command))
    app.add_handler(CommandHandler("top", top_command))
    app.add_handler(CommandHandler("pending", pending_command))
    app.add_handler(CommandHandler("check_sheets", check_sheets_command))
    
    # Role Management Commands
    app.add_handler(CommandHandler("generate_invite", generate_invite_command))
    app.add_handler(CommandHandler("join", join_command))
    app.add_handler(CommandHandler("add_moderator", add_mod_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("list_moderators", list_mod_command))
    
    # Callbacks and Messages
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    return app
