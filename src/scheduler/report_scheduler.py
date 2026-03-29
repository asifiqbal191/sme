"""
Automated Report Scheduler
--------------------------
Sends daily and weekly business reports to Telegram using APScheduler.

Daily Report:  Every day at 9:00 PM (Asia/Dhaka)
Weekly Report: Every Sunday at 9:00 PM (Asia/Dhaka)
Test Report:   Every 1 minute (for testing — disable after verification)
"""

import logging
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pytz import timezone as pytz_timezone

from src.core.config import settings
from src.db.session import async_session
from src.services import analytics

logger = logging.getLogger(__name__)

DHAKA_TZ = pytz_timezone("Asia/Dhaka")

# ---------------------------------------------------------------------------
# Telegram message sender
# ---------------------------------------------------------------------------

async def _send_telegram_message(text: str):
    """Send a message to the configured Telegram chat."""
    import httpx

    chat_id = settings.TELEGRAM_CHAT_ID
    token = settings.TELEGRAM_BOT_TOKEN

    if not chat_id or not token:
        logger.warning("TELEGRAM_CHAT_ID or TELEGRAM_BOT_TOKEN not set. Skipping report.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=30)
            if resp.status_code == 200:
                logger.info(f"Report sent to Telegram successfully to chat_id: {chat_id}")
            else:
                logger.error(f"Failed to send report: {resp.status_code} — {resp.text}")
    except Exception as e:
        logger.error(f"Error sending telegram message: {e}")


# ---------------------------------------------------------------------------
# Report generators
# ---------------------------------------------------------------------------

async def _generate_daily_report():
    """Build and send the daily sales report."""
    logger.info("Generating daily report...")
    try:
        async with async_session() as session:
            stats = await analytics.get_daily_sales(session)
            top = await analytics.get_today_top_product(session)

        total_sales = stats["total_sales"]
        order_count = stats["total_orders"]

        msg = (
            f"📊 *Daily Report:*\n"
            f"Sales: ৳{total_sales:,.2f}\n"
            f"Orders: {order_count}\n"
        )

        if top:
            msg += (
                f"\n🔥 *Top Product:*\n"
                f"{top['product_name']} ({top['quantity']} sold)"
            )
        else:
            msg += "\n_No sales recorded today._"

        await _send_telegram_message(msg)
        logger.info("Daily report task completed.")

    except Exception as e:
        logger.error(f"Error generating daily report: {e}", exc_info=True)


async def _generate_weekly_report():
    """Build and send the weekly sales report."""
    logger.info("Generating weekly report...")
    try:
        async with async_session() as session:
            stats = await analytics.get_weekly_sales(session)
            top = await analytics.get_weekly_top_product(session)

        weekly_sales = stats["total_sales"]

        msg = (
            f"📊 *Weekly Report:*\n"
            f"Sales: ৳{weekly_sales:,.2f}\n"
        )

        if top:
            msg += (
                f"\n🏆 *Top Product:*\n"
                f"{top['product_name']} ({top['quantity']} sold)"
            )
        else:
            msg += "\n_No sales recorded this week._"

        await _send_telegram_message(msg)
        logger.info("Weekly report task completed.")

    except Exception as e:
        logger.error(f"Error generating weekly report: {e}", exc_info=True)


async def _generate_monthly_report():
    """Build and send the monthly sales report."""
    logger.info("Generating monthly report...")
    try:
        async with async_session() as session:
            stats = await analytics.get_monthly_sales(session)
            top = await analytics.get_monthly_top_product(session)

        monthly_sales = stats["total_sales"]

        msg = (
            f"📊 *Monthly Report:*\n"
            f"Sales: ৳{monthly_sales:,.2f}\n"
        )

        if top:
            msg += (
                f"\n🏆 *Top Product:*\n"
                f"{top['product_name']} ({top['quantity']} sold)"
            )
        else:
            msg += "\n_No sales recorded this month._"

        await _send_telegram_message(msg)
        logger.info("Monthly report task completed.")

    except Exception as e:
        logger.error(f"Error generating monthly report: {e}", exc_info=True)


async def _check_sales_drop():
    """
    Checks if today's sales are lower than yesterday's sales and sends an alert.
    Run daily at 10:05 PM.
    """
    logger.info("Checking for sales drop...")
    try:
        async with async_session() as session:
            today_stats = await analytics.get_daily_sales(session)
            yesterday_stats = await analytics.get_yesterday_sales(session)

        today_sales = today_stats["total_sales"]
        yesterday_sales = yesterday_stats["total_sales"]

        if today_sales < yesterday_sales:
            msg = (
                f"⚠️ *Sales Alert:*\n"
                f"Today's sales dropped compared to yesterday.\n\n"
                f"Yesterday: ৳{yesterday_sales:,.2f}\n"
                f"Today: ৳{today_sales:,.2f}"
            )
            await _send_telegram_message(msg)
            logger.info(f"Sales drop alert sent! Today: {today_sales}, Yesterday: {yesterday_sales}")
        else:
            logger.info(f"No sales drop detected. Today: {today_sales}, Yesterday: {yesterday_sales}")

    except Exception as e:
        logger.error(f"Error checking sales drop: {e}", exc_info=True)


async def _trending_product_alert():
    """
    Detects top-selling product of the day and notifies user.
    Run daily at 10:10 PM.
    """
    logger.info("Checking for trending product...")
    try:
        async with async_session() as session:
            top = await analytics.get_top_product(session)

        if top and top["quantity"] > 0:
            msg = (
                f"🔥 *Trending Product Alert:*\n"
                f"Top product today is:\n\n"
                f"*{top['product_name']}*\n"
                f"Sold: {top['quantity']} units"
            )
            await _send_telegram_message(msg)
            logger.info(f"Trending product alert sent: {top['product_name']} ({top['quantity']} units)")
        else:
            logger.info("No sales today. Skipping trending product alert.")

    except Exception as e:
        logger.error(f"Error generating trending product alert: {e}", exc_info=True)


async def _generate_growth_report():
    """
    Calculates growth (today vs yesterday) and sends report.
    Run daily at 10:15 PM.
    """
    logger.info("Generating growth report...")
    try:
        async with async_session() as session:
            today_stats = await analytics.get_daily_sales(session)
            yesterday_stats = await analytics.get_yesterday_sales(session)

        today = today_stats["total_sales"]
        yesterday = yesterday_stats["total_sales"]

        if yesterday == 0:
            if today > 0:
                growth_pct = 100.0
                growth_str = f"+{growth_pct:.1f}%"
            else:
                growth_pct = 0.0
                growth_str = "0%"
        else:
            growth_pct = ((today - yesterday) / yesterday) * 100
            sign = "+" if growth_pct >= 0 else ""
            growth_str = f"{sign}{growth_pct:.1f}%"

        msg = (
            f"📊 *Growth Report:*\n"
            f"Sales Change: *{growth_str}*\n\n"
            f"Yesterday: ৳{yesterday:,.2f}\n"
            f"Today: ৳{today:,.2f}"
        )

        await _send_telegram_message(msg)
        logger.info(f"Growth report sent! Growth: {growth_str}")

    except Exception as e:
        logger.error(f"Error generating growth report: {e}", exc_info=True)


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

scheduler: AsyncIOScheduler | None = None

# ── Set this to False to enable the 1-minute test job ──
TESTING_MODE = False


def start_scheduler():
    """Initialize and start the APScheduler AsyncIOScheduler."""
    global scheduler

    if scheduler and scheduler.running:
        logger.info("Scheduler is already running.")
        return

    # Use AsyncIOScheduler to run directly on the existing event loop
    scheduler = AsyncIOScheduler(timezone=DHAKA_TZ)

    # ── Daily report: every day at 12:00 AM (Midnight) Asia/Dhaka ──
    scheduler.add_job(
        _generate_daily_report,
        trigger=CronTrigger(hour=0, minute=0, timezone=DHAKA_TZ),
        id="daily_report",
        name="Daily Sales Report",
        replace_existing=True,
    )

    # ── Weekly report: every Friday at 12:00 AM (Midnight) Asia/Dhaka ──
    scheduler.add_job(
        _generate_weekly_report,
        trigger=CronTrigger(day_of_week="fri", hour=0, minute=0, timezone=DHAKA_TZ),
        id="weekly_report",
        name="Weekly Sales Report",
        replace_existing=True,
    )

    # ── Monthly report: last day of the month at 11:59 PM Asia/Dhaka ──
    scheduler.add_job(
        _generate_monthly_report,
        trigger=CronTrigger(day="last", hour=23, minute=59, timezone=DHAKA_TZ),
        id="monthly_report",
        name="Monthly Sales Report",
        replace_existing=True,
    )

    # ── Sales Drop Alert: every day at 10:05 PM Asia/Dhaka ──
    scheduler.add_job(
        _check_sales_drop,
        trigger=CronTrigger(hour=22, minute=5, timezone=DHAKA_TZ),
        id="sales_drop_alert",
        name="Sales Drop Alert",
        replace_existing=True,
    )

    # ── Trending Product Alert: every day at 10:10 PM Asia/Dhaka ──
    scheduler.add_job(
        _trending_product_alert,
        trigger=CronTrigger(hour=22, minute=10, timezone=DHAKA_TZ),
        id="trending_product_alert",
        name="Trending Product Alert",
        replace_existing=True,
    )

    # ── Growth Comparison Report: every day at 10:15 PM Asia/Dhaka ──
    scheduler.add_job(
        _generate_growth_report,
        trigger=CronTrigger(hour=22, minute=15, timezone=DHAKA_TZ),
        id="growth_comparison_report",
        name="Growth Comparison Report",
        replace_existing=True,
    )

    # ── Testing job: every 1 minute ──
    if TESTING_MODE:
        scheduler.add_job(
            _generate_daily_report,
            trigger=IntervalTrigger(minutes=1),
            id="test_report",
            name="Test Report (every 1 min)",
            replace_existing=True,
        )
        # ── INITIAL TEST RUN: Fire once immediately after start ──
        from datetime import datetime
        scheduler.add_job(
            _generate_daily_report,
            id="initial_test_run",
            name="Initial Test Run",
            next_run_time=datetime.now(DHAKA_TZ)
        )
        
        logger.info("⚠️  TESTING MODE is ON — report will fire every 1 minute (plus one immediate run).")

    scheduler.start()
    logger.info("✅ Async report scheduler started successfully. Next daily report at 9:00 PM.")


def stop_scheduler():
    """Gracefully shut down the scheduler."""
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Report scheduler stopped.")
        scheduler = None


def _capture_event_loop():
    """No-op for AsyncIOScheduler as it picks up the current loop when started."""
    logger.info("AsyncIOScheduler will use the current event loop.")
