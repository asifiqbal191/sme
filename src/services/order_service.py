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
) -> tuple[Optional[Order], Optional[str]]:
    """
    Saves a parsed order to the database and decrements product stock.
    Returns (order, None) on success, or (None, error_message) on failure.

    Stock rules:
    - If the product is tracked (exists in Products table) and stock < requested qty → rejected.
    - If the product has never been seen before → order is accepted (admin can set stock later).
    """
    try:
        result = await db.execute(select(Product).where(Product.name == parsed.product_name))
        product = result.scalar_one_or_none()

        # Only enforce stock limit when the product is already being tracked
        if product is not None:
            if product.current_stock <= 0:
                return None, (
                    f"❌ *Out of Stock*\n\n"
                    f"*{parsed.product_name}* currently has *0* units available.\n"
                    f"Please contact the admin to restock before placing this order."
                )
            if product.current_stock < parsed.quantity:
                return None, (
                    f"❌ *Insufficient Stock*\n\n"
                    f"*{parsed.product_name}* only has *{product.current_stock}* unit(s) left.\n"
                    f"You requested *{parsed.quantity}* unit(s). Please adjust the quantity."
                )

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

        if product:
            product.current_stock -= parsed.quantity
        else:
            # First time this product appears — create a placeholder (stock not yet set)
            db.add(Product(name=parsed.product_name, current_stock=0))

        await db.commit()
        await db.refresh(new_order)

        logger.info(f"New order saved: {new_order.order_id}")
        return new_order, None

    except Exception as e:
        logger.error(f"Error processing order: {e}", exc_info=True)
        await db.rollback()
        return None, "❌ Failed to save the order due to an internal error. Please try again."
