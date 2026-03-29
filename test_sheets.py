import asyncio
import gspread
from google.oauth2.service_account import Credentials
from src.core.config import settings

async def test_connection():
    print(f"Testing connection to: {settings.GOOGLE_SHEET_NAME}")
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_file(
            settings.GOOGLE_CREDENTIALS_FILE, scopes=scopes
        )
        client = gspread.authorize(creds)
        sheet = client.open(settings.GOOGLE_SHEET_NAME).sheet1
        print("✅ Connection Successful!")
        print(f"URL: {sheet.url}")
        print(f"Rows: {len(sheet.get_all_values())}")
    except Exception as e:
        print(f"❌ Connection Failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())
