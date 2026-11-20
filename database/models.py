"""
Tatkal Proxy - Database Models
Relational schema using SQLAlchemy 2.0 with PostgreSQL & SQLite dual-compatibility.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import List, Optional, Union

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class InventoryStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    ALLOCATED = "ALLOCATED"
    EXPIRED_HOLD = "EXPIRED_HOLD"
    DISABLED = "DISABLED"


class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class PaymentStatus(str, enum.Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    SUBMITTED = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PaymentMethod(str, enum.Enum):
    MANUAL_UPI = "MANUAL_UPI"
    GATEWAY = "GATEWAY"


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


# ============================================================================
# 1. USERS
# ============================================================================
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    orders: Mapped[List[Order]] = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    subscriptions: Mapped[List[Subscription]] = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")
    payments: Mapped[List[Payment]] = relationship("Payment", back_populates="user", foreign_keys="Payment.user_id")

    def __repr__(self) -> str:
        return f"<User id={self.id} tg={self.telegram_id} username={self.username}>"


# ============================================================================
# 2. INVENTORY
# ============================================================================
class Inventory(Base):
    __tablename__ = "inventory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    host: Mapped[str] = mapped_column(String(128), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username_enc: Mapped[str] = mapped_column(String(512), nullable=False)
    password_enc: Mapped[str] = mapped_column(String(512), nullable=False)
    is_special: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=InventoryStatus.AVAILABLE.value, index=True, nullable=False)
    current_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    last_customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    credentials_updated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    subscriptions: Mapped[List[Subscription]] = relationship("Subscription", back_populates="inventory")
    allocations: Mapped[List[ProxyAllocation]] = relationship("ProxyAllocation", back_populates="inventory")
    credential_history: Mapped[List[CredentialHistory]] = relationship("CredentialHistory", back_populates="inventory", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Inventory id={self.id} ip={self.ip}:{self.port} status={self.status} special={self.is_special}>"


# ============================================================================
# 2B. DAILY INVENTORY (Completely Isolated 1-Day Inventory)
# ============================================================================
class DailyInventory(Base):
    __tablename__ = "daily_inventory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    host: Mapped[str] = mapped_column(String(128), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username_enc: Mapped[str] = mapped_column(String(512), nullable=False)
    password_enc: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=InventoryStatus.AVAILABLE.value, index=True, nullable=False)
    current_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    last_customer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    subscriptions: Mapped[List[Subscription]] = relationship("Subscription", back_populates="daily_inventory")

    def __repr__(self) -> str:
        return f"<DailyInventory id={self.id} ip={self.ip}:{self.port} status={self.status}>"


# ============================================================================
# 3. PLANS
# ============================================================================
class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    price_inr: Mapped[float] = mapped_column(Float, nullable=False)
    is_special: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    orders: Mapped[List[Order]] = relationship("Order", back_populates="plan")
    subscriptions: Mapped[List[Subscription]] = relationship("Subscription", back_populates="plan")

    def __repr__(self) -> str:
        return f"<Plan id={self.id} code={self.code} price=₹{self.price_inr}>"


# ============================================================================
# 4. ORDERS
# ============================================================================
class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=OrderStatus.PENDING.value, index=True, nullable=False)
    is_renewal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    renewal_subscription_id: Mapped[Optional[int]] = mapped_column(ForeignKey("subscriptions.id", ondelete="SET NULL", use_alter=True), nullable=True)
    payment_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=True)
    payment_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    expired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    user: Mapped[User] = relationship("User", back_populates="orders")
    plan: Mapped[Plan] = relationship("Plan", back_populates="orders")
    payment: Mapped[Optional[Payment]] = relationship("Payment", back_populates="order", uselist=False)
    subscriptions: Mapped[List[Subscription]] = relationship("Subscription", back_populates="order", foreign_keys="Subscription.order_id")

    @property
    def is_payment_expired(self) -> bool:
        if self.status == OrderStatus.EXPIRED.value:
            return True
        if self.payment_expires_at:
            exp = self.payment_expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) > exp
        return False

    @property
    def subscription(self) -> Optional[Subscription]:
        return self.subscriptions[0] if self.subscriptions else None

    def __repr__(self) -> str:
        return f"<Order id={self.id} code={self.order_code} status={self.status} amt=₹{self.amount}>"


# ============================================================================
# 5. PAYMENTS
# ============================================================================
class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    payment_method: Mapped[str] = mapped_column(String(32), default=PaymentMethod.MANUAL_UPI.value, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    utr: Mapped[Optional[str]] = mapped_column(String(100), unique=True, index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=PaymentStatus.PENDING_VERIFICATION.value, index=True, nullable=False)
    gateway_order_id: Mapped[Optional[str]] = mapped_column(String(100), unique=True, index=True, nullable=True)
    gateway_payment_id: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    gateway_signature: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    admin_notes: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    verified_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=True)
    payment_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    expired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    order: Mapped[Order] = relationship("Order", back_populates="payment")
    user: Mapped[User] = relationship("User", back_populates="payments", foreign_keys=[user_id])
    verifier: Mapped[Optional[User]] = relationship("User", foreign_keys=[verified_by_id])

    @property
    def is_payment_expired(self) -> bool:
        if self.status == PaymentStatus.EXPIRED.value:
            return True
        if self.payment_expires_at:
            exp = self.payment_expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) > exp
        return False

    def __repr__(self) -> str:
        return f"<Payment id={self.id} order_id={self.order_id} method={self.payment_method} status={self.status}>"


# ============================================================================
# 6. SUBSCRIPTIONS
# ============================================================================
class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sub_code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"), nullable=False)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    inventory_id: Mapped[Optional[int]] = mapped_column(ForeignKey("inventory.id"), nullable=True, index=True)
    daily_inventory_id: Mapped[Optional[int]] = mapped_column(ForeignKey("daily_inventory.id", ondelete="SET NULL"), nullable=True, index=True)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default=SubscriptionStatus.ACTIVE.value, index=True, nullable=False)
    reminded_24h: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reminded_1h: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expired_notified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    user: Mapped[User] = relationship("User", back_populates="subscriptions")
    plan: Mapped[Plan] = relationship("Plan", back_populates="subscriptions")
    order: Mapped[Order] = relationship("Order", back_populates="subscriptions", foreign_keys=[order_id])
    inventory: Mapped[Optional[Inventory]] = relationship("Inventory", back_populates="subscriptions")
    daily_inventory: Mapped[Optional[DailyInventory]] = relationship("DailyInventory", back_populates="subscriptions")
    allocations: Mapped[List[ProxyAllocation]] = relationship("ProxyAllocation", back_populates="subscription", cascade="all, delete-orphan")

    @property
    def proxy(self) -> Optional[Union[Inventory, DailyInventory]]:
        return self.daily_inventory if self.daily_inventory_id else self.inventory

    @property
    def proxy_ip(self) -> str:
        p = self.proxy
        return p.ip if p else "N/A"

    def __repr__(self) -> str:
        return f"<Subscription id={self.id} code={self.sub_code} status={self.status} ends={self.end_date}>"


# ============================================================================
# 7. PROXY ALLOCATIONS
# ============================================================================
class ProxyAllocation(Base):
    __tablename__ = "proxy_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False)
    inventory_id: Mapped[Optional[int]] = mapped_column(ForeignKey("inventory.id", ondelete="CASCADE"), nullable=True)
    daily_inventory_id: Mapped[Optional[int]] = mapped_column(ForeignKey("daily_inventory.id", ondelete="CASCADE"), nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)

    subscription: Mapped[Subscription] = relationship("Subscription", back_populates="allocations")
    inventory: Mapped[Optional[Inventory]] = relationship("Inventory", back_populates="allocations")
    daily_inventory: Mapped[Optional[DailyInventory]] = relationship("DailyInventory")

    def __repr__(self) -> str:
        return f"<ProxyAllocation sub={self.subscription_id} inv={self.inventory_id} active={self.is_active}>"


@event.listens_for(Subscription, "before_insert")
@event.listens_for(Subscription, "before_update")
def validate_subscription_inventory_integrity(mapper, connection, target: Subscription):
    """
    Enforce inventory association integrity on Subscription:
    - Daily Proxy subscriptions must reference daily_inventory_id and inventory_id must be None.
    - Standard / Special IP subscriptions must reference inventory_id and daily_inventory_id must be None.
    - Prevents referencing both or neither.
    """
    if target.inventory_id is None and target.daily_inventory_id is None:
        raise ValueError("Subscription must reference either standard inventory_id or daily_inventory_id.")
    if target.inventory_id is not None and target.daily_inventory_id is not None:
        raise ValueError("Subscription cannot reference both standard inventory and daily inventory.")


@event.listens_for(ProxyAllocation, "before_insert")
@event.listens_for(ProxyAllocation, "before_update")
def validate_allocation_inventory_integrity(mapper, connection, target: ProxyAllocation):
    """
    Enforce inventory association integrity on ProxyAllocation:
    - Must reference either inventory_id or daily_inventory_id (mutually exclusive).
    """
    if target.inventory_id is None and target.daily_inventory_id is None:
        raise ValueError("ProxyAllocation must reference either standard inventory_id or daily_inventory_id.")
    if target.inventory_id is not None and target.daily_inventory_id is not None:
        raise ValueError("ProxyAllocation cannot reference both standard inventory and daily inventory.")


# ============================================================================
# 8. CREDENTIAL HISTORY
# ============================================================================
class CredentialHistory(Base):
    __tablename__ = "credential_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inventory_id: Mapped[int] = mapped_column(ForeignKey("inventory.id", ondelete="CASCADE"), nullable=False)
    admin_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    old_host: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    new_host: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    old_port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    new_port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    old_username_enc: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    new_username_enc: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    old_password_enc: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    new_password_enc: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    inventory: Mapped[Inventory] = relationship("Inventory", back_populates="credential_history")

    def __repr__(self) -> str:
        return f"<CredentialHistory inv={self.inventory_id} changed_at={self.changed_at}>"


# ============================================================================
# 9. ADMIN LOGS
# ============================================================================
class AdminLog(Base):
    __tablename__ = "admin_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    target_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    def __repr__(self) -> str:
        return f"<AdminLog action={self.action} admin={self.admin_id} at={self.created_at}>"


# ============================================================================
# 10. SETTINGS
# ============================================================================
class Setting(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    def __repr__(self) -> str:
        return f"<Setting key={self.key} val={self.value}>"


# ============================================================================
# 11. CAMPAIGNS & MARKETING BROADCASTS
# ============================================================================
class CampaignType(str, enum.Enum):
    ANNOUNCEMENT = "ANNOUNCEMENT"
    PROMOTION = "PROMOTION"
    BANNER = "BANNER"


class CampaignStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SENDING = "SENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    admin_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    campaign_type: Mapped[str] = mapped_column(String(32), nullable=False)  # ANNOUNCEMENT, PROMOTION, BANNER
    content_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    media_file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    has_button: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    button_text: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    button_url_or_cb: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=CampaignStatus.DRAFT.value, index=True, nullable=False)
    total_recipients: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    deliveries: Mapped[List[CampaignDelivery]] = relationship("CampaignDelivery", back_populates="campaign", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Campaign id={self.id} code={self.campaign_code} type={self.campaign_type} status={self.status}>"


class CampaignDelivery(Base):
    __tablename__ = "campaign_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="DELIVERED", nullable=False)  # DELIVERED, FAILED
    error_message: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    deleted_from_chat: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deletion_attempted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deletion_error: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    deletion_attempted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="deliveries")
    user: Mapped[User] = relationship("User")

    def __repr__(self) -> str:
        return f"<CampaignDelivery id={self.id} camp={self.campaign_id} tg={self.telegram_id} status={self.status}>"
