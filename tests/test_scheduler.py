"""
Tests for subscription expiry automation, 24h & 1h reminder flags, and expired holding pool.
"""

from datetime import datetime, timedelta, timezone
import pytest
from database.models import Inventory, InventoryStatus, Plan, Subscription, SubscriptionStatus
from database.crud import create_order, allocate_proxy_and_activate_subscription
from services.crypto_service import crypto_service
from services.scheduler_service import scheduler_service


@pytest.mark.asyncio
async def test_subscription_expiry_automation(db_session, test_user, mock_bot):
    # Setup allocated proxy and subscription
    proxy = Inventory(
        ip="45.10.20.30",
        host="45.10.20.30",
        port=8080,
        username_enc=crypto_service.encrypt("expuser"),
        password_enc=crypto_service.encrypt("exppass"),
        is_special=False,
        status=InventoryStatus.ALLOCATED.value,
        credentials_updated=False,
    )
    db_session.add(proxy)
    db_session.commit()

    plan = db_session.query(Plan).filter(Plan.code == "daily_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)

    # Manually backdate subscription end_date to trigger expiration
    now = datetime.now(timezone.utc)
    expired_sub = Subscription(
        sub_code="SUB-TEST-EXPIRED",
        user_id=test_user.id,
        plan_id=plan.id,
        order_id=order.id,
        inventory_id=proxy.id,
        start_date=now - timedelta(days=2),
        end_date=now - timedelta(minutes=5),  # Ended 5 mins ago
        status=SubscriptionStatus.ACTIVE.value,
    )
    db_session.add(expired_sub)
    db_session.commit()

    # Run check function
    # Patch get_db in scheduler_service module to use our test db_session
    import contextlib
    @contextlib.contextmanager
    def mock_get_db():
        yield db_session

    import services.scheduler_service as sched_mod
    orig_get_db = sched_mod.get_db
    sched_mod.get_db = mock_get_db

    try:
        await scheduler_service.check_subscription_expiries(mock_bot)
    finally:
        sched_mod.get_db = orig_get_db

    # Refresh objects
    db_session.refresh(expired_sub)
    db_session.refresh(proxy)

    # Verify status changed to EXPIRED
    assert expired_sub.status == SubscriptionStatus.EXPIRED.value
    assert expired_sub.expired_notified is True

    # CRITICAL: Verify proxy is in EXPIRED_HOLD pool and NOT automatically resale-ready
    assert proxy.status == InventoryStatus.EXPIRED_HOLD.value
    assert proxy.credentials_updated is False
    assert mock_bot.send_message.called
