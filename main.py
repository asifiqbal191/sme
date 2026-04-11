import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import text
from src.core.config import settings
from src.db.session import engine
from src.db.models import Base
from src.bot.bot_manager import bot_manager
from src.scheduler.report_scheduler import start_scheduler, stop_scheduler, _capture_event_loop
import asyncio
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from src.api.dashboard import router as dashboard_router

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB
    logger.info("Initializing database schema...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Migration: add role column to invites if it doesn't exist (SQLite doesn't auto-add columns)
        try:
            await conn.execute(text("ALTER TABLE invites ADD COLUMN role VARCHAR DEFAULT 'MODERATOR'"))
            logger.info("Migration: added 'role' column to invites table.")
        except Exception:
            pass
            
        try:
            await conn.execute(text("ALTER TABLE orders ADD COLUMN created_by_id VARCHAR"))
            logger.info("Migration: added 'created_by_id' column to orders table.")
        except Exception:
            pass  # Column already exists, safe to ignore
    
    # NEW: Ensure primary data is seeded
    from src.db.seed import ensure_base_data
    await ensure_base_data()
        
    logger.info("Starting up Telegram Bots for all tenants...")
    await bot_manager.start_all_tenant_bots()

    # Start the automated report scheduler
    try:
        _capture_event_loop()  # Capture the running asyncio loop for the scheduler
        await start_scheduler()
        logger.info("Report scheduler initialized.")
    except Exception as e:
        logger.error(f"Failed to start report scheduler: {e}", exc_info=True)

    yield
    
    # Teardown
    try:
        stop_scheduler()
    except Exception as e:
        logger.error(f"Error stopping scheduler: {e}", exc_info=True)

    logger.info("Shutting down Telegram Bots...")
    await bot_manager.stop_all_bots()

app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan
)

app.include_router(dashboard_router)
app.mount("/static", StaticFiles(directory="src/static"), name="static")

@app.get("/")
async def root():
    return {
        "message": "Welcome to the Multi-Platform Order Tracking Agent API",
        "docs": "Visit /docs for API documentation",
        "health": "Visit /health for system status",
        "dashboard": "Visit /dashboard to view the order analytics dashboard"
    }

@app.get("/dashboard")
async def serve_dashboard():
    return FileResponse("src/static/index.html")

@app.get("/health")
async def health_check():
    return {"status": "ok"}
