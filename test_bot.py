import asyncio
import logging
from src.bot.telegram_bot import create_bot_application
from src.db.session import engine
from src.db.models import Base

logging.basicConfig(level=logging.INFO)

async def test():
    print("Test: Initializing DB...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    print("Test: Initializing Bot...")
    app = await create_bot_application()
    await app.initialize()
    await app.start()
    
    print("Test: Starting Polling... (will stop in 10s)")
    await app.updater.start_polling(drop_pending_updates=True)
    
    await asyncio.sleep(10)
    
    print("Test: Stopping Bot...")
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    print("Test: Finished.")

if __name__ == "__main__":
    asyncio.run(test())
