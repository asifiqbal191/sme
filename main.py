import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.core.config import settings
from src.db.session import engine
from src.db.models import Base
from src.api.webhooks import router as webhooks_router
from src.bot.telegram_bot import create_bot_application
from src.scheduler.report_scheduler import start_scheduler, stop_scheduler, _capture_event_loop
import asyncio

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

bot_app = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot_app
    
    # Initialize DB (Simple creation for this example, use Alembic usually)
    logger.info("Initializing database schema...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    logger.info("Starting up Telegram Bot...")
    if settings.TELEGRAM_BOT_TOKEN:
        bot_app = await create_bot_application()
        
        # Add Handlers
        from src.bot.telegram_bot import start_command, today_command, orders_command, top_command, pending_command, button_handler, check_sheets_command, chatid_command, handle_message
        from telegram.ext import CommandHandler, CallbackQueryHandler, MessageHandler, filters
        bot_app.add_handler(CommandHandler("start", start_command))
        bot_app.add_handler(CommandHandler("today", today_command))
        bot_app.add_handler(CommandHandler("orders", orders_command))
        bot_app.add_handler(CommandHandler("top", top_command))
        bot_app.add_handler(CommandHandler("pending", pending_command))
        bot_app.add_handler(CommandHandler("check_sheets", check_sheets_command))
        bot_app.add_handler(CommandHandler("chatid", chatid_command))
        bot_app.add_handler(CallbackQueryHandler(button_handler))
        bot_app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
        
        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling(drop_pending_updates=True)
    else:
        logger.warning("No TELEGRAM_BOT_TOKEN provided. Bot is disabled.")

    # Start the automated report scheduler
    try:
        _capture_event_loop()  # Capture the running asyncio loop for the scheduler
        start_scheduler()
        logger.info("Report scheduler initialized.")
    except Exception as e:
        logger.error(f"Failed to start report scheduler: {e}", exc_info=True)

    yield
    
    # Teardown
    # Stop the report scheduler
    try:
        stop_scheduler()
    except Exception as e:
        logger.error(f"Error stopping scheduler: {e}", exc_info=True)

    logger.info("Shutting down Telegram Bot...")
    if bot_app:
        await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()

app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan
)

# Include Routers
app.include_router(webhooks_router, tags=["Webhooks"])

@app.get("/")
async def root():
    return {
        "message": "Welcome to the Multi-Platform Order Tracking Agent API",
        "docs": "Visit /docs for API documentation",
        "health": "Visit /health for system status"
    }

@app.get("/health")
async def health_check():
    return {"status": "ok"}
