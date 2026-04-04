
import asyncio
from sqlalchemy import select
from src.db.session import async_session
from src.db.models import Order, User

async def check():
    async with async_session() as session:
        # Check order 162
        res = await session.execute(select(Order).where(Order.order_id == "162"))
        order = res.scalar_one_or_none()
        if order:
            print(f"Order 162: Platform={order.platform}, ID={order.id}")
        else:
            # Maybe it's like ORD-162?
            res = await session.execute(select(Order).where(Order.order_id.like("%162%")))
            orders = res.scalars().all()
            for o in orders:
                print(f"Found order: order_id={o.order_id}, Platform={o.platform}")
        
        # Also check all moderators
        res = await session.execute(select(User))
        users = res.scalars().all()
        print("\nUsers/Moderators:")
        for u in users:
            print(f"Name={u.full_name}, ID={u.telegram_id}, Role={u.role}, Platform={u.platform}")

if __name__ == "__main__":
    asyncio.run(check())
