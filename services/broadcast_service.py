"""
Tatkal Proxy - Internal Asynchronous Broadcast Engine
Handles controlled batching, rate limiting, retry after, delivery tracking,
duplicate prevention, cancellation, and message deletion with Telegram restriction handling.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional, Set
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.error import RetryAfter, Forbidden, BadRequest, TelegramError

from database.connection import get_db
from database.models import Campaign, CampaignDelivery, CampaignStatus, CampaignType, User, utc_now
from database.crud import (
    get_campaign_by_id,
    get_broadcast_target_users,
    record_campaign_delivery,
    record_campaign_deletion,
)

logger = logging.getLogger("TatkalProxy.BroadcastService")


class BroadcastService:
    def __init__(self):
        self._active_campaign_cancellations: Set[int] = set()

    def cancel_campaign(self, campaign_id: int) -> None:
        """Signal an ongoing campaign to halt sending."""
        self._active_campaign_cancellations.add(campaign_id)
        with get_db() as db:
            camp = get_campaign_by_id(db, campaign_id)
            if camp:
                camp.is_cancelled = True
                camp.status = CampaignStatus.CANCELLED.value
                db.flush()
        logger.info(f"Campaign {campaign_id} marked for cancellation.")

    async def execute_campaign(
        self,
        bot: Bot,
        campaign_id: int,
        admin_chat_id: Optional[int] = None,
        status_message_id: Optional[int] = None,
    ) -> Tuple[int, int]:
        """
        Execute broadcast to all registered users in controlled batches with rate limiting,
        duplicate prevention, and audit tracking.
        Returns: (success_count, failed_count)
        """
        with get_db() as db:
            campaign = get_campaign_by_id(db, campaign_id)
            if not campaign:
                logger.error(f"Campaign {campaign_id} not found.")
                return 0, 0

            campaign.status = CampaignStatus.SENDING.value
            db.flush()

            # Retrieve eligible users
            target_users = get_broadcast_target_users(db)
            total_target = len(target_users)
            campaign.total_recipients = total_target
            db.flush()

            # Preload already delivered user_ids to prevent duplicates
            delivered_user_ids = {
                d.user_id
                for d in db.query(CampaignDelivery.user_id)
                .filter(CampaignDelivery.campaign_id == campaign_id, CampaignDelivery.status == "DELIVERED")
                .all()
            }

            # Prepare inline keyboard if required
            markup: Optional[InlineKeyboardMarkup] = None
            if campaign.has_button and campaign.button_text:
                cb_or_url = campaign.button_url_or_cb or "cust_buy"
                if cb_or_url.startswith("http://") or cb_or_url.startswith("https://"):
                    btn = InlineKeyboardButton(campaign.button_text, url=cb_or_url)
                else:
                    btn = InlineKeyboardButton(campaign.button_text, callback_data=cb_or_url)
                markup = InlineKeyboardMarkup([[btn]])

            campaign_type = campaign.campaign_type
            content_text = campaign.content_text
            media_file_id = campaign.media_file_id
            caption = campaign.caption

        success_count = 0
        failed_count = 0

        for idx, user in enumerate(target_users, start=1):
            # Check cancellation signal
            if campaign_id in self._active_campaign_cancellations:
                logger.info(f"Campaign {campaign_id} cancelled during run at recipient {idx}/{total_target}.")
                with get_db() as db:
                    camp = get_campaign_by_id(db, campaign_id)
                    if camp:
                        camp.status = CampaignStatus.CANCELLED.value
                        camp.completed_at = utc_now()
                self._active_campaign_cancellations.discard(campaign_id)
                break

            # Prevent duplicate deliveries
            if user.id in delivered_user_ids:
                continue

            sent_msg = None
            error_msg: Optional[str] = None

            for attempt in range(2):
                try:
                    if campaign_type == CampaignType.ANNOUNCEMENT.value:
                        sent_msg = await bot.send_message(
                            chat_id=user.telegram_id,
                            text=content_text or "",
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=False,
                            reply_markup=markup,
                        )
                    elif campaign_type == CampaignType.PROMOTION.value:
                        sent_msg = await bot.send_message(
                            chat_id=user.telegram_id,
                            text=content_text or "",
                            parse_mode=ParseMode.HTML,
                            reply_markup=markup,
                        )
                    elif campaign_type == CampaignType.BANNER.value:
                        sent_msg = await bot.send_photo(
                            chat_id=user.telegram_id,
                            photo=media_file_id,
                            caption=caption,
                            parse_mode=ParseMode.HTML,
                            reply_markup=markup,
                        )
                    break
                except RetryAfter as e:
                    logger.warning(f"Rate limited by Telegram. Sleeping {e.retry_after}s.")
                    await asyncio.sleep(e.retry_after + 0.5)
                except Forbidden:
                    # User blocked the bot or chat deactivated
                    error_msg = "User blocked bot or account deactivated"
                    with get_db() as db:
                        u = db.query(User).filter(User.id == user.id).first()
                        if u:
                            u.is_blocked = True
                    break
                except BadRequest as e:
                    error_msg = f"BadRequest: {e}"
                    break
                except Exception as ex:
                    error_msg = str(ex)[:200]
                    break

            # Record delivery audit
            with get_db() as db:
                if sent_msg:
                    record_campaign_delivery(
                        db=db,
                        campaign_id=campaign_id,
                        user_id=user.id,
                        telegram_id=user.telegram_id,
                        message_id=sent_msg.message_id,
                        status="DELIVERED",
                    )
                    success_count += 1
                    delivered_user_ids.add(user.id)
                else:
                    record_campaign_delivery(
                        db=db,
                        campaign_id=campaign_id,
                        user_id=user.id,
                        telegram_id=user.telegram_id,
                        message_id=None,
                        status="FAILED",
                        error_message=error_msg,
                    )
                    failed_count += 1

            # Controlled batching rate limiting (~25 messages/sec)
            await asyncio.sleep(0.04)

            # Update progress to admin periodically
            if admin_chat_id and status_message_id and idx % 20 == 0:
                try:
                    await bot.edit_message_text(
                        chat_id=admin_chat_id,
                        message_id=status_message_id,
                        text=(
                            f"⏳ <b>Broadcasting in progress...</b>\n"
                            f"Progress: <b>{idx}/{total_target}</b> users\n"
                            f"🟢 Sent: <b>{success_count}</b> | 🔴 Failed: <b>{failed_count}</b>"
                        ),
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass

        # Finalize campaign status
        with get_db() as db:
            camp = get_campaign_by_id(db, campaign_id)
            if camp:
                if camp.status != CampaignStatus.CANCELLED.value:
                    camp.status = CampaignStatus.COMPLETED.value
                camp.success_count = success_count
                camp.failed_count = failed_count
                camp.completed_at = utc_now()
                db.flush()

        # Update final message
        if admin_chat_id and status_message_id:
            try:
                final_text = (
                    f"🎉 <b>BROADCAST COMPLETED</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 <b>Total Target:</b> {total_target}\n"
                    f"🟢 <b>Successfully Delivered:</b> <b>{success_count}</b>\n"
                    f"🔴 <b>Failed / Blocked:</b> {failed_count}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"<i>All delivery and message IDs have been archived for audit and deletion management.</i>"
                )
                await bot.edit_message_text(
                    chat_id=admin_chat_id,
                    message_id=status_message_id,
                    text=final_text,
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

        logger.info(f"Campaign {campaign_id} finished: {success_count} delivered, {failed_count} failed.")
        return success_count, failed_count

    async def delete_campaign_messages(
        self,
        bot: Bot,
        campaign_id: int,
        admin_chat_id: Optional[int] = None,
        status_message_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Attempt to delete previously delivered campaign messages from users' private chats.
        Handles Telegram API 48-hour restriction truthfully without false success reporting.
        """
        with get_db() as db:
            deliveries = (
                db.query(CampaignDelivery)
                .filter(
                    CampaignDelivery.campaign_id == campaign_id,
                    CampaignDelivery.status == "DELIVERED",
                    CampaignDelivery.message_id.isnot(None),
                    CampaignDelivery.deleted_from_chat == False,
                )
                .all()
            )
            total_eligible = len(deliveries)
            # Create working copy of items
            items_to_delete = [(d.id, d.telegram_id, d.message_id, d.delivered_at) for d in deliveries]

        if not items_to_delete:
            return {
                "total_attempted": 0,
                "successful": 0,
                "failed": 0,
                "reasons": {"Already deleted or no valid message IDs": 0},
            }

        successful = 0
        failed = 0
        reasons_count: Dict[str, int] = {}
        now = datetime.now(timezone.utc)

        for idx, (del_id, tg_id, msg_id, delivered_at) in enumerate(items_to_delete, start=1):
            if delivered_at and delivered_at.tzinfo is None:
                delivered_at = delivered_at.replace(tzinfo=timezone.utc)

            # Check Telegram 48-hour boundary
            is_older_than_48h = (now - delivered_at).total_seconds() > 48 * 3600 if delivered_at else False

            success = False
            err_reason = None

            try:
                await bot.delete_message(chat_id=tg_id, message_id=msg_id)
                success = True
                successful += 1
            except BadRequest as e:
                err_str = str(e)
                failed += 1
                if is_older_than_48h or "can't be deleted" in err_str.lower():
                    err_reason = "Telegram restriction: Messages older than 48 hours cannot be deleted by bots"
                elif "message to delete not found" in err_str.lower():
                    err_reason = "Message already deleted by user"
                else:
                    err_reason = f"Telegram error: {err_str}"
                reasons_count[err_reason] = reasons_count.get(err_reason, 0) + 1
            except Exception as ex:
                failed += 1
                err_reason = f"Network or user error: {str(ex)[:100]}"
                reasons_count[err_reason] = reasons_count.get(err_reason, 0) + 1

            # Record in database
            with get_db() as db:
                record_campaign_deletion(
                    db=db,
                    delivery_id=del_id,
                    success=success,
                    error_message=err_reason,
                )

            await asyncio.sleep(0.04)

            # Update progress periodically
            if admin_chat_id and status_message_id and idx % 15 == 0:
                try:
                    await bot.edit_message_text(
                        chat_id=admin_chat_id,
                        message_id=status_message_id,
                        text=(
                            f"⏳ <b>Deleting messages from user chats...</b>\n"
                            f"Progress: <b>{idx}/{total_eligible}</b>\n"
                            f"🟢 Deleted: <b>{successful}</b> | 🔴 Failed: <b>{failed}</b>"
                        ),
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass

        return {
            "total_attempted": total_eligible,
            "successful": successful,
            "failed": failed,
            "reasons": reasons_count,
        }


broadcast_service = BroadcastService()
