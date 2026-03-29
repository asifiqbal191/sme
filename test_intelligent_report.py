import asyncio
import logging
from src.scheduler.report_scheduler import _generate_daily_report

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def test_report():
    print("Manually triggering intelligent daily report...")
    await _generate_daily_report()
    print("Done.")

if __name__ == "__main__":
    asyncio.run(test_report())
