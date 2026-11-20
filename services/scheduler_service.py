"""
Tatkal Proxy - Subscription Expiry Automation
Orchestrates automated expiration checks, 24h & 1h customer notifications,
and non-resale holding pool transition using APScheduler.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import or_
from telegram import Bot

from config import settings
from database.connection import get_db
from database.models import (
    Subscription,
    SubscriptionStatus,
    InventoryStatus,
    DailyInventory,
    Plan,
    Order,
    OrderStatus,
    PaymentStatus,
)
from database.crud import create_admin_log
from services.crypto_service import crypto_service
from utils.formatters import format_dt

logger = logging.getLogger("TatkalProxy.Scheduler")


class ExpirySchedulerService:
    def __init__(self):
        self.scheduler: Optional[AsyncIOScheduler] = None
        self._is_running: bool = False

    def init_scheduler(self, bot: Bot) -> AsyncIOScheduler:
        """Initialize APScheduler with duplicate execution safeguards."""
        if self.scheduler is None:
            self.scheduler = AsyncIOScheduler(timezone=timezone.utc)
            # Run check every 60 seconds
            self.scheduler.add_job(
                func=self.check_subscription_expiries,
                trigger=IntervalTrigger(seconds=60),
                args=[bot],
                id="tatkal_subscription_expiry_job",
                name="Subscription Expiry Monitor",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            logger.info("Initialized ExpirySchedulerService with 60-second cycle.")
        return self.scheduler

    def start(self, bot: Bot) -> None:
        """Start the background scheduler."""
        if not self._is_running:
            sched = self.init_scheduler(bot)
            sched.start()
            self._is_running = True
            logger.info("ExpirySchedulerService started successfully.")

    def stop(self) -> None:
        """Safely shutdown the scheduler."""
        if self.scheduler and self._is_running:
            self.scheduler.shutdown(wait=False)
            self._is_running = False
            logger.info("ExpirySchedulerService stopped.")

    @staticmethod
    async def check_subscription_expiries(bot: Bot) -> None:
        """
        Main execution cycle:
        0. 5-Minute Payment Expiry Check
        1. 24-Hour Expiry Reminder
        2. 1-Hour Expiry Reminder
        3. Expiration transition to EXPIRED_HOLD pool
        """
        await ExpirySchedulerService.expire_stale_orders(bot)

        now = datetime.now(timezone.utc)
        remind_24h_threshold = now + timedelta(hours=settings.REMINDER_24H_HOURS)
        remind_1h_threshold = now + timedelta(hours=settings.REMINDER_1H_HOURS)

        with get_db() as db:
            # 1. 24-HOUR REMINDERS (Only for multi-day plans)
            subs_24h = (
                db.query(Subscription)
                .join(Subscription.plan)
                .filter(
                    Subscription.status == SubscriptionStatus.ACTIVE.value,
                    Plan.duration_days > 1,
                    Subscription.end_date <= remind_24h_threshold,
                    Subscription.end_date > remind_1h_threshold,
                    Subscription.reminded_24h == False,
                )
                .all()
            )
            for sub in subs_24h:
                sub.reminded_24h = True
                db.flush()
                msg_24h = (
                    f"⏰ <b>SUBSCRIPTION EXPIRY NOTICE (24 HOURS)</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Your proxy subscription <code>{sub.sub_code}</code> for IP <code>{sub.proxy_ip}</code> "
                    f"will expire in <b>24 hours</b> (on {format_dt(sub.end_date)}).\n\n"
                    f"🔄 <i>To avoid service disruption, please renew your subscription from 'My Subscriptions'.</i>"
                )
                try:
                    await bot.send_message(chat_id=sub.user.telegram_id, text=msg_24h, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Failed to send 24h reminder to {sub.user.telegram_id}: {e}")

            # 2. 1-HOUR REMINDERS
            subs_1h = (
                db.query(Subscription)
                .filter(
                    Subscription.status == SubscriptionStatus.ACTIVE.value,
                    Subscription.end_date <= remind_1h_threshold,
                    Subscription.end_date > now,
                    Subscription.reminded_1h == False,
                )
                .all()
            )
            for sub in subs_1h:
                sub.reminded_1h = True
                db.flush()
                msg_1h = (
                    f"🚨 <b>SUBSCRIPTION EXPIRY WARNING (1 HOUR)</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Your proxy subscription <code>{sub.sub_code}</code> (<code>{sub.proxy_ip}</code>) "
                    f"will expire in <b>less than 1 hour</b>!\n\n"
                    f"⚡ <i>Renew now to maintain continuous access to this IP.</i>"
                )
                try:
                    await bot.send_message(chat_id=sub.user.telegram_id, text=msg_1h, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Failed to send 1h reminder to {sub.user.telegram_id}: {e}")

            # 3. EXPIRED SUBSCRIPTIONS TRANSITION
            expired_subs = (
                db.query(Subscription)
                .filter(
                    Subscription.status == SubscriptionStatus.ACTIVE.value,
                    Subscription.end_date <= now,
                )
                .all()
            )
            for sub in expired_subs:
                sub.status = SubscriptionStatus.EXPIRED.value
                sub.expired_notified = True

                # Check if Daily Proxy or Regular Proxy
                if sub.daily_inventory_id:
                    daily_inv = sub.daily_inventory
                    if daily_inv:
                        daily_inv.status = "EXPIRED"
                        daily_inv.username_enc = crypto_service.encrypt(f"EXPIRED_{uuid.uuid4().hex[:8]}")
                        daily_inv.password_enc = crypto_service.encrypt(f"EXPIRED_{uuid.uuid4().hex[:8]}")
                        daily_inv.current_user_id = None
                    db.flush()

                    create_admin_log(
                        db=db,
                        admin_id=None,
                        action="DAILY_SUBSCRIPTION_EXPIRED",
                        target_type="daily_subscription",
                        target_id=str(sub.id),
                        details=f"Daily subscription {sub.sub_code} expired at midnight IST. Proxy {sub.proxy_ip} purged.",
                    )
                elif sub.inventory_id:
                    inv = sub.inventory
                    if inv:
                        inv.status = InventoryStatus.EXPIRED_HOLD.value
                        inv.credentials_updated = False  # Requires admin rotation before resale
                        db.flush()

                        create_admin_log(
                            db=db,
                            admin_id=None,
                            action="SUBSCRIPTION_EXPIRED",
                            target_type="subscription",
                            target_id=str(sub.id),
                            details=f"Subscription {sub.sub_code} expired. Proxy {inv.ip} moved to EXPIRED_HOLD.",
                        )

                        if settings.ADMIN_IDS:
                            admin_alert = (
                                f"⏰ <b>STOCK EXPIRED — HOLDING POOL NOTICE</b>\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"Proxy: <code>{inv.ip}:{inv.port}</code>\n"
                                f"Previous Customer: <code>{sub.user.telegram_id}</code> (@{sub.user.username or 'N/A'})\n"
                                f"Status: <b>EXPIRED_HOLD</b>\n\n"
                                f"⚠️ <i>This proxy will NOT be sold until you rotate its password in Expired Proxies manager!</i>"
                            )
                            for admin_tg in settings.ADMIN_IDS:
                                try:
                                    await bot.send_message(chat_id=admin_tg, text=admin_alert, parse_mode="HTML")
                                except Exception as ex:
                                    logger.error(f"Failed to alert admin {admin_tg}: {ex}")

                # Notify customer
                cust_msg = (
                    f"🔴 <b>SUBSCRIPTION EXPIRED</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Your proxy subscription <code>{sub.sub_code}</code> has expired.\n"
                    f"IP: <code>{sub.proxy_ip}</code>\n\n"
                    f"Thank you for choosing Tatkal Proxy!"
                )
                try:
                    await bot.send_message(chat_id=sub.user.telegram_id, text=cust_msg, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Failed to send expiry notice to customer {sub.user.telegram_id}: {e}")

    @staticmethod
    async def expire_stale_orders(bot: Bot | None = None) -> int:
        """
        Check for pending orders that have exceeded their 5-minute payment window.
        Mark order as EXPIRED and record expired_at timestamp.
        """
        now = datetime.now(timezone.utc)
        count = 0
        with get_db() as db:
            stale_orders = (
                db.query(Order)
                .filter(
                    Order.status == OrderStatus.PENDING.value,
                    Order.payment_expires_at <= now,
                )
                .all()
            )
            for order in stale_orders:
                order.status = OrderStatus.EXPIRED.value
                order.expired_at = now
                if order.payment and order.payment.status in [PaymentStatus.PENDING_VERIFICATION.value, "SUBMITTED"]:
                    order.payment.status = PaymentStatus.EXPIRED.value
                    order.payment.expired_at = now
                count += 1
                db.flush()
        if count > 0:
            logger.info(f"Expired {count} stale unpaid orders.")
        return count

    @staticmethod
    async def reconcile_overdue_daily_expiries(bot: Bot | None = None) -> int:
        """
        Reconcile overdue daily subscriptions and daily inventory items on startup or recovery.
        Catches any midnight expirations missed during VPS downtime.
        Also cleans up expired unpaid orders.
        """
        await ExpirySchedulerService.expire_stale_orders(bot)

        now = datetime.now(timezone.utc)
        count = 0
        with get_db() as db:
            overdue_daily_subs = (
                db.query(Subscription)
                .join(Subscription.plan)
                .filter(
                    Subscription.status == SubscriptionStatus.ACTIVE.value,
                    or_(Plan.code == "daily_proxy", Subscription.daily_inventory_id.isnot(None)),
                    Subscription.end_date <= now,
                )
                .all()
            )
            for sub in overdue_daily_subs:
                sub.status = SubscriptionStatus.EXPIRED.value
                sub.expired_notified = True
                if sub.daily_inventory:
                    sub.daily_inventory.status = "EXPIRED"
                    sub.daily_inventory.username_enc = crypto_service.encrypt(f"EXPIRED_{uuid.uuid4().hex[:8]}")
                    sub.daily_inventory.password_enc = crypto_service.encrypt(f"EXPIRED_{uuid.uuid4().hex[:8]}")
                    sub.daily_inventory.current_user_id = None
                count += 1
                db.flush()

            # Also expire any available DailyInventory created before today's IST midnight
            IST = timezone(timedelta(hours=5, minutes=30), name="IST")
            ist_now = now.astimezone(IST)
            ist_today_start = datetime(ist_now.year, ist_now.month, ist_now.day, 0, 0, 0, tzinfo=IST).astimezone(timezone.utc)

            stale_daily_stock = (
                db.query(DailyInventory)
                .filter(
                    DailyInventory.status == InventoryStatus.AVAILABLE.value,
                    DailyInventory.created_at < ist_today_start,
                )
                .all()
            )
            for item in stale_daily_stock:
                item.status = "EXPIRED"
                item.username_enc = crypto_service.encrypt(f"EXPIRED_{uuid.uuid4().hex[:8]}")
                item.password_enc = crypto_service.encrypt(f"EXPIRED_{uuid.uuid4().hex[:8]}")
                count += 1
                db.flush()

        logger.info(f"Reconciled {count} overdue daily subscriptions/items.")
        return count


scheduler_service = ExpirySchedulerService()
