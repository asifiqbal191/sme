import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import src.auth.roles as roles
import src.services.tenant_service as tenant_service
from src.core.context import set_tenant_id, tenant_id_var
from src.db.models import Base, Invite, RoleEnum, Tenant, User


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def temp_session_factory(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    run(setup())
    monkeypatch.setattr(roles, "async_session", session_factory)
    monkeypatch.setattr(tenant_service, "async_session", session_factory)
    yield session_factory
    run(engine.dispose())


def test_primary_superadmin_is_global_and_not_duplicated(temp_session_factory, monkeypatch):
    monkeypatch.setattr(roles.settings, "TELEGRAM_CHAT_ID", "999001")
    token = set_tenant_id("tenant-scope-a")

    try:
        first = run(roles.get_user_role("999001"))
        second = run(roles.get_user_role("999001"))
    finally:
        tenant_id_var.reset(token)

    assert first == RoleEnum.SUPERADMIN
    assert second == RoleEnum.SUPERADMIN

    async def check():
        async with temp_session_factory() as session:
            result = await session.execute(
                select(User).where(
                    User.telegram_id == "999001",
                    User.role == RoleEnum.SUPERADMIN,
                )
            )
            return result.scalars().all()

    users = run(check())
    assert len(users) == 1
    assert users[0].tenant_id is None


def test_create_tenant_and_list_clients(temp_session_factory):
    tenant = run(tenant_service.create_tenant("Lux", "token-lux", "Lux Sheet"))
    clients = run(tenant_service.list_tenants())

    assert isinstance(tenant, Tenant)
    assert len(clients) == 1
    assert clients[0]["name"] == "Lux"
    assert clients[0]["google_sheet_name"] == "Lux Sheet"
    assert clients[0]["admin_count"] == 0
    assert clients[0]["moderator_count"] == 0


def test_admin_invite_redeem_stays_bound_to_tenant(temp_session_factory, monkeypatch):
    monkeypatch.setattr(roles.settings, "TELEGRAM_CHAT_ID", "owner-1")
    tenant = run(tenant_service.create_tenant("Nivea", "token-nivea"))
    admin_code = run(roles.generate_admin_invite_code(str(tenant.id)))

    token = set_tenant_id(str(tenant.id))
    try:
        result = run(roles.redeem_invite_code("admin-telegram-1", "Nivea Admin", admin_code))
    finally:
        tenant_id_var.reset(token)

    assert result == RoleEnum.ADMIN

    async def check():
        async with temp_session_factory() as session:
            invite_result = await session.execute(select(Invite).where(Invite.code == admin_code))
            user_result = await session.execute(select(User).where(User.telegram_id == "admin-telegram-1"))
            return invite_result.scalar_one(), user_result.scalar_one()

    invite, user = run(check())
    assert str(invite.tenant_id) == str(tenant.id)
    assert str(user.tenant_id) == str(tenant.id)
    assert user.role == RoleEnum.ADMIN
