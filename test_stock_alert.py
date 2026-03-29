import asyncio
import logging
from src.scheduler.report_scheduler import _check_stock_prediction_alerts

# Setup logging to see what's happening
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def test_alert():
    print("Manually triggering stock prediction alerts check...")
    await _check_stock_prediction_alerts()
    print("Done.")

if __name__ == "__main__":
    asyncio.run(test_alert())
