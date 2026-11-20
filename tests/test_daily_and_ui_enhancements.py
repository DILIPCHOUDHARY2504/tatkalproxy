"""
Comprehensive test suite for:
1. Feature 1: Isolated Daily (1-Day) Proxy Inventory, Upload, Midnight IST Expiry, and Disclaimer
2. Feature 2: Persistent Bottom Navigation Reply Keyboard
3. Feature 3: Admin Inventory Dashboard, Breakdown Stats, and Submenus
"""

from datetime import datetime, timedelta, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock

from database.models import (
    Inventory,
    DailyInventory,
    InventoryStatus,
    Plan,
    Order,
    Subscription,
    SubscriptionStatus,
    User,
)
from database.crud import (
    create_order,
    allocate_proxy_and_activate_subscription,
    get_daily_inventory_stats,
    get_comprehensive_inventory_stats,
    find_proxy_by_ip,
    ip_exists_in_any_inventory,
)
from services.allocation_service import allocation_service
from services.inventory_service import (
    process_txt_inventory,
    process_daily_txt_inventory,
    process_daily_csv_inventory,
    format_proxy_delivery,
)
from services.crypto_service import crypto_service
from services.scheduler_service import scheduler_service
from utils.formatters import (
    DAILY_PROXY_DISCLAIMER,
    format_plan_card,
    format_order_summary,
    format_delivered_proxy_message,
    IST,
)
from keyboards.customer_kb import get_customer_reply_keyboard
from keyboards.admin_kb import (
    get_admin_inventory_menu_keyboard,
    get_admin_upload_regular_keyboard,
    get_admin_upload_daily_keyboard,
)
from handlers.customer import handle_persistent_menu_text
from handlers.admin import verify_admin


# ============================================================================
# 1. FEATURE 1: SEPARATE INVENTORY ISOLATION & ALLOCATION
# ============================================================================
def test_daily_inventory_isolation_and_allocation(db_session, test_user):
    """Verify daily proxies only allocate to Daily plan, and monthly/special never touch daily inventory."""
    # Seed 1 daily proxy, 1 monthly standard proxy, 1 special proxy
    daily_item = DailyInventory(
        ip="103.10.10.1",
        host="103.10.10.1",
        port=8080,
        username_enc=crypto_service.encrypt("dailyuser"),
        password_enc=crypto_service.encrypt("dailypass"),
        status=InventoryStatus.AVAILABLE.value,
    )
    std_item = Inventory(
        ip="45.20.20.1",
        host="45.20.20.1",
        port=8080,
        username_enc=crypto_service.encrypt("stduser"),
        password_enc=crypto_service.encrypt("stdpass"),
        is_special=False,
        status=InventoryStatus.AVAILABLE.value,
    )
    spec_item = Inventory(
        ip="103.30.30.1",
        host="103.30.30.1",
        port=8080,
        username_enc=crypto_service.encrypt("specuser"),
        password_enc=crypto_service.encrypt("specpass"),
        is_special=True,
        status=InventoryStatus.AVAILABLE.value,
    )
    db_session.add_all([daily_item, std_item, spec_item])
    db_session.commit()

    # Check stock check isolation
    daily_plan = db_session.query(Plan).filter(Plan.code == "daily_proxy").first()
    monthly_plan = db_session.query(Plan).filter(Plan.code == "monthly_proxy").first()
    special_plan = db_session.query(Plan).filter(Plan.code == "special_proxy").first()

    has_daily_stock, count_daily = allocation_service.check_plan_stock(db_session, daily_plan.id)
    has_monthly_stock, count_monthly = allocation_service.check_plan_stock(db_session, monthly_plan.id)
    has_special_stock, count_special = allocation_service.check_plan_stock(db_session, special_plan.id)

    assert has_daily_stock and count_daily == 1
    assert has_monthly_stock and count_monthly == 1
    assert has_special_stock and count_special == 1

    # Buy Daily Proxy
    order_daily = create_order(db_session, test_user.id, daily_plan.id, daily_plan.price_inr, quantity=1)
    subs_d, invs_d = allocate_proxy_and_activate_subscription(db_session, order_daily.id)
    assert invs_d[0].ip == "103.10.10.1"
    assert isinstance(invs_d[0], DailyInventory)
    assert subs_d[0].daily_inventory_id == daily_item.id
    assert subs_d[0].inventory_id is None

    # Buy Monthly Proxy -> MUST allocate standard item from Inventory, NEVER DailyInventory
    order_monthly = create_order(db_session, test_user.id, monthly_plan.id, monthly_plan.price_inr, quantity=1)
    subs_m, invs_m = allocate_proxy_and_activate_subscription(db_session, order_monthly.id)
    assert invs_m[0].ip == "45.20.20.1"
    assert isinstance(invs_m[0], Inventory)
    assert subs_m[0].inventory_id == std_item.id
    assert subs_m[0].daily_inventory_id is None

    # Verify Daily Proxy is now out of stock
    has_daily_stock_after, count_daily_after = allocation_service.check_plan_stock(db_session, daily_plan.id)
    assert not has_daily_stock_after and count_daily_after == 0


def test_cross_inventory_duplicate_detection(db_session):
    """Verify duplicate IP prevention across both regular and daily inventory tables."""
    # Add regular proxy
    regular_proxy = Inventory(
        ip="103.50.50.50",
        host="103.50.50.50",
        port=8080,
        username_enc=crypto_service.encrypt("u"),
        password_enc=crypto_service.encrypt("p"),
        is_special=True,
        status=InventoryStatus.AVAILABLE.value,
    )
    db_session.add(regular_proxy)
    db_session.commit()

    assert ip_exists_in_any_inventory(db_session, "103.50.50.50") is True

    # Attempt to upload the SAME IP into daily inventory via TXT -> Must be rejected as duplicate
    txt_content = "103.50.50.50:8080:dailyuser:dailypwd"
    res = process_daily_txt_inventory(db_session, txt_content, admin_id=111)
    assert res.imported_count == 0
    assert res.duplicate_db_count == 1
    assert "already exists in database" in res.errors[0]

    # Attempt to upload into daily inventory via CSV -> Must be rejected as duplicate
    csv_content = "ip,port,username,password\n103.50.50.50,8080,dailyuser,dailypwd"
    res_csv = process_daily_csv_inventory(db_session, csv_content, admin_id=111)
    assert res_csv.imported_count == 0
    assert res_csv.duplicate_db_count == 1


def test_daily_txt_and_csv_import_success(db_session):
    """Test importing fresh daily proxy batch via TXT and CSV."""
    txt_content = (
        "103.77.1.1:8080:user1:pass1\n"
        "103.77.1.2:8080:user2:pass2\n"
        "103.77.1.1:8080:user1:pass1\n"  # Duplicate in file
        "invalid_proxy_line\n"
    )
    res_txt = process_daily_txt_inventory(db_session, txt_content, admin_id=111)
    assert res_txt.total_lines == 4
    assert res_txt.imported_count == 2
    assert res_txt.duplicate_file_count == 1
    assert res_txt.total_errors == 2

    # Verify encrypted storage in DailyInventory
    daily_1 = db_session.query(DailyInventory).filter(DailyInventory.ip == "103.77.1.1").first()
    assert daily_1 is not None
    assert daily_1.username_enc != "user1"  # Encrypted at rest
    assert crypto_service.decrypt(daily_1.username_enc) == "user1"
    assert crypto_service.decrypt(daily_1.password_enc) == "pass1"

    # CSV daily import
    csv_content = "ip,port,username,password\n103.77.1.3,9090,user3,pass3"
    res_csv = process_daily_csv_inventory(db_session, csv_content, admin_id=111)
    assert res_csv.imported_count == 1
    daily_3 = db_session.query(DailyInventory).filter(DailyInventory.ip == "103.77.1.3").first()
    assert daily_3 is not None
    assert daily_3.port == 9090


# ============================================================================
# 2. FEATURE 1C: MIDNIGHT IST EXPIRY & PURGE
# ============================================================================
@pytest.mark.asyncio
async def test_daily_proxy_midnight_ist_expiry_and_credential_quarantine(db_session, test_user, mock_bot):
    """Verify daily proxies expire at midnight IST and credentials are automatically quarantined."""
    daily_item = DailyInventory(
        ip="103.88.88.88",
        host="103.88.88.88",
        port=8080,
        username_enc=crypto_service.encrypt("secret_daily_user"),
        password_enc=crypto_service.encrypt("secret_daily_pass"),
        status=InventoryStatus.AVAILABLE.value,
    )
    db_session.add(daily_item)
    db_session.commit()

    daily_plan = db_session.query(Plan).filter(Plan.code == "daily_proxy").first()
    order = create_order(db_session, test_user.id, daily_plan.id, daily_plan.price_inr, quantity=1)
    subs, items = allocate_proxy_and_activate_subscription(db_session, order.id)
    sub = subs[0]
    inv = items[0]

    # Verify end date is 23:59:59 IST
    ist_end = sub.end_date.astimezone(IST)
    assert ist_end.hour == 23 and ist_end.minute == 59 and ist_end.second == 59

    # Simulate midnight arrival: backdate sub end_date to past
    sub.end_date = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    # Patch get_db in scheduler
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

    db_session.refresh(sub)
    db_session.refresh(daily_item)

    # 1. Subscription must be EXPIRED
    assert sub.status == SubscriptionStatus.EXPIRED.value

    # 2. Daily item must be EXPIRED/quarantined
    assert daily_item.status == "EXPIRED"
    assert daily_item.current_user_id is None

    # 3. Credentials must be randomized/quarantined, NOT readable as the old secret
    decrypted_user = crypto_service.decrypt(daily_item.username_enc)
    assert decrypted_user.startswith("EXPIRED_")
    assert decrypted_user != "secret_daily_user"


@pytest.mark.asyncio
async def test_startup_reconciliation_overdue_daily(db_session, test_user, mock_bot):
    """Test startup recovery catches missed daily expiries."""
    # Stale daily item from yesterday
    yesterday = datetime.now(timezone.utc) - timedelta(days=2)
    stale_item = DailyInventory(
        ip="103.99.99.1",
        host="103.99.99.1",
        port=8080,
        username_enc=crypto_service.encrypt("stale_u"),
        password_enc=crypto_service.encrypt("stale_p"),
        status=InventoryStatus.AVAILABLE.value,
        created_at=yesterday,
    )
    db_session.add(stale_item)
    db_session.commit()

    import contextlib
    @contextlib.contextmanager
    def mock_get_db():
        yield db_session

    import services.scheduler_service as sched_mod
    orig_get_db = sched_mod.get_db
    sched_mod.get_db = mock_get_db

    try:
        count = await scheduler_service.reconcile_overdue_daily_expiries(mock_bot)
    finally:
        sched_mod.get_db = orig_get_db

    db_session.refresh(stale_item)
    assert stale_item.status == "EXPIRED"
    assert count >= 1


# ============================================================================
# 3. FEATURE 1E: CUSTOMER DAILY PROXY DISCLAIMER
# ============================================================================
def test_customer_daily_proxy_disclaimer(db_session):
    """Verify exact disclaimer appears only for 1-day proxy and never for monthly/special."""
    daily_plan = db_session.query(Plan).filter(Plan.code == "daily_proxy").first()
    monthly_plan = db_session.query(Plan).filter(Plan.code == "monthly_proxy").first()
    special_plan = db_session.query(Plan).filter(Plan.code == "special_proxy").first()

    # Plan Cards
    card_daily = format_plan_card(daily_plan, True, 5)
    card_monthly = format_plan_card(monthly_plan, True, 5)
    card_special = format_plan_card(special_plan, True, 5)

    assert "DAILY PROXY NOTICE" in card_daily
    assert "Your proxy is valid only until 11:59 PM IST" in card_daily
    assert "The subscription will automatically expire at midnight" in card_daily
    assert "DAILY PROXY NOTICE" not in card_monthly
    assert "DAILY PROXY NOTICE" not in card_special

    # Order Summaries
    order_daily = Order(order_code="ORD-D1", user_id=1, plan_id=daily_plan.id, amount=20.0, quantity=1, plan=daily_plan)
    order_monthly = Order(order_code="ORD-M1", user_id=1, plan_id=monthly_plan.id, amount=399.0, quantity=1, plan=monthly_plan)

    sum_daily = format_order_summary(order_daily)
    sum_monthly = format_order_summary(order_monthly)
    assert "DAILY PROXY NOTICE" in sum_daily
    assert "DAILY PROXY NOTICE" not in sum_monthly


# ============================================================================
# 4. FEATURE 2: PERSISTENT BOTTOM REPLY KEYBOARD
# ============================================================================
def test_persistent_reply_keyboard_structure():
    """Verify persistent reply keyboard parameters and layout."""
    kb = get_customer_reply_keyboard()
    assert kb.is_persistent is True
    assert kb.resize_keyboard is True
    assert kb.one_time_keyboard is False

    flat_buttons = [btn.text for row in kb.keyboard for btn in row]
    assert "🛒 Buy Proxy" in flat_buttons
    assert "📦 My Proxies" in flat_buttons
    assert "💳 Payment / Orders" in flat_buttons
    assert "👤 My Account" in flat_buttons
    assert "📞 Support" in flat_buttons
    assert "🏠 Main Menu" in flat_buttons


@pytest.mark.asyncio
async def test_persistent_reply_keyboard_routing(db_session, test_user):
    """Test text message routing for bottom persistent buttons."""
    import contextlib
    @contextlib.contextmanager
    def mock_get_db():
        yield db_session

    import handlers.customer as cust_mod
    orig_get_db = cust_mod.get_db
    cust_mod.get_db = mock_get_db

    try:
        for btn_text in ["🛒 Buy Proxy", "📦 My Proxies", "💳 Payment / Orders", "👤 My Account", "📞 Support", "🏠 Main Menu"]:
            update = MagicMock()
            update.message.text = btn_text
            update.effective_user.id = test_user.telegram_id
            update.effective_user.username = test_user.username
            update.message.reply_text = AsyncMock()
            context = MagicMock()
            context.user_data = {}

            handled = await handle_persistent_menu_text(update, context)
            assert handled is True
            assert update.message.reply_text.called
    finally:
        cust_mod.get_db = orig_get_db


# ============================================================================
# 5. FEATURE 3: ADMIN INVENTORY DASHBOARD & SUBMENUS
# ============================================================================
def test_comprehensive_inventory_dashboard_stats(db_session):
    """Verify live breakdown stats for Standard, Special, Daily, and Quarantined."""
    # Seed 2 standard, 3 special, 4 daily, 1 quarantined
    std1 = Inventory(ip="1.1.1.1", host="1.1.1.1", port=80, username_enc="u", password_enc="p", is_special=False, status="AVAILABLE")
    std2 = Inventory(ip="1.1.1.2", host="1.1.1.2", port=80, username_enc="u", password_enc="p", is_special=False, status="ALLOCATED")

    spec1 = Inventory(ip="103.1.1.1", host="103.1.1.1", port=80, username_enc="u", password_enc="p", is_special=True, status="AVAILABLE")
    spec2 = Inventory(ip="103.1.1.2", host="103.1.1.2", port=80, username_enc="u", password_enc="p", is_special=True, status="AVAILABLE")
    spec3 = Inventory(ip="103.1.1.3", host="103.1.1.3", port=80, username_enc="u", password_enc="p", is_special=True, status="ALLOCATED")

    d1 = DailyInventory(ip="103.2.2.1", host="103.2.2.1", port=80, username_enc="u", password_enc="p", status="AVAILABLE")
    d2 = DailyInventory(ip="103.2.2.2", host="103.2.2.2", port=80, username_enc="u", password_enc="p", status="ALLOCATED")
    d3 = DailyInventory(ip="103.2.2.3", host="103.2.2.3", port=80, username_enc="u", password_enc="p", status="EXPIRED")
    d4 = DailyInventory(ip="103.2.2.4", host="103.2.2.4", port=80, username_enc="u", password_enc="p", status="AVAILABLE")

    quarantine = Inventory(ip="2.2.2.2", host="2.2.2.2", port=80, username_enc="u", password_enc="p", is_special=False, status=InventoryStatus.EXPIRED_HOLD.value)

    db_session.add_all([std1, std2, spec1, spec2, spec3, d1, d2, d3, d4, quarantine])
    db_session.commit()

    stats = get_comprehensive_inventory_stats(db_session)
    assert stats["standard_total"] == 3  # std1, std2, quarantine
    assert stats["standard_available"] == 1
    assert stats["standard_allocated"] == 1

    assert stats["special_total"] == 3
    assert stats["special_available"] == 2
    assert stats["special_allocated"] == 1

    assert stats["daily_total"] == 4
    assert stats["daily_available"] == 2
    assert stats["daily_allocated"] == 1
    assert stats["daily_expired"] == 1

    assert stats["quarantined_total"] == 1


def test_admin_inventory_keyboards():
    """Verify action buttons on admin inventory dashboard and submenus."""
    main_kb = get_admin_inventory_menu_keyboard()
    reg_kb = get_admin_upload_regular_keyboard()
    daily_kb = get_admin_upload_daily_keyboard()

    main_callbacks = [btn.callback_data for row in main_kb.inline_keyboard for btn in row]
    assert "admin_upload_regular_menu" in main_callbacks
    assert "admin_upload_daily_menu" in main_callbacks
    assert "admin_search_ip" in main_callbacks
    assert "admin_inventory_menu" in main_callbacks
    assert "admin_home" in main_callbacks

    reg_callbacks = [btn.callback_data for row in reg_kb.inline_keyboard for btn in row]
    assert "admin_upload_txt" in reg_callbacks
    assert "admin_upload_csv" in reg_callbacks

    daily_callbacks = [btn.callback_data for row in daily_kb.inline_keyboard for btn in row]
    assert "admin_upload_daily_txt" in daily_callbacks
    assert "admin_upload_daily_csv" in daily_callbacks


def test_admin_authorization():
    """Verify numeric Telegram admin validation."""
    admin_update = MagicMock()
    admin_update.effective_user.id = 111222333  # In ADMIN_IDS from conftest
    assert verify_admin(admin_update) is True

    non_admin_update = MagicMock()
    non_admin_update.effective_user.id = 999999999
    assert verify_admin(non_admin_update) is False
