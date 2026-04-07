import httpx
import logging
from src.core.config import settings

logger = logging.getLogger(__name__)


async def send_admin_alert(text: str):
    """Send an alert message to all configured admin report chat IDs."""
    chat_ids = settings.report_chat_ids
    token = settings.TELEGRAM_BOT_TOKEN

    if not chat_ids or not token:
        logger.warning("Cannot send admin alert: no chat IDs or bot token configured.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient() as client:
        for chat_id in chat_ids:
            try:
                await client.post(url, json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "Markdown"
                }, timeout=10)
            except Exception as e:
                logger.error(f"Failed to send alert to {chat_id}: {e}")
