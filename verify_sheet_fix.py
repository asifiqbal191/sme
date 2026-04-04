
import asyncio
from src.db.session import async_session
from src.services.config_service import set_active_sheet_name, set_active_sheet_url, get_active_sheet_url

async def verify_fix():
    # 1. Set a mock sheet and URL
    await set_active_sheet_name("Fix Verification Sheet")
    await set_active_sheet_url("https://docs.google.com/spreadsheets/d/verify123")
    
    # 2. Verify retrieval
    url = await get_active_sheet_url()
    print(f"Stored URL: {url}")
    
    if url == "https://docs.google.com/spreadsheets/d/verify123":
        print("✅ Sheet URL Persistence Test Passed!")
    else:
        print("❌ Sheet URL Persistence Test Failed!")

if __name__ == "__main__":
    asyncio.run(verify_fix())
