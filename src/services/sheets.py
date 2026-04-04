import gspread
import asyncio
from typing import Dict, Any
from src.core.config import settings
from google.oauth2.service_account import Credentials
import logging
from src.services.config_service import get_active_sheet_name

logger = logging.getLogger(__name__)

async def push_to_google_sheets(order_data: Dict[str, Any]):
    """
    Appends an order row to Google Sheets concurrently.
    The order_data dict should have keys like:
    id, order_id, product_name, quantity, price, platform, timestamp, payment_status, phone_number
    """
    sheet_name = await get_active_sheet_name()
    if not sheet_name:
        logger.warning("No Google Sheet name set in config. Skipping sync.")
        return

    def _sync_append():
        try:
            creds = Credentials.from_service_account_file(
                settings.GOOGLE_CREDENTIALS_FILE, 
                scopes=[
                    "https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive"
                ]
            )
            client = gspread.authorize(creds)
            
            # Open spreadsheet and worksheet
            try:
                sheet = client.open(sheet_name).sheet1
                
                # Ensure headers exist
                first_row = sheet.row_values(1)
                headers = ["Order ID", "Product", "Qty", "Price", "Platform", "Timestamp", "Status"]
                
                if not first_row or first_row[0] != headers[0]:
                    sheet.insert_row(headers, index=1)
                    sheet.freeze(rows=1)
                    logger.info("Inserted headers and froze the first row in Google Sheet.")
                    
            except gspread.exceptions.SpreadsheetNotFound:
                logger.error(f"Google Sheet '{settings.GOOGLE_SHEET_NAME}' not found.")
                return
            
            # Format row: Order ID | Product | Qty | Price | Platform | Timestamp | Status
            row = [
                order_data.get("order_id"),
                order_data.get("product_name"),
                order_data.get("quantity"),
                order_data.get("price"),
                order_data.get("platform"),
                str(order_data.get("timestamp")),
                order_data.get("payment_status")
            ]
            
            # Append Row
            sheet.append_row(row)
            print("Order pushed to Google Sheets successfully")
            logger.info("Order pushed to Google Sheets successfully")
        except FileNotFoundError:
            print(f"Error pushing to Google Sheets: Credentials file '{settings.GOOGLE_CREDENTIALS_FILE}' not found")
            logger.error(f"Credentials file '{settings.GOOGLE_CREDENTIALS_FILE}' not found. Invalid credentials.")
        except Exception as e:
            # Detailed Debug Logging
            print("Error pushing to Google Sheets:", str(e))
            logger.error(f"Failed to append to Google Sheets: {e}")
            logger.error(f"Sheet Name: {settings.GOOGLE_SHEET_NAME}")
            logger.error(f"Data sent: {row if 'row' in locals() else 'None'}")
            raise e

    # Run blocking gspread in threadpool
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _sync_append)

async def check_google_sheets_connection(sheet_name: str = None):
    """
    Attempts to connect to Google Sheets and return row count or error message.
    If sheet_name is None, it uses the active one from DB.
    """
    if not sheet_name:
        sheet_name = await get_active_sheet_name()
        
    if not sheet_name:
        return {"success": False, "error": "❌ No spreadsheet name provided or set in settings."}

    def _sync_check():
        try:
            creds = Credentials.from_service_account_file(
                settings.GOOGLE_CREDENTIALS_FILE, 
                scopes=[
                    "https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive"
                ]
            )
            client = gspread.authorize(creds)
            
            try:
                sheet = client.open(sheet_name).sheet1
                count = len(sheet.get_all_values())
                url = sheet.url
                return {"success": True, "count": count, "url": url}
            except gspread.exceptions.SpreadsheetNotFound:
                return {"success": False, "error": "❌ Sheet not found or not shared"}
            except Exception as e:
                return {"success": False, "error": f"❌ Connection failed: {str(e)}"}
        except FileNotFoundError:
            return {"success": False, "error": "❌ service_account.json not found"}
        except Exception as e:
            return {"success": False, "error": f"❌ Connection failed: {str(e)}"}

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_check)
