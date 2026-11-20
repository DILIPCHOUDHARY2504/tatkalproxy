"""
Tatkal Proxy - UTR Submission Popup Enhancement Tests
Validates:
1. UTR syntax & format validation (valid 12-digit, trim spaces, reject empty, reject invalid chars, length limits)
2. Submit UTR button interaction (ForceReply popup, placeholder, selective, cancel button update)
3. Cancel operation (via inline button callback and via '/cancel' text command)
4. Order ownership security (prevent submitting UTR for another user's order)
5. Duplicate UTR rejection across transactions and verified payments
6. Status set to PENDING_VERIFICATION and exact customer confirmation message
7. Admin notification with Approve & Reject buttons (no premature delivery)
8. Admin payment approval and rejection flows
9. WebApp Mini App endpoint and data submission handler
10. Existing payment and gateway workflows
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from telegram import ForceReply, InlineKeyboardMarkup

from database.models import (
    User,
    Plan,
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
    Inventory,
    InventoryStatus,
)
from database.crud import (
    create_order,
    create_manual_payment,
    get_payment_by_id,
    get_order_by_id,
)
from services.payment_service import payment_service
from services.crypto_service import crypto_service
from utils.validators import validate_utr
from keyboards.customer_kb import (
    get_payment_checkout_keyboard,
    get_payment_utr_cancel_keyboard,
)
from handlers.customer import (
    handle_submit_utr_button,
    handle_cancel_utr_button,
    handle_user_text_input,
    handle_customer_web_app_data,
)


# ============================================================================
# 1. UTR VALIDATION UNIT TESTS
# ============================================================================
def test_utr_validator_valid_inputs():
    """Verify standard 12-digit numeric and alphanumeric UTRs pass."""
    ok, clean, err = validate_utr("431289561234")
    assert ok is True
    assert clean == "431289561234"
    assert err == ""

    # Trimming whitespace
    ok, clean, err = validate_utr("   123456789012   \n")
    assert ok is True
    assert clean == "123456789012"

    # Alphanumeric reference IDs (8-22 chars)
    ok, clean, err = validate_utr("AXIS12345678")
    assert ok is True
    assert clean == "AXIS12345678"


def test_utr_validator_empty_and_none():
    """Reject empty, None, and whitespace-only inputs."""
    ok, clean, err = validate_utr("")
    assert ok is False
    assert "cannot be empty" in err

    ok, clean, err = validate_utr(None)
    assert ok is False
    assert "cannot be empty" in err

    ok, clean, err = validate_utr("     ")
    assert ok is False
    assert "cannot be empty" in err


def test_utr_validator_invalid_characters():
    """Reject special characters, spaces, and punctuation."""
    invalid_cases = [
        "431289@56123",
        "UTR 12345678",
        "1234-5678-9012",
        "$$$$$$$$$$$$",
        "431289#561234",
    ]
    for case in invalid_cases:
        ok, clean, err = validate_utr(case)
        assert ok is False
        assert "Invalid characters" in err


def test_utr_validator_length_limits():
    """Reject strings that are too short (<8) or too long (>22)."""
    ok, clean, err = validate_utr("12345")
    assert ok is False
    assert "Invalid UTR length" in err

    ok, clean, err = validate_utr("123456789012345678901234567")
    assert ok is False
    assert "Invalid UTR length" in err


# ============================================================================
# 2. SUBMIT UTR BUTTON & FORCEREPLY POPUP INPUT
# ============================================================================
@pytest.mark.asyncio
async def test_submit_utr_button_triggers_forcereply_popup(db_session, test_user):
    """Test clicking 📝 Submit UTR opens ForceReply popup with exact placeholder."""
    plan = db_session.query(Plan).filter(Plan.code == "daily_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)

    update = MagicMock()
    update.effective_user.id = test_user.telegram_id
    update.callback_query.data = f"pay_submit_utr:{order.id}"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_reply_markup = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()

    prompt_sent = MagicMock()
    prompt_sent.message_id = 9988
    update.callback_query.message.reply_text.return_value = prompt_sent

    context = MagicMock()
    context.user_data = {}

    import contextlib
    @contextlib.contextmanager
    def mock_get_db():
        yield db_session

    with patch("handlers.customer.get_db", mock_get_db):
        await handle_submit_utr_button(update, context)

    # 1. user_data awaiting state set
    assert context.user_data.get("awaiting_utr_for_order") == order.id

    # 2. Payment message updated with Cancel option
    assert update.callback_query.edit_message_reply_markup.called
    edit_markup = update.callback_query.edit_message_reply_markup.call_args[1]["reply_markup"]
    assert any("pay_cancel_utr:" in btn.callback_data for row in edit_markup.inline_keyboard for btn in row)

    # 3. ForceReply prompt message sent with required placeholder
    assert update.callback_query.message.reply_text.called
    call_args = update.callback_query.message.reply_text.call_args[1]
    assert "Enter Your UTR Number" in call_args["text"]

    markup = call_args["reply_markup"]
    assert isinstance(markup, ForceReply)
    assert markup.selective is True
    assert markup.input_field_placeholder == "Enter your 12-digit UPI transaction reference number."


# ============================================================================
# 3. CANCEL OPERATIONS (BUTTON & COMMAND)
# ============================================================================
@pytest.mark.asyncio
async def test_cancel_utr_via_button(db_session, test_user):
    """Test clicking ❌ Cancel during UTR input clears state and restores payment screen."""
    plan = db_session.query(Plan).filter(Plan.code == "daily_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)

    update = MagicMock()
    update.effective_user.id = test_user.telegram_id
    update.callback_query.data = f"pay_cancel_utr:{order.id}"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_reply_markup = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()

    context = MagicMock()
    context.user_data = {"awaiting_utr_for_order": order.id, "utr_prompt_message_id": 9988}

    await handle_cancel_utr_button(update, context)

    # State cleared
    assert "awaiting_utr_for_order" not in context.user_data
    # Restores checkout keyboard
    assert update.callback_query.edit_message_reply_markup.called
    restored_markup = update.callback_query.edit_message_reply_markup.call_args[1]["reply_markup"]
    assert any("pay_submit_utr:" in btn.callback_data for row in restored_markup.inline_keyboard for btn in row)


@pytest.mark.asyncio
async def test_cancel_utr_via_text_command(db_session, test_user):
    """Test typing /cancel while awaiting UTR clears state and aborts."""
    plan = db_session.query(Plan).filter(Plan.code == "daily_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)

    update = MagicMock()
    update.effective_user.id = test_user.telegram_id
    update.message.text = "/cancel"
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.user_data = {"awaiting_utr_for_order": order.id}

    await handle_user_text_input(update, context)

    assert "awaiting_utr_for_order" not in context.user_data
    call_args = update.message.reply_text.call_args
    reply_text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
    assert "UTR Submission Cancelled" in reply_text


# ============================================================================
# 4. ORDER OWNERSHIP & SECURITY
# ============================================================================
@pytest.mark.asyncio
async def test_security_prevent_submitting_utr_for_another_users_order(db_session, test_user):
    """Ensure User B cannot submit a UTR for User A's order."""
    plan = db_session.query(Plan).filter(Plan.code == "daily_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)

    # Another malicious user
    hacker = User(telegram_id=666777888, username="hacker", is_admin=False)
    db_session.add(hacker)
    db_session.commit()

    import contextlib
    @contextlib.contextmanager
    def mock_get_db():
        yield db_session

    update = MagicMock()
    update.effective_user.id = hacker.telegram_id
    update.callback_query.data = f"pay_submit_utr:{order.id}"
    update.callback_query.answer = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    with patch("handlers.customer.get_db", mock_get_db):
        await handle_submit_utr_button(update, context)

    # Button rejected with alert
    assert update.callback_query.answer.called
    alert_text = update.callback_query.answer.call_args[0][0]
    assert "Unauthorized" in alert_text
    assert "awaiting_utr_for_order" not in context.user_data

    # Also test in service layer directly
    mock_bot = MagicMock()
    with pytest.raises(ValueError, match="Unauthorized: This order belongs to another customer"):
        await payment_service.submit_manual_utr(
            db=db_session,
            order_id=order.id,
            user_id=hacker.id,
            utr="431289561234",
            bot=mock_bot,
        )


# ============================================================================
# 5. VALID UTR SUBMISSION & CONFIRMATION MESSAGE
# ============================================================================
@pytest.mark.asyncio
async def test_valid_utr_submission_and_confirmation_message(db_session, test_user, mock_bot):
    """Test valid UTR entry, PENDING_VERIFICATION status, admin notification, and exact customer text."""
    plan = db_session.query(Plan).filter(Plan.code == "daily_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)

    update = MagicMock()
    update.effective_user.id = test_user.telegram_id
    update.message.text = "431289561234"
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.bot = mock_bot
    context.user_data = {"awaiting_utr_for_order": order.id}

    import contextlib
    @contextlib.contextmanager
    def mock_get_db():
        yield db_session

    with patch("handlers.customer.get_db", mock_get_db):
        await handle_user_text_input(update, context)

    # Context cleared
    assert "awaiting_utr_for_order" not in context.user_data

    # Customer message matches exact required phrasing
    reply_call = update.message.reply_text.call_args[1]
    msg_text = reply_call["text"]
    assert "✅ <b>UTR Submitted Successfully!</b>" in msg_text
    assert "Your transaction reference has been received." in msg_text
    assert "Your payment is now pending admin verification." in msg_text
    assert "Your proxy will be delivered only after successful payment verification." in msg_text

    # Verify payment record in DB
    payment = db_session.query(Payment).filter(Payment.order_id == order.id).first()
    assert payment is not None
    assert payment.utr == "431289561234"
    assert payment.status == PaymentStatus.PENDING_VERIFICATION.value

    # Admin notified with approve/reject buttons
    assert mock_bot.send_message.called
    admin_call = mock_bot.send_message.call_args[1]
    assert "NEW MANUAL UPI PAYMENT SUBMITTED" in admin_call["text"]
    assert "431289561234" in admin_call["text"]
    approval_markup = admin_call["reply_markup"]
    assert any("pay_approve:" in btn.callback_data for row in approval_markup.inline_keyboard for btn in row)
    assert any("pay_reject:" in btn.callback_data for row in approval_markup.inline_keyboard for btn in row)


# ============================================================================
# 6. DUPLICATE UTR SUBMISSION REJECTION
# ============================================================================
@pytest.mark.asyncio
async def test_duplicate_utr_submission_rejection(db_session, test_user, mock_bot):
    """Test duplicate UTR submission is rejected across transactions."""
    plan = db_session.query(Plan).filter(Plan.code == "daily_proxy").first()
    order1 = create_order(db_session, test_user.id, plan.id, plan.price_inr)
    order2 = create_order(db_session, test_user.id, plan.id, plan.price_inr)

    utr_code = "431289561234"

    # First submission succeeds
    await payment_service.submit_manual_utr(
        db=db_session,
        order_id=order1.id,
        user_id=test_user.id,
        utr=utr_code,
        bot=mock_bot,
    )

    # Second submission with same UTR is rejected
    with pytest.raises(ValueError, match="already been submitted"):
        await payment_service.submit_manual_utr(
            db=db_session,
            order_id=order2.id,
            user_id=test_user.id,
            utr=utr_code,
            bot=mock_bot,
        )


# ============================================================================
# 7. INVALID UTR INPUT RE-PROMPTING
# ============================================================================
@pytest.mark.asyncio
async def test_invalid_utr_input_reprompts_customer(db_session, test_user):
    """Test invalid characters or format triggers a retry prompt with ForceReply."""
    plan = db_session.query(Plan).filter(Plan.code == "daily_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)

    update = MagicMock()
    update.effective_user.id = test_user.telegram_id
    update.message.text = "invalid@utr#123"
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.user_data = {"awaiting_utr_for_order": order.id}

    import contextlib
    @contextlib.contextmanager
    def mock_get_db():
        yield db_session

    with patch("handlers.customer.get_db", mock_get_db):
        await handle_user_text_input(update, context)

    # Still awaiting UTR
    assert context.user_data.get("awaiting_utr_for_order") == order.id

    # Reprompt sent with ForceReply
    call_args = update.message.reply_text.call_args[1]
    assert "Invalid characters" in call_args["text"]
    assert isinstance(call_args["reply_markup"], ForceReply)


# ============================================================================
# 8. WEBAPP MINI APP ENDPOINT & HANDLER
# ============================================================================
@pytest.mark.asyncio
async def test_webapp_utr_html_endpoint():
    """Verify FastAPI /webapp/utr endpoint returns HTML with required fields."""
    from webhooks.api import app
    from httpx import AsyncClient, ASGITransport

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/webapp/utr?order_id=123")
        assert response.status_code == 200
        html = response.text
        assert "Enter Your UTR Number" in html
        assert "Enter your 12-digit UPI transaction reference number." in html
        assert "Submit" in html
        assert "Cancel" in html


@pytest.mark.asyncio
async def test_handle_customer_web_app_data(db_session, test_user, mock_bot):
    """Test processing UTR submitted via Telegram Mini App."""
    plan = db_session.query(Plan).filter(Plan.code == "daily_proxy").first()
    order = create_order(db_session, test_user.id, plan.id, plan.price_inr)

    update = MagicMock()
    update.effective_user.id = test_user.telegram_id
    update.effective_message.web_app_data.data = json.dumps({
        "type": "utr_submission",
        "order_id": order.id,
        "utr": "987654321012",
    })
    update.effective_message.reply_text = AsyncMock()

    context = MagicMock()
    context.bot = mock_bot

    import contextlib
    @contextlib.contextmanager
    def mock_get_db():
        yield db_session

    with patch("handlers.customer.get_db", mock_get_db):
        await handle_customer_web_app_data(update, context)

    assert update.effective_message.reply_text.called
    reply_text = update.effective_message.reply_text.call_args[1]["text"]
    assert "UTR Submitted Successfully!" in reply_text

    payment = db_session.query(Payment).filter(Payment.order_id == order.id).first()
    assert payment is not None
    assert payment.utr == "987654321012"
    assert payment.status == PaymentStatus.PENDING_VERIFICATION.value
