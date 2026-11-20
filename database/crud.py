"""
Tatkal Proxy - Database CRUD Operations
Encapsulates all database queries and updates with atomicity and validation.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple, Dict, Any, Union

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from config import settings
from database.models import (
    AdminLog,
    Campaign,
    CampaignDelivery,
    CampaignStatus,
    CampaignType,
    CredentialHistory,
    Inventory,
    DailyInventory,
    InventoryStatus,
    Order,
    OrderStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
    Plan,
    ProxyAllocation,
    Setting,
    Subscription,
    SubscriptionStatus,
    User,
    utc_now,
)
from services.crypto_service import crypto_service

logger = logging.getLogger("TatkalProxy.CRUD")


# ============================================================================
# USERS CRUD
# ============================================================================
def get_or_create_user(
    db: Session,
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> User:
    """Fetch existing user or create a new user record."""
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    is_admin_flag = settings.is_admin(telegram_id)
    if not user:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            is_admin=is_admin_flag,
        )
        db.add(user)
        db.flush()
        logger.info(f"Created new user: {telegram_id} (@{username})")
    else:
        # Update metadata if changed
        updated = False
        if user.username != username:
            user.username = username
            updated = True
        if user.first_name != first_name:
            user.first_name = first_name
            updated = True
        if user.last_name != last_name:
            user.last_name = last_name
            updated = True
        if user.is_admin != is_admin_flag:
            user.is_admin = is_admin_flag
            updated = True
        if updated:
            db.flush()
    return user


def get_user_by_tg_id(db: Session, telegram_id: int) -> Optional[User]:
    """Retrieve user by Telegram numeric ID."""
    return db.query(User).filter(User.telegram_id == telegram_id).first()


def search_users(db: Session, query_str: str) -> List[User]:
    """Search users by numeric Telegram ID or username."""
    clean = query_str.strip().lstrip("@")
    if clean.isdigit():
        return db.query(User).filter(User.telegram_id == int(clean)).all()
    return db.query(User).filter(User.username.ilike(f"%{clean}%")).all()


def set_user_blocked_status(db: Session, user_id: int, blocked: bool) -> Optional[User]:
    """Block or unblock a user."""
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.is_blocked = blocked
        db.flush()
    return user


# ============================================================================
# PLANS CRUD
# ============================================================================
def get_active_plans(db: Session) -> List[Plan]:
    """Retrieve all active subscription plans ordered by price."""
    return db.query(Plan).filter(Plan.is_active == True).order_by(Plan.price_inr.asc()).all()


def get_plan_by_code(db: Session, code: str) -> Optional[Plan]:
    """Retrieve plan by code identifier."""
    return db.query(Plan).filter(Plan.code == code).first()


def get_plan_by_id(db: Session, plan_id: int) -> Optional[Plan]:
    """Retrieve plan by primary key."""
    return db.query(Plan).filter(Plan.id == plan_id).first()


def update_plan_price(db: Session, plan_id: int, new_price: float, admin_id: int | None = None) -> Plan:
    """Update subscription plan price and record audit log."""
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise ValueError(f"Plan ID {plan_id} not found.")
    old_price = plan.price_inr
    plan.price_inr = round(float(new_price), 2)
    db.flush()

    create_admin_log(
        db=db,
        admin_id=admin_id,
        action="PLAN_PRICE_UPDATED",
        target_type="plan",
        target_id=str(plan_id),
        details=f"Plan '{plan.name}' price changed from ₹{old_price} to ₹{plan.price_inr}",
    )
    return plan


# ============================================================================
# INVENTORY CRUD
# ============================================================================
def ip_exists_in_any_inventory(db: Session, ip_address: str) -> bool:
    """Check whether an IP already exists in regular or daily inventory."""
    clean_ip = ip_address.strip()
    in_reg = db.query(Inventory.id).filter(Inventory.ip == clean_ip).first() is not None
    if in_reg:
        return True
    in_daily = db.query(DailyInventory.id).filter(DailyInventory.ip == clean_ip).first() is not None
    return in_daily


def get_daily_inventory_stats(db: Session) -> Dict[str, int]:
    """Calculate aggregate statistics for Daily Proxy inventory."""
    total = db.query(func.count(DailyInventory.id)).scalar() or 0
    available = (
        db.query(func.count(DailyInventory.id))
        .filter(DailyInventory.status == InventoryStatus.AVAILABLE.value)
        .scalar()
        or 0
    )
    allocated = (
        db.query(func.count(DailyInventory.id))
        .filter(DailyInventory.status == InventoryStatus.ALLOCATED.value)
        .scalar()
        or 0
    )
    expired = (
        db.query(func.count(DailyInventory.id))
        .filter(DailyInventory.status.in_([InventoryStatus.EXPIRED_HOLD.value, "EXPIRED", "PURGED"]))
        .scalar()
        or 0
    )
    return {
        "total": total,
        "available": available,
        "allocated": allocated,
        "expired": expired,
    }


def get_comprehensive_inventory_stats(db: Session) -> Dict[str, Any]:
    """Provide a full dashboard breakdown across standard, special, daily, and quarantined pools."""
    # Standard Proxies (non-special, regular table)
    std_total = (
        db.query(func.count(Inventory.id))
        .filter(Inventory.is_special == False)
        .scalar()
        or 0
    )
    std_avail = (
        db.query(func.count(Inventory.id))
        .filter(Inventory.is_special == False, Inventory.status == InventoryStatus.AVAILABLE.value)
        .scalar()
        or 0
    )
    std_alloc = (
        db.query(func.count(Inventory.id))
        .filter(Inventory.is_special == False, Inventory.status == InventoryStatus.ALLOCATED.value)
        .scalar()
        or 0
    )

    # Special Proxies (103.x.x.x, regular table)
    spec_total = (
        db.query(func.count(Inventory.id))
        .filter(Inventory.is_special == True)
        .scalar()
        or 0
    )
    spec_avail = (
        db.query(func.count(Inventory.id))
        .filter(Inventory.is_special == True, Inventory.status == InventoryStatus.AVAILABLE.value)
        .scalar()
        or 0
    )
    spec_alloc = (
        db.query(func.count(Inventory.id))
        .filter(Inventory.is_special == True, Inventory.status == InventoryStatus.ALLOCATED.value)
        .scalar()
        or 0
    )

    # Daily Proxies (daily_inventory table)
    daily_stats = get_daily_inventory_stats(db)

    # Quarantined / Expired Hold
    quarantined = (
        db.query(func.count(Inventory.id))
        .filter(Inventory.status == InventoryStatus.EXPIRED_HOLD.value)
        .scalar()
        or 0
    )

    return {
        "standard_total": std_total,
        "standard_available": std_avail,
        "standard_allocated": std_alloc,
        "special_total": spec_total,
        "special_available": spec_avail,
        "special_allocated": spec_alloc,
        "daily_total": daily_stats["total"],
        "daily_available": daily_stats["available"],
        "daily_allocated": daily_stats["allocated"],
        "daily_expired": daily_stats["expired"],
        "quarantined_total": quarantined,
    }


def get_inventory_stats(db: Session) -> Dict[str, int]:
    """Calculate aggregate inventory statistics."""
    total = db.query(func.count(Inventory.id)).scalar() or 0
    available = db.query(func.count(Inventory.id)).filter(Inventory.status == InventoryStatus.AVAILABLE.value).scalar() or 0
    allocated = db.query(func.count(Inventory.id)).filter(Inventory.status == InventoryStatus.ALLOCATED.value).scalar() or 0
    special_total = db.query(func.count(Inventory.id)).filter(Inventory.is_special == True).scalar() or 0
    special_available = db.query(func.count(Inventory.id)).filter(
        Inventory.is_special == True, Inventory.status == InventoryStatus.AVAILABLE.value
    ).scalar() or 0
    expired_hold = db.query(func.count(Inventory.id)).filter(Inventory.status == InventoryStatus.EXPIRED_HOLD.value).scalar() or 0
    disabled = db.query(func.count(Inventory.id)).filter(Inventory.status == InventoryStatus.DISABLED.value).scalar() or 0

    return {
        "total": total,
        "available": available,
        "allocated": allocated,
        "special_total": special_total,
        "special_available": special_available,
        "expired_hold": expired_hold,
        "disabled": disabled,
    }


def find_proxy_by_ip(db: Session, ip_address: str) -> Optional[Union[Inventory, DailyInventory]]:
    """Find a proxy record by IP address in either regular or daily inventory."""
    clean_ip = ip_address.strip()
    inv = db.query(Inventory).filter(Inventory.ip == clean_ip).first()
    if inv:
        return inv
    return db.query(DailyInventory).filter(DailyInventory.ip == clean_ip).first()


def search_inventory(db: Session, query_str: str) -> List[Union[Inventory, DailyInventory]]:
    """Search inventory across both regular and daily tables by IP or host."""
    clean = query_str.strip()
    regular_items = db.query(Inventory).filter(
        or_(Inventory.ip.ilike(f"%{clean}%"), Inventory.host.ilike(f"%{clean}%"))
    ).limit(20).all()
    daily_items = db.query(DailyInventory).filter(
        or_(DailyInventory.ip.ilike(f"%{clean}%"), DailyInventory.host.ilike(f"%{clean}%"))
    ).limit(20).all()
    return list(regular_items) + list(daily_items)


def get_expired_hold_inventory(db: Session) -> List[Inventory]:
    """Retrieve all proxies waiting in expired hold state for admin inspection."""
    return db.query(Inventory).filter(Inventory.status == InventoryStatus.EXPIRED_HOLD.value).all()


def update_proxy_credentials(
    db: Session,
    inventory_id: int,
    new_host: str | None = None,
    new_port: int | None = None,
    new_username: str | None = None,
    new_password: str | None = None,
    admin_id: int | None = None,
    reason: str = "Admin manual update",
) -> Inventory:
    """Safely update proxy credentials with encryption and record full audit history."""
    proxy = db.query(Inventory).filter(Inventory.id == inventory_id).first()
    if not proxy:
        raise ValueError(f"Proxy ID {inventory_id} not found.")

    old_host = proxy.host
    old_port = proxy.port
    old_user_enc = proxy.username_enc
    old_pass_enc = proxy.password_enc

    if new_host is not None:
        proxy.host = new_host.strip()
    if new_port is not None:
        proxy.port = int(new_port)
    if new_username is not None:
        proxy.username_enc = crypto_service.encrypt(new_username.strip())
    if new_password is not None:
        proxy.password_enc = crypto_service.encrypt(new_password.strip())

    proxy.credentials_updated = True
    db.flush()

    # Record history
    history = CredentialHistory(
        inventory_id=proxy.id,
        admin_id=admin_id,
        old_host=old_host,
        new_host=proxy.host,
        old_port=old_port,
        new_port=proxy.port,
        old_username_enc=old_user_enc,
        new_username_enc=proxy.username_enc,
        old_password_enc=old_pass_enc,
        new_password_enc=proxy.password_enc,
        reason=reason,
    )
    db.add(history)
    db.flush()

    create_admin_log(
        db=db,
        admin_id=admin_id,
        action="CREDENTIALS_UPDATED",
        target_type="inventory",
        target_id=str(proxy.id),
        details=f"Updated credentials for proxy {proxy.ip}:{proxy.port}. Reason: {reason}",
    )
    return proxy


def release_expired_proxy_to_available(
    db: Session, inventory_id: int, admin_id: int | None = None
) -> Inventory:
    """Admin explicitly approves an expired proxy for resale after credential rotation."""
    proxy = db.query(Inventory).filter(Inventory.id == inventory_id).first()
    if not proxy:
        raise ValueError(f"Proxy ID {inventory_id} not found.")
    if not proxy.credentials_updated:
        raise ValueError("Cannot release proxy for resale before updating its credentials.")

    proxy.status = InventoryStatus.AVAILABLE.value
    proxy.current_user_id = None
    db.flush()

    create_admin_log(
        db=db,
        admin_id=admin_id,
        action="PROXY_RELEASED_FOR_RESALE",
        target_type="inventory",
        target_id=str(proxy.id),
        details=f"Proxy {proxy.ip} marked AVAILABLE for resale by admin {admin_id}.",
    )
    return proxy


def disable_proxy(db: Session, inventory_id: int, admin_id: int | None = None) -> Inventory:
    """Permanently or temporarily disable a proxy."""
    proxy = db.query(Inventory).filter(Inventory.id == inventory_id).first()
    if not proxy:
        raise ValueError(f"Proxy ID {inventory_id} not found.")
    proxy.status = InventoryStatus.DISABLED.value
    db.flush()

    create_admin_log(
        db=db,
        admin_id=admin_id,
        action="PROXY_DISABLED",
        target_type="inventory",
        target_id=str(proxy.id),
        details=f"Proxy {proxy.ip} status set to DISABLED.",
    )
    return proxy


# ============================================================================
# ORDERS CRUD
# ============================================================================
def create_order(
    db: Session,
    user_id: int,
    plan_id: int,
    amount: float,
    quantity: int = 1,
    is_renewal: bool = False,
    renewal_sub_id: int | None = None,
) -> Order:
    """Create a new pending order with specified proxy quantity."""
    now = utc_now()
    expires_at = now + timedelta(minutes=5)
    order_code = f"ORD-{datetime.now().strftime('%Y%m%d%H%M')}-{uuid.uuid4().hex[:6].upper()}"
    order = Order(
        order_code=order_code,
        user_id=user_id,
        plan_id=plan_id,
        amount=amount,
        quantity=max(1, quantity),
        status=OrderStatus.PENDING.value,
        is_renewal=is_renewal,
        renewal_subscription_id=renewal_sub_id,
        payment_created_at=now,
        payment_expires_at=expires_at,
    )
    db.add(order)
    db.flush()
    logger.info(f"Created order {order.order_code} for user {user_id} (qty={order.quantity}, ₹{amount})")
    return order


def get_order_by_code(db: Session, order_code: str) -> Optional[Order]:
    """Retrieve order by order code with relations eagerly loaded."""
    return (
        db.query(Order)
        .options(joinedload(Order.plan), joinedload(Order.user), joinedload(Order.subscriptions))
        .filter(Order.order_code == order_code.strip())
        .first()
    )


def get_order_by_id(db: Session, order_id: int) -> Optional[Order]:
    """Retrieve order by primary key with relations eagerly loaded."""
    return (
        db.query(Order)
        .options(joinedload(Order.plan), joinedload(Order.user), joinedload(Order.subscriptions))
        .filter(Order.id == order_id)
        .first()
    )


def get_pending_orders(db: Session) -> List[Order]:
    """Retrieve pending orders waiting for payment verification."""
    return db.query(Order).filter(Order.status == OrderStatus.PENDING.value).all()


# ============================================================================
# PAYMENTS CRUD
# ============================================================================
def create_manual_payment(
    db: Session, order_id: int, user_id: int, amount: float, utr: str
) -> Payment:
    """Submit a manual UPI payment record with UTR deduplication and ownership check."""
    clean_utr = utr.strip()

    # Verify order ownership
    order = get_order_by_id(db, order_id)
    if not order:
        raise ValueError(f"Order ID {order_id} does not exist.")
    if order.user_id != user_id:
        raise ValueError("Unauthorized: This order belongs to another customer.")

    # Check duplicate UTR across all payments
    existing_utr = db.query(Payment).filter(func.lower(Payment.utr) == clean_utr.lower()).first()
    if existing_utr and existing_utr.order_id != order_id:
        raise ValueError(f"UTR '{clean_utr}' has already been submitted for another transaction.")
    if existing_utr and existing_utr.status == PaymentStatus.VERIFIED.value:
        raise ValueError(f"UTR '{clean_utr}' has already been verified and cannot be reused.")

    # Check if payment record already exists for order
    existing_payment = db.query(Payment).filter(Payment.order_id == order_id).first()
    if existing_payment:
        if existing_payment.user_id != user_id:
            raise ValueError("Unauthorized: This order belongs to another customer.")
        existing_payment.utr = clean_utr
        existing_payment.status = PaymentStatus.PENDING_VERIFICATION.value
        existing_payment.payment_method = PaymentMethod.MANUAL_UPI.value
        db.flush()
        return existing_payment

    payment = Payment(
        order_id=order_id,
        user_id=user_id,
        payment_method=PaymentMethod.MANUAL_UPI.value,
        amount=amount,
        utr=clean_utr,
        status=PaymentStatus.PENDING_VERIFICATION.value,
        payment_created_at=order.payment_created_at or utc_now(),
        payment_expires_at=order.payment_expires_at,
    )
    db.add(payment)
    db.flush()
    logger.info(f"Submitted manual payment for order {order_id} with UTR {clean_utr}")
    return payment


def get_payment_by_id(db: Session, payment_id: int) -> Optional[Payment]:
    return db.query(Payment).filter(Payment.id == payment_id).first()


def get_payment_by_utr(db: Session, utr: str) -> Optional[Payment]:
    return db.query(Payment).filter(Payment.utr == utr.strip()).first()


def get_submitted_payments(db: Session) -> List[Payment]:
    """Retrieve payments awaiting admin verification with relations eagerly loaded."""
    return (
        db.query(Payment)
        .options(joinedload(Payment.order).joinedload(Order.plan), joinedload(Payment.user))
        .filter(Payment.status.in_([PaymentStatus.PENDING_VERIFICATION.value, "SUBMITTED"]))
        .all()
    )


# ============================================================================
# SUBSCRIPTIONS & ATOMIC ALLOCATION
# ============================================================================
def allocate_proxy_and_activate_subscription(
    db: Session, order_id: int, verified_by_id: int | None = None
) -> Tuple[List[Subscription], List[Union[Inventory, DailyInventory]]]:
    """
    Atomically allocate available proxy (or multiple proxies) matching order quantity and plan,
    and activate subscription(s).
    Rules:
    - Daily plan (daily_proxy) allocates STRICTLY from DailyInventory table.
    - Regular plans (monthly_proxy, special_proxy) allocate STRICTLY from Inventory table.
    - 1-day plan expires at midnight (23:59:59 IST) of that day itself.
    - Multiple quantity allocation (1, 3, 5, 10) supported atomically with lock.
    """
    order = db.query(Order).filter(Order.id == order_id).with_for_update().first()
    if not order:
        raise ValueError(f"Order ID {order_id} not found.")

    if order.status == OrderStatus.PAID.value and order.subscriptions:
        logger.warning(f"Order {order.order_code} already fulfilled.")
        return order.subscriptions, [s.proxy for s in order.subscriptions]

    plan = order.plan
    user = order.user
    target_qty = max(1, order.quantity or 1)

    start_time = utc_now()
    if plan.duration_days == 1:
        # One-day proxy expires at midnight of that day itself in Indian Standard Time (23:59:59 IST)
        IST = timezone(timedelta(hours=5, minutes=30), name="IST")
        ist_now = start_time.astimezone(IST)
        ist_midnight = datetime(ist_now.year, ist_now.month, ist_now.day, 23, 59, 59, tzinfo=IST)
        end_time = ist_midnight.astimezone(timezone.utc)
    else:
        end_time = start_time + timedelta(days=plan.duration_days)

    # Handle renewal if order was created as a renewal
    if order.is_renewal and order.renewal_subscription_id:
        existing_sub = (
            db.query(Subscription)
            .filter(Subscription.id == order.renewal_subscription_id)
            .with_for_update()
            .first()
        )
        if existing_sub:
            base_time = max(existing_sub.end_date, utc_now())
            if plan.duration_days == 1:
                IST = timezone(timedelta(hours=5, minutes=30), name="IST")
                ist_base = base_time.astimezone(IST)
                ist_midnight = datetime(ist_base.year, ist_base.month, ist_base.day, 23, 59, 59, tzinfo=IST)
                existing_sub.end_date = ist_midnight.astimezone(timezone.utc)
            else:
                existing_sub.end_date = base_time + timedelta(days=plan.duration_days)
            existing_sub.status = SubscriptionStatus.ACTIVE.value
            existing_sub.reminded_24h = False
            existing_sub.reminded_1h = False
            existing_sub.expired_notified = False
            order.status = OrderStatus.PAID.value
            db.flush()
            logger.info(f"Renewed subscription {existing_sub.sub_code} to {existing_sub.end_date}")
            return [existing_sub], [existing_sub.proxy]

    # SEPARATE INVENTORY ALLOCATION
    if plan.code == "daily_proxy":
        # Strictly query DailyInventory
        query = (
            db.query(DailyInventory)
            .filter(DailyInventory.status == InventoryStatus.AVAILABLE.value)
            .order_by(DailyInventory.id.asc())
            .limit(target_qty)
            .with_for_update()
        )
        available_daily = query.all()
        if len(available_daily) < target_qty:
            raise ValueError(
                f"Insufficient inventory for plan '{plan.name}'. "
                f"Requested {target_qty}, but only {len(available_daily)} available in Daily Inventory."
            )

        created_subs: List[Subscription] = []
        for daily_item in available_daily:
            daily_item.status = InventoryStatus.ALLOCATED.value
            daily_item.current_user_id = user.id
            daily_item.last_customer_id = user.id
            db.flush()

            sub_code = f"SUB-{datetime.now().strftime('%Y%m%d%H%M')}-{uuid.uuid4().hex[:6].upper()}"
            subscription = Subscription(
                sub_code=sub_code,
                user_id=user.id,
                plan_id=plan.id,
                order_id=order.id,
                inventory_id=None,
                daily_inventory_id=daily_item.id,
                start_date=start_time,
                end_date=end_time,
                status=SubscriptionStatus.ACTIVE.value,
            )
            db.add(subscription)
            db.flush()

            allocation = ProxyAllocation(
                subscription_id=subscription.id,
                inventory_id=None,
                daily_inventory_id=daily_item.id,
                user_id=user.id,
                assigned_at=start_time,
                is_active=True,
            )
            db.add(allocation)
            created_subs.append(subscription)

        order.status = OrderStatus.PAID.value
        db.flush()
        logger.info(
            f"Successfully allocated {len(available_daily)} Daily Proxies to user {user.telegram_id} for order {order.order_code}"
        )
        return created_subs, available_daily

    # Standard & Special IP allocation from regular Inventory
    query = (
        db.query(Inventory)
        .filter(
            Inventory.status == InventoryStatus.AVAILABLE.value,
            Inventory.is_special == plan.is_special,
        )
        .order_by(Inventory.id.asc())
        .limit(target_qty)
        .with_for_update()
    )
    available_proxies = query.all()

    if len(available_proxies) < target_qty:
        raise ValueError(
            f"Insufficient inventory for plan '{plan.name}' (Special: {plan.is_special}). "
            f"Requested {target_qty}, but only {len(available_proxies)} available."
        )

    created_subs: List[Subscription] = []
    for available_proxy in available_proxies:
        available_proxy.status = InventoryStatus.ALLOCATED.value
        available_proxy.current_user_id = user.id
        available_proxy.last_customer_id = user.id
        available_proxy.credentials_updated = False
        db.flush()

        sub_code = f"SUB-{datetime.now().strftime('%Y%m%d%H%M')}-{uuid.uuid4().hex[:6].upper()}"
        subscription = Subscription(
            sub_code=sub_code,
            user_id=user.id,
            plan_id=plan.id,
            order_id=order.id,
            inventory_id=available_proxy.id,
            daily_inventory_id=None,
            start_date=start_time,
            end_date=end_time,
            status=SubscriptionStatus.ACTIVE.value,
        )
        db.add(subscription)
        db.flush()

        allocation = ProxyAllocation(
            subscription_id=subscription.id,
            inventory_id=available_proxy.id,
            daily_inventory_id=None,
            user_id=user.id,
            assigned_at=start_time,
            is_active=True,
        )
        db.add(allocation)
        created_subs.append(subscription)

    order.status = OrderStatus.PAID.value
    db.flush()

    logger.info(
        f"Successfully allocated {len(available_proxies)} proxies to user {user.telegram_id} for order {order.order_code}"
    )
    return created_subs, available_proxies


def get_user_subscriptions(db: Session, user_id: int) -> List[Subscription]:
    """Retrieve all subscriptions for a customer with relations eagerly loaded."""
    return (
        db.query(Subscription)
        .options(
            joinedload(Subscription.plan),
            joinedload(Subscription.inventory),
            joinedload(Subscription.daily_inventory),
        )
        .filter(Subscription.user_id == user_id)
        .order_by(Subscription.status.asc(), Subscription.end_date.desc())
        .all()
    )


def get_user_active_subscriptions(db: Session, user_id: int) -> List[Subscription]:
    """Retrieve active subscriptions for a customer with relations eagerly loaded."""
    return (
        db.query(Subscription)
        .options(
            joinedload(Subscription.plan),
            joinedload(Subscription.inventory),
            joinedload(Subscription.daily_inventory),
        )
        .filter(
            Subscription.user_id == user_id,
            Subscription.status == SubscriptionStatus.ACTIVE.value,
        )
        .order_by(Subscription.end_date.asc())
        .all()
    )


def get_subscription_by_code(db: Session, sub_code: str) -> Optional[Subscription]:
    return (
        db.query(Subscription)
        .options(
            joinedload(Subscription.plan),
            joinedload(Subscription.inventory),
            joinedload(Subscription.daily_inventory),
        )
        .filter(Subscription.sub_code == sub_code.strip())
        .first()
    )


def get_subscription_by_id(db: Session, sub_id: int) -> Optional[Subscription]:
    return (
        db.query(Subscription)
        .options(
            joinedload(Subscription.plan),
            joinedload(Subscription.inventory),
            joinedload(Subscription.daily_inventory),
        )
        .filter(Subscription.id == sub_id)
        .first()
    )


# ============================================================================
# AUDIT & ADMIN LOGS
# ============================================================================
def create_admin_log(
    db: Session,
    admin_id: int | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    details: str | None = None,
    ip_address: str | None = None,
) -> AdminLog:
    """Create an entry in admin audit log."""
    log_entry = AdminLog(
        admin_id=admin_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
        ip_address=ip_address,
    )
    db.add(log_entry)
    db.flush()
    return log_entry


def get_recent_admin_logs(db: Session, limit: int = 50) -> List[AdminLog]:
    return db.query(AdminLog).order_by(AdminLog.created_at.desc()).limit(limit).all()


# ============================================================================
# SETTINGS CRUD
# ============================================================================
def get_setting(db: Session, key: str, default: str = "") -> str:
    setting = db.query(Setting).filter(Setting.key == key).first()
    return setting.value if setting else default


def set_setting(db: Session, key: str, value: str, description: str | None = None) -> Setting:
    setting = db.query(Setting).filter(Setting.key == key).first()
    if not setting:
        setting = Setting(key=key, value=value, description=description)
        db.add(setting)
    else:
        setting.value = value
        if description:
            setting.description = description
    db.flush()
    return setting


# ============================================================================
# REVENUE & DASHBOARD METRICS
# ============================================================================
def get_dashboard_metrics(db: Session) -> Dict[str, Any]:
    """Calculate comprehensive business metrics for admin dashboard."""
    inv_stats = get_inventory_stats(db)

    now = utc_now()
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    # Subscriptions
    active_subs = (
        db.query(func.count(Subscription.id))
        .filter(Subscription.status == SubscriptionStatus.ACTIVE.value)
        .scalar()
        or 0
    )
    expired_subs = (
        db.query(func.count(Subscription.id))
        .filter(Subscription.status == SubscriptionStatus.EXPIRED.value)
        .scalar()
        or 0
    )

    # Pending Payments
    pending_payments = (
        db.query(func.count(Payment.id))
        .filter(Payment.status.in_([PaymentStatus.PENDING_VERIFICATION.value, "SUBMITTED"]))
        .scalar()
        or 0
    )

    # Revenue from verified payments
    today_rev = (
        db.query(func.sum(Payment.amount))
        .filter(
            Payment.status == PaymentStatus.VERIFIED.value,
            Payment.verified_at >= today_start,
        )
        .scalar()
        or 0.0
    )

    month_rev = (
        db.query(func.sum(Payment.amount))
        .filter(
            Payment.status == PaymentStatus.VERIFIED.value,
            Payment.verified_at >= month_start,
        )
        .scalar()
        or 0.0
    )

    total_customers = db.query(func.count(User.id)).scalar() or 0

    return {
        "inventory": inv_stats,
        "active_subs": active_subs,
        "expired_subs": expired_subs,
        "pending_payments": pending_payments,
        "today_revenue": float(today_rev),
        "monthly_revenue": float(month_rev),
        "total_customers": total_customers,
    }


# ============================================================================
# CAMPAIGNS & MARKETING CRUD
# ============================================================================
def create_campaign(
    db: Session,
    admin_id: int | None,
    campaign_type: str,
    content_text: str | None = None,
    media_file_id: str | None = None,
    caption: str | None = None,
    has_button: bool = False,
    button_text: str | None = None,
    button_url_or_cb: str | None = None,
) -> Campaign:
    """Create a new broadcast campaign draft."""
    code = f"CAMP-{datetime.now().strftime('%Y%m%d%H%M')}-{uuid.uuid4().hex[:6].upper()}"
    campaign = Campaign(
        campaign_code=code,
        admin_id=admin_id,
        campaign_type=campaign_type,
        content_text=content_text,
        media_file_id=media_file_id,
        caption=caption,
        has_button=has_button,
        button_text=button_text,
        button_url_or_cb=button_url_or_cb,
        status=CampaignStatus.DRAFT.value,
    )
    db.add(campaign)
    db.flush()
    return campaign


def get_campaign_by_id(db: Session, campaign_id: int) -> Optional[Campaign]:
    """Retrieve campaign with deliveries loaded."""
    return (
        db.query(Campaign)
        .options(joinedload(Campaign.deliveries))
        .filter(Campaign.id == campaign_id)
        .first()
    )


def get_campaign_by_code(db: Session, campaign_code: str) -> Optional[Campaign]:
    """Retrieve campaign by code."""
    return db.query(Campaign).filter(Campaign.campaign_code == campaign_code.strip()).first()


def get_campaigns_by_type(db: Session, campaign_type: str | None = None, limit: int = 20) -> List[Campaign]:
    """Retrieve recent campaigns, optionally filtered by type."""
    query = db.query(Campaign)
    if campaign_type:
        query = query.filter(Campaign.campaign_type == campaign_type)
    return query.order_by(Campaign.id.desc()).limit(limit).all()


def get_broadcast_target_users(db: Session) -> List[User]:
    """Retrieve all active, non-blocked registered users eligible for broadcasts."""
    return (
        db.query(User)
        .filter(User.is_blocked == False)
        .order_by(User.id.asc())
        .all()
    )


def record_campaign_delivery(
    db: Session,
    campaign_id: int,
    user_id: int,
    telegram_id: int,
    message_id: int | None = None,
    status: str = "DELIVERED",
    error_message: str | None = None,
) -> CampaignDelivery:
    """Record individual user message delivery for tracking and future deletion."""
    delivery = CampaignDelivery(
        campaign_id=campaign_id,
        user_id=user_id,
        telegram_id=telegram_id,
        message_id=message_id,
        status=status,
        error_message=error_message,
        delivered_at=utc_now(),
    )
    db.add(delivery)
    db.flush()
    return delivery


def get_campaign_deliveries(db: Session, campaign_id: int) -> List[CampaignDelivery]:
    """Get all deliveries for a specific campaign."""
    return (
        db.query(CampaignDelivery)
        .filter(CampaignDelivery.campaign_id == campaign_id)
        .all()
    )


def record_campaign_deletion(
    db: Session,
    delivery_id: int,
    success: bool,
    error_message: str | None = None,
) -> None:
    """Update status of a message deletion attempt."""
    delivery = db.query(CampaignDelivery).filter(CampaignDelivery.id == delivery_id).first()
    if delivery:
        delivery.deletion_attempted = True
        delivery.deleted_from_chat = success
        delivery.deletion_error = error_message if not success else None
        delivery.deletion_attempted_at = utc_now()
        db.flush()
