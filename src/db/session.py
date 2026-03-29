from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from src.core.config import settings

engine = create_async_engine(settings.DATABASE_URI, echo=False)

async_session = async_sessionmaker(
    engine, expire_on_commit=False
)

async def get_db():
    async with async_session() as session:
        yield session
