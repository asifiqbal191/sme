
import asyncio
from src.db.session import async_session
from src.services.analytics import get_daily_sales

async def check_sales():
    async with async_session() as session:
        stats = await get_daily_sales(session)
        print(f"Total Sales for Today: ৳{stats['total_sales']:,.2f}")
        print(f"Total Orders: {stats['total_orders']}")

if __name__ == "__main__":
    asyncio.run(check_sales())
