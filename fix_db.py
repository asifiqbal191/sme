
import asyncio
from sqlalchemy import select, update
from src.db.session import async_session
from src.db.models import Order, User, PlatformEnum

async def fix_db():
    async with async_session() as session:
        # 1. Update moderator 1392310097
        res = await session.execute(select(User).where(User.telegram_id == "1392310097"))
        user = res.scalar_one_or_none()
        if user:
            print(f"Updating user {user.telegram_id} ({user.full_name}) to FACEBOOK")
            user.platform = PlatformEnum.FACEBOOK
        
        # 2. Update order ORD-162 to FACEBOOK
        res = await session.execute(select(Order).where(Order.order_id == "ORD-162"))
        order = res.scalar_one_or_none()
        if order:
            print(f"Updating order {order.order_id} to FACEBOOK")
            order.platform = PlatformEnum.FACEBOOK
            
        # 3. Update order ORD-164 (also from the same time/user) to FACEBOOK
        res = await session.execute(select(Order).where(Order.order_id == "ORD-164"))
        order64 = res.scalar_one_or_none()
        if order64:
            print(f"Updating order {order64.order_id} to FACEBOOK")
            order64.platform = PlatformEnum.FACEBOOK
            
        await session.commit()
        print("Database update complete.")

if __name__ == "__main__":
    asyncio.run(fix_db())
