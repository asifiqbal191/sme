import asyncio
from src.db.session import engine
from src.db.models import Base

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        print("DB schema initialized/updated")

if __name__ == "__main__":
    asyncio.run(init_db())
