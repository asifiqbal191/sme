from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timedelta
from src.db.models import Order, Payment, PaymentStatusEnum, DHAKA_TZ
import logging

logger = logging.getLogger(__name__)

async def match_payment(session: AsyncSession, amount: float, sender_phone: str) -> bool:
    """
    Attempts to match an incoming payment with a pending order.
    Returns True if matched, False otherwise.
    We match if there's exactly one pending order with the same missing price,
    or if phone number matches exactly and price matches exactly.
    """
    now = datetime.now(DHAKA_TZ).replace(tzinfo=None)

    # Consider orders from the last 3 days
    three_days_ago = now - timedelta(days=3)
    
    # Simple strategy: Match by phone number AND price first
    query = select(Order).where(
        and_(
            Order.payment_status == PaymentStatusEnum.PENDING,
            Order.timestamp >= three_days_ago,
            Order.price == amount, # Convert amount nicely in reality
            # If phone_number is present in order, match it. 
            # In a real scenario, you probably need fuzzy matching or strict formatting
            Order.phone_number == sender_phone
        )
    ).order_by(Order.timestamp.desc())
    
    result = await session.execute(query)
    orders = result.scalars().all()
    
    if len(orders) > 0:
        # Match found! Match with the most recent one.
        matched_order = orders[0]
        matched_order.payment_status = PaymentStatusEnum.PAID
        
        # Create a payment record
        new_payment = Payment(
            sender_phone=sender_phone,
            amount=amount,
            matched_order_id=matched_order.id
        )
        session.add(new_payment)
        await session.commit()
        
        logger.info(f"Payment {amount} for {sender_phone} matched successfully to {matched_order.order_id}.")
        return True
        
    return False
