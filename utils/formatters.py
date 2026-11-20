"""
Tatkal Proxy - Message Formatters & UI Presentation
Maintains consistent brand voice, clean layouts, and standard emoji aesthetics.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import List, Optional, Union
from database.models import Plan, Order, Subscription, Inventory, DailyInventory
from services.inventory_service import format_proxy_delivery

# Indian Standard Time (UTC+05:30)
IST = timezone(timedelta(hours=5, minutes=30), name="IST")

DAILY_PROXY_DISCLAIMER = (
    "⚠️ <b>DAILY PROXY NOTICE</b>\n\n"
    "This is a 1-Day Proxy subscription.\n\n"
    "Your proxy is valid only until 11:59 PM IST on the day of purchase, regardless of the purchase time.\n\n"
    "The subscription will automatically expire at midnight (12:00 AM IST).\n\n"
    "Fresh daily proxy inventory is uploaded every morning.\n\n"
    "Please note that unused subscription time will not carry over to the next day."
)


def format_currency(amount: float) -> str:
    """Format INR currency."""
    return f"₹{amount:,.0f}" if amount.is_integer() else f"₹{amount:,.2f}"


def format_dt(dt: datetime | None) -> str:
    """Format datetime into clean readable string in Indian Standard Time (IST)."""
    if not dt:
        return "N/A"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ist_dt = dt.astimezone(IST)
    return ist_dt.strftime("%d %b %Y, %I:%M %p IST")


def format_time_remaining(end_date: datetime) -> str:
    """Format remaining duration until expiry."""
    now = datetime.now(timezone.utc)
    if end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=timezone.utc)
    diff = end_date - now
    if diff.total_seconds() <= 0:
        return "Expired"
    days = diff.days
    hours = int(diff.seconds // 3600)
    minutes = int((diff.seconds % 3600) // 60)
    if days > 0:
        return f"{days}d {hours}h remaining"
    elif hours > 0:
        return f"{hours}h {minutes}m remaining"
    else:
        return f"{minutes}m remaining"


def format_welcome_message() -> str:
    """Standard welcome storefront greeting."""
    return (
        "🚀 <b>WELCOME TO TATKAL PROXY</b>\n"
        "<i>Premium Proxy Store</i>\n\n"
        "⚡ <b>Fast Delivery</b>\n"
        "🔒 <b>Secure Credentials</b>\n"
        "📅 <b>Flexible Subscription Plans</b>\n"
        "💳 <b>Easy UPI Payments</b>\n\n"
        "Select an option from the menu below to get started:"
    )


def format_plan_card(plan: Plan, in_stock: bool, stock_count: int) -> str:
    """Formatted plan details card with 103.x.x.x indication and disclaimer for Daily Proxy."""
    stock_text = f"🟢 In Stock ({stock_count} available)" if in_stock else "🔴 Out of Stock"
    special_tag = "🌟 <b>Dedicated 103.x.x.x Series IP</b>\n" if plan.is_special else "🌐 <b>Standard Dedicated IP</b>\n"

    card = (
        f"📦 <b>{plan.name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Price:</b> {format_currency(plan.price_inr)} / IP\n"
        f"⏳ <b>Duration:</b> {plan.duration_days} Day{'s' if plan.duration_days > 1 else ''}\n"
        f"{special_tag}"
        f"📊 <b>Stock Status:</b> {stock_text}\n"
        f"📝 <i>{plan.description or 'High-speed dedicated proxy'}</i>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
    )
    if plan.code == "daily_proxy" or plan.duration_days == 1:
        card += f"\n{DAILY_PROXY_DISCLAIMER}\n"
    return card


def format_payment_countdown(expires_at: datetime | None) -> str:
    """Format countdown string (MM:SS) for payment expiry."""
    if not expires_at:
        return "05:00"
    now = datetime.now(timezone.utc)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    remaining_secs = int((expires_at - now).total_seconds())
    if remaining_secs <= 0:
        return "EXPIRED"
    mins = remaining_secs // 60
    secs = remaining_secs % 60
    return f"{mins:02d}:{secs:02d}"


def format_payment_expiry_ist(expires_at: datetime | None) -> str:
    """Format payment expiry time in Indian Standard Time (IST)."""
    if not expires_at:
        return "N/A"
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    ist_dt = expires_at.astimezone(IST)
    return ist_dt.strftime("%I:%M:%S %p IST")


def format_order_summary(order: Order, upi_id: str | None = None) -> str:
    """
    Summary displayed during payment checkout.
    Clean, minimal payment screen layout with 5-minute expiry countdown and Telegram support link.
    Completely removes lengthy 4-step instruction block.
    """
    renewal_str = " (Renewal)" if order.is_renewal else ""
    qty_line = f"Quantity: {order.quantity} IP{'s' if order.quantity > 1 else ''}\n" if order.quantity > 1 else ""

    countdown = format_payment_countdown(order.payment_expires_at)
    ist_time = format_payment_expiry_ist(order.payment_expires_at)

    if countdown == "EXPIRED" or order.is_payment_expired or order.status == "EXPIRED":
        expiry_block = "⏳ <b>Status:</b> <b>EXPIRED</b>\n<i>This payment window has closed. Please start a new purchase.</i>"
    else:
        expiry_block = (
            f"⏳ <b>Payment expires in:</b> <code>{countdown}</code>\n"
            f"Expires at: {ist_time}"
        )

    summary = (
        f"💳 <b>TATKAL PROXY – PAYMENT{renewal_str}</b>\n\n"
        f"Order ID: <code>{order.order_code}</code>\n"
        f"Plan: {order.plan.name}\n"
        f"{qty_line}"
        f"Amount: <b>{format_currency(order.amount)}</b>\n\n"
        f"{expiry_block}\n\n"
        f"💬 <b>Telegram Support:</b> <a href=\"https://t.me/TatkalProxySupport\">@TatkalProxySupport</a>"
    )
    if order.plan.code == "daily_proxy" or order.plan.duration_days == 1:
        summary += f"\n\n{DAILY_PROXY_DISCLAIMER}"
    return summary


def format_delivered_proxy_message(
    subscriptions: Union[Subscription, List[Subscription]],
    inventory_items: Union[Union[Inventory, DailyInventory], List[Union[Inventory, DailyInventory]]],
) -> str:
    """
    Message accompanying delivered proxies.
    Rule: Delivered proxy lines must be exactly ip:port:user:pass, one proxy per line.
    Appends Daily Proxy Disclaimer only for 1-day proxies.
    """
    subs_list = subscriptions if isinstance(subscriptions, list) else [subscriptions]
    invs_list = inventory_items if isinstance(inventory_items, list) else [inventory_items]

    primary_sub = subs_list[0]
    proxy_lines = "\n".join(format_proxy_delivery(item) for item in invs_list)
    qty_header = f" ({len(invs_list)} IPs)" if len(invs_list) > 1 else ""

    msg = (
        f"🎉 <b>PAYMENT VERIFIED — PROXIES DELIVERED{qty_header}</b>\n\n"
        f"Subscription: <code>{primary_sub.sub_code}</code>\n"
        f"Plan: {primary_sub.plan.name}\n"
        f"Expires: <b>{format_dt(primary_sub.end_date)}</b>\n\n"
        f"<b>Your Dedicated Proxy Credentials:</b>\n"
        f"<code>{proxy_lines}</code>\n\n"
        f"⚠️ <i>Please store your credentials safely. You can manage this proxy from 'My Subscriptions'.</i>"
    )
    if primary_sub.plan.code == "daily_proxy" or primary_sub.plan.duration_days == 1:
        msg += f"\n\n{DAILY_PROXY_DISCLAIMER}"
    return msg
