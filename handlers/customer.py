"""
Tatkal Proxy - Customer Telegram Handlers
Implements complete customer shopping experience: browsing, ordering, QR checkout,
UTR submission, subscription management, and proxy renewals.
"""

from __future__ import annotations

import io
import json
import logging
from sqlalchemy.orm import joinedload
from telegram import Update, ForceReply, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database.connection import get_db
from database.crud import (
    get_or_create_user,
    get_active_plans,
    get_plan_by_id,
    create_order,
    get_order_by_id,
    get_user_subscriptions,
    get_subscription_by_id,
    get_setting,
)
from database.models import Order, OrderStatus, SubscriptionStatus, PaymentStatus, utc_now
from services.allocation_service import allocation_service
from services.payment_service import payment_service, LatePaymentExpiredError
from services.inventory_service import format_proxy_delivery
from utils.qr_generator import generate_upi_qr_bytes
from utils.formatters import (
    format_welcome_message,
    format_plan_card,
    format_order_summary,
    format_dt,
    format_time_remaining,
    format_currency,
    DAILY_PROXY_DISCLAIMER,
)
from keyboards.customer_kb import (
    get_customer_reply_keyboard,
    get_customer_main_menu_keyboard,
    get_plans_keyboard,
    get_plan_quantity_keyboard,
    get_plan_confirm_keyboard,
    get_payment_checkout_keyboard,
    get_payment_utr_cancel_keyboard,
    get_payment_expired_keyboard,
    get_subscription_list_keyboard,
    get_subscription_detail_keyboard,
    get_back_to_home_keyboard,
)
from utils.validators import validate_utr

logger = logging.getLogger("TatkalProxy.CustomerHandler")


# ============================================================================
# /start & MAIN MENU
# ============================================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command. Registers user and renders welcome storefront."""
    tg_user = update.effective_user
    if not tg_user:
        return

    with get_db() as db:
        user = get_or_create_user(
            db=db,
            telegram_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
        )
        if user.is_blocked:
            await update.effective_message.reply_text("⛔ Your access to Tatkal Proxy has been suspended.")
            return

    msg = format_welcome_message()
    await update.effective_message.reply_text(
        "⚡ <i>Tatkal Proxy Navigation Menu ready.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_customer_reply_keyboard(),
    )
    await update.effective_message.reply_text(
        text=msg,
        parse_mode=ParseMode.HTML,
        reply_markup=get_customer_main_menu_keyboard(),
    )


async def handle_customer_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to storefront main menu."""
    query = update.callback_query
    await query.answer()
    msg = format_welcome_message()
    await query.edit_message_text(
        text=msg,
        parse_mode=ParseMode.HTML,
        reply_markup=get_customer_main_menu_keyboard(),
    )


# ============================================================================
# BROWSE PLANS & BUY FLOW
# ============================================================================
async def handle_browse_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display subscription plans."""
    query = update.callback_query
    await query.answer()

    with get_db() as db:
        plans = get_active_plans(db)

    if not plans:
        await query.edit_message_text(
            "⚠️ No active plans found. Please check back shortly.",
            reply_markup=get_back_to_home_keyboard(),
        )
        return

    text = (
        "🛍 <b>TATKAL PROXY — SUBSCRIPTION PLANS</b>\n\n"
        "Select a plan below to view details and check instant stock availability:"
    )
    await query.edit_message_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_plans_keyboard(plans),
    )


async def handle_plan_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display selected plan details and quantity selector (1, 3, 5, 10 IPs)."""
    query = update.callback_query
    await query.answer()
    plan_id = int(query.data.split(":")[1])

    with get_db() as db:
        plan = get_plan_by_id(db, plan_id)
        if not plan:
            await query.edit_message_text("Plan not found.", reply_markup=get_back_to_home_keyboard())
            return
        has_stock, stock_count = allocation_service.check_plan_stock(db, plan.id)

    card_text = format_plan_card(plan, has_stock, stock_count)
    if has_stock:
        card_text += "\n🔢 <b>Select IP Quantity to Purchase:</b>"
        markup = get_plan_quantity_keyboard(plan.id, plan.price_inr, stock_count)
    else:
        markup = get_back_to_home_keyboard()

    await query.edit_message_text(
        text=card_text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


async def handle_quantity_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Create order for multiple IPs, generate dynamic UPI QR code, and prompt payment."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    plan_id = int(parts[1])
    quantity = int(parts[2])
    tg_user = update.effective_user

    with get_db() as db:
        user = get_or_create_user(
            db=db,
            telegram_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
        )
        plan = get_plan_by_id(db, plan_id)
        if not plan:
            await query.edit_message_text("Plan not found.", reply_markup=get_back_to_home_keyboard())
            return

        has_stock, stock_count = allocation_service.check_plan_stock(db, plan.id)
        if stock_count < quantity:
            await query.answer(f"Insufficient stock! Only {stock_count} IPs available.", show_alert=True)
            return

        total_amount = plan.price_inr * quantity
        order = create_order(
            db=db,
            user_id=user.id,
            plan_id=plan.id,
            amount=total_amount,
            quantity=quantity,
            is_renewal=False,
        )
        upi_id = get_setting(db, "upi_id", "tatkalproxy@okaxis")
        upi_name = get_setting(db, "upi_name", "Tatkal Proxy Store")

        # Generate QR image bytes with exact order amount
        qr_bytes = generate_upi_qr_bytes(
            upi_id=upi_id,
            payee_name=upi_name,
            amount=order.amount,
            order_code=order.order_code,
        )
        # format_order_summary shows amount and instructions WITHOUT showing the UPI ID string
        caption = format_order_summary(order)

    # Delete original text message and send photo with QR code
    try:
        await query.message.delete()
    except Exception:
        pass

    await context.bot.send_photo(
        chat_id=tg_user.id,
        photo=io.BytesIO(qr_bytes),
        caption=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=get_payment_checkout_keyboard(order.id),
    )


async def handle_qty_out_of_stock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Alert user when requested quantity exceeds stock."""
    query = update.callback_query
    await query.answer("❌ Selected quantity is currently out of stock.", show_alert=True)


async def handle_order_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fallback handler redirecting to quantity selection."""
    query = update.callback_query
    await query.answer()
    plan_id = int(query.data.split(":")[1])

    with get_db() as db:
        plan = get_plan_by_id(db, plan_id)
        if not plan:
            await query.edit_message_text("Plan not found.", reply_markup=get_back_to_home_keyboard())
            return
        has_stock, stock_count = allocation_service.check_plan_stock(db, plan.id)

    card_text = format_plan_card(plan, has_stock, stock_count)
    if has_stock:
        card_text += "\n🔢 <b>Select IP Quantity to Purchase:</b>"
        markup = get_plan_quantity_keyboard(plan.id, plan.price_inr, stock_count)
    else:
        markup = get_back_to_home_keyboard()

    await query.edit_message_text(
        text=card_text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


# ============================================================================
# UTR SUBMISSION & PAYMENT STATUS (POPUP INPUT ENHANCEMENT)
# ============================================================================
async def handle_submit_utr_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Open popup input interface (ForceReply) for customer to enter their 12-digit UTR.
    Displays placeholder, Submit, and Cancel options.
    Enforces security: verifies order exists and belongs to current user.
    """
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split(":")[1])

    with get_db() as db:
        user = get_or_create_user(db=db, telegram_id=update.effective_user.id)
        order = get_order_by_id(db, order_id)
        if not order:
            await query.answer("❌ Order not found.", show_alert=True)
            return
        if order.user_id != user.id:
            await query.answer("❌ Unauthorized: You cannot submit UTR for another user's order.", show_alert=True)
            return
        if order.status == OrderStatus.PAID.value:
            await query.answer("✅ This order has already been paid and fulfilled.", show_alert=True)
            return
        if order.status == OrderStatus.CANCELLED.value:
            await query.answer("❌ This order has been cancelled.", show_alert=True)
            return
        if order.is_payment_expired or order.status == OrderStatus.EXPIRED.value:
            order.status = OrderStatus.EXPIRED.value
            if not order.expired_at:
                order.expired_at = utc_now()
            db.flush()
            await query.answer("⏳ Payment request expired (5-minute limit). Please start a fresh purchase.", show_alert=True)
            try:
                await query.edit_message_caption(
                    caption=format_order_summary(order),
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_payment_expired_keyboard(),
                )
            except Exception:
                try:
                    await query.edit_message_reply_markup(reply_markup=get_payment_expired_keyboard())
                except Exception:
                    pass
            return

    context.user_data["awaiting_utr_for_order"] = order_id

    # Update payment message with Cancel option
    try:
        await query.edit_message_reply_markup(reply_markup=get_payment_utr_cancel_keyboard(order_id))
    except Exception:
        pass

    prompt_text = (
        "📝 <b>Enter Your UTR Number</b>\n\n"
        "Please enter your <b>12-digit UPI transaction reference number</b> in the input popup below.\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "• <b>Placeholder:</b> <i>Enter your 12-digit UPI transaction reference number.</i>\n"
        "• <b>Submit:</b> Type the UTR in the reply box and tap Send.\n"
        "• <b>Cancel:</b> Tap 'Cancel' on the message above or type <code>/cancel</code>."
    )
    prompt_msg = await query.message.reply_text(
        text=prompt_text,
        parse_mode=ParseMode.HTML,
        reply_markup=ForceReply(
            selective=True,
            input_field_placeholder="Enter your 12-digit UPI transaction reference number.",
        ),
    )
    context.user_data["utr_prompt_message_id"] = prompt_msg.message_id


async def handle_cancel_utr_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle customer clicking Cancel during UTR input."""
    query = update.callback_query
    await query.answer("UTR submission cancelled.")
    order_id = int(query.data.split(":")[1])

    context.user_data.pop("awaiting_utr_for_order", None)
    context.user_data.pop("utr_prompt_message_id", None)

    try:
        await query.edit_message_reply_markup(reply_markup=get_payment_checkout_keyboard(order_id))
    except Exception:
        pass

    await query.message.reply_text(
        "❌ <b>UTR Submission Cancelled</b>\n\n"
        "You can click <b>📝 Submit UTR</b> on the payment screen whenever you are ready.",
        parse_mode=ParseMode.HTML,
    )


async def handle_customer_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle UTR submitted through Telegram Mini App / WebApp modal."""
    msg = update.effective_message
    if not msg or not msg.web_app_data:
        return

    try:
        data = json.loads(msg.web_app_data.data)
    except Exception:
        return

    if data.get("type") == "utr_submission":
        order_id = data.get("order_id")
        raw_utr = data.get("utr")
        tg_user = update.effective_user

        is_valid, clean_utr, err_msg = validate_utr(raw_utr)
        if not is_valid:
            await msg.reply_text(
                f"❌ <b>Invalid UTR:</b> {err_msg}",
                parse_mode=ParseMode.HTML,
            )
            return

        with get_db() as db:
            user = get_or_create_user(db=db, telegram_id=tg_user.id)
            try:
                payment, _ = await payment_service.submit_manual_utr(
                    db=db,
                    order_id=order_id,
                    user_id=user.id,
                    utr=clean_utr,
                    bot=context.bot,
                )
                confirmation_text = (
                    "✅ <b>UTR Submitted Successfully!</b>\n\n"
                    "Your transaction reference has been received.\n\n"
                    "Your payment is now pending admin verification.\n\n"
                    "Your proxy will be delivered only after successful payment verification."
                )
                await msg.reply_text(
                    text=confirmation_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_customer_main_menu_keyboard(),
                )
            except LatePaymentExpiredError as le:
                await msg.reply_text(
                    f"⏳ <b>Payment Request Expired:</b>\n\n{str(le)}\n\n"
                    f"💬 <b>Telegram Support:</b> <a href=\"https://t.me/TatkalProxySupport\">@TatkalProxySupport</a>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_payment_expired_keyboard(),
                )
            except Exception as e:
                await msg.reply_text(
                    f"❌ <b>UTR Submission Failed:</b> {str(e)}",
                    parse_mode=ParseMode.HTML,
                )


async def handle_user_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages from customer (e.g. UTR or admin state inputs)."""
    text = update.message.text.strip()
    tg_user = update.effective_user

    # Check if user is awaiting UTR submission
    order_id = context.user_data.get("awaiting_utr_for_order")
    if order_id:
        # Check cancel command / keyword
        if text.lower() in ["/cancel", "cancel", "exit"]:
            context.user_data.pop("awaiting_utr_for_order", None)
            context.user_data.pop("utr_prompt_message_id", None)
            await update.message.reply_text(
                "❌ <b>UTR Submission Cancelled</b>\n\n"
                "You can click <b>📝 Submit UTR</b> on the payment screen whenever you are ready.",
                parse_mode=ParseMode.HTML,
                reply_markup=get_payment_checkout_keyboard(order_id),
            )
            return

        # Validate UTR using validate_utr
        is_valid, clean_utr, err_msg = validate_utr(text)
        if not is_valid:
            # Re-prompt with ForceReply popup so customer can fix it easily
            await update.message.reply_text(
                text=f"❌ <b>Invalid UTR Number</b>\n\n{err_msg}\n\nPlease enter your 12-digit UPI transaction reference number:",
                parse_mode=ParseMode.HTML,
                reply_markup=ForceReply(
                    selective=True,
                    input_field_placeholder="Enter your 12-digit UPI transaction reference number.",
                ),
            )
            return

        with get_db() as db:
            user = get_or_create_user(db=db, telegram_id=tg_user.id)
            try:
                payment, msg = await payment_service.submit_manual_utr(
                    db=db,
                    order_id=order_id,
                    user_id=user.id,
                    utr=clean_utr,
                    bot=context.bot,
                )
                context.user_data.pop("awaiting_utr_for_order", None)
                context.user_data.pop("utr_prompt_message_id", None)

                confirmation_text = (
                    "✅ <b>UTR Submitted Successfully!</b>\n\n"
                    "Your transaction reference has been received.\n\n"
                    "Your payment is now pending admin verification.\n\n"
                    "Your proxy will be delivered only after successful payment verification."
                )
                await update.message.reply_text(
                    text=confirmation_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_customer_main_menu_keyboard(),
                )
            except LatePaymentExpiredError as le:
                context.user_data.pop("awaiting_utr_for_order", None)
                context.user_data.pop("utr_prompt_message_id", None)
                await update.message.reply_text(
                    f"⏳ <b>Payment Request Expired</b>\n\n{str(le)}\n\n"
                    f"💬 <b>Telegram Support:</b> <a href=\"https://t.me/TatkalProxySupport\">@TatkalProxySupport</a>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_payment_expired_keyboard(),
                )
            except ValueError as ve:
                logger.warning(f"Validation error submitting UTR for order {order_id}: {ve}")
                await update.message.reply_text(
                    f"❌ <b>UTR Submission Failed</b>\n\n{str(ve)}\n\nPlease check your reference number and try again:",
                    parse_mode=ParseMode.HTML,
                    reply_markup=ForceReply(
                        selective=True,
                        input_field_placeholder="Enter your 12-digit UPI transaction reference number.",
                    ),
                )
            except Exception as e:
                logger.error(f"Error submitting UTR: {e}")
                await update.message.reply_text(
                    f"❌ Error submitting UTR: {str(e)}",
                    reply_markup=get_payment_checkout_keyboard(order_id),
                )
        return

    # Check if text matches persistent bottom menu button
    handled_menu = await handle_persistent_menu_text(update, context)
    if handled_menu:
        return

    # Check admin state inputs if handled via admin module
    from handlers.admin import handle_admin_text_input
    admin_handled = await handle_admin_text_input(update, context)
    if not admin_handled:
        await update.message.reply_text(
            "Please select an option from the menu below:",
            reply_markup=get_customer_main_menu_keyboard(),
        )


async def handle_check_payment_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check live status of an order."""
    query = update.callback_query
    order_id = int(query.data.split(":")[1])

    with get_db() as db:
        order = get_order_by_id(db, order_id)
        if not order:
            await query.answer("Order not found.", show_alert=True)
            return

        if order.status == OrderStatus.PAID.value and order.subscription:
            await query.answer("Payment verified!", show_alert=True)
            msg = (
                f"✅ <b>Order {order.order_code} is PAID & FULFILLED!</b>\n"
                f"Subscription: <code>{order.subscription.sub_code}</code>\n"
                f"Proxy IP: <code>{order.subscription.proxy_ip}</code>"
            )
            if order.plan.code == "daily_proxy" or order.plan.duration_days == 1:
                msg += f"\n\n{DAILY_PROXY_DISCLAIMER}"
            await query.message.reply_text(msg, parse_mode=ParseMode.HTML)
        elif order.status == OrderStatus.CANCELLED.value:
            await query.answer("Order has been cancelled.", show_alert=True)
        else:
            await query.answer("Payment is pending admin verification.", show_alert=True)


async def handle_order_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel pending checkout order and release state."""
    query = update.callback_query
    order_id = int(query.data.split(":")[1])

    context.user_data.pop("awaiting_utr_for_order", None)
    context.user_data.pop("utr_prompt_message_id", None)

    with get_db() as db:
        order = get_order_by_id(db, order_id)
        if order and order.status in [OrderStatus.PENDING.value, OrderStatus.EXPIRED.value]:
            order.status = OrderStatus.CANCELLED.value
            if order.payment and order.payment.status in [PaymentStatus.PENDING_VERIFICATION.value, "SUBMITTED"]:
                order.payment.status = PaymentStatus.REJECTED.value
                order.payment.admin_notes = "Order cancelled by customer"
            db.flush()

    await query.answer("Payment cancelled.", show_alert=True)
    try:
        await query.edit_message_caption(
            caption=f"❌ <b>PAYMENT CANCELLED</b>\n\nOrder <code>{order.order_code if order else order_id}</code> has been cancelled.\n\nYou can start a fresh purchase at any time.",
            parse_mode=ParseMode.HTML,
            reply_markup=get_payment_expired_keyboard(),
        )
    except Exception:
        try:
            await query.edit_message_text(
                text=f"❌ <b>Payment Cancelled</b>\n\nOrder <code>{order.order_code if order else order_id}</code> has been cancelled.",
                parse_mode=ParseMode.HTML,
                reply_markup=get_payment_expired_keyboard(),
            )
        except Exception:
            await query.message.reply_text(
                "❌ Order cancelled. Returning to main menu.",
                reply_markup=get_customer_main_menu_keyboard(),
            )


# ============================================================================
# MY SUBSCRIPTIONS & RENEWAL
# ============================================================================
async def handle_my_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List customer subscriptions."""
    query = update.callback_query
    await query.answer()
    tg_user = update.effective_user

    with get_db() as db:
        user = get_or_create_user(db=db, telegram_id=tg_user.id)
        subs = get_user_subscriptions(db, user.id)

    if not subs:
        await query.edit_message_text(
            "📦 <b>You do not have any subscriptions yet.</b>\n\nClick below to browse plans!",
            parse_mode=ParseMode.HTML,
            reply_markup=get_customer_main_menu_keyboard(),
        )
        return

    text = "📦 <b>MY SUBSCRIPTIONS</b>\n\nSelect a subscription to view proxy credentials and details:"
    await query.edit_message_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_subscription_list_keyboard(subs),
    )


async def handle_view_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """View credentials and expiration countdown of a specific subscription."""
    query = update.callback_query
    await query.answer()
    sub_id = int(query.data.split(":")[1])

    with get_db() as db:
        sub = get_subscription_by_id(db, sub_id)
        if not sub:
            await query.edit_message_text("Subscription not found.", reply_markup=get_back_to_home_keyboard())
            return

        inv = sub.proxy
        proxy_line = format_proxy_delivery(inv) if inv else "N/A"
        proxy_ip_str = inv.ip if inv else "N/A"
        status_emoji = "🟢" if sub.status == SubscriptionStatus.ACTIVE.value else "🔴"
        remaining = format_time_remaining(sub.end_date)
        is_active = sub.status == SubscriptionStatus.ACTIVE.value
        is_daily = sub.plan.code == "daily_proxy" or sub.plan.duration_days == 1

    detail_msg = (
        f"{status_emoji} <b>SUBSCRIPTION DETAILS</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🧾 <b>Code:</b> <code>{sub.sub_code}</code>\n"
        f"📦 <b>Plan:</b> {sub.plan.name}\n"
        f"📅 <b>Expires:</b> {format_dt(sub.end_date)} ({remaining})\n"
        f"🌐 <b>IP Address:</b> <code>{proxy_ip_str}</code>\n\n"
        f"<b>Your Proxy String:</b>\n"
        f"<code>{proxy_line}</code>\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    if is_daily:
        detail_msg += f"\n\n{DAILY_PROXY_DISCLAIMER}"
    await query.edit_message_text(
        text=detail_msg,
        parse_mode=ParseMode.HTML,
        reply_markup=get_subscription_detail_keyboard(sub.id, is_active),
    )


async def handle_renew_subscription_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Initiate renewal payment for an existing subscription."""
    query = update.callback_query
    await query.answer()
    sub_id = int(query.data.split(":")[1])
    tg_user = update.effective_user

    with get_db() as db:
        sub = get_subscription_by_id(db, sub_id)
        if not sub:
            await query.edit_message_text("Subscription not found.", reply_markup=get_back_to_home_keyboard())
            return

        user = get_or_create_user(db=db, telegram_id=tg_user.id)
        plan = sub.plan

        # Create renewal order attached to subscription
        order = create_order(
            db=db,
            user_id=user.id,
            plan_id=plan.id,
            amount=plan.price_inr,
            is_renewal=True,
            renewal_sub_id=sub.id,
        )
        upi_id = get_setting(db, "upi_id", "tatkalproxy@okaxis")
        upi_name = get_setting(db, "upi_name", "Tatkal Proxy Store")

        qr_bytes = generate_upi_qr_bytes(
            upi_id=upi_id,
            payee_name=upi_name,
            amount=order.amount,
            order_code=order.order_code,
        )
        caption = format_order_summary(order, upi_id)

    try:
        await query.message.delete()
    except Exception:
        pass

    await context.bot.send_photo(
        chat_id=tg_user.id,
        photo=io.BytesIO(qr_bytes),
        caption=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=get_payment_checkout_keyboard(order.id),
    )


# ============================================================================
# PAYMENT HISTORY & SUPPORT
# ============================================================================
async def handle_payment_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """View recent payment transactions."""
    query = update.callback_query
    await query.answer()
    tg_user = update.effective_user

    from sqlalchemy.orm import joinedload
    from database.models import Order

    with get_db() as db:
        user = get_or_create_user(db=db, telegram_id=tg_user.id)
        orders = (
            db.query(Order)
            .options(joinedload(Order.plan))
            .filter(Order.user_id == user.id)
            .order_by(Order.created_at.desc())
            .limit(10)
            .all()
        )

        if not orders:
            await query.edit_message_text(
                "💳 <b>No payment history found.</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=get_back_to_home_keyboard(),
            )
            return

        text = "💳 <b>PAYMENT HISTORY</b>\n━━━━━━━━━━━━━━━━━━\n"
        for ord_item in orders:
            status_tag = "✅ Paid" if ord_item.status == OrderStatus.PAID.value else f"⏳ {ord_item.status}"
            plan_name = ord_item.plan.name if ord_item.plan else "Standard Plan"
            text += (
                f"🧾 <code>{ord_item.order_code}</code>\n"
                f"   Plan: {plan_name} | {format_currency(ord_item.amount)}\n"
                f"   Status: {status_tag} | {format_dt(ord_item.created_at)}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
            )

    await query.edit_message_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_back_to_home_keyboard(),
    )


async def handle_customer_support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display customer support details."""
    query = update.callback_query
    await query.answer()

    with get_db() as db:
        contact = get_setting(db, "support_contact", "@TatkalProxySupport")

    support_msg = (
        "🆘 <b>TATKAL PROXY SUPPORT</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Need help with your proxy subscription or payment verification?\n\n"
        f"💬 <b>Telegram Support:</b> {contact}\n"
        "⏰ <b>Hours:</b> 24/7 Priority Support\n\n"
        "Please provide your <b>Order ID</b> or <b>Subscription Code</b> when messaging support."
    )
    await query.edit_message_text(
        text=support_msg,
        parse_mode=ParseMode.HTML,
        reply_markup=get_back_to_home_keyboard(),
    )


# ============================================================================
# PERSISTENT BOTTOM MENU HANDLER
# ============================================================================
async def handle_persistent_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Handle clicks from persistent bottom reply keyboard.
    Returns True if the message was handled as a persistent menu action, False otherwise.
    """
    if not update.message or not update.message.text:
        return False
    text = update.message.text.strip()
    tg_user = update.effective_user
    if not tg_user:
        return False

    valid_buttons = ["🛒 Buy Proxy", "📦 My Proxies", "💳 Payment / Orders", "👤 My Account", "📞 Support", "🏠 Main Menu"]
    if text not in valid_buttons:
        return False

    # Clear pending single-step prompt states if user tapped navigation
    context.user_data.pop("awaiting_utr_for_order", None)

    if text == "🛒 Buy Proxy":
        with get_db() as db:
            plans = get_active_plans(db)
        if not plans:
            await update.message.reply_text("No active plans available at the moment.")
            return True
        await update.message.reply_text(
            "🛍 <b>TATKAL PROXY — SUBSCRIPTION PLANS</b>\n\n"
            "Select a plan below to view details and check instant stock availability:",
            parse_mode=ParseMode.HTML,
            reply_markup=get_plans_keyboard(plans),
        )
        return True

    elif text == "📦 My Proxies":
        with get_db() as db:
            user = get_or_create_user(db=db, telegram_id=tg_user.id)
            subs = get_user_subscriptions(db, user.id)
        if not subs:
            await update.message.reply_text(
                "📦 <b>MY SUBSCRIPTIONS</b>\n━━━━━━━━━━━━━━━━━━\n<i>You don't have any active proxies yet.</i>\n\nClick '🛒 Buy Proxy' below to purchase one!",
                parse_mode=ParseMode.HTML,
                reply_markup=get_back_to_home_keyboard(),
            )
            return True
        await update.message.reply_text(
            f"📦 <b>MY SUBSCRIPTIONS ({len(subs)} Total)</b>\n━━━━━━━━━━━━━━━━━━\nClick any subscription to view details or renew:",
            parse_mode=ParseMode.HTML,
            reply_markup=get_subscription_list_keyboard(subs),
        )
        return True

    elif text == "💳 Payment / Orders":
        with get_db() as db:
            user = get_or_create_user(db=db, telegram_id=tg_user.id)
            orders = (
                db.query(Order)
                .options(joinedload(Order.plan))
                .filter(Order.user_id == user.id)
                .order_by(Order.id.desc())
                .limit(10)
                .all()
            )
            if not orders:
                await update.message.reply_text(
                    "💳 <b>ORDER & PAYMENT HISTORY</b>\n━━━━━━━━━━━━━━━━━━\n<i>No orders found.</i>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_back_to_home_keyboard(),
                )
                return True
            history_text = "💳 <b>YOUR RECENT ORDERS</b>\n━━━━━━━━━━━━━━━━━━\n"
            for ord_item in orders:
                status_icon = "🟢" if ord_item.status == "PAID" else ("🟡" if ord_item.status == "PENDING" else "🔴")
                plan_name = ord_item.plan.name if ord_item.plan else "Proxy"
                history_text += (
                    f"🧾 <code>{ord_item.order_code}</code> — {format_currency(ord_item.amount)}\n"
                    f"   Plan: {plan_name} (x{ord_item.quantity or 1})\n"
                    f"   Status: {status_icon} <b>{ord_item.status}</b>\n"
                    f"   Date: {format_dt(ord_item.created_at)}\n"
                    f"──────────────────\n"
                )
        await update.message.reply_text(history_text, parse_mode=ParseMode.HTML, reply_markup=get_back_to_home_keyboard())
        return True

    elif text == "👤 My Account":
        with get_db() as db:
            user = get_or_create_user(db=db, telegram_id=tg_user.id)
            subs = get_user_subscriptions(db, user.id)
            active_count = sum(1 for s in subs if s.status == SubscriptionStatus.ACTIVE.value)
            orders_count = db.query(Order).filter(Order.user_id == user.id).count()
        uname = f"@{user.username}" if user.username else "N/A"
        account_msg = (
            "👤 <b>TATKAL PROXY — MY ACCOUNT</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🆔 <b>Telegram ID:</b> <code>{user.telegram_id}</code>\n"
            f"👤 <b>Username:</b> {uname}\n"
            f"📅 <b>Registered:</b> {format_dt(user.created_at)}\n"
            f"📦 <b>Total Orders:</b> {orders_count}\n"
            f"⚡ <b>Active Proxies:</b> <b>{active_count}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "<i>High-speed dedicated private proxies with instant delivery.</i>"
        )
        await update.message.reply_text(account_msg, parse_mode=ParseMode.HTML, reply_markup=get_back_to_home_keyboard())
        return True

    elif text == "📞 Support":
        with get_db() as db:
            contact = get_setting(db, "support_contact", "@TatkalProxySupport")
        support_msg = (
            "🆘 <b>TATKAL PROXY SUPPORT</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Need help with your proxy subscription or payment verification?\n\n"
            f"💬 <b>Telegram Support:</b> {contact}\n"
            "⏰ <b>Hours:</b> 24/7 Priority Support\n\n"
            "Please provide your <b>Order ID</b> or <b>Subscription Code</b> when messaging support."
        )
        await update.message.reply_text(support_msg, parse_mode=ParseMode.HTML, reply_markup=get_back_to_home_keyboard())
        return True

    elif text == "🏠 Main Menu":
        welcome_text = format_welcome_message()
        await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML, reply_markup=get_customer_main_menu_keyboard())
        return True

    return False
