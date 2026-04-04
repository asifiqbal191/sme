import logging
import asyncio
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.services.parser import ParsedOrder
from src.services.sheets import push_to_google_sheets
from src.services import analytics
from src.db.models import Order, PlatformEnum

logger = logging.getLogger(__name__)

async def process_telegram_order(parsed: ParsedOrder, message_id: int, db: AsyncSession, platform: PlatformEnum = PlatformEnum.TELEGRAM) -> Optional[Order]:
    """
    Saves a parsed Telegram order to the database, triggers the Google Sheets sync
    in the background, and returns the Order object.
    """
    try:
        new_order = Order(
            order_id=parsed.order_id or f"ORD-{message_id}",
            product_name=parsed.product_name,
            quantity=parsed.quantity,
            price=parsed.price,
            platform=platform,
            payment_status=parsed.payment_status
        )
        db.add(new_order)
        await db.commit()
        await db.refresh(new_order)

        order_dict = {
            "id": str(new_order.id),
            "order_id": new_order.order_id,
            "product_name": new_order.product_name,
            "quantity": new_order.quantity,
            "price": float(new_order.price),
            "platform": new_order.platform.value,
            "timestamp": new_order.timestamp.isoformat(),
            "payment_status": new_order.payment_status.value
        }
        
        # We fire and forget the push to sheets
        asyncio.create_task(push_to_sheets_safe(order_dict))
        
        logger.info(f"New Telegram order created: {new_order.order_id}")
        return new_order
        
    except Exception as e:
        logger.error(f"Error processing telegram order: {e}", exc_info=True)
        await db.rollback()
        return None

async def push_to_sheets_safe(order_dict: dict):
    """Safely push to google sheets without failing the main request."""
    try:
        await push_to_google_sheets(order_dict)
    except Exception as e:
        logger.error(f"Failed to push order to sheets: {e}")
