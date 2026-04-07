from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List

class Settings(BaseSettings):
    PROJECT_NAME: str = "Multi-Platform Order Tracking Agent"

    # Database Settings
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: str = "5432"
    POSTGRES_DB: str = "ordertracker"

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""  # Primary admin chat ID (used for auto-promotion)
    TELEGRAM_REPORT_CHAT_IDS: str = ""  # Additional report recipients, comma-separated

    @property
    def report_chat_ids(self) -> List[str]:
        """Returns all chat IDs that should receive scheduled reports (primary admin + extras)."""
        ids = [self.TELEGRAM_CHAT_ID] if self.TELEGRAM_CHAT_ID else []
        if self.TELEGRAM_REPORT_CHAT_IDS:
            extras = [cid.strip() for cid in self.TELEGRAM_REPORT_CHAT_IDS.split(",") if cid.strip()]
            for cid in extras:
                if cid not in ids:
                    ids.append(cid)
        return ids

    # Google Sheets
    GOOGLE_SHEET_NAME: str = "Orders Dashboard"
    GOOGLE_CREDENTIALS_FILE: str = "service_account.json"

    @property
    def DATABASE_URI(self) -> str:
        # Override to use SQLite for easy local testing
        return "sqlite+aiosqlite:///./ordertracker.db"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
