"""
Tatkal Proxy - Customer Telegram Keyboards
Modern, clean, intuitive Telegram inline keyboards.
"""

from __future__ import annotations

from typing import List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from database.models import Plan, Subscription


def get_customer_reply_keyboard() -> ReplyKeyboardMarkup:
    """Persistent bottom navigation reply keyboard."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("🛒 Buy Proxy"), KeyboardButton("📦 My Proxies")],
            [KeyboardButton("💳 Payment / Orders"), KeyboardButton("👤 My Account")],
            [KeyboardButton("📞 Support"), KeyboardButton("🏠 Main Menu")],
        ],
        resize_keyboard=True,
        is_persistent=True,
        one_time_keyboard=False,
    )


def get_customer_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Storefront main menu inline buttons."""
    keyboard = [
        [
            InlineKeyboardButton("🛍 Buy Proxies", callback_data="cust_buy"),
            InlineKeyboardButton("📦 My Subscriptions", callback_data="cust_subs"),
        ],
        [
            InlineKeyboardButton("🔄 Renew Proxy", callback_data="cust_renew"),
            InlineKeyboardButton("💳 Payment History", callback_data="cust_history"),
        ],
        [
            InlineKeyboardButton("🆘 Support", callback_data="cust_support"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_plans_keyboard(plans: List[Plan]) -> InlineKeyboardMarkup:
    """List available plans for customer selection, highlighting 103.x.x.x."""
    keyboard = []
    for plan in plans:
        if plan.is_special:
            btn_text = f"🌟 {plan.name} (103.x.x.x) — ₹{plan.price_inr:.0f}"
        else:
            btn_text = f"📦 {plan.name} — ₹{plan.price_inr:.0f}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"plan_select:{plan.id}")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Main Menu", callback_data="cust_home")])
    return InlineKeyboardMarkup(keyboard)


def get_plan_quantity_keyboard(
    plan_id: int, plan_price: float, available_stock: int
) -> InlineKeyboardMarkup:
    """Quantity selection buttons (1, 3, 5, 10 IPs)."""
    quantities = [1, 3, 5, 10]
    keyboard = []
    row = []

    for qty in quantities:
        total = plan_price * qty
        if available_stock >= qty:
            btn_text = f"{qty} IP{'s' if qty > 1 else ''} (₹{total:,.0f})"
            callback = f"order_qty:{plan_id}:{qty}"
        else:
            btn_text = f"{qty} IPs (Out of Stock)"
            callback = f"qty_out_of_stock:{plan_id}:{qty}"

        row.append(InlineKeyboardButton(btn_text, callback_data=callback))
        if len(row) == 2:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("🔙 Back to Plans", callback_data="cust_buy")])
    return InlineKeyboardMarkup(keyboard)


def get_plan_confirm_keyboard(plan_id: int, in_stock: bool) -> InlineKeyboardMarkup:
    """Confirmation buttons for plan purchase."""
    keyboard = []
    if in_stock:
        keyboard.append([InlineKeyboardButton("✅ Select Quantity & Pay", callback_data=f"plan_select:{plan_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Plans", callback_data="cust_buy")])
    return InlineKeyboardMarkup(keyboard)


def get_payment_checkout_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """Payment screen action buttons: Submit UTR and Cancel Payment."""
    keyboard = [
        [InlineKeyboardButton("📝 Submit UTR", callback_data=f"pay_submit_utr:{order_id}")],
        [InlineKeyboardButton("❌ Cancel Payment", callback_data=f"order_cancel:{order_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_payment_expired_keyboard() -> InlineKeyboardMarkup:
    """Keyboard shown when a payment has expired or been cancelled."""
    keyboard = [
        [InlineKeyboardButton("🛒 Buy Proxy (Fresh Request)", callback_data="cust_buy")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="cust_home")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_payment_utr_cancel_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """Keyboard shown when customer is prompted for UTR popup input."""
    keyboard = [
        [InlineKeyboardButton("❌ Cancel", callback_data=f"pay_cancel_utr:{order_id}")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="cust_home")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_subscription_list_keyboard(subscriptions: List[Subscription]) -> InlineKeyboardMarkup:
    """Keyboard listing customer's active subscriptions."""
    keyboard = []
    for sub in subscriptions:
        status_emoji = "🟢" if sub.status == "ACTIVE" else "🔴"
        btn_text = f"{status_emoji} {sub.sub_code} ({sub.plan.name}) - {sub.proxy_ip}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"sub_view:{sub.id}")])
    keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="cust_home")])
    return InlineKeyboardMarkup(keyboard)


def get_subscription_detail_keyboard(sub_id: int, is_active: bool) -> InlineKeyboardMarkup:
    """Detail actions on a specific subscription."""
    keyboard = []
    if is_active:
        keyboard.append([InlineKeyboardButton("🔄 Renew This Proxy", callback_data=f"sub_renew:{sub_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Subscriptions", callback_data="cust_subs")])
    return InlineKeyboardMarkup(keyboard)


def get_back_to_home_keyboard() -> InlineKeyboardMarkup:
    """Simple back to home button."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Main Menu", callback_data="cust_home")]])
