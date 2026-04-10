import contextvars
import uuid
from contextlib import contextmanager
from typing import Iterator, Optional

# Global context variable to store the current tenant_id for the current asyncio task.
tenant_id_var: contextvars.ContextVar[Optional[uuid.UUID | str]] = contextvars.ContextVar('tenant_id', default=None)
tenant_scope_disabled_var: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "tenant_scope_disabled",
    default=False,
)

def normalize_tenant_id(tenant_id: uuid.UUID | str | None) -> uuid.UUID | str | None:
    if tenant_id in (None, ""):
        return None
    if isinstance(tenant_id, uuid.UUID):
        return tenant_id
    try:
        return uuid.UUID(str(tenant_id))
    except (ValueError, TypeError):
        return str(tenant_id)

def set_tenant_id(tenant_id: uuid.UUID | str | None):
    return tenant_id_var.set(normalize_tenant_id(tenant_id))

def get_tenant_id() -> Optional[uuid.UUID | str]:
    return tenant_id_var.get()

def is_tenant_scope_disabled() -> bool:
    return tenant_scope_disabled_var.get()

@contextmanager
def without_tenant_scope() -> Iterator[None]:
    """Temporarily bypass tenant filtering for global superadmin operations."""
    token = tenant_scope_disabled_var.set(True)
    try:
        yield
    finally:
        tenant_scope_disabled_var.reset(token)
