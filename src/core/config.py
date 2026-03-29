from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

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
    TELEGRAM_CHAT_ID: str = ""
    
    # Webhooks & APIs
    FACEBOOK_VERIFY_TOKEN: str = "my_custom_verify_token_123"
    WHATSAPP_VERIFY_TOKEN: str = "my_whatsapp_verify_token_123"
    
    # Google Sheets
    GOOGLE_SHEET_NAME: str = "Orders Dashboard"
    GOOGLE_CREDENTIALS_FILE: str = "service_account.json"
    
    @property
    def DATABASE_URI(self) -> str:
        # Override to use SQLite for easy local testing
        return "sqlite+aiosqlite:///./ordertracker.db"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
