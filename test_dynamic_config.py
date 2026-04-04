
import asyncio
from src.db.session import async_session, engine
from src.db.models import Base
from src.services.config_service import get_active_sheet_name, set_active_sheet_name

async def test_dynamic_config():
    # 1. Initialize DB (ensure new table exists)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    # 2. Check default
    name = await get_active_sheet_name()
    print(f"Default Sheet Name: {name}") # Should be None
    
    # 3. Set new name
    test_name = "My Dynamic Test Sheet"
    await set_active_sheet_name(test_name)
    print(f"Setting Sheet Name to: {test_name}")
    
    # 4. Verify
    updated_name = await get_active_sheet_name()
    print(f"Updated Sheet Name: {updated_name}")
    
    if updated_name == test_name:
        print("✅ Dynamic Config Test Passed!")
    else:
        print("❌ Dynamic Config Test Failed!")

if __name__ == "__main__":
    asyncio.run(test_dynamic_config())
