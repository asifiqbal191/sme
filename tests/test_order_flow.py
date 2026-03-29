import asyncio
import os
import sys

# Add project root to sys.path
sys.path.append(os.getcwd())

from src.services.parser import parse_order_message
from src.services.sheets import push_to_google_sheets
from datetime import datetime, timezone

async def test_parsing():
    message = """#ORDER
ID: TEST-001
Product: Shirt
Qty: 1
Price: 500"""
    parsed = parse_order_message(message)
    print(f"Parsed Order: {parsed}")
    assert parsed.order_id == "TEST-001"
    assert parsed.product_name == "Shirt"
    assert parsed.quantity == 1
    assert parsed.price == 500.0

async def test_sheets_push():
    order_data = {
        "order_id": "TEST-001",
        "product_name": "Shirt",
        "quantity": 1,
        "price": 500.0,
        "platform": "TELEGRAM",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payment_status": "PENDING"
    }
    print(f"Pushing data: {order_data}")
    try:
        await push_to_google_sheets(order_data)
        print("Test push successful (Check your Google Sheet!)")
    except Exception as e:
        print(f"Test push failed: {e}")

if __name__ == "__main__":
    print("Starting verification tests...")
    asyncio.run(test_parsing())
    # Note: Running sheets push requires valid credentials and sheet name in .env
    asyncio.run(test_sheets_push())
    print("Verification completed.")
