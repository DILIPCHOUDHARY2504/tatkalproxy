"""
Tests for atomic allocation, plan stock checking, multi-quantity purchases, and 1-day midnight expiry.
"""

from datetime import datetime, timezone
import pytest
from database.models import Inventory, DailyInventory, InventoryStatus, Plan, Order, Subscription, SubscriptionStatus
from database.crud import create_order, allocate_proxy_and_activate_subscription
from services.allocation_service import allocation_service
from services.crypto_service import crypto_service


def test_atomic_allocation_standard_vs_special(db_session, test_user):
    # Add 1 standard proxy, 1 special proxy, and 1 isolated daily proxy
    std_proxy = Inventory(
        ip="45.1.2.3",
        host="45.1.2.3",
        port=8080,
        username_enc=crypto_service.encrypt("stduser"),
        password_enc=crypto_service.encrypt("stdpass"),
        is_special=False,
        status=InventoryStatus.AVAILABLE.value,
    )
    spec_proxy = Inventory(
        ip="103.1.2.3",
        host="103.1.2.3",
        port=8080,
        username_enc=crypto_service.encrypt("specuser"),
        password_enc=crypto_service.encrypt("specpass"),
        is_special=True,
        status=InventoryStatus.AVAILABLE.value,
    )
    daily_proxy = DailyInventory(
        ip="103.99.1.1",
        host="103.99.1.1",
        port=8080,
        username_enc=crypto_service.encrypt("dailyuser"),
        password_enc=crypto_service.encrypt("dailypass"),
        status=InventoryStatus.AVAILABLE.value,
    )
    db_session.add_all([std_proxy, spec_proxy, daily_proxy])
    db_session.commit()

    # User buys Daily Proxy (Allocates strictly from DailyInventory)
    daily_plan = db_session.query(Plan).filter(Plan.code == "daily_proxy").first()
    order_daily = create_order(db_session, test_user.id, daily_plan.id, daily_plan.price_inr, quantity=1)

    subs_daily, invs_daily = allocate_proxy_and_activate_subscription(db_session, order_daily.id)
    inv_daily = invs_daily[0]
    sub_daily = subs_daily[0]
    assert inv_daily.ip == "103.99.1.1"
    assert inv_daily.status == InventoryStatus.ALLOCATED.value
    assert sub_daily.status == SubscriptionStatus.ACTIVE.value
    assert sub_daily.daily_inventory_id == daily_proxy.id

    # Verify 1-day midnight expiry rule: expires at 23:59:59 IST today!
    from utils.formatters import IST
    ist_end = sub_daily.end_date.astimezone(IST)
    assert ist_end.hour == 23
    assert ist_end.minute == 59
    assert ist_end.second == 59

    # User buys Monthly Proxy (Standard Pool from regular inventory)
    monthly_plan = db_session.query(Plan).filter(Plan.code == "monthly_proxy").first()
    order_monthly = create_order(db_session, test_user.id, monthly_plan.id, monthly_plan.price_inr, quantity=1)
    subs_month, invs_month = allocate_proxy_and_activate_subscription(db_session, order_monthly.id)
    assert invs_month[0].ip == "45.1.2.3"
    assert invs_month[0].status == InventoryStatus.ALLOCATED.value

    # User buys Special Proxy (103.x.x.x Pool from regular inventory)
    spec_plan = db_session.query(Plan).filter(Plan.code == "special_proxy").first()
    order_spec = create_order(db_session, test_user.id, spec_plan.id, spec_plan.price_inr, quantity=1)

    subs_spec, invs_spec = allocate_proxy_and_activate_subscription(db_session, order_spec.id)
    inv_spec = invs_spec[0]
    sub_spec = subs_spec[0]
    assert inv_spec.ip == "103.1.2.3"
    assert inv_spec.status == InventoryStatus.ALLOCATED.value
    assert sub_spec.status == SubscriptionStatus.ACTIVE.value


def test_multiple_ips_purchase_allocation(db_session, test_user):
    """Test purchasing 3 proxies in a single order."""
    # Add 4 standard proxies
    proxies = [
        Inventory(
            ip=f"45.10.20.{i}",
            host=f"45.10.20.{i}",
            port=8080,
            username_enc=crypto_service.encrypt(f"user{i}"),
            password_enc=crypto_service.encrypt(f"pass{i}"),
            is_special=False,
            status=InventoryStatus.AVAILABLE.value,
        )
        for i in range(1, 5)
    ]
    db_session.add_all(proxies)
    db_session.commit()

    monthly_plan = db_session.query(Plan).filter(Plan.code == "monthly_proxy").first()
    total_amount = monthly_plan.price_inr * 3
    order = create_order(db_session, test_user.id, monthly_plan.id, total_amount, quantity=3)

    subs, invs = allocate_proxy_and_activate_subscription(db_session, order.id)
    assert len(subs) == 3
    assert len(invs) == 3
    assert all(inv.status == InventoryStatus.ALLOCATED.value for inv in invs)
    # Check distinct IPs allocated
    ips = {inv.ip for inv in invs}
    assert len(ips) == 3


def test_out_of_stock_allocation_rejection(db_session, test_user):
    # Ensure no proxies in inventory
    db_session.query(Inventory).delete()
    db_session.commit()

    daily_plan = db_session.query(Plan).filter(Plan.code == "daily_proxy").first()
    has_stock, count = allocation_service.check_plan_stock(db_session, daily_plan.id)
    assert has_stock is False
    assert count == 0

    order = create_order(db_session, test_user.id, daily_plan.id, daily_plan.price_inr)
    with pytest.raises(ValueError, match="Insufficient inventory"):
        allocate_proxy_and_activate_subscription(db_session, order.id)
