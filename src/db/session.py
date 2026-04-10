from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria
from src.core.config import settings
from src.core.context import get_tenant_id, is_tenant_scope_disabled

engine = create_async_engine(settings.DATABASE_URI, echo=False)

async_session = async_sessionmaker(
    engine, expire_on_commit=False
)

from src.db.models import Base

@event.listens_for(Session, "do_orm_execute")
def _add_tenant_filter(execute_state):
    tenant_id = get_tenant_id()
    if tenant_id is not None and not is_tenant_scope_disabled():
        if execute_state.is_select or execute_state.is_update or execute_state.is_delete:
            execute_state.statement = execute_state.statement.options(
                with_loader_criteria(
                    Base,
                    lambda cls: cls.tenant_id == tenant_id if hasattr(cls, 'tenant_id') else True,
                    include_aliases=True,
                    track_closure_variables=False,
                )
            )

@event.listens_for(Session, "before_flush")
def _receive_before_flush(session, flush_context, instances):
    tenant_id = get_tenant_id()
    if tenant_id is not None and not is_tenant_scope_disabled():
        for obj in session.new:
            if hasattr(obj, 'tenant_id') and getattr(obj, 'tenant_id') is None:
                obj.tenant_id = tenant_id

async def get_db():
    async with async_session() as session:
        yield session
