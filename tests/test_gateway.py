"""
Tests for automatic payment gateway HMAC signature verification, amount integrity,
and duplicate webhook idempotency.
"""

import hmac
import hashlib
import pytest
from database.models import Inventory, InventoryStatus, Plan, OrderStatus
from database.crud import create_order
from services.gateway_service import gateway_service
from services.crypto_service import crypto_service
from config import settings


@pytest.mark.asyncio
async def test_gateway_webhook_hmac_and_idempotency(db_session, test_user):
    # Setup inventory
    proxy = Inventory(
        ip="103.88.99.11",
        host="103.88.99.11",
        port=8080,
        username_enc=crypto_service.encrypt("gwuser"),
        password_enc=crypto_service.encrypt("gwpass"),
        is_special=True,
        status=InventoryStatus.AVAILABLE.value,
    )
    db_session.add(proxy)
    db_session.commit()

    plan = db_session.query(Plan).filter(Plan.code == "special_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)

    # Compute valid HMAC signature
    payload_body = f'{{"order_code": "{order.order_code}", "payment_id": "pay_test_123", "amount": {order.amount}}}'.encode("utf-8")
    valid_sig = hmac.new(
        key=settings.PAYMENT_GATEWAY_WEBHOOK_SECRET.encode("utf-8"),
        msg=payload_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    assert gateway_service.provider.verify_webhook_signature(payload_body, valid_sig) is True
    assert gateway_service.provider.verify_webhook_signature(payload_body, "wrong_signature") is False

    # Process webhook
    success, msg, data = await gateway_service.process_verified_webhook(
        db=db_session,
        order_code=order.order_code,
        gateway_payment_id="pay_test_123",
        amount_received=order.amount,
        signature=valid_sig,
        bot=None,
    )
    assert success is True
    assert data["proxy_ip"] == "103.88.99.11"
    assert order.status == OrderStatus.PAID.value

    # IDEMPOTENCY TEST: Send the exact same webhook again
    success2, msg2, data2 = await gateway_service.process_verified_webhook(
        db=db_session,
        order_code=order.order_code,
        gateway_payment_id="pay_test_123",
        amount_received=order.amount,
        signature=valid_sig,
        bot=None,
    )
    assert success2 is True
    assert "already fulfilled" in msg2

    # AMOUNT MISMATCH TEST: Order for 499, received 100
    order_mismatch = create_order(db_session, test_user.id, plan.id, plan.price_inr)
    success3, msg3, _ = await gateway_service.process_verified_webhook(
        db=db_session,
        order_code=order_mismatch.order_code,
        gateway_payment_id="pay_test_mismatch",
        amount_received=100.0,
        signature=valid_sig,
        bot=None,
    )
    assert success3 is False
    assert "Amount mismatch" in msg3
