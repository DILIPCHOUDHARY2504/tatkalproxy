"""
Tatkal Proxy - Database Schema Migration Module
Handles safe, zero-data-loss schema migrations for SQLite and PostgreSQL.
Specifically ensures:
1. subscriptions.inventory_id is NULLABLE (for Daily Proxy subscriptions)
2. subscriptions.daily_inventory_id exists and is NULLABLE
3. proxy_allocations.inventory_id is NULLABLE
4. proxy_allocations.daily_inventory_id exists and is NULLABLE
Preserves:
- All existing subscriptions, orders, users, payments, inventory, and foreign key relations.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Optional
from sqlalchemy import text, Engine
from config import settings

logger = logging.getLogger("TatkalProxy.Migration")


def run_migrations(target_engine: Optional[Engine] = None) -> bool:
    """
    Run database migrations.
    Auto-detects SQLite vs PostgreSQL.
    Returns True if migrations succeeded.
    """
    if target_engine is None:
        from database.connection import engine
        target_engine = engine

    dialect_name = target_engine.dialect.name
    logger.info(f"Running database migrations for dialect '{dialect_name}'...")

    if dialect_name == "sqlite":
        return _migrate_sqlite(target_engine)
    elif dialect_name in ("postgresql", "postgres"):
        return _migrate_postgres(target_engine)
    else:
        logger.warning(f"Unsupported dialect '{dialect_name}' for custom migrations. Skipping.")
        return True


def _migrate_sqlite(target_engine: Engine) -> bool:
    """
    Safely migrates SQLite tables to make inventory_id nullable using official
    12-step table recreation procedure while preserving all existing rows.
    """
    # Raw DB-API connection needed for PRAGMA foreign_keys manipulation
    raw_conn = target_engine.raw_connection()
    try:
        cur = raw_conn.cursor()

        # ---------------------------------------------------------------------
        # 1. SUBSCRIPTIONS TABLE MIGRATION
        # ---------------------------------------------------------------------
        cur.execute("PRAGMA table_info(subscriptions)")
        sub_cols = cur.fetchall()
        if sub_cols:
            col_dict = {c[1]: {"type": c[2], "notnull": c[3]} for c in sub_cols}
            needs_sub_migration = False

            if "inventory_id" in col_dict and col_dict["inventory_id"]["notnull"] == 1:
                needs_sub_migration = True
                logger.info("subscriptions.inventory_id is NOT NULL; migration required to make it nullable.")

            if "daily_inventory_id" not in col_dict:
                needs_sub_migration = True
                logger.info("subscriptions.daily_inventory_id is missing; migration required to add it.")

            if needs_sub_migration:
                logger.info("Migrating SQLite 'subscriptions' table to make inventory_id nullable...")
                cur.execute("PRAGMA foreign_keys = OFF")

                # Create replacement table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS subscriptions_migrated (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sub_code VARCHAR(64) NOT NULL,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        plan_id INTEGER NOT NULL REFERENCES plans(id),
                        order_id INTEGER NOT NULL REFERENCES orders(id),
                        inventory_id INTEGER REFERENCES inventory(id),
                        daily_inventory_id INTEGER REFERENCES daily_inventory(id) ON DELETE SET NULL,
                        start_date DATETIME NOT NULL,
                        end_date DATETIME NOT NULL,
                        status VARCHAR(32) NOT NULL,
                        reminded_24h BOOLEAN NOT NULL DEFAULT 0,
                        reminded_1h BOOLEAN NOT NULL DEFAULT 0,
                        expired_notified BOOLEAN NOT NULL DEFAULT 0,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL
                    )
                """)

                # Copy data
                has_daily_col = "daily_inventory_id" in col_dict
                if has_daily_col:
                    cur.execute("""
                        INSERT INTO subscriptions_migrated (
                            id, sub_code, user_id, plan_id, order_id, inventory_id, daily_inventory_id,
                            start_date, end_date, status, reminded_24h, reminded_1h, expired_notified,
                            created_at, updated_at
                        )
                        SELECT 
                            id, sub_code, user_id, plan_id, order_id, inventory_id, daily_inventory_id,
                            start_date, end_date, status, reminded_24h, reminded_1h, expired_notified,
                            created_at, updated_at
                        FROM subscriptions
                    """)
                else:
                    cur.execute("""
                        INSERT INTO subscriptions_migrated (
                            id, sub_code, user_id, plan_id, order_id, inventory_id, daily_inventory_id,
                            start_date, end_date, status, reminded_24h, reminded_1h, expired_notified,
                            created_at, updated_at
                        )
                        SELECT 
                            id, sub_code, user_id, plan_id, order_id, inventory_id, NULL,
                            start_date, end_date, status, reminded_24h, reminded_1h, expired_notified,
                            created_at, updated_at
                        FROM subscriptions
                    """)

                cur.execute("DROP TABLE subscriptions")
                cur.execute("ALTER TABLE subscriptions_migrated RENAME TO subscriptions")

                # Recreate indexes
                cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_subscriptions_sub_code ON subscriptions (sub_code)")
                cur.execute("CREATE INDEX IF NOT EXISTS ix_subscriptions_user_id ON subscriptions (user_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS ix_subscriptions_order_id ON subscriptions (order_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS ix_subscriptions_inventory_id ON subscriptions (inventory_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS ix_subscriptions_daily_inventory_id ON subscriptions (daily_inventory_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS ix_subscriptions_end_date ON subscriptions (end_date)")
                cur.execute("CREATE INDEX IF NOT EXISTS ix_subscriptions_status ON subscriptions (status)")

                raw_conn.commit()
                cur.execute("PRAGMA foreign_keys = ON")
                logger.info("Successfully migrated 'subscriptions' table. inventory_id is now nullable.")

        # ---------------------------------------------------------------------
        # 2. PROXY_ALLOCATIONS TABLE MIGRATION
        # ---------------------------------------------------------------------
        cur.execute("PRAGMA table_info(proxy_allocations)")
        alloc_cols = cur.fetchall()
        if alloc_cols:
            col_dict = {c[1]: {"type": c[2], "notnull": c[3]} for c in alloc_cols}
            needs_alloc_migration = False

            if "inventory_id" in col_dict and col_dict["inventory_id"]["notnull"] == 1:
                needs_alloc_migration = True
                logger.info("proxy_allocations.inventory_id is NOT NULL; migration required to make it nullable.")

            if "daily_inventory_id" not in col_dict:
                needs_alloc_migration = True
                logger.info("proxy_allocations.daily_inventory_id is missing; migration required to add it.")

            if needs_alloc_migration:
                logger.info("Migrating SQLite 'proxy_allocations' table to make inventory_id nullable...")
                cur.execute("PRAGMA foreign_keys = OFF")

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS proxy_allocations_migrated (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
                        inventory_id INTEGER REFERENCES inventory(id) ON DELETE CASCADE,
                        daily_inventory_id INTEGER REFERENCES daily_inventory(id) ON DELETE CASCADE,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        assigned_at DATETIME NOT NULL,
                        revoked_at DATETIME,
                        is_active BOOLEAN NOT NULL DEFAULT 1
                    )
                """)

                has_daily_col = "daily_inventory_id" in col_dict
                if has_daily_col:
                    cur.execute("""
                        INSERT INTO proxy_allocations_migrated (
                            id, subscription_id, inventory_id, daily_inventory_id, user_id, assigned_at, revoked_at, is_active
                        )
                        SELECT 
                            id, subscription_id, inventory_id, daily_inventory_id, user_id, assigned_at, revoked_at, is_active
                        FROM proxy_allocations
                    """)
                else:
                    cur.execute("""
                        INSERT INTO proxy_allocations_migrated (
                            id, subscription_id, inventory_id, daily_inventory_id, user_id, assigned_at, revoked_at, is_active
                        )
                        SELECT 
                            id, subscription_id, inventory_id, NULL, user_id, assigned_at, revoked_at, is_active
                        FROM proxy_allocations
                    """)

                cur.execute("DROP TABLE proxy_allocations")
                cur.execute("ALTER TABLE proxy_allocations_migrated RENAME TO proxy_allocations")

                # Recreate indexes
                cur.execute("CREATE INDEX IF NOT EXISTS ix_proxy_allocations_is_active ON proxy_allocations (is_active)")
                cur.execute("CREATE INDEX IF NOT EXISTS ix_proxy_allocations_subscription_id ON proxy_allocations (subscription_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS ix_proxy_allocations_inventory_id ON proxy_allocations (inventory_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS ix_proxy_allocations_daily_inventory_id ON proxy_allocations (daily_inventory_id)")

                raw_conn.commit()
                cur.execute("PRAGMA foreign_keys = ON")
                logger.info("Successfully migrated 'proxy_allocations' table. inventory_id is now nullable.")

        # ---------------------------------------------------------------------
        # 3. ORDERS TABLE: 5-MINUTE PAYMENT EXPIRY COLUMNS
        # ---------------------------------------------------------------------
        cur.execute("PRAGMA table_info(orders)")
        order_cols = [c[1] for c in cur.fetchall()]
        if order_cols:
            if "payment_created_at" not in order_cols:
                cur.execute("ALTER TABLE orders ADD COLUMN payment_created_at DATETIME")
                logger.info("Added 'payment_created_at' column to orders table.")
            if "payment_expires_at" not in order_cols:
                cur.execute("ALTER TABLE orders ADD COLUMN payment_expires_at DATETIME")
                logger.info("Added 'payment_expires_at' column to orders table.")
            if "expired_at" not in order_cols:
                cur.execute("ALTER TABLE orders ADD COLUMN expired_at DATETIME")
                logger.info("Added 'expired_at' column to orders table.")
            cur.execute("CREATE INDEX IF NOT EXISTS ix_orders_payment_expires_at ON orders(payment_expires_at)")
            raw_conn.commit()

        # ---------------------------------------------------------------------
        # 4. PAYMENTS TABLE: 5-MINUTE PAYMENT EXPIRY COLUMNS
        # ---------------------------------------------------------------------
        cur.execute("PRAGMA table_info(payments)")
        pay_cols = [c[1] for c in cur.fetchall()]
        if pay_cols:
            if "payment_created_at" not in pay_cols:
                cur.execute("ALTER TABLE payments ADD COLUMN payment_created_at DATETIME")
                logger.info("Added 'payment_created_at' column to payments table.")
            if "payment_expires_at" not in pay_cols:
                cur.execute("ALTER TABLE payments ADD COLUMN payment_expires_at DATETIME")
                logger.info("Added 'payment_expires_at' column to payments table.")
            if "expired_at" not in pay_cols:
                cur.execute("ALTER TABLE payments ADD COLUMN expired_at DATETIME")
                logger.info("Added 'expired_at' column to payments table.")
            cur.execute("CREATE INDEX IF NOT EXISTS ix_payments_payment_expires_at ON payments(payment_expires_at)")
            raw_conn.commit()

        return True
    except Exception as e:
        logger.error(f"Error during SQLite schema migration: {e}", exc_info=True)
        raw_conn.rollback()
        raise
    finally:
        raw_conn.close()


def _migrate_postgres(target_engine: Engine) -> bool:
    """
    Safely migrates PostgreSQL schema to make inventory_id nullable and add daily_inventory_id.
    """
    try:
        with target_engine.begin() as conn:
            # 1. subscriptions.inventory_id nullable
            conn.execute(text("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name = 'subscriptions' AND column_name = 'inventory_id' AND is_nullable = 'NO'
                    ) THEN
                        ALTER TABLE subscriptions ALTER COLUMN inventory_id DROP NOT NULL;
                    END IF;
                END $$;
            """))

            # 2. subscriptions.daily_inventory_id column
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name = 'subscriptions' AND column_name = 'daily_inventory_id'
                    ) THEN
                        ALTER TABLE subscriptions ADD COLUMN daily_inventory_id INTEGER REFERENCES daily_inventory(id) ON DELETE SET NULL;
                        CREATE INDEX IF NOT EXISTS ix_subscriptions_daily_inventory_id ON subscriptions(daily_inventory_id);
                    END IF;
                END $$;
            """))

            # 3. proxy_allocations.inventory_id nullable
            conn.execute(text("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name = 'proxy_allocations' AND column_name = 'inventory_id' AND is_nullable = 'NO'
                    ) THEN
                        ALTER TABLE proxy_allocations ALTER COLUMN inventory_id DROP NOT NULL;
                    END IF;
                END $$;
            """))

            # 4. proxy_allocations.daily_inventory_id column
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name = 'proxy_allocations' AND column_name = 'daily_inventory_id'
                    ) THEN
                        ALTER TABLE proxy_allocations ADD COLUMN daily_inventory_id INTEGER REFERENCES daily_inventory(id) ON DELETE CASCADE;
                        CREATE INDEX IF NOT EXISTS ix_proxy_allocations_daily_inventory_id ON proxy_allocations(daily_inventory_id);
                    END IF;
                END $$;
            """))

            # 5. orders: payment expiry columns
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'orders' AND column_name = 'payment_created_at') THEN
                        ALTER TABLE orders ADD COLUMN payment_created_at TIMESTAMP WITH TIME ZONE;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'orders' AND column_name = 'payment_expires_at') THEN
                        ALTER TABLE orders ADD COLUMN payment_expires_at TIMESTAMP WITH TIME ZONE;
                        CREATE INDEX IF NOT EXISTS ix_orders_payment_expires_at ON orders(payment_expires_at);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'orders' AND column_name = 'expired_at') THEN
                        ALTER TABLE orders ADD COLUMN expired_at TIMESTAMP WITH TIME ZONE;
                    END IF;
                END $$;
            """))

            # 6. payments: payment expiry columns
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'payments' AND column_name = 'payment_created_at') THEN
                        ALTER TABLE payments ADD COLUMN payment_created_at TIMESTAMP WITH TIME ZONE;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'payments' AND column_name = 'payment_expires_at') THEN
                        ALTER TABLE payments ADD COLUMN payment_expires_at TIMESTAMP WITH TIME ZONE;
                        CREATE INDEX IF NOT EXISTS ix_payments_payment_expires_at ON payments(payment_expires_at);
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'payments' AND column_name = 'expired_at') THEN
                        ALTER TABLE payments ADD COLUMN expired_at TIMESTAMP WITH TIME ZONE;
                    END IF;
                END $$;
            """))

        logger.info("PostgreSQL schema migration completed successfully.")
        return True
    except Exception as e:
        logger.error(f"Error during PostgreSQL schema migration: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from database.connection import engine
    run_migrations(engine)
