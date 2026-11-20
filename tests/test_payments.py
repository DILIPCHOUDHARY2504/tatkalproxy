"""
Tests for manual UPI payments, UTR deduplication, approval, rejection, and proxy delivery.
"""

import pytest
from database.models import Inventory, InventoryStatus, Plan, PaymentStatus, OrderStatus
from database.crud import create_order, create_manual_payment
from services.payment_service import payment_service
from services.crypto_service import crypto_service


@pytest.mark.asyncio
async def test_manual_upi_payment_flow(db_session, test_user, test_admin, mock_bot):
    # Setup inventory
    proxy = Inventory(
        ip="103.5.5.5",
        host="103.5.5.5",
        port=8080,
        username_enc=crypto_service.encrypt("upiuser"),
        password_enc=crypto_service.encrypt("upipass"),
        is_special=True,
        status=InventoryStatus.AVAILABLE.value,
    )
    db_session.add(proxy)
    db_session.commit()

    plan = db_session.query(Plan).filter(Plan.code == "special_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)

    # Customer submits UTR
    utr_code = "431289123456"
    payment, msg = await payment_service.submit_manual_utr(
        db=db_session,
        order_id=order.id,
        user_id=test_user.id,
        utr=utr_code,
        bot=mock_bot,
    )
    assert payment.status == PaymentStatus.SUBMITTED.value
    assert payment.utr == utr_code

    # Verify duplicate UTR submission prevention
    order2 = create_order(db_session, test_user.id, plan.id, plan.price_inr)
    with pytest.raises(ValueError, match="already been submitted"):
        await payment_service.submit_manual_utr(
            db=db_session,
            order_id=order2.id,
            user_id=test_user.id,
            utr=utr_code,  # Same UTR
            bot=mock_bot,
        )

    # Admin verifies and approves payment
    sub, delivered_inv = await payment_service.verify_and_deliver(
        db=db_session,
        payment_id=payment.id,
        admin_tg_id=test_admin.telegram_id,
        bot=mock_bot,
    )

    assert payment.status == PaymentStatus.VERIFIED.value
    assert order.status == OrderStatus.PAID.value
    assert delivered_inv.status == InventoryStatus.ALLOCATED.value
    assert mock_bot.send_message.called


@pytest.mark.asyncio
async def test_manual_payment_rejection(db_session, test_user, test_admin, mock_bot):
    plan = db_session.query(Plan).filter(Plan.code == "daily_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)

    payment = create_manual_payment(db_session, order.id, test_user.id, order.amount, "FAKEUTR123")

    rejected_payment = await payment_service.reject_payment(
        db=db_session,
        payment_id=payment.id,
        admin_tg_id=test_admin.telegram_id,
        bot=mock_bot,
        reason="UTR not in bank statement",
    )

    assert rejected_payment.status == PaymentStatus.REJECTED.value
    assert order.status == OrderStatus.CANCELLED.value
