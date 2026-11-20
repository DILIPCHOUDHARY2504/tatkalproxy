"""
Tests for administrative security authorization, pricing updates, audit trails,
and credential rotation enforcement on expired inventory.
"""

import pytest
from config import settings
from database.models import Inventory, InventoryStatus, Plan, AdminLog
from database.crud import (
    update_plan_price,
    update_proxy_credentials,
    release_expired_proxy_to_available,
    disable_proxy,
    search_users,
    set_user_blocked_status,
)
from services.crypto_service import crypto_service


def test_numeric_admin_authorization():
    # settings.ADMIN_IDS configured with 111222333, 444555666 in conftest
    assert settings.is_admin(111222333) is True
    assert settings.is_admin(444555666) is True
    assert settings.is_admin(999999999) is False
    assert settings.is_admin(None) is False


def test_plan_price_modification_and_audit(db_session, test_admin):
    daily_plan = db_session.query(Plan).filter(Plan.code == "daily_proxy").first()
    assert daily_plan.price_inr == 20.0

    # Admin changes price to 25.0
    updated_plan = update_plan_price(db_session, daily_plan.id, 25.0, admin_id=test_admin.id)
    assert updated_plan.price_inr == 25.0

    # Verify audit log created
    log = (
        db_session.query(AdminLog)
        .filter(AdminLog.action == "PLAN_PRICE_UPDATED", AdminLog.target_id == str(daily_plan.id))
        .first()
    )
    assert log is not None
    assert "25.0" in log.details


def test_credential_editing_and_audit(db_session, test_admin):
    proxy = Inventory(
        ip="103.11.22.33",
        host="103.11.22.33",
        port=8080,
        username_enc=crypto_service.encrypt("olduser"),
        password_enc=crypto_service.encrypt("oldpass"),
        is_special=True,
        status=InventoryStatus.AVAILABLE.value,
        credentials_updated=True,
    )
    db_session.add(proxy)
    db_session.commit()

    # Admin rotates password
    updated_proxy = update_proxy_credentials(
        db=db_session,
        inventory_id=proxy.id,
        new_password="NewRotatedPassword!456",
        admin_id=test_admin.id,
        reason="Routine rotation",
    )

    decrypted_pass = crypto_service.decrypt(updated_proxy.password_enc)
    assert decrypted_pass == "NewRotatedPassword!456"

    # Verify audit log and credential history
    assert len(updated_proxy.credential_history) == 1
    hist = updated_proxy.credential_history[0]
    assert crypto_service.decrypt(hist.old_password_enc) == "oldpass"
    assert crypto_service.decrypt(hist.new_password_enc) == "NewRotatedPassword!456"


def test_expired_proxy_resale_authorization(db_session, test_admin):
    expired_proxy = Inventory(
        ip="103.77.88.99",
        host="103.77.88.99",
        port=8080,
        username_enc=crypto_service.encrypt("exp_user"),
        password_enc=crypto_service.encrypt("exp_pass"),
        is_special=True,
        status=InventoryStatus.EXPIRED_HOLD.value,
        credentials_updated=False,  # Not rotated yet!
    )
    db_session.add(expired_proxy)
    db_session.commit()

    # Attempting resale before rotating credentials must be rejected
    with pytest.raises(ValueError, match="Cannot release proxy for resale before updating its credentials"):
        release_expired_proxy_to_available(db_session, expired_proxy.id, admin_id=test_admin.id)

    # Now rotate credentials
    update_proxy_credentials(
        db=db_session,
        inventory_id=expired_proxy.id,
        new_password="RotatedPassword999",
        admin_id=test_admin.id,
    )

    # Now resale release succeeds
    released = release_expired_proxy_to_available(db_session, expired_proxy.id, admin_id=test_admin.id)
    assert released.status == InventoryStatus.AVAILABLE.value


def test_customer_blocking_and_lookup(db_session, test_user):
    # Lookup by username
    users = search_users(db_session, "testcustomer")
    assert len(users) == 1
    assert users[0].telegram_id == test_user.telegram_id

    # Block user
    blocked_user = set_user_blocked_status(db_session, test_user.id, blocked=True)
    assert blocked_user.is_blocked is True
