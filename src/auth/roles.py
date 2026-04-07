import logging
import secrets
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy.future import select

from src.db.session import async_session
from src.db.models import User, RoleEnum, Invite, PlatformEnum
from src.core.config import settings

logger = logging.getLogger(__name__)

async def get_user_role(telegram_id: str) -> RoleEnum | None:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        
        # Auto-promote configured admin if no role is found
        if not user and str(telegram_id) == str(settings.TELEGRAM_CHAT_ID):
            logger.info(f"Auto-promoting {telegram_id} to ADMIN from config.")
            new_admin = User(telegram_id=telegram_id, role=RoleEnum.ADMIN)
            session.add(new_admin)
            await session.commit()
            return RoleEnum.ADMIN
            
        if user and user.is_banned:
            return None
            
        return user.role if user else None

def require_admin(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = str(update.effective_user.id)
        role = await get_user_role(user_id)
        if role != RoleEnum.ADMIN:
            if update.effective_message:
                if role == RoleEnum.MODERATOR:
                    await update.effective_message.reply_text("⛔ Access Denied. Admin privileges required to view or click this.")
                else:
                    msg = "⛔ **Access Denied**\n\nYou are not connected yet! To get access, please enter the invitation code provided by your Admin like so:\n\n👉 `/join INV-XXXX`"
                    await update.effective_message.reply_text(msg, parse_mode="Markdown")
            elif update.callback_query:
                await update.callback_query.answer("⛔ Access Denied. Admin privileges required.", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def require_moderator_or_admin(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = str(update.effective_user.id)
        role = await get_user_role(user_id)
        if role not in (RoleEnum.ADMIN, RoleEnum.MODERATOR):
            if update.effective_message:
                msg = "⛔ **Access Denied**\n\nYou are not connected yet! To get access, please enter the invitation code provided by your Admin like so:\n\n👉 `/join INV-XXXX`"
                await update.effective_message.reply_text(msg, parse_mode="Markdown")
            elif update.callback_query:
                 await update.callback_query.answer("⛔ Access Denied. You must join via an invite code first.", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

async def generate_invite_code(platform: PlatformEnum = None) -> str:
    code = f"INV-{secrets.token_hex(4).upper()}"
    async with async_session() as session:
        invite = Invite(code=code, platform=platform, role=RoleEnum.MODERATOR)
        session.add(invite)
        await session.commit()
    return code

async def generate_admin_invite_code() -> str | None:
    """Generates a one-time admin invite. Returns None if a secondary admin already exists."""
    async with async_session() as session:
        existing = await session.execute(
            select(User).where(User.role == RoleEnum.ADMIN, User.telegram_id != settings.TELEGRAM_CHAT_ID)
        )
        if existing.scalar_one_or_none():
            return None  # Already has a secondary admin

        code = f"ADM-{secrets.token_hex(4).upper()}"
        invite = Invite(code=code, role=RoleEnum.ADMIN)
        session.add(invite)
        await session.commit()
    return code

async def redeem_invite_code(telegram_id: str, full_name: str, code: str) -> bool | str:
    """Returns True if successful, or an error string."""
    async with async_session() as session:
        # Check if invite is valid
        result = await session.execute(select(Invite).where(Invite.code == code, Invite.is_used == False))
        invite = result.scalar_one_or_none()
        if not invite:
            return "Invalid or already used invite code."

        # Check if user already exists
        user_result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_result.scalar_one_or_none()
        if user:
            return "You are already registered."

        # For admin invites, enforce max 1 secondary admin
        if invite.role == RoleEnum.ADMIN:
            existing = await session.execute(
                select(User).where(User.role == RoleEnum.ADMIN, User.telegram_id != settings.TELEGRAM_CHAT_ID)
            )
            if existing.scalar_one_or_none():
                return "Admin slot is already filled. Contact your primary admin."

        # Mark invite and create user with the role from the invite
        assigned_role = invite.role
        invite.is_used = True
        invite.used_by = telegram_id

        new_user = User(telegram_id=telegram_id, full_name=full_name, role=assigned_role, platform=invite.platform)
        session.add(new_user)
        session.add(invite)
        await session.commit()
        return assigned_role

async def get_secondary_admin() -> dict | None:
    """Returns the secondary admin (non-primary) if one exists."""
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.role == RoleEnum.ADMIN, User.telegram_id != settings.TELEGRAM_CHAT_ID)
        )
        user = result.scalar_one_or_none()
        if user:
            return {"id": user.telegram_id, "name": user.full_name or "Unknown"}
        return None

async def remove_secondary_admin(telegram_id: str) -> bool:
    """Removes a secondary admin. Cannot remove the primary admin."""
    async with async_session() as session:
        result = await session.execute(
            select(User).where(
                User.telegram_id == telegram_id,
                User.role == RoleEnum.ADMIN,
                User.telegram_id != settings.TELEGRAM_CHAT_ID
            )
        )
        user = result.scalar_one_or_none()
        if user:
            await session.delete(user)
            await session.commit()
            return True
        return False

async def add_moderator(telegram_id: str, full_name: str = None) -> bool:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user:
            return False
        
        new_user = User(telegram_id=telegram_id, full_name=full_name, role=RoleEnum.MODERATOR)
        session.add(new_user)
        await session.commit()
        return True

async def set_ban_status(telegram_id: str, is_banned: bool) -> bool:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user and user.role != RoleEnum.ADMIN:
            user.is_banned = is_banned
            await session.commit()
            return True
        return False

async def get_all_moderators() -> list[dict]:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.role == RoleEnum.MODERATOR))
        users = result.scalars().all()
        return [{
            "id": u.telegram_id, 
            "name": u.full_name or "Unknown",
            "platform": u.platform,
            "is_banned": u.is_banned
        } for u in users]

async def get_user_platform(telegram_id: str) -> PlatformEnum | None:
    """Gets the platform of the specific user. Returns None if not set."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user and user.platform:
            return user.platform
        return None
