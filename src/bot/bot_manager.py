import logging
import asyncio
from typing import Dict, Optional

from telegram.ext import Application
from src.db.session import async_session
from sqlalchemy import select
from src.db.models import Tenant

logger = logging.getLogger(__name__)

class BotManager:
    def __init__(self):
        # Maps tenant_id (str) -> Application
        self.active_bots: Dict[str, Application] = {}
        # Maps bot_token (str) -> tenant_id (str)
        self.token_to_tenant: Dict[str, str] = {}
        
    def get_tenant_id_from_token(self, token: str) -> Optional[str]:
        """Returns the tenant ID associated with a given bot token. This is used by handlers."""
        return self.token_to_tenant.get(token)

    async def start_all_tenant_bots(self):
        """Starts a bot runner for every active tenant in the database."""
        async with async_session() as session:
            result = await session.execute(select(Tenant).where(Tenant.is_active == True))
            tenants = result.scalars().all()
            
        logger.info(f"Found {len(tenants)} active tenants. Starting bots...")
        for tenant in tenants:
            await self.start_tenant_bot(tenant)

    async def start_tenant_bot(self, tenant):
        """Build and start a bot for a specific tenant."""
        from src.bot.telegram_bot import create_bot_application
        
        tenant_id_str = str(tenant.id)
        if tenant_id_str in self.active_bots:
            logger.warning(f"Bot for tenant {tenant.name} is already running.")
            return self.active_bots[tenant_id_str]

        try:
            logger.info(f"Starting bot for {tenant.name}...")
            app = await create_bot_application(tenant.bot_token)
            
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            
            self.active_bots[tenant_id_str] = app
            self.token_to_tenant[tenant.bot_token] = tenant_id_str
            logger.info(f"Bot for {tenant.name} started successfully.")
            return app
        except Exception as e:
            logger.error(f"Failed to start bot for tenant {tenant.name}: {e}")
            return None

    def get_bot_username(self, tenant_id: str) -> Optional[str]:
        app = self.active_bots.get(str(tenant_id))
        if not app:
            return None
        return getattr(app.bot, "username", None)

    async def stop_all_bots(self):
        """Stops all running bot instances safely."""
        logger.info("Stopping all bots...")
        for tenant_id, app in self.active_bots.items():
            try:
                await app.updater.stop()
                await app.stop()
                await app.shutdown()
            except Exception as e:
                logger.error(f"Error stopping bot for tenant {tenant_id}: {e}")
                
        self.active_bots.clear()
        self.token_to_tenant.clear()

# Global bot manager instance
bot_manager = BotManager()
