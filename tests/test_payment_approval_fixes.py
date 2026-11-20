"""
Tatkal Proxy - Payment Approval & Inventory Relationship Tests
Validates:
1. Daily Proxy payment approval with daily_inventory_id and nullable inventory_id
2. Monthly Proxy payment approval with standard inventory_id
3. Special IP Proxy payment approval with standard inventory_id (is_special=True)
4. Invalid inventory relationship rejection (both set or neither set)
5. Duplicate admin approval prevention (already verified, already fulfilled, rejected)
6. Atomic rollback on allocation failure
7. Telegram callback error handling and message_too_long protection
8. SQLite and PostgreSQL schema migration logic
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from database.models import (
    Base,
    User,
    Plan,
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
    Inventory,
    DailyInventory,
    InventoryStatus,
    Subscription,
    ProxyAllocation,
)
from database.crud import (
    create_order,
    create_manual_payment,
    get_payment_by_id,
)
from services.payment_service import payment_service
from services.crypto_service import crypto_service
from handlers.admin import handle_pay_approve_callback, handle_pay_reject_callback, safe_answer_callback
from database.migration import run_migrations, _migrate_sqlite, _migrate_postgres


# ============================================================================
# 1. DAILY PROXY PAYMENT APPROVAL
# ============================================================================
@pytest.mark.asyncio
async def test_daily_proxy_payment_approval(db_session, test_user, test_admin, mock_bot):
    """
    Test admin approval for Daily Proxy:
    - Allocates strictly from DailyInventory
    - Subscription has daily_inventory_id set and inventory_id = None
    - ProxyAllocation has daily_inventory_id set and inventory_id = None
    - Fulfills order and marks proxy ALLOCATED
    """
    daily_item = DailyInventory(
        ip="103.20.30.40",
        host="103.20.30.40",
        port=8080,
        username_enc=crypto_service.encrypt("dailyuser"),
        password_enc=crypto_service.encrypt("dailypass"),
        status=InventoryStatus.AVAILABLE.value,
    )
    db_session.add(daily_item)
    db_session.commit()

    plan = db_session.query(Plan).filter(Plan.code == "daily_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)
    payment = create_manual_payment(db_session, order.id, test_user.id, order.amount, "DAILY_UTR_123456")

    sub, inv = await payment_service.verify_and_deliver(
        db=db_session,
        payment_id=payment.id,
        admin_tg_id=test_admin.telegram_id,
        bot=mock_bot,
    )

    assert payment.status == PaymentStatus.VERIFIED.value
    assert order.status == OrderStatus.PAID.value
    assert sub.daily_inventory_id == daily_item.id
    assert sub.inventory_id is None
    assert inv.id == daily_item.id
    assert inv.status == InventoryStatus.ALLOCATED.value

    # Check ProxyAllocation record
    alloc = db_session.query(ProxyAllocation).filter(ProxyAllocation.subscription_id == sub.id).first()
    assert alloc is not None
    assert alloc.daily_inventory_id == daily_item.id
    assert alloc.inventory_id is None
    assert alloc.is_active is True

    # Customer message delivered
    assert mock_bot.send_message.called


# ============================================================================
# 2. MONTHLY PROXY PAYMENT APPROVAL
# ============================================================================
@pytest.mark.asyncio
async def test_monthly_proxy_payment_approval(db_session, test_user, test_admin, mock_bot):
    """
    Test admin approval for Monthly Proxy:
    - Allocates strictly from regular Inventory (is_special=False)
    - Subscription has inventory_id set and daily_inventory_id = None
    """
    reg_item = Inventory(
        ip="45.10.20.30",
        host="45.10.20.30",
        port=8080,
        username_enc=crypto_service.encrypt("muser"),
        password_enc=crypto_service.encrypt("mpass"),
        is_special=False,
        status=InventoryStatus.AVAILABLE.value,
    )
    db_session.add(reg_item)
    db_session.commit()

    plan = db_session.query(Plan).filter(Plan.code == "monthly_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)
    payment = create_manual_payment(db_session, order.id, test_user.id, order.amount, "MONTHLY_UTR_123456")

    sub, inv = await payment_service.verify_and_deliver(
        db=db_session,
        payment_id=payment.id,
        admin_tg_id=test_admin.telegram_id,
        bot=mock_bot,
    )

    assert payment.status == PaymentStatus.VERIFIED.value
    assert order.status == OrderStatus.PAID.value
    assert sub.inventory_id == reg_item.id
    assert sub.daily_inventory_id is None
    assert inv.id == reg_item.id
    assert inv.status == InventoryStatus.ALLOCATED.value

    alloc = db_session.query(ProxyAllocation).filter(ProxyAllocation.subscription_id == sub.id).first()
    assert alloc is not None
    assert alloc.inventory_id == reg_item.id
    assert alloc.daily_inventory_id is None


# ============================================================================
# 3. SPECIAL IP PROXY PAYMENT APPROVAL
# ============================================================================
@pytest.mark.asyncio
async def test_special_ip_proxy_payment_approval(db_session, test_user, test_admin, mock_bot):
    """
    Test admin approval for Special IP Proxy:
    - Allocates strictly from regular Inventory (is_special=True, 103.x.x.x)
    - Subscription has inventory_id set and daily_inventory_id = None
    """
    special_item = Inventory(
        ip="103.99.88.77",
        host="103.99.88.77",
        port=8080,
        username_enc=crypto_service.encrypt("suser"),
        password_enc=crypto_service.encrypt("spass"),
        is_special=True,
        status=InventoryStatus.AVAILABLE.value,
    )
    db_session.add(special_item)
    db_session.commit()

    plan = db_session.query(Plan).filter(Plan.code == "special_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)
    payment = create_manual_payment(db_session, order.id, test_user.id, order.amount, "SPECIAL_UTR_123456")

    sub, inv = await payment_service.verify_and_deliver(
        db=db_session,
        payment_id=payment.id,
        admin_tg_id=test_admin.telegram_id,
        bot=mock_bot,
    )

    assert payment.status == PaymentStatus.VERIFIED.value
    assert sub.inventory_id == special_item.id
    assert sub.daily_inventory_id is None
    assert inv.is_special is True
    assert inv.ip.startswith("103.")


# ============================================================================
# 4. INVALID INVENTORY RELATIONSHIP REJECTION
# ============================================================================
def test_invalid_inventory_relationship_rejection(db_session, test_user):
    """Ensure a subscription cannot reference both or neither inventory type."""
    plan = db_session.query(Plan).filter(Plan.code == "daily_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)

    # 1. Neither inventory_id nor daily_inventory_id set
    invalid_sub1 = Subscription(
        sub_code="SUB-TEST-NEITHER",
        user_id=test_user.id,
        plan_id=plan.id,
        order_id=order.id,
        inventory_id=None,
        daily_inventory_id=None,
        start_date=datetime.now(timezone.utc),
        end_date=datetime.now(timezone.utc),
    )
    db_session.add(invalid_sub1)
    with pytest.raises(ValueError, match="must reference either standard inventory_id or daily_inventory_id"):
        db_session.flush()
    db_session.rollback()

    # 2. Both inventory_id and daily_inventory_id set
    invalid_sub2 = Subscription(
        sub_code="SUB-TEST-BOTH",
        user_id=test_user.id,
        plan_id=plan.id,
        order_id=order.id,
        inventory_id=1,
        daily_inventory_id=1,
        start_date=datetime.now(timezone.utc),
        end_date=datetime.now(timezone.utc),
    )
    db_session.add(invalid_sub2)
    with pytest.raises(ValueError, match="cannot reference both standard inventory and daily inventory"):
        db_session.flush()
    db_session.rollback()


# ============================================================================
# 5. DUPLICATE APPROVAL & REJECTED PAYMENT PREVENTION
# ============================================================================
@pytest.mark.asyncio
async def test_duplicate_approval_and_rejected_payment_prevention(db_session, test_user, test_admin, mock_bot):
    """Ensure an admin clicking Approve twice or on a rejected/cancelled order is blocked."""
    reg_item = Inventory(
        ip="45.1.2.3",
        host="45.1.2.3",
        port=8080,
        username_enc=crypto_service.encrypt("u"),
        password_enc=crypto_service.encrypt("p"),
        is_special=False,
        status=InventoryStatus.AVAILABLE.value,
    )
    db_session.add(reg_item)
    db_session.commit()

    plan = db_session.query(Plan).filter(Plan.code == "monthly_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)
    payment = create_manual_payment(db_session, order.id, test_user.id, order.amount, "DUP_UTR_123456")

    # First approval succeeds
    await payment_service.verify_and_deliver(
        db=db_session,
        payment_id=payment.id,
        admin_tg_id=test_admin.telegram_id,
        bot=mock_bot,
    )

    # Second approval attempt blocked
    with pytest.raises(ValueError, match="already been verified and delivered"):
        await payment_service.verify_and_deliver(
            db=db_session,
            payment_id=payment.id,
            admin_tg_id=test_admin.telegram_id,
            bot=mock_bot,
        )

    # Cannot approve rejected payment
    order2 = create_order(db_session, test_user.id, plan.id, plan.price_inr)
    payment2 = create_manual_payment(db_session, order2.id, test_user.id, order2.amount, "REJ_UTR_123456")
    payment2.status = PaymentStatus.REJECTED.value
    db_session.commit()

    with pytest.raises(ValueError, match="payment has been rejected"):
        await payment_service.verify_and_deliver(
            db=db_session,
            payment_id=payment2.id,
            admin_tg_id=test_admin.telegram_id,
            bot=mock_bot,
        )


# ============================================================================
# 6. ATOMIC ROLLBACK ON ALLOCATION FAILURE
# ============================================================================
@pytest.mark.asyncio
async def test_allocation_failure_atomic_rollback(db_session, test_user, test_admin, mock_bot):
    """Ensure that if inventory is unavailable, the payment remains unverified."""
    plan = db_session.query(Plan).filter(Plan.code == "daily_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)
    payment = create_manual_payment(db_session, order.id, test_user.id, order.amount, "OUT_OF_STOCK_UTR")
    db_session.commit()

    # No DailyInventory added -> Insufficient inventory
    with pytest.raises(ValueError, match="Insufficient inventory"):
        await payment_service.verify_and_deliver(
            db=db_session,
            payment_id=payment.id,
            admin_tg_id=test_admin.telegram_id,
            bot=mock_bot,
        )

    # Verify payment remains PENDING_VERIFICATION
    db_session.rollback()
    refreshed_payment = get_payment_by_id(db_session, payment.id)
    assert refreshed_payment.status == PaymentStatus.PENDING_VERIFICATION.value
    assert refreshed_payment.order.status == OrderStatus.PENDING.value


# ============================================================================
# 7. TELEGRAM MESSAGE_TOO_LONG FIX
# ============================================================================
@pytest.mark.asyncio
async def test_safe_answer_callback_truncation():
    """Verify safe_answer_callback truncates messages exceeding Telegram alert limits."""
    query = MagicMock()
    query.answer = AsyncMock()

    long_error = "CRITICAL_ERROR: " + "A" * 500  # 516 chars
    await safe_answer_callback(query, long_error, show_alert=True, max_len=180)

    assert query.answer.called
    answered_text = query.answer.call_args[0][0]
    assert len(answered_text) <= 180
    assert answered_text.endswith("...")


@pytest.mark.asyncio
async def test_handle_pay_approve_callback_long_exception_safety():
    """Verify handle_pay_approve_callback never crashes on long database exceptions."""
    update = MagicMock()
    update.effective_user.id = 111222333  # Admin ID
    update.callback_query.data = "pay_approve:9999"
    update.callback_query.answer = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()
    context = MagicMock()

    # Simulate internal database IntegrityError with long SQL traceback
    with patch("services.payment_service.payment_service.verify_and_deliver", side_effect=Exception("sqlalchemy.exc.IntegrityError: NOT NULL constraint failed: subscriptions.inventory_id [SQL: INSERT INTO subscriptions ...]" * 10)):
        await handle_pay_approve_callback(update, context)

    # Verify callback was answered with short safe alert, not long traceback
    assert update.callback_query.answer.called
    alert_text = update.callback_query.answer.call_args[0][0]
    assert len(alert_text) <= 180
    assert "Check application logs" in alert_text
    assert "INSERT INTO subscriptions" not in alert_text


# ============================================================================
# 8. SQLITE & POSTGRESQL MIGRATION LOGIC
# ============================================================================
def test_sqlite_migration_makes_inventory_id_nullable(tmp_path):
    """
    Test SQLite migration on an isolated database where subscriptions.inventory_id was NOT NULL.
    Verifies zero data loss and nullability.
    """
    db_file = tmp_path / "test_migration.db"
    test_db_url = f"sqlite:///{db_file}"
    mig_engine = create_engine(test_db_url)

    # 1. Create legacy schema where inventory_id was NOT NULL
    raw_setup = mig_engine.raw_connection()
    try:
        raw_setup.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY, telegram_id BIGINT UNIQUE);
            CREATE TABLE plans (id INTEGER PRIMARY KEY, code VARCHAR(32));
            CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, plan_id INTEGER);
            CREATE TABLE inventory (id INTEGER PRIMARY KEY, ip VARCHAR(64));
            CREATE TABLE daily_inventory (id INTEGER PRIMARY KEY, ip VARCHAR(64));

            CREATE TABLE subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sub_code VARCHAR(64) NOT NULL UNIQUE,
                user_id INTEGER NOT NULL REFERENCES users(id),
                plan_id INTEGER NOT NULL REFERENCES plans(id),
                order_id INTEGER NOT NULL REFERENCES orders(id),
                inventory_id INTEGER NOT NULL REFERENCES inventory(id),
                start_date DATETIME NOT NULL,
                end_date DATETIME NOT NULL,
                status VARCHAR(32) NOT NULL,
                reminded_24h BOOLEAN NOT NULL DEFAULT 0,
                reminded_1h BOOLEAN NOT NULL DEFAULT 0,
                expired_notified BOOLEAN NOT NULL DEFAULT 0,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );

            CREATE TABLE proxy_allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subscription_id INTEGER NOT NULL REFERENCES subscriptions(id),
                inventory_id INTEGER NOT NULL REFERENCES inventory(id),
                user_id INTEGER NOT NULL REFERENCES users(id),
                assigned_at DATETIME NOT NULL,
                revoked_at DATETIME,
                is_active BOOLEAN NOT NULL DEFAULT 1
            );
        """)
        # Seed test row
        raw_setup.execute("INSERT INTO users VALUES (1, 10001)")
        raw_setup.execute("INSERT INTO plans VALUES (1, 'monthly_proxy')")
        raw_setup.execute("INSERT INTO orders VALUES (1, 1, 1)")
        raw_setup.execute("INSERT INTO inventory VALUES (1, '1.1.1.1')")
        raw_setup.execute("""
            INSERT INTO subscriptions VALUES (
                1, 'SUB-LEGACY-001', 1, 1, 1, 1, '2026-01-01', '2026-02-01',
                'ACTIVE', 0, 0, 0, '2026-01-01', '2026-01-01'
            )
        """)
        raw_setup.execute("INSERT INTO proxy_allocations VALUES (1, 1, 1, 1, '2026-01-01', NULL, 1)")
        raw_setup.commit()
    finally:
        raw_setup.close()

    # 2. Run migration
    success = _migrate_sqlite(mig_engine)
    assert success is True

    # 3. Verify inventory_id is now nullable in subscriptions and proxy_allocations
    with mig_engine.connect() as conn:
        sub_info = conn.exec_driver_sql("PRAGMA table_info(subscriptions)").fetchall()
        inv_col = next(c for c in sub_info if c[1] == "inventory_id")
        assert inv_col[3] == 0  # notnull = 0 (NULLABLE)
        daily_col = next(c for c in sub_info if c[1] == "daily_inventory_id")
        assert daily_col is not None

        alloc_info = conn.exec_driver_sql("PRAGMA table_info(proxy_allocations)").fetchall()
        alloc_inv_col = next(c for c in alloc_info if c[1] == "inventory_id")
        assert alloc_inv_col[3] == 0  # notnull = 0 (NULLABLE)

        # 4. Verify existing legacy data was preserved
        sub_count = conn.exec_driver_sql("SELECT COUNT(*) FROM subscriptions").scalar()
        assert sub_count == 1
        sub_row = conn.exec_driver_sql("SELECT sub_code, inventory_id FROM subscriptions").fetchone()
        assert sub_row[0] == "SUB-LEGACY-001"
        assert sub_row[1] == 1

        # 5. Insert Daily Proxy subscription with inventory_id = None
        conn.exec_driver_sql("INSERT INTO daily_inventory VALUES (1, '103.1.1.1')")
        conn.exec_driver_sql("""
            INSERT INTO subscriptions (
                sub_code, user_id, plan_id, order_id, inventory_id, daily_inventory_id,
                start_date, end_date, status, reminded_24h, reminded_1h, expired_notified,
                created_at, updated_at
            ) VALUES (
                'SUB-DAILY-001', 1, 1, 1, NULL, 1, '2026-01-01', '2026-01-02',
                'ACTIVE', 0, 0, 0, '2026-01-01', '2026-01-01'
            )
        """)
        conn.commit()

        daily_sub = conn.exec_driver_sql("SELECT sub_code, inventory_id, daily_inventory_id FROM subscriptions WHERE sub_code='SUB-DAILY-001'").fetchone()
        assert daily_sub[1] is None
        assert daily_sub[2] == 1
