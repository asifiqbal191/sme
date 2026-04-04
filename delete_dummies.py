
import asyncio
from src.db.session import async_session
from src.db.models import Order
from sqlalchemy import delete

async def delete_dummies():
    async with async_session() as session:
        # Delete orders with TEST in ID
        query = delete(Order).where(Order.order_id.like("%TEST%"))
        result = await session.execute(query)
        deleted_count = result.rowcount
        
        # Also delete TEST-001 if not caught
        query2 = delete(Order).where(Order.order_id == "TEST-001")
        result2 = await session.execute(query2)
        deleted_count += result2.rowcount
        
        await session.commit()
        print(f"Deleted {deleted_count} dummy orders.")

if __name__ == "__main__":
    asyncio.run(delete_dummies())
