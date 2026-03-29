import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Numeric, DateTime, Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from typing import Optional
import enum

class Base(DeclarativeBase):
    pass

class PlatformEnum(str, enum.Enum):
    FACEBOOK = "FACEBOOK"
    WHATSAPP = "WHATSAPP"
    TELEGRAM = "TELEGRAM"

class PaymentStatusEnum(str, enum.Enum):
    PENDING = "PENDING"
    PAID = "PAID"

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
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

class Payment(Base):
    __tablename__ = "payments"
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    sender_phone: Mapped[str] = mapped_column(String(20), index=True)
    amount: Mapped[float] = mapped_column(Numeric(10, 2))
    matched_order_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
