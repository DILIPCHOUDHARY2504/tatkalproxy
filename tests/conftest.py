"""
Tatkal Proxy - Test Configuration & Pytest Fixtures
"""

import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import AsyncMock, MagicMock

# Force test configuration
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ENCRYPTION_KEY"] = "uKz8h6w_xN3qJ8yD-Vb7F3z6Q2o0M8w4P5s1L7r4E2I="
os.environ["ADMIN_IDS"] = "111222333,444555666"

from database.models import Base, User, Plan, Inventory, InventoryStatus
from database.connection import seed_default_plans, seed_default_settings
from services.crypto_service import CryptoService


@pytest.fixture(scope="function")
def test_engine():
    """Create in-memory SQLite engine for tests."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(test_engine):
    """Provide transactional database session for each test."""
    TestingSession = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=test_engine)
    session = TestingSession()
    # Seed default plans and settings
    seed_default_plans(session)
    seed_default_settings(session)
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="function")
def mock_bot():
    """Mock telegram.Bot instance for testing notifications."""
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=True)
    bot.send_photo = AsyncMock(return_value=True)
    return bot


@pytest.fixture(scope="function")
def test_user(db_session):
    """Seed a test customer."""
    user = User(
        telegram_id=987654321,
        username="testcustomer",
        first_name="Test",
        last_name="Customer",
        is_admin=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def test_admin(db_session):
    """Seed a test admin."""
    admin = User(
        telegram_id=111222333,
        username="testadmin",
        first_name="Admin",
        is_admin=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin
