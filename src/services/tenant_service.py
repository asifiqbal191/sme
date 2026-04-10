from sqlalchemy import func, select

from src.core.context import without_tenant_scope
from src.db.models import RoleEnum, Tenant, User
from src.db.session import async_session


def _clean_client_name(name: str) -> str:
    return " ".join((name or "").split())


async def create_tenant(name: str, bot_token: str, google_sheet_name: str | None = None) -> Tenant:
    client_name = _clean_client_name(name)
    token = (bot_token or "").strip()
    sheet_name = (google_sheet_name or "").strip() or None

    if not client_name:
        raise ValueError("Client name is required.")
    if not token:
        raise ValueError("Bot token is required.")

    with without_tenant_scope():
        async with async_session() as session:
            existing_by_name = await session.execute(
                select(Tenant).where(func.lower(Tenant.name) == client_name.lower())
            )
            if existing_by_name.scalar_one_or_none():
                raise ValueError(f"Client '{client_name}' already exists.")

            existing_by_token = await session.execute(
                select(Tenant).where(Tenant.bot_token == token)
            )
            if existing_by_token.scalar_one_or_none():
                raise ValueError("This bot token is already assigned to another client.")

            tenant = Tenant(
                name=client_name,
                bot_token=token,
                google_sheet_name=sheet_name,
                is_active=True,
            )
            session.add(tenant)
            await session.commit()
            await session.refresh(tenant)
            return tenant


async def list_tenants() -> list[dict]:
    with without_tenant_scope():
        async with async_session() as session:
            result = await session.execute(select(Tenant).order_by(Tenant.created_at.asc(), Tenant.name.asc()))
            tenants = result.scalars().all()

            # Fetch all user roles directly to avoid N+1 queries and UUID string formatting bugs in SQLite
            users_res = await session.execute(select(User.tenant_id, User.role))
            all_users = users_res.fetchall()
            
            tenant_admins = {}
            tenant_mods = {}
            for t_id, role in all_users:
                if t_id is None: 
                    continue
                t_str = str(t_id)
                if role == RoleEnum.ADMIN:
                    tenant_admins[t_str] = tenant_admins.get(t_str, 0) + 1
                elif role == RoleEnum.MODERATOR:
                    tenant_mods[t_str] = tenant_mods.get(t_str, 0) + 1

            data: list[dict] = []
            for tenant in tenants:
                t_str = str(tenant.id)
                data.append(
                    {
                        "id": t_str,
                        "name": tenant.name,
                        "is_active": tenant.is_active,
                        "google_sheet_name": tenant.google_sheet_name,
                        "admin_count": tenant_admins.get(t_str, 0),
                        "moderator_count": tenant_mods.get(t_str, 0),
                    }
                )
            return data


async def get_tenant_by_name(name: str) -> Tenant | None:
    client_name = _clean_client_name(name)
    if not client_name:
        return None

    with without_tenant_scope():
        async with async_session() as session:
            result = await session.execute(
                select(Tenant).where(func.lower(Tenant.name) == client_name.lower())
            )
            return result.scalar_one_or_none()
