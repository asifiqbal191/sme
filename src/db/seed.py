import logging
from sqlalchemy import select
from src.db.session import async_session
from src.db.models import Tenant, User, RoleEnum
from src.core.config import settings

logger = logging.getLogger(__name__)

async def ensure_base_data():
    """
    Ensures that a Primary Tenant and a Superadmin user exist in the database.
    This is critical for fresh deployments on platforms like Railway.
    """
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing. Skipping auto-seed.")
        return

    try:
        async with async_session() as session:
            # 1. Ensure Primary Tenant exists
            result = await session.execute(
                select(Tenant).where(Tenant.bot_token == settings.TELEGRAM_BOT_TOKEN)
            )
            tenant = result.scalar_one_or_none()

            if not tenant:
                logger.info("Auto-seeding: Creating primary tenant...")
                tenant = Tenant(
                    name="Primary Admin",
                    bot_token=settings.TELEGRAM_BOT_TOKEN,
                    is_active=True
                )
                session.add(tenant)
                await session.flush()  # Get tenant ID
            else:
                logger.info(f"Primary tenant '{tenant.name}' already exists.")

            # 2. Ensure Superadmin User exists
            result = await session.execute(
                select(User).where(User.telegram_id == str(settings.TELEGRAM_CHAT_ID))
            )
            user = result.scalar_one_or_none()

            if not user:
                logger.info(f"Auto-seeding: Creating superadmin user for ID {settings.TELEGRAM_CHAT_ID}...")
                user = User(
                    tenant_id=tenant.id,
                    telegram_id=str(settings.TELEGRAM_CHAT_ID),
                    full_name="System Owner",
                    role=RoleEnum.SUPERADMIN
                )
                session.add(user)
            else:
                if user.role != RoleEnum.SUPERADMIN:
                    logger.info(f"Auto-seeding: Promoting user {user.telegram_id} to SUPERADMIN...")
                    user.role = RoleEnum.SUPERADMIN
                if user.tenant_id is None:
                    user.tenant_id = tenant.id

            await session.commit()
            logger.info("✅ Database auto-seeding completed.")

    except Exception as e:
        logger.error(f"Auto-seeding failed: {e}", exc_info=True)
        raise  # Re-raise so main.py can log it, but startup continues
