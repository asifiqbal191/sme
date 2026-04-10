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

    # Web Dashboard
    DASHBOARD_URL: str = "https://your-sme-app.up.railway.app/dashboard"

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
    GOOGLE_CREDENTIALS_JSON: Optional[str] = None # For Railway/Production

    DATABASE_URL: Optional[str] = None # Railway provides this

    @property
    def DATABASE_URI(self) -> str:
        # 1. Check for full connection string (common in Railway/Supabase)
        if self.DATABASE_URL:
            # Convert postgres:// to postgresql+asyncpg:// for SQLAlchemy async
            url = self.DATABASE_URL
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+asyncpg://", 1)
            elif url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            return url

        # 2. Construct from components
        if self.POSTGRES_USER and self.POSTGRES_PASSWORD:
            return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        
        # 3. Fallback to SQLite
        return "sqlite+aiosqlite:///./ordertracker.db"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
