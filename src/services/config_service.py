
from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError
from src.db.session import async_session
from src.db.models import GlobalConfig
import logging

logger = logging.getLogger(__name__)

async def get_config(key: str) -> str | None:
    try:
        async with async_session() as session:
            result = await session.execute(select(GlobalConfig).where(GlobalConfig.key == key))
            config = result.scalar_one_or_none()
            return config.value if config else None
    except ProgrammingError:
        # Table doesn't exist yet (fresh deploy) — return None and use defaults
        logger.warning(f"get_config: 'global_config' table not ready yet, returning None for key='{key}'")
        return None
    except Exception as e:
        logger.error(f"get_config error for key='{key}': {e}")
        return None

async def set_config(key: str, value: str):
    try:
        async with async_session() as session:
            result = await session.execute(select(GlobalConfig).where(GlobalConfig.key == key))
            config = result.scalar_one_or_none()

            if config:
                config.value = value
            else:
                new_config = GlobalConfig(key=key, value=value)
                session.add(new_config)

            await session.commit()
    except ProgrammingError:
        logger.warning(f"set_config: 'global_config' table not ready yet, skipping key='{key}'")
    except Exception as e:
        logger.error(f"set_config error for key='{key}': {e}")

async def get_active_sheet_name() -> str | None:
    """Returns the spreadsheet name from DB, or None if not set."""
    return await get_config("google_sheet_name")

async def set_active_sheet_name(name: str):
    await set_config("google_sheet_name", name)

async def get_active_sheet_url() -> str | None:
    """Returns the spreadsheet URL from DB, or None if not set."""
    return await get_config("google_sheet_url")

async def set_active_sheet_url(url: str):
    await set_config("google_sheet_url", url)


# ---------------------------------------------------------------------------
# Schedule Job Configuration
# ---------------------------------------------------------------------------

# Central configuration for all scheduled jobs.
# time_key    → DB key that stores the HH:MM time string
# enabled_key → DB key that stores "true"/"false" (None = always-on, no toggle)
# default_time→ Used when no DB value is saved yet
SCHEDULE_JOBS: dict[str, dict] = {
    "daily_report": {
        "name": "📊 Daily Report",
        "description": "Full daily sales summary with AI recommendations",
        "time_key": "sched_daily_report",
        "default_time": "23:59",
        "enabled_key": None,
        "recurrence": "Every day",
    },
    "weekly_report": {
        "name": "📅 Weekly Report",
        "description": "7-day sales summary with top product",
        "time_key": "sched_weekly_report",
        "default_time": "23:59",
        "enabled_key": None,
        "recurrence": "Every Friday",
    },
    "monthly_report": {
        "name": "📅 Monthly Report",
        "description": "30-day sales summary with top product",
        "time_key": "sched_monthly_report",
        "default_time": "23:59",
        "enabled_key": None,
        "recurrence": "Last day of month",
    },
    "sales_drop_alert": {
        "name": "⚠️ Sales Drop Alert",
        "description": "Fires when today's sales are lower than yesterday's",
        "time_key": "sched_sales_drop",
        "default_time": "22:05",
        "enabled_key": "alert_sales_drop_on",
        "recurrence": "Every day",
    },
    "trending_product_alert": {
        "name": "🔥 Trending Product Alert",
        "description": "Highlights the top-selling product of the day",
        "time_key": "sched_trending",
        "default_time": "22:10",
        "enabled_key": "alert_trending_on",
        "recurrence": "Every day",
    },
    "growth_comparison_report": {
        "name": "📈 Growth Comparison",
        "description": "Compares today vs yesterday's sales and shows growth %",
        "time_key": "sched_growth",
        "default_time": "22:15",
        "enabled_key": "alert_growth_on",
        "recurrence": "Every day",
    },
    "stock_prediction_alert": {
        "name": "📦 Stock Prediction Alert",
        "description": "Warns when products may run out within 5 days",
        "time_key": "sched_stock_pred",
        "default_time": "22:20",
        "enabled_key": "alert_stock_pred_on",
        "recurrence": "Every day",
    },
}


async def get_job_time(job_id: str) -> str:
    """Return the saved HH:MM time for a job, or its default if not set."""
    cfg = SCHEDULE_JOBS.get(job_id)
    if not cfg:
        return "00:00"
    val = await get_config(cfg["time_key"])
    return val if val else cfg["default_time"]


async def get_job_enabled(job_id: str) -> bool:
    """Return whether an alert job is enabled. Always-on jobs always return True."""
    cfg = SCHEDULE_JOBS.get(job_id)
    if not cfg or not cfg.get("enabled_key"):
        return True
    val = await get_config(cfg["enabled_key"])
    return val != "false"


async def set_job_time(job_id: str, time_str: str):
    """Persist the HH:MM time for a job to DB."""
    cfg = SCHEDULE_JOBS.get(job_id)
    if cfg:
        await set_config(cfg["time_key"], time_str)


async def set_job_enabled(job_id: str, enabled: bool):
    """Persist the enabled state for an alert job to DB."""
    cfg = SCHEDULE_JOBS.get(job_id)
    if cfg and cfg.get("enabled_key"):
        await set_config(cfg["enabled_key"], "true" if enabled else "false")
