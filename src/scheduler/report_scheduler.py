"""
Automated Report Scheduler
--------------------------
Sends daily and weekly business reports to Telegram using APScheduler.

Daily Report:  Every day at 9:00 PM (Asia/Dhaka)
Weekly Report: Every Sunday at 9:00 PM (Asia/Dhaka)
Test Report:   Every 1 minute (for testing — disable after verification)
"""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
from pytz import timezone as pytz_timezone

from src.core.config import settings
from src.db.session import async_session
from src.services import analytics
from src.services.notifier import send_admin_alert

logger = logging.getLogger(__name__)

DHAKA_TZ = pytz_timezone("Asia/Dhaka")

# ---------------------------------------------------------------------------
# Telegram message sender
# ---------------------------------------------------------------------------

async def _send_telegram_message(text: str):
    """Send a message to all configured report chat IDs."""
    import httpx

    chat_ids = settings.report_chat_ids
    token = settings.TELEGRAM_BOT_TOKEN

    if not chat_ids or not token:
        logger.warning("No report chat IDs or TELEGRAM_BOT_TOKEN configured. Skipping report.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    async with httpx.AsyncClient() as client:
        for chat_id in chat_ids:
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
            }
            try:
                resp = await client.post(url, json=payload, timeout=30)
                if resp.status_code == 200:
                    logger.info(f"Report sent to chat_id: {chat_id}")
                else:
                    logger.error(f"Failed to send to {chat_id}: {resp.status_code} — {resp.text}")
            except Exception as e:
                logger.error(f"Error sending to {chat_id}: {e}")


# ---------------------------------------------------------------------------
# Report generators
# ---------------------------------------------------------------------------

async def _generate_daily_report():
    """Build and send the enhanced intelligent daily report."""
    logger.info("Generating intelligent daily report...")
    try:
        async with async_session() as session:
            # 1. Basic Stats
            today_stats = await analytics.get_daily_sales(session)
            total_sales = today_stats["total_sales"]
            order_count = today_stats["total_orders"]
            
            # 2. Performance Insight (Today vs Yesterday)
            yesterday_stats = await analytics.get_yesterday_sales(session)
            yesterday_sales = yesterday_stats["total_sales"]
            
            growth_str = "0%"
            if yesterday_sales > 0:
                growth = ((total_sales - yesterday_sales) / yesterday_sales) * 100
                growth_str = f"{'+' if growth >= 0 else ''}{growth:.1f}%"
            elif total_sales > 0:
                growth_str = "+100%"
                
            # 3. Product Analysis (Top product + contribution)
            top = await analytics.get_today_top_product(session)
            
            # 4. Revenue Breakdown (Top 3)
            # Use Dhaka local time (DB now stores local time)
            now_dhaka = datetime.now(DHAKA_TZ).replace(tzinfo=None)
            start_of_day = now_dhaka.replace(hour=0, minute=0, second=0, microsecond=0)
            
            breakdown = await analytics.get_revenue_breakdown(session, start_of_day, now_dhaka)
            
            # 5. Alert System
            LOW_SALES_THRESHOLD = 1000.0
            LOW_ORDERS_THRESHOLD = 2 # Lowered for testing
            alerts = []
            if total_sales < LOW_SALES_THRESHOLD:
                alerts.append("⚠️ Low sales detected today")
            if order_count < LOW_ORDERS_THRESHOLD:
                alerts.append("⚠️ Order volume is low")

            # 6. AI Recommendations
            recommendations = []
            # Performance based
            if growth_str.startswith('+'):
                val = float(growth_str.strip('+%'))
                if val > 20: recommendations.append("🚀 Great growth! Celebrate and promote top product tomorrow.")
                else: recommendations.append("📈 Steady growth. Keep your current strategy.")
            elif growth_str.startswith('-'):
                recommendations.append("📉 Sales are down. Consider a flash discount or checking ad campaigns.")
            
            # Product based
            if top and total_sales > 0:
                contribution = (top["revenue"] / total_sales) * 100
                if contribution > 50:
                    recommendations.append("🎯 One product is dominating. Consider diversifying your catalog.")
            
            if total_sales == 0:
                recommendations.append("🔍 No sales today? Check if your order parsing is working correctly.")

            if not recommendations:
                recommendations.append("✅ Monitoring looks good. Focus on customer response speed.")

            # Build Message
            msg_parts = [
                f"📊 *Daily Report:*",
                f"Sales: ৳{total_sales:,.2f}",
                f"Orders: {order_count}",
                f"",
                f"📈 *Performance Insight:*",
                f"Sales Change: *{growth_str}* (vs yesterday)",
                f""
            ]
            
            if top:
                contribution = (top["revenue"] / total_sales) * 100 if total_sales > 0 else 0
                msg_parts.extend([
                    f"🔥 *Top Product:*",
                    f"{top['product_name']} ({top['quantity']} sold)",
                    f"",
                    f"💡 *Insight:*",
                    f"This product contributed {contribution:.1f}% of total sales",
                    f""
                ])
                
            if breakdown:
                msg_parts.append(f"💰 *Revenue Breakdown:*")
                for item in breakdown:
                    msg_parts.append(f"{item['product_name']} → ৳{item['revenue']:,.2f}")
                msg_parts.append("")
                
            if alerts:
                msg_parts.extend(alerts)
                msg_parts.append("")
                
            msg_parts.append(f"🤖 *AI Recommendation:*")
            for rec in recommendations:
                msg_parts.append(f"- {rec}")

            await _send_telegram_message("\n".join(msg_parts))
            logger.info("Intelligent daily report task completed.")

    except Exception as e:
        logger.error(f"Error generating intelligent daily report: {e}", exc_info=True)
        await send_admin_alert(f"🚨 *Scheduler Error*\n\nJob: Daily Report\nError: `{str(e)[:200]}`")


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
        await send_admin_alert(f"🚨 *Scheduler Error*\n\nJob: Weekly Report\nError: `{str(e)[:200]}`")


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
        await send_admin_alert(f"🚨 *Scheduler Error*\n\nJob: Monthly Report\nError: `{str(e)[:200]}`")


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
        await send_admin_alert(f"🚨 *Scheduler Error*\n\nJob: Sales Drop Alert\nError: `{str(e)[:200]}`")


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
        await send_admin_alert(f"🚨 *Scheduler Error*\n\nJob: Trending Product Alert\nError: `{str(e)[:200]}`")


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
        await send_admin_alert(f"🚨 *Scheduler Error*\n\nJob: Growth Report\nError: `{str(e)[:200]}`")
        
async def _check_stock_prediction_alerts():
    """
    Predicts when products will run out and sends alerts for those < 5 days.
    Run daily at 10:20 PM.
    """
    logger.info("Checking for stock prediction alerts...")
    try:
        async with async_session() as session:
            predictions = await analytics.get_stock_predictions(session)

        alerts_sent = 0
        for p in predictions:
            days = p["days_remaining"]
            if days < 5:
                # Format days nicely
                days_str = f"{days:.1f}" if days > 0 else "0"
                msg = (
                    f"📦 *Stock Alert:*\n"
                    f"*{p['product_name']}* may run out in *{days_str}* days.\n\n"
                    f"Current Stock: {p['current_stock']} units\n"
                    f"Avg Daily Sales: {p['avg_daily_sales']:.2f} units"
                )
                await _send_telegram_message(msg)
                alerts_sent += 1
                logger.info(f"Stock alert sent for {p['product_name']}: {days_str} days remaining.")
        
        if alerts_sent == 0:
            logger.info("No stock alerts needed today.")
        else:
            logger.info(f"Total stock alerts sent: {alerts_sent}")

    except Exception as e:
        logger.error(f"Error checking stock prediction alerts: {e}", exc_info=True)
        await send_admin_alert(f"🚨 *Scheduler Error*\n\nJob: Stock Prediction Alert\nError: `{str(e)[:200]}`")


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

    # ── Stock Prediction Alert: every day at 10:20 PM Asia/Dhaka ──
    scheduler.add_job(
        _check_stock_prediction_alerts,
        trigger=CronTrigger(hour=22, minute=20, timezone=DHAKA_TZ),
        id="stock_prediction_alert",
        name="Stock Prediction Alert",
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
