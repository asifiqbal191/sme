import logging
from telegram import BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, TypeHandler, ContextTypes
from telegram import Update
from src.core.config import settings
from src.core.context import set_tenant_id
from src.bot.bot_manager import bot_manager

from src.bot.handlers import (
    start_command,
    chatid_command,
    today_command,
    orders_command,
    search_command,
    top_command,
    pending_command,
    markpaid_command,
    setstock_command,
    stock_command,
    team_stats_command,
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
    alerts_command,
    mod_stock_command,
    lowstock_command,
    forcereport_command,
    new_client_command,
    list_clients_command
)

logger = logging.getLogger(__name__)

async def set_tenant_context(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Middleware to set tenant ID for the current request based on the Bot Token."""
    if context.bot and context.bot.token:
        tenant_id = bot_manager.get_tenant_id_from_token(context.bot.token)
        if tenant_id:
            set_tenant_id(tenant_id)

async def post_init(application: Application) -> None:
    await application.bot.set_my_commands([
        BotCommand("start", "Open Main Menu"),
        BotCommand("chatid", "Get Telegram Chat ID"),
        BotCommand("newclient", "Create a new client tenant"),
        BotCommand("listclients", "List all client tenants"),
    ])
    logger.info("Native telegram menu setup complete.")

async def create_bot_application(token: str) -> Application:
    app = Application.builder().token(token).post_init(post_init).build()
    
    # Middleware to set Tenant ID
    app.add_handler(TypeHandler(Update, set_tenant_context), group=-1)

    # Superadmin Commands
    app.add_handler(CommandHandler("newclient", new_client_command))
    app.add_handler(CommandHandler("listclients", list_clients_command))
    
    # Core/Admin Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("chatid", chatid_command))
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("weekly", weekly_command))
    app.add_handler(CommandHandler("monthly", monthly_command))
    app.add_handler(CommandHandler("growth", growth_command))
    app.add_handler(CommandHandler("alerts", alerts_command))
    app.add_handler(CommandHandler("orders", orders_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("top", top_command))
    app.add_handler(CommandHandler("pending", pending_command))
    app.add_handler(CommandHandler("check_sheets", check_sheets_command))
    app.add_handler(CommandHandler("setstock", setstock_command))
    app.add_handler(CommandHandler("markpaid", markpaid_command))
    app.add_handler(CommandHandler("stock", stock_command))
    app.add_handler(CommandHandler("teamstats", team_stats_command))
    app.add_handler(CommandHandler("mystock", mod_stock_command))
    app.add_handler(CommandHandler("lowstock", lowstock_command))
    app.add_handler(CommandHandler("forcereport", forcereport_command))
    
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
