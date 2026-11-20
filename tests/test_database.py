"""
Tests for database initialization, schema integrity, and seeded data.
"""

from database.models import Plan, Setting, User


def test_database_initialization(db_session):
    # Verify plans are seeded
    plans = db_session.query(Plan).all()
    assert len(plans) == 3

    plan_codes = {p.code: p for p in plans}
    assert "daily_proxy" in plan_codes
    assert "monthly_proxy" in plan_codes
    assert "special_proxy" in plan_codes

    # Verify plan properties
    assert plan_codes["daily_proxy"].duration_days == 1
    assert plan_codes["daily_proxy"].price_inr == 20.0
    assert plan_codes["daily_proxy"].is_special is False

    assert plan_codes["monthly_proxy"].duration_days == 30
    assert plan_codes["monthly_proxy"].price_inr == 399.0
    assert plan_codes["monthly_proxy"].is_special is False

    assert plan_codes["special_proxy"].duration_days == 30
    assert plan_codes["special_proxy"].price_inr == 499.0
    assert plan_codes["special_proxy"].is_special is True


def test_default_settings_seeded(db_session):
    upi_setting = db_session.query(Setting).filter(Setting.key == "upi_id").first()
    assert upi_setting is not None
    assert "@" in upi_setting.value


def test_detached_plan_attribute_access(db_session):
    """Verify that models retrieved from database remain accessible after session commits/closes."""
    from database.crud import get_active_plans
    from keyboards.customer_kb import get_plans_keyboard

    plans = get_active_plans(db_session)
    db_session.commit()
    db_session.close()

    # Session is now closed and committed (expire_on_commit=False prevents DetachedInstanceError)
    assert len(plans) >= 3
    for plan in plans:
        # Access scalar attributes outside of active session
        assert plan.name != ""
        assert plan.price_inr > 0

    # Ensure keyboard building succeeds without DetachedInstanceError
    kb = get_plans_keyboard(plans)
    assert kb is not None
    assert len(kb.inline_keyboard) >= 4
