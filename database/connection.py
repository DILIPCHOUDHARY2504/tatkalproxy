"""
Tatkal Proxy - Database Engine & Session Management
Handles engine instantiation, connection pools, table creation, and seed data.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import settings
from database.models import Base, Plan, Setting

logger = logging.getLogger("TatkalProxy.Database")

# Determine engine parameters based on database driver
engine_kwargs = {"echo": False}
if settings.DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # PostgreSQL connection pool settings
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20
    engine_kwargs["pool_pre_ping"] = True

engine = create_engine(settings.DATABASE_URL, **engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Context manager for transactional database operations."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Database transaction error: {e}", exc_info=True)
        raise
    finally:
        session.close()


def seed_default_plans(db: Session) -> None:
    """Seed initial subscription plans if they do not exist."""
    default_plans = [
        {
            "code": "daily_proxy",
            "name": "Daily Proxy",
            "duration_days": 1,
            "price_inr": 20.0,
            "is_special": False,
            "description": "24 Hours High-Speed Dedicated Proxy (Standard Pool)",
        },
        {
            "code": "monthly_proxy",
            "name": "Monthly Proxy",
            "duration_days": 30,
            "price_inr": 399.0,
            "is_special": False,
            "description": "30 Days High-Speed Dedicated Proxy (Standard Pool)",
        },
        {
            "code": "special_proxy",
            "name": "Special IP Proxy",
            "duration_days": 30,
            "price_inr": 499.0,
            "is_special": True,
            "description": "30 Days Premium Dedicated 103.x.x.x Special IP Proxy",
        },
    ]

    for plan_data in default_plans:
        existing = db.query(Plan).filter(Plan.code == plan_data["code"]).first()
        if not existing:
            plan = Plan(**plan_data)
            db.add(plan)
            logger.info(f"Seeded plan: {plan.name} (₹{plan.price_inr})")
    db.commit()


def seed_default_settings(db: Session) -> None:
    """Seed default application settings if not set."""
    defaults = {
        "upi_id": settings.UPI_ID if settings.UPI_ID else "tatkalproxy@okaxis",
        "upi_name": settings.UPI_NAME or "Tatkal Proxy Store",
        "support_contact": "@TatkalProxySupport",
        "terms_notice": "Proxies are dedicated. No refunds after proxy delivery. Auto-renewal can be scheduled anytime.",
    }

    for key, val in defaults.items():
        existing = db.query(Setting).filter(Setting.key == key).first()
        if not existing:
            setting = Setting(key=key, value=val, description=f"Default {key}")
            db.add(setting)
    db.commit()


def migrate_schema() -> None:
    """Safely apply backward-compatible schema updates for SQLite/Postgres without dropping tables."""
    try:
        from database.migration import run_migrations
        run_migrations(engine)
    except Exception as e:
        logger.warning(f"Schema migration note: {e}")


def init_db() -> None:
    """Create all tables and seed default plans and configurations."""
    logger.info("Initializing database schema...")
    Base.metadata.create_all(bind=engine)
    migrate_schema()
    with get_db() as db:
        seed_default_plans(db)
        seed_default_settings(db)
    logger.info("Database initialized successfully.")
