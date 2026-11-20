"""
Tatkal Proxy - Admin Telegram Keyboards
Comprehensive administrative control panel inline keyboards.
"""

from __future__ import annotations

from typing import List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database.models import Inventory, Payment, Plan


def get_admin_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Admin dashboard central menu."""
    keyboard = [
        [
            InlineKeyboardButton("📊 Dashboard", callback_data="admin_dashboard"),
            InlineKeyboardButton("📦 Inventory", callback_data="admin_inventory_menu"),
        ],
        [
            InlineKeyboardButton("👥 Customers", callback_data="admin_customers_menu"),
            InlineKeyboardButton("💰 Orders & Payments", callback_data="admin_payments_menu"),
        ],
        [
            InlineKeyboardButton("🔐 Credential Manager", callback_data="admin_cred_menu"),
            InlineKeyboardButton("⏰ Expired Proxies", callback_data="admin_expired_menu"),
        ],
        [
            InlineKeyboardButton("📈 Sales Reports", callback_data="admin_sales_report"),
            InlineKeyboardButton("📢 Marketing & Broadcast", callback_data="admin_marketing_menu"),
        ],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings_menu"),
            InlineKeyboardButton("🚪 Exit Admin Panel", callback_data="cust_home"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_inventory_menu_keyboard() -> InlineKeyboardMarkup:
    """Inventory dashboard control buttons."""
    keyboard = [
        [
            InlineKeyboardButton("📤 Upload Standard Inventory", callback_data="admin_upload_regular_menu"),
            InlineKeyboardButton("📅 Upload Daily Proxies", callback_data="admin_upload_daily_menu"),
        ],
        [
            InlineKeyboardButton("🔍 Search Proxy by IP", callback_data="admin_search_ip"),
            InlineKeyboardButton("📊 Refresh Inventory", callback_data="admin_inventory_menu"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Admin Dashboard", callback_data="admin_home"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_upload_regular_keyboard() -> InlineKeyboardMarkup:
    """Submenu for uploading standard / monthly / special proxies."""
    keyboard = [
        [
            InlineKeyboardButton("📄 Upload Regular TXT", callback_data="admin_upload_txt"),
            InlineKeyboardButton("📊 Upload Regular CSV", callback_data="admin_upload_csv"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Inventory", callback_data="admin_inventory_menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_admin_upload_daily_keyboard() -> InlineKeyboardMarkup:
    """Submenu for uploading daily proxies."""
    keyboard = [
        [
            InlineKeyboardButton("📄 Upload Daily TXT", callback_data="admin_upload_daily_txt"),
            InlineKeyboardButton("📊 Upload Daily CSV", callback_data="admin_upload_daily_csv"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Inventory", callback_data="admin_inventory_menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_payment_approval_keyboard(payment_id: int) -> InlineKeyboardMarkup:
    """Inline verification buttons for manual UPI payment."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Approve & Deliver", callback_data=f"pay_approve:{payment_id}"),
            InlineKeyboardButton("❌ Reject Payment", callback_data=f"pay_reject:{payment_id}"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Payments", callback_data="admin_payments_menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_late_payment_approval_keyboard(payment_id: int) -> InlineKeyboardMarkup:
    """Inline verification buttons for late-submitted (expired) payment."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Recover & Deliver", callback_data=f"pay_recover:{payment_id}"),
            InlineKeyboardButton("❌ Reject Payment", callback_data=f"pay_reject:{payment_id}"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Payments", callback_data="admin_payments_menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_expired_proxy_action_keyboard(inventory_id: int) -> InlineKeyboardMarkup:
    """Action buttons for expired inventory items."""
    keyboard = [
        [
            InlineKeyboardButton("🔑 Rotate Password", callback_data=f"exp_rotate_pass:{inventory_id}"),
            InlineKeyboardButton("✏️ Edit Credentials", callback_data=f"exp_edit_cred:{inventory_id}"),
        ],
        [
            InlineKeyboardButton("♻️ Mark Available for Resale", callback_data=f"exp_resale:{inventory_id}"),
            InlineKeyboardButton("🚫 Permanently Disable", callback_data=f"exp_disable:{inventory_id}"),
        ],
        [
            InlineKeyboardButton("📜 View History", callback_data=f"cred_history:{inventory_id}"),
            InlineKeyboardButton("🔙 Back to Expired", callback_data="admin_expired_menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_credential_manager_action_keyboard(inventory_id: int) -> InlineKeyboardMarkup:
    """Actions inside Credential Manager."""
    keyboard = [
        [
            InlineKeyboardButton("🔑 Change Password", callback_data=f"cred_change_pass:{inventory_id}"),
            InlineKeyboardButton("👤 Change Username", callback_data=f"cred_change_user:{inventory_id}"),
        ],
        [
            InlineKeyboardButton("🌐 Change Host", callback_data=f"cred_change_host:{inventory_id}"),
            InlineKeyboardButton("🔌 Change Port", callback_data=f"cred_change_port:{inventory_id}"),
        ],
        [
            InlineKeyboardButton("📜 Audit History", callback_data=f"cred_history:{inventory_id}"),
            InlineKeyboardButton("🔙 Back to Search", callback_data="admin_cred_menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_settings_menu_keyboard(plans: List[Plan]) -> InlineKeyboardMarkup:
    """Settings sub-menu for price modification and UPI."""
    keyboard = []
    for plan in plans:
        keyboard.append([
            InlineKeyboardButton(
                f"✏️ Edit {plan.name} (₹{plan.price_inr:.0f})",
                callback_data=f"set_price_plan:{plan.id}",
            )
        ])
    keyboard.append([InlineKeyboardButton("💳 Update UPI ID", callback_data="set_upi_id")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Admin Menu", callback_data="admin_home")])
    return InlineKeyboardMarkup(keyboard)


def get_back_to_admin_keyboard() -> InlineKeyboardMarkup:
    """Back to admin home button."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_home")]])


# ============================================================================
# MARKETING & BROADCAST KEYBOARDS
# ============================================================================
def get_admin_marketing_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Marketing & Broadcast central menu.
    Requirement: Display ONLY these three options (plus back button).
    """
    keyboard = [
        [InlineKeyboardButton("📢 Send Announcement", callback_data="mkt_announcement")],
        [InlineKeyboardButton("🎯 Send Promotion", callback_data="mkt_promotion")],
        [InlineKeyboardButton("🖼 Send Image / Banner", callback_data="mkt_banner")],
        [InlineKeyboardButton("🔙 Back to Admin Dashboard", callback_data="admin_home")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_campaign_confirm_keyboard(campaign_id: int) -> InlineKeyboardMarkup:
    """Confirmation buttons before triggering broadcast."""
    keyboard = [
        [InlineKeyboardButton("🚀 Confirm & Broadcast Now", callback_data=f"mkt_confirm_send:{campaign_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="admin_marketing_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_banner_workflow_keyboard() -> InlineKeyboardMarkup:
    """Image & Banner management options inside the banner workflow."""
    keyboard = [
        [InlineKeyboardButton("📤 Upload New Image / Banner", callback_data="mkt_banner_upload")],
        [InlineKeyboardButton("📜 View Sent Banners & Deletions", callback_data="mkt_banner_history")],
        [InlineKeyboardButton("🔙 Back to Marketing Menu", callback_data="admin_marketing_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_banner_button_option_keyboard(campaign_id: int) -> InlineKeyboardMarkup:
    """Option to attach 'Buy Now' button to banner."""
    keyboard = [
        [InlineKeyboardButton("✅ Attach '🛒 Buy Now' Button", callback_data=f"mkt_btn_add:{campaign_id}")],
        [InlineKeyboardButton("❌ No Button", callback_data=f"mkt_btn_skip:{campaign_id}")],
        [InlineKeyboardButton("🔙 Cancel", callback_data="mkt_banner")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_banner_action_keyboard(campaign_id: int, has_eligible_retries: bool = False) -> InlineKeyboardMarkup:
    """Action buttons for previous banner campaigns."""
    keyboard = [
        [InlineKeyboardButton("🗑 Delete Image / Banner from Users' Chats", callback_data=f"mkt_del_prompt:{campaign_id}")],
    ]
    if has_eligible_retries:
        keyboard.append([InlineKeyboardButton("🔄 Retry Eligible Failed Deletions", callback_data=f"mkt_del_prompt:{campaign_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Banners", callback_data="mkt_banner")])
    return InlineKeyboardMarkup(keyboard)


def get_banner_deletion_confirm_keyboard(campaign_id: int) -> InlineKeyboardMarkup:
    """Confirmation modal before attempting banner deletion from chats."""
    keyboard = [
        [InlineKeyboardButton("🗑 Yes, Attempt Deletion Now", callback_data=f"mkt_del_confirm:{campaign_id}")],
        [InlineKeyboardButton("❌ Cancel & Keep Messages", callback_data=f"mkt_view_banner:{campaign_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)
