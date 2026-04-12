import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.services.parser import ParsedOrder
from src.db.models import Order, Product, PlatformEnum

logger = logging.getLogger(__name__)


async def process_telegram_order(
    parsed: ParsedOrder,
    message_id: int,
    db: AsyncSession,
    platform: PlatformEnum = PlatformEnum.TELEGRAM,
    created_by_id: str = None,
) -> Optional[Order]:
    """
    Saves a parsed order to the database and auto-updates the product stock record.
    Orders are stored in PostgreSQL — use /export to download as Excel.
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
            created_by_id=created_by_id,
        )
        db.add(new_order)

        # Auto-populate product stock record
        result = await db.execute(select(Product).where(Product.name == parsed.product_name))
        product = result.scalar_one_or_none()
        if product:
            if product.current_stock > 0:
                product.current_stock = max(0, product.current_stock - parsed.quantity)
        else:
            # First time this product is seen — create entry with 0 stock
            db.add(Product(name=parsed.product_name, current_stock=0))

        await db.commit()
        await db.refresh(new_order)

        logger.info(f"New order saved: {new_order.order_id}")
        return new_order

    except Exception as e:
        logger.error(f"Error processing order: {e}", exc_info=True)
        await db.rollback()
        return None
