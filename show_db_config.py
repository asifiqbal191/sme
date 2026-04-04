
import asyncio
from src.services.config_service import get_active_sheet_name, get_active_sheet_url

async def show_db():
    name = await get_active_sheet_name()
    url = await get_active_sheet_url()
    print(f"Spreadsheet Name: {name}")
    print(f"Spreadsheet URL: {url}")

if __name__ == "__main__":
    asyncio.run(show_db())
