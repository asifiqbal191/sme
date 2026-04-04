"""
🚀 SME Order Tracker
Starts the FastAPI server and Telegram Bot.

Usage:
    python start.py
    python start.py --port 8080
"""

import os
import sys
import argparse
import subprocess
import time
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("launcher")


def main():
    # ── VENV AUTO-SWITCHER ──
    # If the user types 'python start.py' instead of using start.bat, 
    # this will automatically reroute them to the .venv python!
    if sys.prefix == sys.base_prefix:
        venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "Scripts", "python.exe")
        if os.path.exists(venv_python):
            logger.info("🔄 Redirecting to virtual environment Python...")
            os.execl(venv_python, venv_python, *sys.argv)
            
    parser = argparse.ArgumentParser(description="Launch SME Order Tracker bot")
    parser.add_argument("--port", type=int, default=8000, help="Port for FastAPI background tasks (default: 8000)")
    args = parser.parse_args()

    port = args.port

    print(f"\n🚀 Starting System on http://127.0.0.1:{port}\n")

    try:
        import uvicorn
        logger.info(f"🚀 Starting FastAPI server on port {port}...")
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=port,
            reload=True,
            log_level="info",
        )
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down...")
    except ImportError:
        logger.error("❌ uvicorn is not installed. Please run `pip install -r requirements.txt`")

if __name__ == "__main__":
    main()
