import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Numeric, DateTime, Enum as SAEnum, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from typing import Optional
import enum
import pytz

# Bangladesh local timezone
DHAKA_TZ = pytz.timezone("Asia/Dhaka")

def now_local():
    """Returns current time in Bangladesh (Asia/Dhaka) as a naive datetime for DB storage."""
    return datetime.now(DHAKA_TZ).replace(tzinfo=None)

class Base(DeclarativeBase):
    pass

class PlatformEnum(str, enum.Enum):
    FACEBOOK = "FACEBOOK"
    WHATSAPP = "WHATSAPP"
    TELEGRAM = "TELEGRAM"

class PaymentStatusEnum(str, enum.Enum):
    PENDING = "PENDING"
    PAID = "PAID"

class RoleEnum(str, enum.Enum):
    ADMIN = "ADMIN"
    MODERATOR = "MODERATOR"

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    telegram_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[RoleEnum] = mapped_column(SAEnum(RoleEnum))
    platform: Mapped[Optional[PlatformEnum]] = mapped_column(SAEnum(PlatformEnum), nullable=True)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)

class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    used_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    platform: Mapped[Optional[PlatformEnum]] = mapped_column(SAEnum(PlatformEnum), nullable=True)
    role: Mapped[RoleEnum] = mapped_column(SAEnum(RoleEnum), default=RoleEnum.MODERATOR)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)

class Order(Base):
    __tablename__ = "orders"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    product_name: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    price: Mapped[float] = mapped_column(Numeric(10, 2))
    platform: Mapped[PlatformEnum] = mapped_column(SAEnum(PlatformEnum))
    payment_status: Mapped[PaymentStatusEnum] = mapped_column(SAEnum(PaymentStatusEnum), default=PaymentStatusEnum.PENDING)
    phone_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_by_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=now_local)

class Payment(Base):
    __tablename__ = "payments"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    sender_phone: Mapped[str] = mapped_column(String(20), index=True)
    amount: Mapped[float] = mapped_column(Numeric(10, 2))
    matched_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=now_local)

class Product(Base):
    __tablename__ = "products"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    current_stock: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)

class GlobalConfig(Base):
    __tablename__ = "global_config"
    
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)

