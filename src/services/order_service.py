import logging
import asyncio
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.services.parser import ParsedOrder
from src.services.sheets import push_to_google_sheets
from src.db.models import Order, Product, PlatformEnum

logger = logging.getLogger(__name__)

MAX_SHEET_RETRIES = 3
RETRY_DELAY_SECONDS = 5


async def process_telegram_order(parsed: ParsedOrder, message_id: int, db: AsyncSession, platform: PlatformEnum = PlatformEnum.TELEGRAM, created_by_id: str = None) -> Optional[Order]:
    """
    Saves a parsed order to the database, auto-updates the product stock record,
    then fires a Google Sheets sync in the background with retry.
    """
    try:
        new_order = Order(
            order_id=parsed.order_id or f"ORD-{message_id}",
            product_name=parsed.product_name,
            quantity=parsed.quantity,
            price=parsed.price,
            platform=platform,
            payment_status=parsed.payment_status,
            phone_number=parsed.phone_number,
            created_by_id=created_by_id
        )
        db.add(new_order)

        # --- Auto-populate product stock record ---
        result = await db.execute(select(Product).where(Product.name == parsed.product_name))
        product = result.scalar_one_or_none()
        if product:
            # Deduct stock if it is being tracked (stock > 0)
            if product.current_stock > 0:
                product.current_stock = max(0, product.current_stock - parsed.quantity)
        else:
            # First time this product is seen — create entry with 0 stock
            # Admin sets the real stock via /setstock command
            db.add(Product(name=parsed.product_name, current_stock=0))

        await db.commit()
        await db.refresh(new_order)

        order_dict = {
            "id": str(new_order.id),
            "order_id": new_order.order_id,
            "product_name": new_order.product_name,
            "quantity": new_order.quantity,
            "price": float(new_order.price),
            "platform": new_order.platform.value,
            "timestamp": new_order.timestamp.strftime("%Y-%m-%d %I:%M %p"),
            "payment_status": new_order.payment_status.value,
            "phone_number": new_order.phone_number or ""
        }

        # Fire-and-forget Sheets sync with retry + admin alert on failure
        asyncio.create_task(_push_to_sheets_with_retry(order_dict, new_order.order_id))

        logger.info(f"New order created: {new_order.order_id}")
        return new_order

    except Exception as e:
        logger.error(f"Error processing order: {e}", exc_info=True)
        await db.rollback()
        return None


async def _push_to_sheets_with_retry(order_dict: dict, order_id: str):
    """Retry Sheets sync up to MAX_SHEET_RETRIES times, notify admin on total failure."""
    from src.services.notifier import send_admin_alert

    for attempt in range(1, MAX_SHEET_RETRIES + 1):
        try:
            await push_to_google_sheets(order_dict)
            logger.info(f"Sheets sync succeeded for {order_id} on attempt {attempt}.")
            return
        except Exception as e:
            logger.warning(f"Sheets sync attempt {attempt}/{MAX_SHEET_RETRIES} failed for {order_id}: {e}")
            if attempt < MAX_SHEET_RETRIES:
                await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)  # 5s, 10s back-off

    # All retries exhausted
    logger.error(f"All {MAX_SHEET_RETRIES} Sheets sync attempts failed for order {order_id}.")
    await send_admin_alert(
        f"⚠️ *Google Sheets Sync Failed*\n\n"
        f"Order `{order_id}` could not be synced after {MAX_SHEET_RETRIES} attempts.\n"
        f"Please check your Sheets connection in ⚙️ Settings."
    )
