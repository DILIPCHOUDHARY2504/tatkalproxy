"""
Tatkal Proxy - Marketing & Broadcast Feature Tests
Validates:
1. Admin Authorization & Marketing Menu structure (ONLY 3 options)
2. Announcement compose, preview, recipient count, and broadcast execution
3. Promotion compose with live database pricing, '🛒 Buy Now' button, and delivery
4. Image / Banner upload, caption, button, preview, and broadcast
5. Delivery tracking, message_id storage, and duplicate prevention
6. Rate limiting (RetryAfter) and blocked user handling
7. Campaign internal cancellation
8. Banner management, view history, and message deletion with Telegram 48-hour restriction handling
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from telegram.error import RetryAfter, Forbidden, BadRequest

from database.models import (
    User,
    Plan,
    Campaign,
    CampaignDelivery,
    CampaignStatus,
    CampaignType,
)
from database.crud import (
    create_campaign,
    get_campaign_by_id,
    get_campaigns_by_type,
    get_broadcast_target_users,
    record_campaign_delivery,
)
from services.broadcast_service import broadcast_service
from keyboards.admin_kb import (
    get_admin_main_menu_keyboard,
    get_admin_marketing_menu_keyboard,
    get_campaign_confirm_keyboard,
    get_banner_workflow_keyboard,
    get_banner_button_option_keyboard,
    get_banner_action_keyboard,
    get_banner_deletion_confirm_keyboard,
)
from handlers.admin import (
    verify_admin,
    handle_admin_marketing_menu,
    handle_mkt_announcement_prompt,
    handle_mkt_promotion_prompt,
    handle_mkt_banner_menu,
    handle_mkt_banner_upload_prompt,
    handle_admin_photo_upload,
    handle_mkt_btn_add,
    handle_mkt_btn_skip,
    handle_mkt_confirm_send,
    handle_mkt_banner_history,
    handle_mkt_view_banner,
    handle_mkt_delete_prompt,
    handle_mkt_delete_confirm,
    handle_admin_text_input,
)


# ============================================================================
# 1. ADMIN AUTHORIZATION & MENU STRUCTURE
# ============================================================================
def test_marketing_menu_exact_three_options():
    """Verify Marketing & Broadcast menu displays ONLY the 3 requested options plus back."""
    kb = get_admin_marketing_menu_keyboard()
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]

    # Must contain ONLY these 3 action options
    assert "mkt_announcement" in callbacks
    assert "mkt_promotion" in callbacks
    assert "mkt_banner" in callbacks
    assert "admin_home" in callbacks

    # MUST NOT contain separate broadcast, broadcast history, stats, or cancel buttons
    forbidden = ["broadcast_now", "broadcast_history", "broadcast_stats", "cancel_broadcast"]
    for fb in forbidden:
        assert fb not in callbacks

    # Only 4 buttons total (3 options + 1 back to admin)
    all_buttons = [btn for row in kb.inline_keyboard for btn in row]
    assert len(all_buttons) == 4


def test_admin_main_menu_has_marketing_entry():
    """Verify admin main dashboard has the Marketing & Broadcast button."""
    kb = get_admin_main_menu_keyboard()
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "admin_marketing_menu" in callbacks


@pytest.mark.asyncio
async def test_admin_marketing_authorization_gate():
    """Ensure non-admin users cannot open marketing menu or execute marketing actions."""
    unauthorized_update = MagicMock()
    unauthorized_update.effective_user.id = 999999999  # Non-admin
    unauthorized_update.callback_query.answer = AsyncMock()
    unauthorized_update.callback_query.edit_message_text = AsyncMock()
    context = MagicMock()

    await handle_admin_marketing_menu(unauthorized_update, context)
    assert not unauthorized_update.callback_query.edit_message_text.called

    await handle_mkt_announcement_prompt(unauthorized_update, context)
    assert not unauthorized_update.callback_query.answer.called


# ============================================================================
# 2. 📢 SEND ANNOUNCEMENT WORKFLOW
# ============================================================================
@pytest.mark.asyncio
async def test_announcement_compose_preview_and_broadcast(db_session, test_user):
    """Test announcement text composition, recipient counting, preview, and broadcast delivery."""
    # Seed a second test user
    user2 = User(telegram_id=987654322, username="user2", is_admin=False, is_blocked=False)
    db_session.add(user2)
    db_session.commit()

    admin_update = MagicMock()
    admin_update.effective_user.id = 111222333  # Authorized admin
    admin_update.message.text = "🚀 <b>Important System Upgrade</b>\nOur network has been expanded with ultra-low latency routes! Check it out."
    admin_update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {"admin_state": "AWAITING_ANNOUNCEMENT_TEXT"}

    # Patch get_db
    import contextlib
    @contextlib.contextmanager
    def mock_get_db():
        yield db_session

    with patch("handlers.admin.get_db", mock_get_db), patch("services.broadcast_service.get_db", mock_get_db):
        handled = await handle_admin_text_input(admin_update, context)
        assert handled is True
        assert admin_update.message.reply_text.called

        # Verify preview text & campaign created
        call_args = admin_update.message.reply_text.call_args[1]
        assert "ANNOUNCEMENT PREVIEW" in call_args["text"]
        assert "Important System Upgrade" in call_args["text"]
        assert "Target Recipients:" in call_args["text"]

        campaign = db_session.query(Campaign).filter(Campaign.campaign_type == CampaignType.ANNOUNCEMENT.value).first()
        assert campaign is not None
        assert campaign.status == CampaignStatus.DRAFT.value

        # Mock Bot for delivery
        mock_bot = MagicMock()
        mock_sent_msg = MagicMock()
        mock_sent_msg.message_id = 55001
        mock_bot.send_message = AsyncMock(return_value=mock_sent_msg)

        success, failed = await broadcast_service.execute_campaign(mock_bot, campaign.id)
        assert success == 3
        assert failed == 0

        db_session.refresh(campaign)
        assert campaign.status == CampaignStatus.COMPLETED.value
        assert campaign.success_count == 3

        # Verify CampaignDelivery records
        deliveries = db_session.query(CampaignDelivery).filter(CampaignDelivery.campaign_id == campaign.id).all()
        assert len(deliveries) == 3  # test_user, user2, admin
        assert deliveries[0].message_id == 55001
        assert deliveries[0].status == "DELIVERED"


# ============================================================================
# 3. 🎯 SEND PROMOTION WORKFLOW
# ============================================================================
@pytest.mark.asyncio
async def test_promotion_with_db_prices_and_buy_button(db_session, test_user):
    """Test promotional message with database pricing and interactive '🛒 Buy Now' button."""
    admin_update = MagicMock()
    admin_update.effective_user.id = 111222333
    admin_update.callback_query.answer = AsyncMock()
    admin_update.callback_query.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    import contextlib
    @contextlib.contextmanager
    def mock_get_db():
        yield db_session

    with patch("handlers.admin.get_db", mock_get_db):
        await handle_mkt_promotion_prompt(admin_update, context)
        assert context.user_data.get("admin_state") == "AWAITING_PROMOTION_TEXT"
        reply_call = admin_update.callback_query.message.reply_text.call_args[1]
        # Must show actual DB prices (₹20, ₹399, ₹499)
        assert "₹20" in reply_call["text"]
        assert "₹399" in reply_call["text"]
        assert "₹499" in reply_call["text"]

    # Now admin sends promotion text
    text_update = MagicMock()
    text_update.effective_user.id = 111222333
    text_update.message.text = "🔥 <b>Weekend Special 20% OFF!</b> Use code TATKAL20 at checkout."
    text_update.message.reply_text = AsyncMock()

    with patch("handlers.admin.get_db", mock_get_db), patch("services.broadcast_service.get_db", mock_get_db):
        handled = await handle_admin_text_input(text_update, context)
        assert handled is True
        preview_text = text_update.message.reply_text.call_args[1]["text"]
        assert "PROMOTION PREVIEW" in preview_text
        assert "[🛒 Buy Now]" in preview_text

        campaign = db_session.query(Campaign).filter(Campaign.campaign_type == CampaignType.PROMOTION.value).first()
        assert campaign is not None
        assert campaign.has_button is True
        assert campaign.button_text == "🛒 Buy Now"

        mock_bot = MagicMock()
        mock_msg = MagicMock()
        mock_msg.message_id = 77001
        mock_bot.send_message = AsyncMock(return_value=mock_msg)

        success, failed = await broadcast_service.execute_campaign(mock_bot, campaign.id)
        assert success == 2
        assert failed == 0
        # Verify reply markup with Buy Now button was passed to bot
        send_kwargs = mock_bot.send_message.call_args[1]
        assert send_kwargs["reply_markup"] is not None
        btn = send_kwargs["reply_markup"].inline_keyboard[0][0]
        assert btn.text == "🛒 Buy Now"
        assert btn.callback_data == "cust_buy"


# ============================================================================
# 4. 🖼 SEND IMAGE / BANNER WORKFLOW
# ============================================================================
@pytest.mark.asyncio
async def test_banner_upload_preview_and_broadcast(db_session, test_user):
    """Test image/banner upload, caption support, button options, and broadcasting."""
    import contextlib
    @contextlib.contextmanager
    def mock_get_db():
        yield db_session

    # Step 1: Admin sends photo
    photo_update = MagicMock()
    photo_update.effective_user.id = 111222333
    photo_obj = MagicMock()
    photo_obj.file_id = "AgACAgIAAxkBAAI_BANNER_TEST_FILE_ID_12345"
    photo_update.message.photo = [photo_obj]
    photo_update.message.caption = "🎉 Exclusive Diwali Offer - Dedicated High Speed IPs!"
    photo_update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {"admin_state": "AWAITING_BANNER_PHOTO"}

    with patch("handlers.admin.get_db", mock_get_db):
        await handle_admin_photo_upload(photo_update, context)
        assert photo_update.message.reply_text.called
        camp_id = context.user_data.get("pending_banner_campaign_id")
        assert camp_id is not None

        campaign = db_session.query(Campaign).filter(Campaign.id == camp_id).first()
        assert campaign.campaign_type == CampaignType.BANNER.value
        assert campaign.media_file_id == "AgACAgIAAxkBAAI_BANNER_TEST_FILE_ID_12345"
        assert "Exclusive Diwali Offer" in campaign.caption

    # Step 2: Admin attaches 'Buy Now' button
    btn_query_update = MagicMock()
    btn_query_update.effective_user.id = 111222333
    btn_query_update.callback_query.data = f"mkt_btn_add:{camp_id}"
    btn_query_update.callback_query.answer = AsyncMock()
    btn_query_update.effective_message.reply_text = AsyncMock()
    context.bot.send_photo = AsyncMock()

    with patch("handlers.admin.get_db", mock_get_db), patch("services.broadcast_service.get_db", mock_get_db):
        await handle_mkt_btn_add(btn_query_update, context)
        assert context.bot.send_photo.called
        assert btn_query_update.effective_message.reply_text.called

        db_session.refresh(campaign)
        assert campaign.has_button is True

        # Step 3: Broadcast banner
        mock_bot = MagicMock()
        mock_photo_msg = MagicMock()
        mock_photo_msg.message_id = 88001
        mock_bot.send_photo = AsyncMock(return_value=mock_photo_msg)

        success, failed = await broadcast_service.execute_campaign(mock_bot, campaign.id)
        assert success == 2
        assert failed == 0

        # Verify photo broadcast parameters
        photo_kwargs = mock_bot.send_photo.call_args[1]
        assert photo_kwargs["photo"] == "AgACAgIAAxkBAAI_BANNER_TEST_FILE_ID_12345"
        assert photo_kwargs["caption"] == "🎉 Exclusive Diwali Offer - Dedicated High Speed IPs!"


# ============================================================================
# 5. DUPLICATE PREVENTION & RATE LIMITING & BLOCKED ACCOUNTS
# ============================================================================
@pytest.mark.asyncio
async def test_duplicate_delivery_prevention(db_session, test_user):
    """Ensure broadcast engine never sends duplicate messages to users who already received a campaign."""
    camp = create_campaign(db_session, admin_id=1, campaign_type=CampaignType.ANNOUNCEMENT.value, content_text="Test")
    # Mark user as already delivered
    record_campaign_delivery(db_session, camp.id, test_user.id, test_user.telegram_id, message_id=101, status="DELIVERED")
    db_session.commit()

    import contextlib
    @contextlib.contextmanager
    def mock_get_db():
        yield db_session

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    with patch("services.broadcast_service.get_db", mock_get_db):
        success, failed = await broadcast_service.execute_campaign(mock_bot, camp.id)
        # Should skip because user already received message
        assert not mock_bot.send_message.called
        assert success == 0


@pytest.mark.asyncio
async def test_rate_limiting_retry_after_and_blocked_user(db_session, test_user):
    """Test that RetryAfter exception is caught and slept, and Forbidden marks account as blocked."""
    camp = create_campaign(db_session, admin_id=1, campaign_type=CampaignType.ANNOUNCEMENT.value, content_text="Rate limit test")
    db_session.commit()

    import contextlib
    @contextlib.contextmanager
    def mock_get_db():
        yield db_session

    mock_bot = MagicMock()
    # First user triggers RetryAfter then succeeds
    mock_msg = MagicMock()
    mock_msg.message_id = 9911
    mock_bot.send_message = AsyncMock(side_effect=[RetryAfter(0.1), mock_msg])

    with patch("services.broadcast_service.get_db", mock_get_db), patch("asyncio.sleep", AsyncMock()):
        success, failed = await broadcast_service.execute_campaign(mock_bot, camp.id)
        assert success == 1

    # Second user is blocked
    camp2 = create_campaign(db_session, admin_id=1, campaign_type=CampaignType.ANNOUNCEMENT.value, content_text="Blocked test")
    db_session.commit()
    mock_bot.send_message = AsyncMock(side_effect=Forbidden("Forbidden: bot was blocked by the user"))

    with patch("services.broadcast_service.get_db", mock_get_db), patch("asyncio.sleep", AsyncMock()):
        success2, failed2 = await broadcast_service.execute_campaign(mock_bot, camp2.id)
        assert failed2 == 1
        db_session.refresh(test_user)
        assert test_user.is_blocked is True


# ============================================================================
# 6. INTERNAL CAMPAIGN CANCELLATION
# ============================================================================
@pytest.mark.asyncio
async def test_campaign_internal_cancellation(db_session, test_user):
    """Test that an ongoing campaign can be cancelled internally."""
    camp = create_campaign(db_session, admin_id=1, campaign_type=CampaignType.ANNOUNCEMENT.value, content_text="Cancel me")
    db_session.commit()

    import contextlib
    @contextlib.contextmanager
    def mock_get_db():
        yield db_session

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    with patch("services.broadcast_service.get_db", mock_get_db):
        # Pre-set cancellation flag
        broadcast_service.cancel_campaign(camp.id)
        await broadcast_service.execute_campaign(mock_bot, camp.id)
        # Should not send any message because it was cancelled
        assert not mock_bot.send_message.called
        db_session.refresh(camp)
        assert camp.status == CampaignStatus.CANCELLED.value


# ============================================================================
# 7. IMAGE / BANNER MESSAGE DELETION WITH TELEGRAM API RESTRICTIONS
# ============================================================================
@pytest.mark.asyncio
async def test_banner_message_deletion_and_48h_restriction(db_session, test_user):
    """
    Test attempting message deletion from users' private chats.
    Verifies accurate tracking of successful deletions and truthful reporting of
    Telegram's 48-hour restriction without false claims.
    """
    camp = create_campaign(db_session, admin_id=1, campaign_type=CampaignType.BANNER.value, media_file_id="PHOTO_123")
    db_session.commit()

    # User 1: Recent message (<48h) -> should succeed
    deliv_recent = record_campaign_delivery(db_session, camp.id, test_user.id, test_user.telegram_id, message_id=1001, status="DELIVERED")

    # User 2: Old message (>48h) -> Telegram will reject with BadRequest
    user_old = User(telegram_id=987654333, username="old_user", is_blocked=False)
    db_session.add(user_old)
    db_session.commit()

    deliv_old = record_campaign_delivery(db_session, camp.id, user_old.id, user_old.telegram_id, message_id=1002, status="DELIVERED")
    deliv_old.delivered_at = datetime.now(timezone.utc) - timedelta(hours=50)
    db_session.commit()

    import contextlib
    @contextlib.contextmanager
    def mock_get_db():
        yield db_session

    # Mock delete_message: succeeds for 1001, raises BadRequest for 1002 (older than 48 hours)
    async def mock_delete_msg(chat_id, message_id):
        if message_id == 1001:
            return True
        elif message_id == 1002:
            raise BadRequest("Message can't be deleted for everyone")

    mock_bot = MagicMock()
    mock_bot.delete_message = AsyncMock(side_effect=mock_delete_msg)

    with patch("services.broadcast_service.get_db", mock_get_db), patch("asyncio.sleep", AsyncMock()):
        result = await broadcast_service.delete_campaign_messages(mock_bot, camp.id)

        assert result["total_attempted"] == 2
        assert result["successful"] == 1
        assert result["failed"] == 1

        # Check failure explanation discloses Telegram restriction truthfully
        assert any("Telegram restriction: Messages older than 48 hours" in reason for reason in result["reasons"])

        db_session.refresh(deliv_recent)
        db_session.refresh(deliv_old)

        # Recent is recorded as deleted
        assert deliv_recent.deleted_from_chat is True
        assert deliv_recent.deletion_attempted is True
        assert deliv_recent.deletion_error is None

        # Old is recorded as failed with exact reason
        assert deliv_old.deleted_from_chat is False
        assert deliv_old.deletion_attempted is True
        assert "48 hours" in deliv_old.deletion_error
