
import asyncio
from src.db.session import async_session
from src.db.models import Order
from sqlalchemy import select

async def list_orders():
    async with async_session() as session:
        res = await session.execute(select(Order).order_by(Order.timestamp.desc()))
        orders = res.scalars().all()
        for o in orders:
            print(f"{o.order_id} | {o.product_name} | {o.platform} | {o.timestamp}")

if __name__ == "__main__":
    asyncio.run(list_orders())
