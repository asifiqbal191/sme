import logging
import secrets
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy.future import select

from src.core.context import get_tenant_id, normalize_tenant_id, without_tenant_scope
from src.db.session import async_session
from src.db.models import User, RoleEnum, Invite, PlatformEnum
from src.core.config import settings
from src.services import config_service

logger = logging.getLogger(__name__)
ADMIN_ROLES = (RoleEnum.ADMIN, RoleEnum.SUPERADMIN)
MANAGEMENT_ROLES = (RoleEnum.ADMIN, RoleEnum.MODERATOR, RoleEnum.SUPERADMIN)

def _resolve_target_tenant_id(tenant_id: str | None = None) -> str | None:
    return normalize_tenant_id(tenant_id or get_tenant_id())

async def _ensure_primary_superadmin(telegram_id: str) -> RoleEnum | None:
    if str(telegram_id) != str(settings.TELEGRAM_CHAT_ID):
        return None

    with without_tenant_scope():
        async with async_session() as session:
            result = await session.execute(
                select(User).where(
                    User.telegram_id == telegram_id,
                    User.role == RoleEnum.SUPERADMIN,
                    User.tenant_id == None,  # noqa: E711
                )
            )
            user = result.scalar_one_or_none()
            if user:
                return None if user.is_banned else RoleEnum.SUPERADMIN

            logger.info("Auto-promoting %s to SUPERADMIN from config.", telegram_id)
            session.add(
                User(
                    telegram_id=telegram_id,
                    role=RoleEnum.SUPERADMIN,
                    tenant_id=None,
                )
            )
            await session.commit()
            return RoleEnum.SUPERADMIN

async def get_user_role(telegram_id: str) -> RoleEnum | None:
    superadmin_role = await _ensure_primary_superadmin(telegram_id)
    if superadmin_role is not None:
        return superadmin_role

    tid = normalize_tenant_id(get_tenant_id())
    async with async_session() as session:
        # Filter by both telegram_id AND tenant_id to support multi-tenant access
        query = select(User).where(User.telegram_id == telegram_id)
        if tid:
            query = query.where(User.tenant_id == tid)
            
        result = await session.execute(query)
        user = result.scalar_one_or_none()

        if user and user.is_banned:
            return None

        return user.role if user else None

def require_superadmin(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = str(update.effective_user.id)
        if user_id != str(settings.TELEGRAM_CHAT_ID):
            if update.effective_message:
                await update.effective_message.reply_text("⛔ Access Denied. Superadmin privileges required.")
            elif update.callback_query:
                await update.callback_query.answer("⛔ Access Denied. Superadmin privileges required.", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def require_admin(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = str(update.effective_user.id)
        role = await get_user_role(user_id)
        if role not in ADMIN_ROLES:
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

def require_spreadsheet(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        
        # Check if a spreadsheet is connected
        sheet_name = await config_service.get_active_sheet_name()
        if not sheet_name:
            user_id = str(update.effective_user.id)
            role = await get_user_role(user_id)
            
            # Message for Admin/Superadmin
            if role in ADMIN_ROLES:
                msg = (
                    "📊 **Spreadsheet Required**\n\n"
                    "Before you can use any tracking features, you must connect a Google Spreadsheet.\n\n"
                    "**Why?** This ensures all coordinates and orders are safely backed up in real-time.\n\n"
                    "Tap the button below to start the connection guide:"
                )
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Connect Spreadsheet", callback_data="cmd_manage_sheets")]])
            else:
                # Message for Moderators
                msg = (
                    "⚠️ **System Not Ready**\n\n"
                    "Your Admin has not connected a Google Spreadsheet yet. "
                    "Features will be enabled once the setup is complete.\n\n"
                    "Please notify your Admin to link a spreadsheet."
                )
                keyboard = None

            if update.effective_message:
                await update.effective_message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)
            elif update.callback_query:
                await update.callback_query.answer("⚠️ Spreadsheet connection required.", show_alert=True)
            return
            
        return await func(update, context, *args, **kwargs)
    return wrapper

def require_moderator_or_admin(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = str(update.effective_user.id)
        role = await get_user_role(user_id)
        if role not in MANAGEMENT_ROLES:
            if update.effective_message:
                msg = "⛔ **Access Denied**\n\nYou are not connected yet! To get access, please enter the invitation code provided by your Admin like so:\n\n👉 `/join INV-XXXX`"
                await update.effective_message.reply_text(msg, parse_mode="Markdown")
            elif update.callback_query:
                 await update.callback_query.answer("⛔ Access Denied. You must join via an invite code first.", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

async def generate_invite_code(platform: PlatformEnum = None, tenant_id: str | None = None) -> str:
    code = f"INV-{secrets.token_hex(4).upper()}"
    target_tenant_id = _resolve_target_tenant_id(tenant_id)

    if tenant_id is not None:
        with without_tenant_scope():
            async with async_session() as session:
                session.add(
                    Invite(
                        code=code,
                        platform=platform,
                        role=RoleEnum.MODERATOR,
                        tenant_id=target_tenant_id,
                    )
                )
                await session.commit()
                return code

    async with async_session() as session:
        session.add(
            Invite(
                code=code,
                platform=platform,
                role=RoleEnum.MODERATOR,
                tenant_id=target_tenant_id,
            )
        )
        await session.commit()
        return code

async def generate_admin_invite_code(tenant_id: str | None = None) -> str | None:
    """Generate a one-time tenant admin invite."""
    target_tenant_id = _resolve_target_tenant_id(tenant_id)
    if target_tenant_id is None:
        return None

    with without_tenant_scope():
        async with async_session() as session:
            existing = await session.execute(
                select(User).where(
                    User.role == RoleEnum.ADMIN,
                    User.tenant_id == target_tenant_id,
                )
            )
            if existing.scalar_one_or_none():
                return None

            code = f"ADM-{secrets.token_hex(4).upper()}"
            session.add(Invite(code=code, role=RoleEnum.ADMIN, tenant_id=target_tenant_id))
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

        # Check if user already exists IN THIS TENANT
        user_result = await session.execute(
            select(User).where(
                User.telegram_id == telegram_id,
                User.tenant_id == invite.tenant_id
            )
        )
        user = user_result.scalar_one_or_none()
        if user:
            return "You are already registered for this client."

        # For admin invites, enforce max 1 tenant admin
        if invite.role == RoleEnum.ADMIN:
            with without_tenant_scope():
                existing = await session.execute(
                    select(User).where(
                        User.role == RoleEnum.ADMIN,
                        User.tenant_id == invite.tenant_id,
                    )
                )
                if existing.scalar_one_or_none():
                    return "Admin slot is already filled for this client."

        # Mark invite and create user with the role from the invite
        invite.is_used = True
        invite.used_by = telegram_id

        new_user = User(
            telegram_id=telegram_id,
            full_name=full_name,
            role=invite.role,
            platform=invite.platform,
            tenant_id=invite.tenant_id,
        )
        session.add(new_user)
        session.add(invite)
        await session.commit()
        return invite.role

async def get_tenant_admin(tenant_id: str | None = None) -> dict | None:
    target_tenant_id = _resolve_target_tenant_id(tenant_id)
    if target_tenant_id is None:
        return None

    with without_tenant_scope():
        async with async_session() as session:
            result = await session.execute(
                select(User).where(
                    User.role == RoleEnum.ADMIN,
                    User.tenant_id == target_tenant_id,
                )
            )
            user = result.scalar_one_or_none()
            if user:
                return {"id": user.telegram_id, "name": user.full_name or "Unknown"}
            return None

async def remove_tenant_admin(telegram_id: str, tenant_id: str | None = None) -> bool:
    target_tenant_id = _resolve_target_tenant_id(tenant_id)
    if target_tenant_id is None:
        return False

    with without_tenant_scope():
        async with async_session() as session:
            result = await session.execute(
                select(User).where(
                    User.telegram_id == telegram_id,
                    User.role == RoleEnum.ADMIN,
                    User.tenant_id == target_tenant_id,
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
        if user and user.role not in ADMIN_ROLES:
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
