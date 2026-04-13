"""
Automated Report Scheduler
--------------------------
Sends daily and weekly business reports to Telegram using APScheduler.

Schedule times and alert on/off states are stored in the GlobalConfig DB table
so admins can change them at runtime via the bot's Settings menu without
restarting the server.

Recipients are resolved from the database at runtime:
  - Every active Tenant's Admin users receive reports via that tenant's bot token.
  - No env-var chat ID lists needed — the DB IS the source of truth.
"""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
from pytz import timezone as pytz_timezone

from src.db.session import async_session
from src.services import analytics

logger = logging.getLogger(__name__)

DHAKA_TZ = pytz_timezone("Asia/Dhaka")


# ---------------------------------------------------------------------------
# Recipient resolution — pull from DB, no env vars needed
# ---------------------------------------------------------------------------

async def _get_tenant_recipients() -> list[tuple]:
    """
    Returns a list of (bot_token, admin_chat_id, tenant_id) for every active
    tenant that has at least one non-banned admin.  Reports are sent to each
    admin via that tenant's own bot token.
    """
    from src.db.models import Tenant, User, RoleEnum
    from sqlalchemy import select, and_

    recipients = []
    async with async_session() as session:
        tenants_result = await session.execute(
            select(Tenant).where(Tenant.is_active == True)  # noqa: E712
        )
        tenants = tenants_result.scalars().all()

        for tenant in tenants:
            admins_result = await session.execute(
                select(User).where(
                    and_(
                        User.tenant_id == tenant.id,
                        User.role == RoleEnum.ADMIN,
                        User.is_banned == False,  # noqa: E712
                    )
                )
            )
            for admin in admins_result.scalars().all():
                recipients.append((tenant.bot_token, admin.telegram_id, tenant.id))

    if not recipients:
        logger.warning("No active tenants with admins found — report delivery skipped.")
    return recipients


# ---------------------------------------------------------------------------
# Low-level sender
# ---------------------------------------------------------------------------

async def _send_message(bot_token: str, chat_id: str, text: str) -> None:
    """Send a Telegram message via a specific bot token."""
    import httpx

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=30)
            if resp.status_code == 200:
                logger.info(f"Report sent → chat {chat_id}")
            else:
                logger.error(f"Telegram error for chat {chat_id}: {resp.status_code} — {resp.text}")
    except Exception as e:
        logger.error(f"HTTP error sending to {chat_id}: {e}")


# ---------------------------------------------------------------------------
# Report generators — each iterates all tenants
# ---------------------------------------------------------------------------

async def _generate_daily_report():
    """Build and send the enhanced intelligent daily report to every tenant's admin."""
    logger.info("Generating daily report for all tenants...")
    recipients = await _get_tenant_recipients()

    for bot_token, chat_id, tenant_id in recipients:
        try:
            async with async_session() as session:
                # Basic stats — scoped to this tenant
                today_stats = await analytics.get_daily_sales(session, tenant_id=tenant_id)
                total_sales = today_stats["total_sales"]
                order_count = today_stats["total_orders"]

                yesterday_stats = await analytics.get_yesterday_sales(session, tenant_id=tenant_id)
                yesterday_sales = yesterday_stats["total_sales"]

                top = await analytics.get_today_top_product(session, tenant_id=tenant_id)

                now_dhaka = datetime.now(DHAKA_TZ).replace(tzinfo=None)
                start_of_day = now_dhaka.replace(hour=0, minute=0, second=0, microsecond=0)
                breakdown = await analytics.get_revenue_breakdown(
                    session, start_of_day, now_dhaka, tenant_id=tenant_id
                )

            # Growth
            if yesterday_sales > 0:
                growth = ((total_sales - yesterday_sales) / yesterday_sales) * 100
                growth_str = f"{'+' if growth >= 0 else ''}{growth:.1f}%"
            elif total_sales > 0:
                growth_str = "+100%"
            else:
                growth_str = "0%"

            # Alerts
            alerts = []
            LOW_SALES_THRESHOLD = 1000.0
            LOW_ORDERS_THRESHOLD = 2
            if total_sales < LOW_SALES_THRESHOLD:
                alerts.append("⚠️ Low sales detected today")
            if order_count < LOW_ORDERS_THRESHOLD:
                alerts.append("⚠️ Order volume is low")

            # AI recommendations
            recommendations = []
            if growth_str.startswith('+'):
                val = float(growth_str.strip('+%'))
                if val > 20:
                    recommendations.append("🚀 Great growth! Celebrate and promote top product tomorrow.")
                else:
                    recommendations.append("📈 Steady growth. Keep your current strategy.")
            elif growth_str.startswith('-'):
                recommendations.append("📉 Sales are down. Consider a flash discount or checking ad campaigns.")

            if top and total_sales > 0:
                contribution = (top["revenue"] / total_sales) * 100
                if contribution > 50:
                    recommendations.append("🎯 One product is dominating. Consider diversifying your catalog.")

            if total_sales == 0:
                recommendations.append("🔍 No sales today? Check if your order parsing is working correctly.")

            if not recommendations:
                recommendations.append("✅ Monitoring looks good. Focus on customer response speed.")

            # Build message
            msg_parts = [
                "📊 *Daily Report:*",
                f"Sales: ৳{total_sales:,.2f}",
                f"Orders: {order_count}",
                "",
                "📈 *Performance Insight:*",
                f"Sales Change: *{growth_str}* (vs yesterday)",
                "",
            ]

            if top:
                contribution = (top["revenue"] / total_sales) * 100 if total_sales > 0 else 0
                msg_parts += [
                    "🔥 *Top Product:*",
                    f"{top['product_name']} ({top['quantity']} sold)",
                    "",
                    "💡 *Insight:*",
                    f"This product contributed {contribution:.1f}% of total sales",
                    "",
                ]

            if breakdown:
                msg_parts.append("💰 *Revenue Breakdown:*")
                for item in breakdown:
                    msg_parts.append(f"{item['product_name']} → ৳{item['revenue']:,.2f}")
                msg_parts.append("")

            if alerts:
                msg_parts += alerts
                msg_parts.append("")

            msg_parts.append("🤖 *AI Recommendation:*")
            for rec in recommendations:
                msg_parts.append(f"- {rec}")

            await _send_message(bot_token, chat_id, "\n".join(msg_parts))
            logger.info(f"Daily report sent for tenant {tenant_id} → chat {chat_id}")

        except Exception as e:
            logger.error(f"Error generating daily report for tenant {tenant_id}: {e}", exc_info=True)


async def _generate_weekly_report():
    """Send the weekly sales report to every tenant's admin."""
    logger.info("Generating weekly report for all tenants...")
    recipients = await _get_tenant_recipients()

    for bot_token, chat_id, tenant_id in recipients:
        try:
            async with async_session() as session:
                stats = await analytics.get_weekly_sales(session, tenant_id=tenant_id)
                top = await analytics.get_weekly_top_product(session, tenant_id=tenant_id)

            msg = (
                f"📊 *Weekly Report:*\n"
                f"Sales: ৳{stats['total_sales']:,.2f}\n"
                f"Orders: {stats['total_orders']}"
            )
            if top:
                msg += f"\n\n🏆 *Top Product:*\n{top['product_name']} ({top['quantity']} sold)"
            else:
                msg += "\n\n_No sales recorded this week._"

            await _send_message(bot_token, chat_id, msg)

        except Exception as e:
            logger.error(f"Error generating weekly report for tenant {tenant_id}: {e}", exc_info=True)


async def _generate_monthly_report():
    """Send the monthly sales report to every tenant's admin."""
    logger.info("Generating monthly report for all tenants...")
    recipients = await _get_tenant_recipients()

    for bot_token, chat_id, tenant_id in recipients:
        try:
            async with async_session() as session:
                stats = await analytics.get_monthly_sales(session, tenant_id=tenant_id)
                top = await analytics.get_monthly_top_product(session, tenant_id=tenant_id)

            msg = (
                f"📊 *Monthly Report:*\n"
                f"Sales: ৳{stats['total_sales']:,.2f}\n"
                f"Orders: {stats['total_orders']}"
            )
            if top:
                msg += f"\n\n🏆 *Top Product:*\n{top['product_name']} ({top['quantity']} sold)"
            else:
                msg += "\n\n_No sales recorded this month._"

            await _send_message(bot_token, chat_id, msg)

        except Exception as e:
            logger.error(f"Error generating monthly report for tenant {tenant_id}: {e}", exc_info=True)


async def _check_sales_drop():
    """Alert if today's sales are lower than yesterday's."""
    logger.info("Checking sales drop for all tenants...")
    recipients = await _get_tenant_recipients()

    for bot_token, chat_id, tenant_id in recipients:
        try:
            async with async_session() as session:
                today_stats = await analytics.get_daily_sales(session, tenant_id=tenant_id)
                yesterday_stats = await analytics.get_yesterday_sales(session, tenant_id=tenant_id)

            today_sales = today_stats["total_sales"]
            yesterday_sales = yesterday_stats["total_sales"]

            if today_sales < yesterday_sales:
                msg = (
                    f"⚠️ *Sales Alert:*\n"
                    f"Today's sales dropped vs yesterday.\n\n"
                    f"Yesterday: ৳{yesterday_sales:,.2f}\n"
                    f"Today: ৳{today_sales:,.2f}"
                )
                await _send_message(bot_token, chat_id, msg)
                logger.info(f"Sales drop alert sent for tenant {tenant_id}")
            else:
                logger.info(f"No sales drop for tenant {tenant_id} (today={today_sales}, yesterday={yesterday_sales})")

        except Exception as e:
            logger.error(f"Error checking sales drop for tenant {tenant_id}: {e}", exc_info=True)


async def _trending_product_alert():
    """Alert about the top-selling product of the day."""
    logger.info("Checking trending product for all tenants...")
    recipients = await _get_tenant_recipients()

    for bot_token, chat_id, tenant_id in recipients:
        try:
            async with async_session() as session:
                top = await analytics.get_top_product(session, tenant_id=tenant_id)

            if top and top["quantity"] > 0:
                msg = (
                    f"🔥 *Trending Product Alert:*\n"
                    f"Top product today:\n\n"
                    f"*{top['product_name']}*\n"
                    f"Sold: {top['quantity']} units"
                )
                await _send_message(bot_token, chat_id, msg)

        except Exception as e:
            logger.error(f"Error trending product alert for tenant {tenant_id}: {e}", exc_info=True)


async def _generate_growth_report():
    """Calculate today vs yesterday growth and send report."""
    logger.info("Generating growth report for all tenants...")
    recipients = await _get_tenant_recipients()

    for bot_token, chat_id, tenant_id in recipients:
        try:
            async with async_session() as session:
                today_stats = await analytics.get_daily_sales(session, tenant_id=tenant_id)
                yesterday_stats = await analytics.get_yesterday_sales(session, tenant_id=tenant_id)

            today = today_stats["total_sales"]
            yesterday = yesterday_stats["total_sales"]

            if yesterday == 0:
                growth_str = "+100%" if today > 0 else "0%"
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
            await _send_message(bot_token, chat_id, msg)

        except Exception as e:
            logger.error(f"Error growth report for tenant {tenant_id}: {e}", exc_info=True)


async def _check_stock_prediction_alerts():
    """Warn when products may run out within 5 days."""
    logger.info("Checking stock predictions for all tenants...")
    recipients = await _get_tenant_recipients()

    for bot_token, chat_id, tenant_id in recipients:
        try:
            async with async_session() as session:
                predictions = await analytics.get_stock_predictions(session, tenant_id=tenant_id)

            alerts_sent = 0
            for p in predictions:
                days_left = p["days_remaining"]
                if days_left < 5:
                    days_str = f"{days_left:.1f}" if days_left > 0 else "0"
                    msg = (
                        f"📦 *Stock Alert:*\n"
                        f"*{p['product_name']}* may run out in *{days_str}* days.\n\n"
                        f"Current Stock: {p['current_stock']} units\n"
                        f"Avg Daily Sales: {p['avg_daily_sales']:.2f} units"
                    )
                    await _send_message(bot_token, chat_id, msg)
                    alerts_sent += 1

            if alerts_sent:
                logger.info(f"Sent {alerts_sent} stock alerts for tenant {tenant_id}")

        except Exception as e:
            logger.error(f"Error stock prediction alert for tenant {tenant_id}: {e}", exc_info=True)


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

scheduler: AsyncIOScheduler | None = None

TESTING_MODE = False

_JOB_FUNCS = {
    "daily_report": _generate_daily_report,
    "weekly_report": _generate_weekly_report,
    "monthly_report": _generate_monthly_report,
    "sales_drop_alert": _check_sales_drop,
    "trending_product_alert": _trending_product_alert,
    "growth_comparison_report": _generate_growth_report,
    "stock_prediction_alert": _check_stock_prediction_alerts,
}


def _make_trigger(job_id: str, hour: int, minute: int) -> CronTrigger:
    if job_id == "weekly_report":
        return CronTrigger(day_of_week="fri", hour=hour, minute=minute, timezone=DHAKA_TZ)
    if job_id == "monthly_report":
        return CronTrigger(day="last", hour=hour, minute=minute, timezone=DHAKA_TZ)
    return CronTrigger(hour=hour, minute=minute, timezone=DHAKA_TZ)


async def start_scheduler():
    """Initialize and start the APScheduler AsyncIOScheduler.

    Times and enabled states are loaded from the DB so admin customisations
    made via the bot's Settings menu persist across restarts.
    """
    global scheduler

    if scheduler and scheduler.running:
        logger.info("Scheduler is already running.")
        return

    from src.services.config_service import SCHEDULE_JOBS, get_job_time, get_job_enabled

    scheduler = AsyncIOScheduler(timezone=DHAKA_TZ)

    disabled_jobs: list[str] = []
    for job_id, job_cfg in SCHEDULE_JOBS.items():
        time_str = await get_job_time(job_id)
        parts = time_str.split(":")
        h, m = int(parts[0]), int(parts[1])

        scheduler.add_job(
            _JOB_FUNCS[job_id],
            trigger=_make_trigger(job_id, h, m),
            id=job_id,
            name=job_cfg["name"],
            replace_existing=True,
        )

        if job_cfg.get("enabled_key") and not await get_job_enabled(job_id):
            disabled_jobs.append(job_id)

    if TESTING_MODE:
        scheduler.add_job(
            _generate_daily_report,
            trigger=IntervalTrigger(minutes=1),
            id="test_report",
            name="Test Report (every 1 min)",
            replace_existing=True,
        )
        scheduler.add_job(
            _generate_daily_report,
            id="initial_test_run",
            name="Initial Test Run",
            next_run_time=datetime.now(DHAKA_TZ),
        )
        logger.info("⚠️  TESTING MODE is ON — report will fire every 1 minute.")

    scheduler.start()

    for job_id in disabled_jobs:
        scheduler.pause_job(job_id)
        logger.info(f"Alert job '{job_id}' is disabled — paused.")

    logger.info("✅ Async report scheduler started successfully.")


def stop_scheduler():
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Report scheduler stopped.")
        scheduler = None


# ---------------------------------------------------------------------------
# Runtime reschedule & toggle (called from bot handlers)
# ---------------------------------------------------------------------------

async def reschedule_job_time(job_id: str, hour: int, minute: int) -> bool:
    """Persist the new time to DB and reschedule the live job immediately."""
    from src.services.config_service import SCHEDULE_JOBS, set_job_time

    if job_id not in SCHEDULE_JOBS or scheduler is None:
        return False

    time_str = f"{hour:02d}:{minute:02d}"
    await set_job_time(job_id, time_str)
    scheduler.reschedule_job(job_id, trigger=_make_trigger(job_id, hour, minute))
    logger.info(f"Job '{job_id}' rescheduled to {time_str}.")
    return True


async def toggle_job_enabled(job_id: str) -> bool | None:
    """Toggle an alert job on or off; persist and apply live."""
    from src.services.config_service import SCHEDULE_JOBS, get_job_enabled, set_job_enabled

    if job_id not in SCHEDULE_JOBS or scheduler is None:
        return None

    cfg = SCHEDULE_JOBS[job_id]
    if not cfg.get("enabled_key"):
        return None  # Always-on job

    is_on = await get_job_enabled(job_id)
    new_state = not is_on
    await set_job_enabled(job_id, new_state)

    if new_state:
        scheduler.resume_job(job_id)
        logger.info(f"Alert job '{job_id}' enabled — resumed.")
    else:
        scheduler.pause_job(job_id)
        logger.info(f"Alert job '{job_id}' disabled — paused.")

    return new_state
