import gspread
import asyncio
from typing import Dict, Any
from src.core.config import settings
from google.oauth2.service_account import Credentials
import logging
from src.services.config_service import get_active_sheet_name

logger = logging.getLogger(__name__)

# Serialize all sheet appends to prevent race conditions from concurrent orders
_sheets_lock = asyncio.Lock()

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
                headers = ["Order ID", "Product", "Qty", "Price", "Platform", "Timestamp", "Status", "Phone"]
                
                if not first_row or first_row[0] != headers[0]:
                    sheet.insert_row(headers, index=1)
                    sheet.freeze(rows=1)
                    logger.info("Inserted headers and froze the first row in Google Sheet.")
                elif len(first_row) < len(headers) or "Phone" not in first_row:
                    sheet.update(values=[headers], range_name='A1:H1')
                    logger.info("Updated headers in Google Sheet to include new columns.")
                    
            except gspread.exceptions.SpreadsheetNotFound:
                logger.error(f"Google Sheet '{settings.GOOGLE_SHEET_NAME}' not found.")
                return
            
            # Format row: Order ID | Product | Qty | Price | Platform | Timestamp | Status | Phone
            phone = order_data.get("phone_number") or ""
            # Prefix phone with apostrophe so Google Sheets treats it as text (preserves leading zeros)
            phone_cell = f"'{phone}" if phone else ""
            row = [
                order_data.get("order_id"),
                order_data.get("product_name"),
                order_data.get("quantity"),
                order_data.get("price"),
                order_data.get("platform"),
                str(order_data.get("timestamp")),
                order_data.get("payment_status"),
                phone_cell
            ]
            
            # Append Row
            sheet.append_row(row, insert_data_option="INSERT_ROWS")
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

    # Serialize appends to prevent race conditions when multiple orders arrive simultaneously
    async with _sheets_lock:
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

async def update_order_field_in_sheets(order_id: str, field: str, new_value):
    """
    Finds the row for order_id and updates a single field column.
    field: 'product' | 'qty' | 'price' | 'phone'
    """
    sheet_name = await get_active_sheet_name()
    if not sheet_name:
        return

    # Column positions match headers: Order ID(1), Product(2), Qty(3), Price(4),
    #                                  Platform(5), Timestamp(6), Status(7), Phone(8)
    col_map = {"product": 2, "qty": 3, "price": 4, "phone": 8}
    col = col_map.get(field)
    if col is None:
        return

    def _sync_update():
        try:
            creds = Credentials.from_service_account_file(
                settings.GOOGLE_CREDENTIALS_FILE,
                scopes=[
                    "https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive"
                ]
            )
            client = gspread.authorize(creds)
            sheet = client.open(sheet_name).sheet1
            try:
                cell = sheet.find(order_id, in_column=1)
                if cell:
                    # Prefix phone with apostrophe to preserve leading zeros in Sheets
                    value_str = f"'{new_value}" if field == "phone" else str(new_value)
                    sheet.update_cell(cell.row, col, value_str)
                    logger.info(f"Updated '{field}' for {order_id} in Google Sheets → {new_value}")
            except gspread.exceptions.CellNotFound:
                logger.warning(f"Order {order_id} not found in Google Sheets. Could not update {field}.")
        except Exception as e:
            logger.error(f"Failed to update field '{field}' in Sheets for {order_id}: {e}")

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _sync_update)


async def update_payment_status_in_sheets(order_id: str, new_status: str):
    """
    Finds the row for order_id in Google Sheets and updates its Status.
    """
    sheet_name = await get_active_sheet_name()
    if not sheet_name:
        logger.warning(f"No Google Sheet active. Can't update status for {order_id}.")
        return

    def _sync_update():
        try:
            creds = Credentials.from_service_account_file(
                settings.GOOGLE_CREDENTIALS_FILE, 
                scopes=[
                    "https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive"
                ]
            )
            client = gspread.authorize(creds)
            sheet = client.open(sheet_name).sheet1
            
            # Find the cell containing the order ID
            try:
                cell = sheet.find(order_id, in_column=1)
                if cell:
                    # Status is the 7th column (G)
                    sheet.update_cell(cell.row, 7, new_status)
                    logger.info(f"Updated status for {order_id} in Google Sheets to {new_status}.")
            except gspread.exceptions.CellNotFound:
                logger.warning(f"Order {order_id} not found in Google Sheets. Could not update status.")
                
        except Exception as e:
            logger.error(f"Failed to update payment status in Sheets for {order_id}: {e}")

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _sync_update)

