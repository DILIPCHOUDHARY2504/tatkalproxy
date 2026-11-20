"""
Tatkal Proxy - Payment Gateway Integration Architecture
Abstract, provider-independent payment gateway architecture with HMAC signature
verification, amount integrity checks, and duplicate webhook idempotency.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from telegram import Bot

from config import settings
from database.models import Order, Payment, PaymentStatus, PaymentMethod, OrderStatus
from database.crud import get_order_by_code, create_admin_log
from services.allocation_service import allocation_service
from utils.formatters import format_delivered_proxy_message

logger = logging.getLogger("TatkalProxy.GatewayService")


class BasePaymentGatewayProvider(ABC):
    """Abstract base provider for external payment gateways (e.g. Razorpay, Cashfree, Stripe)."""

    @abstractmethod
    def create_order(self, order_code: str, amount_inr: float, customer_email: str | None = None) -> Dict[str, Any]:
        """Create order on the remote payment gateway provider."""
        pass

    @abstractmethod
    def verify_webhook_signature(self, payload_bytes: bytes, signature_header: str) -> bool:
        """Verify cryptographic HMAC signature from payment gateway."""
        pass


class GenericHMACGatewayProvider(BasePaymentGatewayProvider):
    """
    Production-ready HMAC SHA256 gateway implementation.
    Validates webhook signatures using configured secret.
    """

    def __init__(self, secret_key: str | None = None):
        self.secret_key = secret_key or settings.PAYMENT_GATEWAY_WEBHOOK_SECRET

    def create_order(self, order_code: str, amount_inr: float, customer_email: str | None = None) -> Dict[str, Any]:
        # Formats standardized payload according to standard gateway specifications
        return {
            "gateway_order_id": f"gw_ord_{order_code.lower()}",
            "amount": amount_inr,
            "currency": "INR",
            "status": "created",
        }

    def verify_webhook_signature(self, payload_bytes: bytes, signature_header: str) -> bool:
        """Verify HMAC SHA-256 signature against webhook payload."""
        if not signature_header or not self.secret_key:
            return False

        expected_sig = hmac.new(
            key=self.secret_key.encode("utf-8"),
            msg=payload_bytes,
            digestmod=hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected_sig, signature_header)


class GatewayService:
    def __init__(self, provider: Optional[BasePaymentGatewayProvider] = None):
        self.provider = provider or GenericHMACGatewayProvider()

    async def process_verified_webhook(
        self,
        db: Session,
        order_code: str,
        gateway_payment_id: str,
        amount_received: float,
        signature: str,
        bot: Optional[Bot] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Process incoming verified webhook callback idempotently.
        Ensures amount verification, order existence, and single proxy delivery.
        """
        order = get_order_by_code(db, order_code)
        if not order:
            logger.error(f"Webhook received for non-existent order: {order_code}")
            return False, "Order not found", None

        # Idempotency check: If order is already paid, return 200 without duplicate allocation
        if order.status == OrderStatus.PAID.value:
            sub_code = order.subscription.sub_code if order.subscription else "FULFILLED"
            logger.info(f"Idempotent webhook for already fulfilled order {order_code}")
            return True, "Order already fulfilled", {"subscription_code": sub_code}

        # Amount verification check
        if abs(order.amount - amount_received) > 0.01:
            logger.error(
                f"Amount mismatch on order {order_code}: expected ₹{order.amount}, got ₹{amount_received}"
            )
            return False, "Amount mismatch", None

        # Check existing payment or create
        payment = db.query(Payment).filter(Payment.order_id == order.id).first()
        if not payment:
            payment = Payment(
                order_id=order.id,
                user_id=order.user_id,
                payment_method=PaymentMethod.GATEWAY.value,
                amount=amount_received,
                gateway_payment_id=gateway_payment_id,
                gateway_signature=signature,
                status=PaymentStatus.VERIFIED.value,
            )
            db.add(payment)
        else:
            # Check duplicate transaction ID replay
            if payment.gateway_payment_id and payment.gateway_payment_id != gateway_payment_id:
                return False, "Duplicate payment ID conflict", None
            payment.payment_method = PaymentMethod.GATEWAY.value
            payment.gateway_payment_id = gateway_payment_id
            payment.gateway_signature = signature
            payment.status = PaymentStatus.VERIFIED.value

        db.flush()

        # Fulfill order atomically
        sub, inv, delivery_line = allocation_service.fulfill_order(
            db=db, order_id=order.id, verified_by_id=None
        )

        create_admin_log(
            db=db,
            admin_id=None,
            action="GATEWAY_WEBHOOK_FULFILLED",
            target_type="order",
            target_id=str(order.id),
            details=f"Gateway payment {gateway_payment_id} for order {order_code} (₹{amount_received}) verified. Proxy {inv.ip} delivered.",
        )

        # Dispatch proxy to customer if bot is provided
        if bot and order.user:
            cust_msg = format_delivered_proxy_message(sub, inv)
            try:
                await bot.send_message(
                    chat_id=order.user.telegram_id,
                    text=cust_msg,
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error(f"Failed to dispatch proxy via bot: {e}")

        return True, "Success", {
            "order_code": order.order_code,
            "subscription_code": sub.sub_code,
            "proxy_ip": inv.ip,
        }


gateway_service = GatewayService()
