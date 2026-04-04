
from sqlalchemy import select
from src.db.session import async_session
from src.db.models import GlobalConfig
from src.core.config import settings

async def get_config(key: str) -> str | None:
    async with async_session() as session:
        result = await session.execute(select(GlobalConfig).where(GlobalConfig.key == key))
        config = result.scalar_one_or_none()
        return config.value if config else None

async def set_config(key: str, value: str):
    async with async_session() as session:
        result = await session.execute(select(GlobalConfig).where(GlobalConfig.key == key))
        config = result.scalar_one_or_none()
        
        if config:
            config.value = value
        else:
            new_config = GlobalConfig(key=key, value=value)
            session.add(new_config)
            
        await session.commit()

async def get_active_sheet_name() -> str | None:
    """Returns the spreadsheet name from DB, or None if not set."""
    return await get_config("google_sheet_name")

async def set_active_sheet_name(name: str):
    await set_config("google_sheet_name", name)

async def get_active_sheet_url() -> str | None:
    """Returns the spreadsheet URL from DB, or None if not set."""
    return await get_config("google_sheet_url")

async def set_active_sheet_url(url: str):
    await set_config("google_sheet_url", url)
