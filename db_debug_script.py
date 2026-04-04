
import asyncio
from sqlalchemy import select
from src.db.session import async_session
from src.db.models import Order, User

async def check():
    async with async_session() as session:
        # List last 10 orders
        res = await session.execute(select(Order).order_by(Order.timestamp.desc()).limit(20))
        orders = res.scalars().all()
        
        with open("f:/SME/db_debug.txt", "w", encoding="utf-8") as f:
            f.write("Last 20 Orders:\n")
            for o in orders:
                f.write(f"ID={o.order_id}, Product={o.product_name}, Platform={o.platform}, Time={o.timestamp}\n")
            
            # Check all moderators
            res = await session.execute(select(User))
            users = res.scalars().all()
            f.write("\nAll Users:\n")
            for u in users:
                f.write(f"Name={u.full_name}, ID={u.telegram_id}, Role={u.role}, Platform={u.platform}\n")

if __name__ == "__main__":
    asyncio.run(check())
