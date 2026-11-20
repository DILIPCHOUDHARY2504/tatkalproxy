"""
Tatkal Proxy - Payment Service
Handles manual UPI workflow, admin notifications, payment approval/rejection,
and proxy delivery dispatch.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from telegram import Bot

from config import settings
from database.models import Order, Payment, PaymentStatus, OrderStatus, Subscription, Inventory, utc_now
from database.crud import (
    create_manual_payment,
    create_admin_log,
    get_payment_by_id,
    get_order_by_id,
    get_setting,
)
from services.allocation_service import allocation_service
from utils.formatters import format_delivered_proxy_message, format_currency, format_dt
from keyboards.admin_kb import get_payment_approval_keyboard, get_late_payment_approval_keyboard
from utils.validators import validate_utr

logger = logging.getLogger("TatkalProxy.PaymentService")


class LatePaymentExpiredError(ValueError):
    """Raised when customer submits a UTR for an expired order/payment."""
    pass


class PaymentService:
    @staticmethod
    async def submit_manual_utr(
        db: Session,
        order_id: int,
        user_id: int,
        utr: str,
        bot: Optional[Bot] = None,
    ) -> Tuple[Payment, str]:
        """
        Record customer-submitted UTR and notify administrators.
        Customer UTR is treated as unverified until admin checks their bank app.
        Enforces:
        - Order ownership
        - UTR syntax and format
        - Duplicate prevention
        - Unverified pending status
        """
        order = get_order_by_id(db, order_id)
        if not order:
            raise ValueError(f"Order ID {order_id} does not exist.")

        if order.user_id != user_id:
            raise ValueError("Unauthorized: This order belongs to another customer.")

        if order.status == OrderStatus.PAID.value:
            raise ValueError("This order has already been paid and fulfilled.")

        if order.status == OrderStatus.CANCELLED.value:
            raise ValueError("This order has been cancelled and cannot accept payment.")

        is_valid, clean_utr, err_msg = validate_utr(utr)
        if not is_valid:
            raise ValueError(err_msg)

        # Check 5-minute payment expiration
        if order.is_payment_expired or order.status == OrderStatus.EXPIRED.value:
            order.status = OrderStatus.EXPIRED.value
            if not order.expired_at:
                order.expired_at = utc_now()

            # Record payment with status EXPIRED so transaction reference is not silently discarded
            payment = create_manual_payment(
                db=db,
                order_id=order.id,
                user_id=user_id,
                amount=order.amount,
                utr=clean_utr,
            )
            payment.status = PaymentStatus.EXPIRED.value
            payment.admin_notes = "LATE PAYMENT: Submitted after 5-minute expiry"
            payment.expired_at = utc_now()
            db.flush()

            # Alert admin with Recover & Deliver and Reject options
            if bot and settings.ADMIN_IDS:
                admin_msg = (
                    f"⚠️ <b>LATE MANUAL UPI PAYMENT (ORDER EXPIRED)</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"🧾 <b>Order:</b> <code>{order.order_code}</code> (EXPIRED)\n"
                    f"👤 <b>Customer:</b> @{order.user.username or 'N/A'} (ID: <code>{order.user.telegram_id}</code>)\n"
                    f"📦 <b>Plan:</b> {order.plan.name}\n"
                    f"💵 <b>Amount:</b> <b>{format_currency(order.amount)}</b>\n"
                    f"🔢 <b>Submitted UTR:</b> <code>{clean_utr}</code>\n"
                    f"⏰ <b>Expired At:</b> {format_dt(order.payment_expires_at)}\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"⚠️ <i>Customer submitted UTR after 5-minute expiry. Verify in your bank app and decide whether to Recover & Deliver.</i>"
                )
                for admin_tg_id in settings.ADMIN_IDS:
                    try:
                        await bot.send_message(
                            chat_id=admin_tg_id,
                            text=admin_msg,
                            parse_mode="HTML",
                            reply_markup=get_late_payment_approval_keyboard(payment.id),
                        )
                    except Exception as ex:
                        logger.error(f"Failed to notify admin {admin_tg_id} of late payment: {ex}")

            raise LatePaymentExpiredError(
                f"This payment request expired after 5 minutes.\n"
                f"Your UTR ({clean_utr}) has been safely recorded.\n"
                f"Please contact @TatkalProxySupport with your payment proof."
            )

        payment = create_manual_payment(
            db=db,
            order_id=order.id,
            user_id=user_id,
            amount=order.amount,
            utr=clean_utr,
        )

        # Notify admins if bot instance is available
        if bot and settings.ADMIN_IDS:
            admin_msg = (
                f"🔔 <b>NEW MANUAL UPI PAYMENT SUBMITTED</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🧾 <b>Order:</b> <code>{order.order_code}</code>\n"
                f"👤 <b>Customer:</b> @{order.user.username or 'N/A'} (ID: <code>{order.user.telegram_id}</code>)\n"
                f"📦 <b>Plan:</b> {order.plan.name}\n"
                f"💵 <b>Amount:</b> <b>{format_currency(order.amount)}</b>\n"
                f"🔢 <b>Submitted UTR:</b> <code>{payment.utr}</code>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"⚠️ <i>Please independently check your UPI/Bank app before approving!</i>"
            )
            for admin_tg_id in settings.ADMIN_IDS:
                try:
                    await bot.send_message(
                        chat_id=admin_tg_id,
                        text=admin_msg,
                        parse_mode="HTML",
                        reply_markup=get_payment_approval_keyboard(payment.id),
                    )
                except Exception as ex:
                    logger.error(f"Failed to notify admin {admin_tg_id}: {ex}")

        return payment, "UTR submitted successfully. Awaiting admin verification."

    @staticmethod
    async def verify_and_deliver(
        db: Session,
        payment_id: int,
        admin_tg_id: int,
        bot: Bot,
        notes: str | None = None,
    ) -> Tuple[Subscription, Inventory]:
        """
        Admin approves payment.
        Performs atomic allocation, fulfills order, and dispatches proxy to customer.
        """
        payment = get_payment_by_id(db, payment_id)
        if not payment:
            raise ValueError(f"Payment ID {payment_id} not found.")

        if payment.status == PaymentStatus.VERIFIED.value:
            raise ValueError("This payment has already been verified and delivered.")

        if payment.status == PaymentStatus.REJECTED.value:
            raise ValueError("This payment has been rejected and cannot be approved.")

        order = payment.order
        if not order:
            raise ValueError(f"Order associated with payment {payment_id} missing.")

        if order.status == OrderStatus.CANCELLED.value:
            raise ValueError("This order has been cancelled and cannot be fulfilled.")

        if order.status == OrderStatus.PAID.value and order.subscriptions:
            raise ValueError("This order has already been fulfilled and delivered.")

        if order.status == OrderStatus.EXPIRED.value or payment.status == PaymentStatus.EXPIRED.value or order.is_payment_expired:
            raise ValueError("This payment/order has expired. Use 'Recover & Deliver' to fulfill an expired payment.")

        # Allocate proxy and activate subscription
        sub, inv, delivery_line = allocation_service.fulfill_order(
            db=db, order_id=order.id, verified_by_id=None
        )

        payment.status = PaymentStatus.VERIFIED.value
        payment.admin_notes = notes or f"Approved by admin {admin_tg_id}"
        payment.verified_at = utc_now()
        db.flush()

        # Audit log
        create_admin_log(
            db=db,
            admin_id=None,
            action="PAYMENT_APPROVED",
            target_type="payment",
            target_id=str(payment.id),
            details=f"Payment for order {order.order_code} (₹{payment.amount}) verified by {admin_tg_id}. Proxy {inv.ip} delivered.",
        )

        # Dispatch delivery message to customer with all allocated proxies
        customer_msg = format_delivered_proxy_message(sub, inv)
        try:
            await bot.send_message(
                chat_id=order.user.telegram_id,
                text=customer_msg,
                parse_mode="HTML",
            )
            logger.info(f"Delivered proxy {inv.ip} to customer {order.user.telegram_id}")
        except Exception as e:
            logger.error(f"Failed to deliver Telegram message to customer {order.user.telegram_id}: {e}")

        return sub, inv

    @staticmethod
    async def reject_payment(
        db: Session,
        payment_id: int,
        admin_tg_id: int,
        bot: Bot,
        reason: str = "Invalid or unverified UTR/transaction reference.",
    ) -> Payment:
        """Admin rejects a payment."""
        payment = get_payment_by_id(db, payment_id)
        if not payment:
            raise ValueError(f"Payment ID {payment_id} not found.")

        payment.status = PaymentStatus.REJECTED.value
        payment.admin_notes = f"Rejected by admin {admin_tg_id}: {reason}"
        db.flush()

        order = payment.order
        if order:
            order.status = OrderStatus.CANCELLED.value
            db.flush()

        create_admin_log(
            db=db,
            admin_id=None,
            action="PAYMENT_REJECTED",
            target_type="payment",
            target_id=str(payment.id),
            details=f"Payment for order {order.order_code if order else 'N/A'} rejected by {admin_tg_id}. Reason: {reason}",
        )

        # Notify customer
        if order and order.user:
            reject_msg = (
                f"❌ <b>PAYMENT NOT VERIFIED</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🧾 <b>Order:</b> <code>{order.order_code}</code>\n"
                f"Reason: <i>{reason}</i>\n\n"
                f"If you believe this is a mistake, please reach out to Support."
            )
            try:
                await bot.send_message(
                    chat_id=order.user.telegram_id,
                    text=reject_msg,
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(f"Failed to send rejection to user {order.user.telegram_id}: {e}")

        return payment

    @staticmethod
    async def recover_and_deliver(
        db: Session,
        payment_id: int,
        admin_tg_id: int,
        bot: Bot,
        notes: str | None = None,
    ) -> Tuple[Subscription, Inventory]:
        """
        Admin recovers and approves a late (expired) payment.
        Performs atomic allocation, fulfills order, and dispatches proxy to customer.
        """
        payment = get_payment_by_id(db, payment_id)
        if not payment:
            raise ValueError(f"Payment ID {payment_id} not found.")

        if payment.status == PaymentStatus.VERIFIED.value:
            raise ValueError("This payment has already been verified and delivered.")

        order = payment.order
        if not order:
            raise ValueError(f"Order associated with payment {payment_id} missing.")

        if order.status == OrderStatus.PAID.value and order.subscriptions:
            raise ValueError("This order has already been fulfilled and delivered.")

        # Allocate proxy and activate subscription
        sub, inv, delivery_line = allocation_service.fulfill_order(
            db=db, order_id=order.id, verified_by_id=None
        )

        payment.status = PaymentStatus.VERIFIED.value
        payment.admin_notes = notes or f"Recovered and approved late payment by admin {admin_tg_id}"
        payment.verified_at = utc_now()
        db.flush()

        # Audit log
        create_admin_log(
            db=db,
            admin_id=None,
            action="PAYMENT_RECOVERED_AND_APPROVED",
            target_type="payment",
            target_id=str(payment.id),
            details=f"Late payment for expired order {order.order_code} (₹{payment.amount}) recovered and verified by {admin_tg_id}. Proxy {inv.ip} delivered.",
        )

        # Dispatch delivery message to customer
        customer_msg = format_delivered_proxy_message(sub, inv)
        try:
            await bot.send_message(
                chat_id=order.user.telegram_id,
                text=customer_msg,
                parse_mode="HTML",
            )
            logger.info(f"Delivered recovered proxy {inv.ip} to customer {order.user.telegram_id}")
        except Exception as e:
            logger.error(f"Failed to deliver Telegram message to customer {order.user.telegram_id}: {e}")

        return sub, inv


payment_service = PaymentService()
