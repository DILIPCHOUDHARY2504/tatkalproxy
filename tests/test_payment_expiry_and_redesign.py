"""
Tests for UPI Payment Screen Redesign, 5-Minute Expiry Countdown,
Late Payment Recording, Admin Late Recovery, and Customer Cancellation.
"""

import io
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from database.crud import (
    create_manual_payment,
    create_order,
    get_order_by_id,
    get_payment_by_id,
)
from database.models import (
    Inventory,
    InventoryStatus,
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
    Plan,
    utc_now,
)
from handlers.customer import (
    handle_order_cancel,
    handle_submit_utr_button,
    handle_user_text_input,
)
from keyboards.admin_kb import (
    get_late_payment_approval_keyboard,
    get_payment_approval_keyboard,
)
from keyboards.customer_kb import (
    get_payment_checkout_keyboard,
    get_payment_expired_keyboard,
)
from services.crypto_service import crypto_service
from services.payment_service import LatePaymentExpiredError, payment_service
from services.scheduler_service import ExpirySchedulerService
from utils.formatters import (
    IST,
    format_currency,
    format_order_summary,
    format_payment_countdown,
    format_payment_expiry_ist,
)
from utils.qr_generator import generate_upi_qr_bytes


def test_payment_screen_clean_layout_and_no_old_instructions(db_session, test_user):
    """
    Ensure format_order_summary produces clean minimal layout with:
    - Order ID, Plan, Amount
    - 5-minute expiry countdown
    - IST expiration time
    - Clickable Telegram Support link: @TatkalProxySupport
    - Absolutely NO old 4-step instructions
    """
    plan = db_session.query(Plan).filter(Plan.code == "monthly_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)

    summary = format_order_summary(order)

    # 1. Header & Required Details
    assert "💳 <b>TATKAL PROXY – PAYMENT</b>" in summary
    assert f"<code>{order.order_code}</code>" in summary
    assert plan.name in summary
    assert format_currency(order.amount) in summary

    # 2. Expiry Countdown & IST timestamp
    assert "⏳ <b>Payment expires in:</b>" in summary
    assert "Expires at:" in summary
    assert "IST" in summary

    # 3. Clickable Telegram Support
    assert "💬 <b>Telegram Support:</b>" in summary
    assert '<a href="https://t.me/TatkalProxySupport">@TatkalProxySupport</a>' in summary

    # 4. Strictly Verify Old Instructions are REMOVED
    assert "Scan the QR code above with any UPI app" not in summary
    assert "Pay the exact amount" not in summary
    assert "Copy the 12-digit" not in summary
    assert "Click 'Submit UTR'" not in summary


def test_dynamic_upi_qr_generator_preserved():
    """Verify that existing dynamic UPI QR generator functions intact."""
    qr_bytes = generate_upi_qr_bytes(
        upi_id="tatkalproxy@okaxis",
        payee_name="Tatkal Proxy Store",
        amount=399.0,
        order_code="ORD-TEST-12345",
    )
    assert isinstance(qr_bytes, bytes)
    assert len(qr_bytes) > 100
    # Valid PNG signature
    assert qr_bytes.startswith(b"\x89PNG")


def test_payment_checkout_and_expired_keyboards():
    """Verify payment screen buttons and expired keyboard structure."""
    order_id = 999
    kb = get_payment_checkout_keyboard(order_id)
    buttons = [btn for row in kb.inline_keyboard for btn in row]

    # Exactly: Submit UTR and Cancel Payment
    button_texts = [b.text for b in buttons]
    assert "📝 Submit UTR" in button_texts
    assert "❌ Cancel Payment" in button_texts

    cb_datas = [b.callback_data for b in buttons]
    assert f"pay_submit_utr:{order_id}" in cb_datas
    assert f"order_cancel:{order_id}" in cb_datas

    # Expired keyboard buttons
    exp_kb = get_payment_expired_keyboard()
    exp_buttons = [btn for row in exp_kb.inline_keyboard for btn in row]
    exp_texts = [b.text for b in exp_buttons]
    assert "🛒 Buy Proxy (Fresh Request)" in exp_texts
    assert "🔙 Main Menu" in exp_texts


def test_5_minute_payment_expiry_calculation(db_session, test_user):
    """Verify 5-minute expiry calculation and is_payment_expired property."""
    plan = db_session.query(Plan).filter(Plan.code == "daily_proxy").first()
    before = utc_now()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)
    after = utc_now()

    assert order.payment_created_at is not None
    assert order.payment_expires_at is not None

    # Expiry strictly ~5 minutes after creation
    diff = (order.payment_expires_at - order.payment_created_at).total_seconds()
    assert abs(diff - 300) < 2

    # Not expired initially
    assert order.is_payment_expired is False

    # Simulate expired order
    order.payment_expires_at = utc_now() - timedelta(seconds=10)
    db_session.flush()
    assert order.is_payment_expired is True


@pytest.mark.asyncio
async def test_utr_submission_rejected_when_payment_expired(db_session, test_user, mock_bot):
    """
    When customer submits UTR after 5-minute expiry:
    1. Raise LatePaymentExpiredError
    2. Payment record saved with status EXPIRED and note (never silently discarded)
    3. Admin notified with late payment approval keyboard (Recover & Deliver / Reject)
    """
    plan = db_session.query(Plan).filter(Plan.code == "special_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)

    # Fast forward past 5-minute expiry
    order.payment_expires_at = utc_now() - timedelta(minutes=1)
    db_session.commit()

    late_utr = "998877665544"
    with pytest.raises(LatePaymentExpiredError, match="expired after 5 minutes"):
        await payment_service.submit_manual_utr(
            db=db_session,
            order_id=order.id,
            user_id=test_user.id,
            utr=late_utr,
            bot=mock_bot,
        )

    # Verify payment record is saved as EXPIRED, not lost
    payment = db_session.query(Payment).filter(Payment.order_id == order.id).first()
    assert payment is not None
    assert payment.status == PaymentStatus.EXPIRED.value
    assert payment.utr == late_utr
    assert "LATE PAYMENT" in payment.admin_notes

    # Verify admin was notified with get_late_payment_approval_keyboard
    assert mock_bot.send_message.called
    call_kwargs = mock_bot.send_message.call_args[1]
    assert "LATE MANUAL UPI PAYMENT" in call_kwargs["text"]
    assert isinstance(call_kwargs["reply_markup"], type(get_late_payment_approval_keyboard(payment.id)))


@pytest.mark.asyncio
async def test_standard_approval_blocked_for_expired_payment(db_session, test_user, test_admin, mock_bot):
    """verify_and_deliver blocks approval for expired payment, directing admin to Recover & Deliver."""
    plan = db_session.query(Plan).filter(Plan.code == "monthly_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)
    order.payment_expires_at = utc_now() - timedelta(minutes=2)
    order.status = OrderStatus.EXPIRED.value

    payment = create_manual_payment(db_session, order.id, test_user.id, order.amount, "123456789012")
    payment.status = PaymentStatus.EXPIRED.value
    db_session.commit()

    with pytest.raises(ValueError, match="Use 'Recover & Deliver'"):
        await payment_service.verify_and_deliver(
            db=db_session,
            payment_id=payment.id,
            admin_tg_id=test_admin.telegram_id,
            bot=mock_bot,
        )


@pytest.mark.asyncio
async def test_admin_recover_and_deliver_late_payment(db_session, test_user, test_admin, mock_bot):
    """Admin uses recover_and_deliver to successfully fulfill a late-paid expired order."""
    proxy = Inventory(
        ip="103.99.88.77",
        host="103.99.88.77",
        port=8080,
        username_enc=crypto_service.encrypt("recuser"),
        password_enc=crypto_service.encrypt("recpass"),
        is_special=True,
        status=InventoryStatus.AVAILABLE.value,
    )
    db_session.add(proxy)
    db_session.commit()

    plan = db_session.query(Plan).filter(Plan.code == "special_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)
    order.payment_expires_at = utc_now() - timedelta(minutes=5)
    order.status = OrderStatus.EXPIRED.value

    payment = create_manual_payment(db_session, order.id, test_user.id, order.amount, "776655443322")
    payment.status = PaymentStatus.EXPIRED.value
    db_session.commit()

    sub, inv = await payment_service.recover_and_deliver(
        db=db_session,
        payment_id=payment.id,
        admin_tg_id=test_admin.telegram_id,
        bot=mock_bot,
    )

    assert payment.status == PaymentStatus.VERIFIED.value
    assert order.status == OrderStatus.PAID.value
    assert inv.status == InventoryStatus.ALLOCATED.value
    assert mock_bot.send_message.called


@pytest.mark.asyncio
async def test_customer_cancel_payment_handler(db_session, test_user):
    """Customer clicking '❌ Cancel Payment' marks order CANCELLED and edits message."""
    import contextlib
    @contextlib.contextmanager
    def mock_get_db():
        yield db_session

    plan = db_session.query(Plan).filter(Plan.code == "daily_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)
    db_session.commit()

    query = MagicMock()
    query.data = f"order_cancel:{order.id}"
    query.answer = AsyncMock()
    query.edit_message_caption = AsyncMock()
    query.message = MagicMock()

    update = MagicMock()
    update.callback_query = query
    context = MagicMock()
    context.user_data = {"awaiting_utr_for_order": order.id}

    with patch("handlers.customer.get_db", mock_get_db):
        await handle_order_cancel(update, context)

    # Verify context cleared
    assert "awaiting_utr_for_order" not in context.user_data

    # Verify order cancelled in DB
    refreshed_order = get_order_by_id(db_session, order.id)
    assert refreshed_order.status == OrderStatus.CANCELLED.value

    # Verify UI updated with cancellation notice
    query.edit_message_caption.assert_called_once()
    caption_arg = query.edit_message_caption.call_args[1]["caption"]
    assert "PAYMENT CANCELLED" in caption_arg


@pytest.mark.asyncio
async def test_scheduler_expires_stale_orders(db_session, test_user):
    """Background scheduler sweeps and marks orders older than 5 minutes as EXPIRED."""
    import contextlib
    @contextlib.contextmanager
    def mock_get_db():
        yield db_session

    plan = db_session.query(Plan).filter(Plan.code == "monthly_proxy").first()

    # Stale order
    stale_order = create_order(db_session, test_user.id, plan.id, plan.price_inr)
    stale_order.payment_expires_at = utc_now() - timedelta(minutes=2)

    # Active fresh order
    fresh_order = create_order(db_session, test_user.id, plan.id, plan.price_inr)
    fresh_order.payment_expires_at = utc_now() + timedelta(minutes=4)
    db_session.commit()

    with patch("services.scheduler_service.get_db", mock_get_db):
        count = await ExpirySchedulerService.expire_stale_orders()
    assert count >= 1

    db_session.refresh(stale_order)
    db_session.refresh(fresh_order)

    assert stale_order.status == OrderStatus.EXPIRED.value
    assert stale_order.expired_at is not None
    assert fresh_order.status == OrderStatus.PENDING.value


@pytest.mark.asyncio
async def test_submit_utr_button_alert_when_order_expired(db_session, test_user):
    """Clicking Submit UTR on an already expired order alerts user and edits caption."""
    import contextlib
    @contextlib.contextmanager
    def mock_get_db():
        yield db_session

    plan = db_session.query(Plan).filter(Plan.code == "daily_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)
    order.payment_expires_at = utc_now() - timedelta(minutes=1)
    db_session.commit()

    query = MagicMock()
    query.data = f"pay_submit_utr:{order.id}"
    query.answer = AsyncMock()
    query.edit_message_caption = AsyncMock()
    query.message = MagicMock()

    update = MagicMock()
    update.callback_query = query
    update.effective_user.id = test_user.telegram_id
    context = MagicMock()
    context.user_data = {}

    with patch("handlers.customer.get_db", mock_get_db):
        await handle_submit_utr_button(update, context)

    # Verify alert was shown to customer
    query.answer.assert_called_with("⏳ Payment request expired (5-minute limit). Please start a fresh purchase.", show_alert=True)
    # Verify caption was updated to expired layout
    query.edit_message_caption.assert_called_once()
    assert "EXPIRED" in query.edit_message_caption.call_args[1]["caption"]
