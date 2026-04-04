
import asyncio
from sqlalchemy import select
from src.db.session import async_session
from src.db.models import Order, User

async def check():
    async with async_session() as session:
        # List last 10 orders
        res = await session.execute(select(Order).order_by(Order.timestamp.desc()).limit(10))
        orders = res.scalars().all()
        print("Last 10 Orders:")
        for o in orders:
            print(f"ID={o.order_id}, Product={o.product_name}, Platform={o.platform}, Time={o.timestamp}")
        
        # Check all moderators
        res = await session.execute(select(User))
        users = res.scalars().all()
        print("\nAll Users:")
        for u in users:
            print(f"Name={u.full_name}, ID={u.telegram_id}, Role={u.role}, Platform={u.platform}")

if __name__ == "__main__":
    asyncio.run(check())
