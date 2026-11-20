"""
Tatkal Proxy - Advanced Admin Telegram Dashboard
Implements full administrative control: statistics, credential management,
expired inventory rotation, customer audits, price modifications, and payment approvals.
"""

from __future__ import annotations

import logging
from typing import Optional, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import settings
from database.connection import get_db
from database.models import (
    Campaign,
    CampaignDelivery,
    CampaignStatus,
    CampaignType,
    Inventory,
    DailyInventory,
    InventoryStatus,
    Order,
    Payment,
    PaymentStatus,
    Plan,
    Subscription,
    SubscriptionStatus,
    User,
)
from database.crud import (
    get_or_create_user,
    get_dashboard_metrics,
    get_inventory_stats,
    get_comprehensive_inventory_stats,
    find_proxy_by_ip,
    search_inventory,
    get_expired_hold_inventory,
    update_proxy_credentials,
    release_expired_proxy_to_available,
    disable_proxy,
    search_users,
    set_user_blocked_status,
    get_active_plans,
    update_plan_price,
    set_setting,
    get_setting,
    get_submitted_payments,
    get_payment_by_id,
    get_recent_admin_logs,
    create_campaign,
    get_campaign_by_id,
    get_campaigns_by_type,
    get_broadcast_target_users,
)
from services.crypto_service import crypto_service
from services.payment_service import payment_service
from services.inventory_service import (
    process_txt_inventory,
    process_csv_inventory,
    process_daily_txt_inventory,
    process_daily_csv_inventory,
)
from services.broadcast_service import broadcast_service
from utils.formatters import format_currency, format_dt
from keyboards.admin_kb import (
    get_admin_main_menu_keyboard,
    get_admin_inventory_menu_keyboard,
    get_admin_upload_regular_keyboard,
    get_admin_upload_daily_keyboard,
    get_credential_manager_action_keyboard,
    get_expired_proxy_action_keyboard,
    get_settings_menu_keyboard,
    get_back_to_admin_keyboard,
    get_payment_approval_keyboard,
    get_admin_marketing_menu_keyboard,
    get_campaign_confirm_keyboard,
    get_banner_workflow_keyboard,
    get_banner_button_option_keyboard,
    get_banner_action_keyboard,
    get_banner_deletion_confirm_keyboard,
)

logger = logging.getLogger("TatkalProxy.AdminHandler")


def verify_admin(update: Update) -> bool:
    """Validate numeric Telegram user ID against authorized admin list."""
    user = update.effective_user
    return bool(user and settings.is_admin(user.id))


# ============================================================================
# /admin COMMAND & MAIN MENU
# ============================================================================
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /admin command."""
    if not verify_admin(update):
        await update.effective_message.reply_text("⛔ Unauthorized. Admin privileges required.")
        return

    text = (
        "👑 <b>TATKAL PROXY — ADMIN CONTROL PANEL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Welcome to the administrative console. Select an option to manage the store:"
    )
    await update.effective_message.reply_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_admin_main_menu_keyboard(),
    )


async def handle_admin_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return to admin central dashboard."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()
    text = (
        "👑 <b>TATKAL PROXY — ADMIN CONTROL PANEL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Welcome to the administrative console. Select an option to manage the store:"
    )
    await query.edit_message_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_admin_main_menu_keyboard(),
    )


# ============================================================================
# 1. DASHBOARD & SALES REPORTS
# ============================================================================
async def handle_admin_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display real-time business statistics."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()

    with get_db() as db:
        metrics = get_dashboard_metrics(db)
        inv = metrics["inventory"]

    dash_text = (
        "📊 <b>TATKAL PROXY — LIVE DASHBOARD</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Today's Revenue:</b> {format_currency(metrics['today_revenue'])}\n"
        f"📈 <b>Monthly Revenue:</b> {format_currency(metrics['monthly_revenue'])}\n"
        f"⏳ <b>Pending Payments:</b> {metrics['pending_payments']}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📦 <b>INVENTORY OVERVIEW:</b>\n"
        f"   • Total Proxies: <b>{inv['total']}</b>\n"
        f"   • Available (Standard): <b>{inv['available']}</b>\n"
        f"   • Allocated (In Use): <b>{inv['allocated']}</b>\n"
        f"   • Special IPs (103.x): <b>{inv['special_available']}/{inv['special_total']}</b>\n"
        f"   • Expired (Holding): <b>{inv['expired_hold']}</b>\n"
        f"   • Disabled: <b>{inv['disabled']}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👥 <b>CUSTOMERS & SUBSCRIPTIONS:</b>\n"
        f"   • Total Registered Users: <b>{metrics['total_customers']}</b>\n"
        f"   • Active Subscriptions: <b>{metrics['active_subs']}</b>\n"
        f"   • Expired Subscriptions: <b>{metrics['expired_subs']}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await query.edit_message_text(
        text=dash_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_back_to_admin_keyboard(),
    )


async def handle_admin_sales_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display recent sales and transaction log."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()

    with get_db() as db:
        recent_logs = get_recent_admin_logs(db, limit=15)

    report_text = "📈 <b>RECENT SYSTEM AUDIT & SALES LOG</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    if not recent_logs:
        report_text += "<i>No recent audit records found.</i>\n"
    else:
        for log in recent_logs:
            report_text += (
                f"• <b>{log.action}</b> ({format_dt(log.created_at)})\n"
                f"  <i>{log.details or 'N/A'}</i>\n\n"
            )

    await query.edit_message_text(
        text=report_text[:4000],
        parse_mode=ParseMode.HTML,
        reply_markup=get_back_to_admin_keyboard(),
    )


# ============================================================================
# 2. INVENTORY & UPLOAD MANAGEMENT
# ============================================================================
async def handle_admin_inventory_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show comprehensive Inventory Dashboard with breakdowns across all pools."""
    if not verify_admin(update):
        return
    query = update.callback_query
    if query:
        await query.answer()

    with get_db() as db:
        stats = get_comprehensive_inventory_stats(db)

    text = (
        "📦 <b>TATKAL PROXY — INVENTORY DASHBOARD</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🌐 <b>Standard Proxies (Monthly):</b>\n"
        f"   • Available: <b>{stats['standard_available']}</b>\n"
        f"   • Allocated: {stats['standard_allocated']}\n"
        f"   • Total Stock: {stats['standard_total']}\n\n"
        "🌟 <b>Special IP Proxies (103.x.x.x):</b>\n"
        f"   • Available: <b>{stats['special_available']}</b>\n"
        f"   • Allocated: {stats['special_allocated']}\n"
        f"   • Total Stock: {stats['special_total']}\n\n"
        "📅 <b>Daily (1-Day) Proxies:</b>\n"
        f"   • Available: <b>{stats['daily_available']}</b>\n"
        f"   • Allocated: {stats['daily_allocated']}\n"
        f"   • Expired Today: {stats['daily_expired']}\n"
        f"   • Total Daily Stock: {stats['daily_total']}\n\n"
        f"⚠️ <b>Quarantined / Expired Hold:</b> <b>{stats['quarantined_total']}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Stock counts update automatically on every purchase & midnight expiry.</i>"
    )

    if query and query.message:
        try:
            await query.edit_message_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=get_admin_inventory_menu_keyboard(),
            )
            return
        except Exception:
            pass

    chat_id = update.effective_chat.id
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_admin_inventory_menu_keyboard(),
    )


async def handle_admin_upload_regular_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Submenu for uploading regular / monthly / special 103.x proxies."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()
    text = (
        "📤 <b>UPLOAD STANDARD / SPECIAL PROXIES</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Select the file format to import into Monthly & Special inventory pools:"
    )
    await query.edit_message_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_admin_upload_regular_keyboard(),
    )


async def handle_admin_upload_daily_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Submenu for uploading daily 1-day proxies."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()
    text = (
        "📅 <b>UPLOAD DAILY (1-DAY) PROXIES</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Select the file format to import today's fresh Daily Proxies batch:\n\n"
        "⚠️ <i>Daily proxies are strictly isolated in daily inventory and automatically expire at midnight IST.</i>"
    )
    await query.edit_message_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_admin_upload_daily_keyboard(),
    )


async def upload_daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command /upload_daily to directly trigger daily proxy upload."""
    if not verify_admin(update):
        return

    # If document is attached directly with /upload_daily
    if update.message and update.message.document:
        context.user_data["admin_expecting_file"] = "DAILY_AUTO"
        await handle_document_upload(update, context)
        return

    context.user_data["admin_expecting_file"] = "DAILY_TXT"
    msg = (
        "📅 <b>UPLOAD DAILY PROXIES (1-DAY INVENTORY)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Please send a <b>.txt</b> or <b>.csv</b> document to this chat.\n\n"
        "<b>Format (one proxy per line):</b>\n"
        "<code>103.10.20.30:8080:username:password</code>\n\n"
        "• Proxies will be stored in isolated <b>Daily Inventory</b>.\n"
        "• Automatically expires at <b>11:59:59 PM IST</b> today.\n"
        "• Duplicates across all tables are rejected.\n"
        "• Credentials encrypted at rest."
    )
    await update.message.reply_text(
        text=msg,
        parse_mode=ParseMode.HTML,
        reply_markup=get_back_to_admin_keyboard(),
    )


async def handle_upload_daily_txt_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt admin to upload TXT file for daily inventory."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()
    context.user_data["admin_expecting_file"] = "DAILY_TXT"

    msg = (
        "📅 <b>UPLOAD DAILY PROXIES VIA TXT FILE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Please send a <b>.txt</b> document to this chat.\n\n"
        "<b>Format (one per line):</b>\n"
        "<code>ip:host:user:pass</code>\n"
        "Example:\n"
        "<code>103.10.20.30:8080:username:password</code>\n\n"
        "• Stored in isolated <b>Daily Inventory</b>.\n"
        "• Valid until <b>11:59:59 PM IST</b> today.\n"
        "• Credentials stored encrypted at rest."
    )
    await query.message.reply_text(text=msg, parse_mode=ParseMode.HTML, reply_markup=get_back_to_admin_keyboard())


async def handle_upload_daily_csv_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt admin to upload CSV file for daily inventory."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()
    context.user_data["admin_expecting_file"] = "DAILY_CSV"

    msg = (
        "📅 <b>UPLOAD DAILY PROXIES VIA CSV FILE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Please send a <b>.csv</b> document to this chat.\n\n"
        "<b>Accepted Header Columns:</b>\n"
        "<code>ip,port,username,password,host</code>\n"
        "Example:\n"
        "<code>103.10.20.30,8080,myuser,mypass,103.10.20.30</code>\n\n"
        "• Stored in isolated <b>Daily Inventory</b>.\n"
        "• Valid until <b>11:59:59 PM IST</b> today."
    )
    await query.message.reply_text(text=msg, parse_mode=ParseMode.HTML, reply_markup=get_back_to_admin_keyboard())


async def handle_upload_txt_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Instruct admin to upload TXT file for regular inventory."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()
    context.user_data["admin_expecting_file"] = "TXT"

    msg = (
        "📄 <b>UPLOAD REGULAR PROXIES VIA TXT FILE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Please send a <b>.txt</b> document to this chat.\n\n"
        "<b>Format (one per line):</b>\n"
        "<code>ip:host:user:pass</code>\n"
        "Example:\n"
        "<code>103.10.20.30:8080:username:password</code>\n\n"
        "• Duplicates will be rejected automatically.\n"
        "• 103.x.x.x IPs will be classified as Special IPs.\n"
        "• Credentials will be stored encrypted at rest."
    )
    await query.message.reply_text(text=msg, parse_mode=ParseMode.HTML, reply_markup=get_back_to_admin_keyboard())


async def handle_upload_csv_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Instruct admin to upload CSV file for regular inventory."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()
    context.user_data["admin_expecting_file"] = "CSV"

    msg = (
        "📊 <b>UPLOAD REGULAR PROXIES VIA CSV FILE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Please send a <b>.csv</b> document to this chat.\n\n"
        "<b>Accepted Header Columns:</b>\n"
        "<code>ip,port,username,password,host</code>\n"
        "Example:\n"
        "<code>103.10.20.30,8080,myuser,mypass,103.10.20.30</code>"
    )
    await query.message.reply_text(text=msg, parse_mode=ParseMode.HTML, reply_markup=get_back_to_admin_keyboard())


async def handle_document_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming TXT or CSV document from admin for regular or daily inventory."""
    if not verify_admin(update):
        return

    doc = update.message.document
    if not doc:
        return

    file_type = context.user_data.pop("admin_expecting_file", None)
    file_name = doc.file_name.lower()

    if not file_type:
        if file_name.endswith(".csv"):
            file_type = "CSV"
        elif file_name.endswith(".txt"):
            file_type = "TXT"
        else:
            await update.message.reply_text("Please upload a .txt or .csv file.")
            return

    # Download document
    status_msg = await update.message.reply_text("⏳ Processing uploaded proxy file...")
    try:
        tg_file = await doc.get_file()
        file_bytes = await tg_file.download_as_bytearray()
        content = file_bytes.decode("utf-8", errors="replace")
    except Exception as e:
        logger.error(f"Failed to read uploaded document: {e}")
        await status_msg.edit_text(f"❌ Failed to download or read file: {e}")
        return

    is_daily = False
    with get_db() as db:
        if file_type == "DAILY_TXT":
            res = process_daily_txt_inventory(db, content, admin_id=update.effective_user.id)
            is_daily = True
        elif file_type == "DAILY_CSV":
            res = process_daily_csv_inventory(db, content, admin_id=update.effective_user.id)
            is_daily = True
        elif file_type == "DAILY_AUTO":
            if file_name.endswith(".csv"):
                res = process_daily_csv_inventory(db, content, admin_id=update.effective_user.id)
            else:
                res = process_daily_txt_inventory(db, content, admin_id=update.effective_user.id)
            is_daily = True
        elif file_type == "TXT":
            res = process_txt_inventory(db, content, admin_id=update.effective_user.id)
        else:
            res = process_csv_inventory(db, content, admin_id=update.effective_user.id)

    title = "DAILY INVENTORY IMPORT REPORT" if is_daily else f"INVENTORY IMPORT REPORT ({file_type})"
    daily_notice = "\n📅 <i>Stored in Isolated Daily Inventory (Expires 11:59 PM IST)</i>\n" if is_daily else ""

    report = (
        f"✅ <b>{title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📁 <b>File:</b> {doc.file_name}\n"
        f"📊 <b>Total Rows:</b> {res.total_lines}\n"
        f"🟢 <b>Successfully Imported:</b> <b>{res.imported_count}</b>\n"
    )
    if not is_daily:
        report += (
            f"🌟 <b>Special IPs (103.x):</b> {res.special_count}\n"
            f"🌐 <b>Standard IPs:</b> {res.standard_count}\n"
        )
    report += (
        f"⚠️ <b>Duplicate In File:</b> {res.duplicate_file_count}\n"
        f"⚠️ <b>Already In Database:</b> {res.duplicate_db_count}\n"
        f"❌ <b>Errors / Skipped:</b> {res.total_errors}\n"
        f"{daily_notice}"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    if res.errors:
        report += "<b>Error Samples:</b>\n" + "\n".join(f"• {e}" for e in res.errors[:5])

    await status_msg.edit_text(report, parse_mode=ParseMode.HTML, reply_markup=get_admin_inventory_menu_keyboard())


# ============================================================================
# 3. CREDENTIAL MANAGER & AUDIT TRAIL
# ============================================================================
async def handle_credential_manager_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt for proxy search by IP."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()

    context.user_data["admin_state"] = "AWAITING_IP_SEARCH"
    text = (
        "🔐 <b>CREDENTIAL MANAGER</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Please send the <b>IP address</b> of the proxy you want to inspect or edit.\n"
        "Example: <code>103.10.20.30</code>"
    )
    await query.message.reply_text(text=text, parse_mode=ParseMode.HTML, reply_markup=get_back_to_admin_keyboard())


async def display_proxy_credential_card(
    chat_id: int, proxy_ip: str, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Render full credential details including decrypted secret values for admin."""
    with get_db() as db:
        proxy = find_proxy_by_ip(db, proxy_ip)
        if not proxy:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Proxy with IP <code>{proxy_ip}</code> not found in inventory.",
                parse_mode=ParseMode.HTML,
                reply_markup=get_back_to_admin_keyboard(),
            )
            return

        user_plain = crypto_service.decrypt(proxy.username_enc, safe=True)
        pass_plain = crypto_service.decrypt(proxy.password_enc, safe=True)
        last_cust_str = f"User ID {proxy.last_customer_id}" if proxy.last_customer_id else "None"
        special_str = "🌟 Special 103.x Subnet" if proxy.is_special else "🌐 Standard Subnet"

        card = (
            f"🔐 <b>PROXY CREDENTIAL DETAILS</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🌐 <b>IP Address:</b> <code>{proxy.ip}</code>\n"
            f"🖥 <b>Host:</b> <code>{proxy.host}</code>\n"
            f"🔌 <b>Port:</b> <code>{proxy.port}</code>\n"
            f"👤 <b>Username:</b> <code>{user_plain}</code>\n"
            f"🔑 <b>Password:</b> <code>{pass_plain}</code>\n"
            f"🏷 <b>Type:</b> {special_str}\n"
            f"📊 <b>Status:</b> <b>{proxy.status}</b>\n"
            f"🔄 <b>Credentials Updated:</b> {'Yes' if proxy.credentials_updated else 'No (Action Required)'}\n"
            f"👤 <b>Previous Customer:</b> {last_cust_str}\n"
            f"📅 <b>Last Modified:</b> {format_dt(proxy.updated_at)}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=card,
            parse_mode=ParseMode.HTML,
            reply_markup=get_credential_manager_action_keyboard(proxy.id),
        )


async def handle_cred_change_prompt(
    update: Update, context: ContextTypes.DEFAULT_TYPE, field_name: str
) -> None:
    """Prompt admin to enter new value for proxy field."""
    query = update.callback_query
    await query.answer()
    proxy_id = int(query.data.split(":")[1])

    context.user_data["admin_state"] = f"EDIT_PROXY_{field_name.upper()}"
    context.user_data["edit_proxy_id"] = proxy_id

    await query.message.reply_text(
        f"✏️ Please enter the new <b>{field_name}</b> for this proxy:",
        parse_mode=ParseMode.HTML,
        reply_markup=get_back_to_admin_keyboard(),
    )


# ============================================================================
# 4. EXPIRED PROXY MANAGER
# ============================================================================
async def handle_expired_proxies_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """View and manage proxies whose subscriptions have expired."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()

    with get_db() as db:
        expired_items = get_expired_hold_inventory(db)

    if not expired_items:
        text = (
            "⏰ <b>EXPIRED PROXIES — HOLDING POOL</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🟢 No expired proxies are currently held. All stock is clean!"
        )
        await query.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=get_back_to_admin_keyboard())
        return

    text = (
        f"⏰ <b>EXPIRED PROXIES ({len(expired_items)} Pending Action)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ <i>Proxies here are NEVER resold automatically. Rotate credentials before releasing to available pool.</i>\n\n"
    )
    for p in expired_items[:8]:
        text += (
            f"• <b>{p.ip}:{p.port}</b> | Prev Cust: {p.last_customer_id or 'N/A'}\n"
            f"  Credentials Updated: {'✅' if p.credentials_updated else '❌ No'}\n"
            f"  /inspect_{p.id}\n\n"
        )

    await query.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=get_back_to_admin_keyboard())


async def handle_expired_resale_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin marks expired proxy available for resale after credentials rotation."""
    query = update.callback_query
    inv_id = int(query.data.split(":")[1])

    with get_db() as db:
        try:
            proxy = release_expired_proxy_to_available(db, inv_id, admin_id=update.effective_user.id)
            await query.answer("Proxy marked AVAILABLE for resale!", show_alert=True)
            await query.message.reply_text(
                f"✅ Proxy <code>{proxy.ip}</code> is now <b>AVAILABLE</b> for new purchases.",
                parse_mode=ParseMode.HTML,
                reply_markup=get_admin_inventory_menu_keyboard(),
            )
        except Exception as e:
            await query.answer(f"Error: {e}", show_alert=True)


async def handle_expired_disable_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin disables expired proxy permanently."""
    query = update.callback_query
    inv_id = int(query.data.split(":")[1])

    with get_db() as db:
        proxy = disable_proxy(db, inv_id, admin_id=update.effective_user.id)
        await query.answer("Proxy disabled.", show_alert=True)
        await query.message.reply_text(
            f"🚫 Proxy <code>{proxy.ip}</code> has been disabled.",
            parse_mode=ParseMode.HTML,
            reply_markup=get_admin_inventory_menu_keyboard(),
        )


# ============================================================================
# 5. CUSTOMER MANAGEMENT
# ============================================================================
async def handle_admin_customers_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display comprehensive customer list with assigned IP(s) and expiration dates."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()

    from sqlalchemy.orm import joinedload

    with get_db() as db:
        users = (
            db.query(User)
            .options(
                joinedload(User.subscriptions).joinedload(Subscription.inventory),
                joinedload(User.subscriptions).joinedload(Subscription.daily_inventory),
                joinedload(User.subscriptions).joinedload(Subscription.plan),
            )
            .order_by(User.id.desc())
            .limit(20)
            .all()
        )

        if not users:
            text = (
                "👥 <b>CUSTOMER DIRECTORY</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "<i>No customers registered yet.</i>"
            )
            await query.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=get_back_to_admin_keyboard())
            return

        text = f"👥 <b>CUSTOMER LIST ({len(users)} Customers)</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        for u in users:
            uname = f"@{u.username}" if u.username else "No Username"
            status_tag = "🔴 Blocked" if u.is_blocked else "🟢 Active"
            text += f"👤 <b>{uname}</b> (<code>{u.telegram_id}</code>) — {status_tag}\n"

            # Check subscriptions
            if not u.subscriptions:
                text += "   <i>No proxy allocated</i>\n"
            else:
                for sub in u.subscriptions:
                    state_dot = "🟢" if sub.status == SubscriptionStatus.ACTIVE.value else "🔴"
                    ip_str = sub.proxy_ip
                    plan_name = sub.plan.name if sub.plan else "Proxy"
                    text += f"   • 🌐 <code>{ip_str}</code> ({plan_name})\n"
                    text += f"     ⏳ Expiry: <b>{format_dt(sub.end_date)}</b> ({state_dot} {sub.status})\n"
            text += "────────────────────────────\n"

        text += "\n🔍 <i>Tip: Send a customer's numeric ID or @username to view full profile.</i>"

    context.user_data["admin_state"] = "AWAITING_CUSTOMER_SEARCH"

    # Truncate if Telegram length limit
    if len(text) > 4000:
        text = text[:3900] + "\n\n<i>[Showing first 20 customers]</i>"

    try:
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=get_back_to_admin_keyboard(),
        )
    except Exception:
        await query.message.reply_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=get_back_to_admin_keyboard(),
        )


async def display_customer_profile(
    chat_id: int, query_term: str, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Render customer profile, order history, and active subscriptions."""
    with get_db() as db:
        users = search_users(db, query_term)
        if not users:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ No customer found matching '<code>{query_term}</code>'.",
                parse_mode=ParseMode.HTML,
                reply_markup=get_back_to_admin_keyboard(),
            )
            return

        user = users[0]
        status_tag = "🔴 BLOCKED" if user.is_blocked else "🟢 ACTIVE"
        active_subs = [s for s in user.subscriptions if s.status == SubscriptionStatus.ACTIVE.value]

        profile = (
            f"👤 <b>CUSTOMER PROFILE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 <b>Telegram ID:</b> <code>{user.telegram_id}</code>\n"
            f"👤 <b>Username:</b> @{user.username or 'N/A'}\n"
            f"📛 <b>Name:</b> {user.first_name or ''} {user.last_name or ''}\n"
            f"🏷 <b>Status:</b> {status_tag}\n"
            f"📅 <b>Joined:</b> {format_dt(user.created_at)}\n"
            f"📦 <b>Total Orders:</b> {len(user.orders)}\n"
            f"⚡ <b>Active Subscriptions:</b> {len(active_subs)}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        if active_subs:
            profile += "<b>Current Active Proxies:</b>\n"
            for s in active_subs:
                profile += f"• <code>{s.proxy_ip}</code> ({s.plan.name}) — Ends: {format_dt(s.end_date)}\n"

        await context.bot.send_message(
            chat_id=chat_id,
            text=profile,
            parse_mode=ParseMode.HTML,
            reply_markup=get_back_to_admin_keyboard(),
        )


# ============================================================================
# 6. ORDERS & PAYMENT APPROVALS
# ============================================================================
async def handle_admin_payments_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List pending manual payments."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()

    with get_db() as db:
        pending = get_submitted_payments(db)

    if not pending:
        await query.edit_message_text(
            "💰 <b>ORDERS & PAYMENTS</b>\n\n🟢 No pending payments awaiting verification.",
            parse_mode=ParseMode.HTML,
            reply_markup=get_back_to_admin_keyboard(),
        )
        return

    text = f"💰 <b>PENDING MANUAL PAYMENTS ({len(pending)})</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for p in pending[:5]:
        text += (
            f"🧾 <b>Order:</b> <code>{p.order.order_code}</code>\n"
            f"👤 <b>User:</b> @{p.user.username or 'N/A'} (<code>{p.user.telegram_id}</code>)\n"
            f"💵 <b>Amount:</b> {format_currency(p.amount)}\n"
            f"🔢 <b>UTR:</b> <code>{p.utr or 'N/A'}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )

    # Offer approval keyboard for the first pending payment
    first_payment = pending[0]
    await query.edit_message_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_payment_approval_keyboard(first_payment.id),
    )


async def safe_answer_callback(
    query,
    text: str,
    show_alert: bool = True,
    max_len: int = 180,
) -> None:
    """
    Safely acknowledge a Telegram callback query without crashing.
    Truncates text to adhere to Telegram's 200-character callback alert limit.
    Catches and logs any TelegramError to avoid cascading failures.
    """
    try:
        clean_text = str(text).strip()
        if len(clean_text) > max_len:
            clean_text = clean_text[:max_len - 3] + "..."
        await query.answer(clean_text, show_alert=show_alert)
    except Exception as ex:
        logger.warning(f"Failed to answer callback query safely: {ex}")


async def handle_pay_approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin clicks Approve on a payment."""
    if not verify_admin(update):
        return
    query = update.callback_query
    payment_id = int(query.data.split(":")[1])

    with get_db() as db:
        try:
            sub, inv = await payment_service.verify_and_deliver(
                db=db,
                payment_id=payment_id,
                admin_tg_id=update.effective_user.id,
                bot=context.bot,
            )
            await safe_answer_callback(query, "Payment Approved & Proxy Delivered!", show_alert=True)
            await query.message.reply_text(
                f"✅ <b>PAYMENT APPROVED & PROXY DELIVERED</b>\n\n"
                f"Delivered IP: <code>{inv.ip}</code>\n"
                f"Customer Telegram: <code>{sub.user.telegram_id}</code>\n"
                f"Subscription: <code>{sub.sub_code}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=get_admin_main_menu_keyboard(),
            )
        except ValueError as ve:
            logger.warning(f"Validation error approving payment {payment_id}: {ve}")
            err_msg = str(ve)
            await safe_answer_callback(query, f"❌ {err_msg}", show_alert=True)
            try:
                await query.message.reply_text(
                    f"⚠️ <b>Approval Blocked:</b> {err_msg}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_admin_main_menu_keyboard(),
                )
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Internal error approving payment {payment_id}: {e}", exc_info=True)
            safe_alert = "❌ Payment approval failed. Check application logs for details."
            await safe_answer_callback(query, safe_alert, show_alert=True)
            try:
                await query.message.reply_text(
                    "❌ <b>Payment Approval Failed</b>\n\nAn internal error occurred. Please check application logs for details.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_admin_main_menu_keyboard(),
                )
            except Exception:
                pass


async def handle_pay_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin clicks Reject on a payment."""
    if not verify_admin(update):
        return
    query = update.callback_query
    payment_id = int(query.data.split(":")[1])

    with get_db() as db:
        try:
            payment = await payment_service.reject_payment(
                db=db,
                payment_id=payment_id,
                admin_tg_id=update.effective_user.id,
                bot=context.bot,
                reason="Transaction reference could not be verified in bank records.",
            )
            await safe_answer_callback(query, "Payment Rejected.", show_alert=True)
            await query.message.reply_text(
                f"❌ Payment {payment_id} marked REJECTED and customer notified.",
                reply_markup=get_admin_main_menu_keyboard(),
            )
        except ValueError as ve:
            logger.warning(f"Validation error rejecting payment {payment_id}: {ve}")
            await safe_answer_callback(query, f"❌ {str(ve)}", show_alert=True)
        except Exception as e:
            logger.error(f"Internal error rejecting payment {payment_id}: {e}", exc_info=True)
            safe_alert = "❌ Payment rejection failed. Check logs for details."
            await safe_answer_callback(query, safe_alert, show_alert=True)


async def handle_pay_recover_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin clicks 'Recover & Deliver' on a late-submitted (expired) payment."""
    if not verify_admin(update):
        return
    query = update.callback_query
    payment_id = int(query.data.split(":")[1])

    with get_db() as db:
        try:
            sub, inv = await payment_service.recover_and_deliver(
                db=db,
                payment_id=payment_id,
                admin_tg_id=update.effective_user.id,
                bot=context.bot,
            )
            await safe_answer_callback(query, "Late Payment Recovered & Proxy Delivered!", show_alert=True)
            await query.message.reply_text(
                f"✅ <b>LATE PAYMENT RECOVERED & PROXY DELIVERED</b>\n\n"
                f"Delivered IP: <code>{inv.ip}</code>\n"
                f"Customer Telegram: <code>{sub.user.telegram_id}</code>\n"
                f"Subscription: <code>{sub.sub_code}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=get_admin_main_menu_keyboard(),
            )
        except ValueError as ve:
            logger.warning(f"Validation error recovering payment {payment_id}: {ve}")
            err_msg = str(ve)
            await safe_answer_callback(query, f"❌ {err_msg}", show_alert=True)
            try:
                await query.message.reply_text(
                    f"⚠️ <b>Recovery Blocked:</b> {err_msg}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_admin_main_menu_keyboard(),
                )
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Internal error recovering payment {payment_id}: {e}", exc_info=True)
            safe_alert = "❌ Payment recovery failed. Check application logs for details."
            await safe_answer_callback(query, safe_alert, show_alert=True)
            try:
                await query.message.reply_text(
                    "❌ <b>Payment Recovery Failed</b>\n\nAn internal error occurred. Please check application logs for details.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_admin_main_menu_keyboard(),
                )
            except Exception:
                pass


# ============================================================================
# 7. SETTINGS & DYNAMIC PRICING
# ============================================================================
async def handle_admin_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display settings and plan price editors."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()

    with get_db() as db:
        plans = get_active_plans(db)
        upi = get_setting(db, "upi_id", settings.UPI_ID)

    text = (
        "⚙️ <b>TATKAL PROXY SETTINGS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💳 <b>Current UPI ID:</b> <code>{upi}</code>\n\n"
        "Select a plan below to change its price through Telegram:"
    )
    await query.edit_message_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_settings_menu_keyboard(plans),
    )


async def handle_set_price_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt admin for new plan price."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()
    plan_id = int(query.data.split(":")[1])

    context.user_data["admin_state"] = "EDIT_PLAN_PRICE"
    context.user_data["edit_plan_id"] = plan_id

    await query.message.reply_text(
        "💵 Please enter the <b>new price in ₹ INR</b> (e.g. <code>25</code> or <code>450</code>):",
        parse_mode=ParseMode.HTML,
        reply_markup=get_back_to_admin_keyboard(),
    )


async def handle_set_upi_id_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt admin for new UPI ID."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()

    context.user_data["admin_state"] = "EDIT_UPI_ID"
    await query.message.reply_text(
        "💳 Please enter the <b>new UPI ID</b> (e.g. <code>yourname@upi</code>):",
        parse_mode=ParseMode.HTML,
        reply_markup=get_back_to_admin_keyboard(),
    )


# ============================================================================
# 8. MARKETING & BROADCAST (ANNOUNCEMENT, PROMOTION, BANNER)
# ============================================================================
async def handle_admin_marketing_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Main Marketing & Broadcast control panel.
    Requirement: Display ONLY Announcement, Promotion, Image / Banner.
    """
    if not verify_admin(update):
        return
    query = update.callback_query
    if query:
        await query.answer()

    text = (
        "📢 <b>TATKAL PROXY — MARKETING & BROADCAST</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Directly reach all registered customers with announcements, promotional offers, and visual banners.\n\n"
        "Select an action below:"
    )
    markup = get_admin_marketing_menu_keyboard()

    if query and query.message:
        try:
            await query.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=markup)
            return
        except Exception:
            pass

    chat_id = update.effective_chat.id
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def handle_mkt_announcement_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt admin to compose general announcement."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()
    context.user_data["admin_state"] = "AWAITING_ANNOUNCEMENT_TEXT"

    text = (
        "📢 <b>COMPOSE ANNOUNCEMENT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Please send the message you wish to broadcast to all registered customers.\n\n"
        "• Supports HTML formatting (<b>bold</b>, <i>italic</i>, <code>code</code>)\n"
        "• Emojis and clickable links are fully supported.\n"
        "• You will see a live preview and exact recipient count before sending."
    )
    await query.message.reply_text(text=text, parse_mode=ParseMode.HTML, reply_markup=get_back_to_admin_keyboard())


async def handle_mkt_promotion_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt admin to compose promotional offer with dynamic plan pricing from DB."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()
    context.user_data["admin_state"] = "AWAITING_PROMOTION_TEXT"

    with get_db() as db:
        plans = get_active_plans(db)
        pricing_lines = "\n".join(
            f"• <b>{p.name}:</b> {format_currency(p.price_inr)} ({p.duration_days} Day{'s' if p.duration_days > 1 else ''})"
            for p in plans
        )

    text = (
        "🎯 <b>COMPOSE PROMOTION</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Current Database Subscription Plans & Prices:</b>\n"
        f"{pricing_lines}\n\n"
        "Please send your promotional offer / discount message.\n\n"
        "• Bold, italic, emojis, and clickable links are supported.\n"
        "• A <code>🛒 Buy Now</code> button will be attached automatically.\n"
        "• You will see a live preview and recipient count before sending."
    )
    await query.message.reply_text(text=text, parse_mode=ParseMode.HTML, reply_markup=get_back_to_admin_keyboard())


async def handle_mkt_banner_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Image / Banner menu inside the banner workflow."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()

    text = (
        "🖼 <b>IMAGE & BANNER BROADCAST</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Upload and broadcast visual banners (JPG / PNG) to all customers, or view previous campaigns and manage message deletions."
    )
    await query.edit_message_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_banner_workflow_keyboard(),
    )


async def handle_mkt_banner_upload_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Instruct admin to send photo for banner campaign."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()
    context.user_data["admin_state"] = "AWAITING_BANNER_PHOTO"

    text = (
        "🖼 <b>UPLOAD IMAGE / BANNER</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Please send an image (<b>JPG</b> or <b>PNG</b>) to this chat.\n\n"
        "• You can attach a caption directly with the photo.\n"
        "• You can attach an interactive <code>🛒 Buy Now</code> button.\n"
        "• You will preview the banner before confirming the broadcast."
    )
    await query.message.reply_text(text=text, parse_mode=ParseMode.HTML, reply_markup=get_back_to_admin_keyboard())


async def handle_admin_photo_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle image uploaded by admin for banner broadcast."""
    if not verify_admin(update):
        return

    if context.user_data.get("admin_state") != "AWAITING_BANNER_PHOTO":
        return

    photo_list = update.message.photo
    if not photo_list:
        return

    context.user_data.pop("admin_state", None)
    best_photo = photo_list[-1]
    file_id = best_photo.file_id
    caption = update.message.caption or ""

    with get_db() as db:
        admin_user = get_or_create_user(db=db, telegram_id=update.effective_user.id)
        campaign = create_campaign(
            db=db,
            admin_id=admin_user.id,
            campaign_type=CampaignType.BANNER.value,
            media_file_id=file_id,
            caption=caption,
            has_button=False,
        )
        camp_id = campaign.id

    context.user_data["pending_banner_campaign_id"] = camp_id

    prompt_msg = (
        "🖼 <b>Banner Image Received!</b>\n\n"
        f"<b>Caption:</b> {caption if caption else '<i>No caption attached</i>'}\n\n"
        "Would you like to attach a <code>🛒 Buy Now</code> button to this banner?"
    )
    await update.message.reply_text(
        text=prompt_msg,
        parse_mode=ParseMode.HTML,
        reply_markup=get_banner_button_option_keyboard(camp_id),
    )


async def handle_mkt_btn_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Attach Buy Now button to banner campaign and display preview."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()
    camp_id = int(query.data.split(":")[1])

    with get_db() as db:
        camp = get_campaign_by_id(db, camp_id)
        if camp:
            camp.has_button = True
            camp.button_text = "🛒 Buy Now"
            camp.button_url_or_cb = "cust_buy"
            db.flush()
        target_count = len(get_broadcast_target_users(db))
        media_id = camp.media_file_id if camp else None
        caption = camp.caption if camp else ""

    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Buy Now", callback_data="cust_buy")]])

    # Send photo preview
    if media_id:
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=media_id,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )

    confirm_text = (
        "🖼 <b>BANNER PREVIEW (WITH 'BUY NOW' BUTTON)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 <b>Target Recipients:</b> <b>{target_count}</b> registered users\n"
        "🔘 <b>Button:</b> [🛒 Buy Now] (opens plan catalog)\n\n"
        "Ready to broadcast this banner to all customers?"
    )
    await update.effective_message.reply_text(
        text=confirm_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_campaign_confirm_keyboard(camp_id),
    )


async def handle_mkt_btn_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Skip button attachment and display preview."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()
    camp_id = int(query.data.split(":")[1])

    with get_db() as db:
        camp = get_campaign_by_id(db, camp_id)
        if camp:
            camp.has_button = False
            db.flush()
        target_count = len(get_broadcast_target_users(db))
        media_id = camp.media_file_id if camp else None
        caption = camp.caption if camp else ""

    # Send photo preview without button
    if media_id:
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=media_id,
            caption=caption,
            parse_mode=ParseMode.HTML,
        )

    confirm_text = (
        "🖼 <b>BANNER PREVIEW (WITHOUT BUTTON)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 <b>Target Recipients:</b> <b>{target_count}</b> registered users\n\n"
        "Ready to broadcast this banner to all customers?"
    )
    await update.effective_message.reply_text(
        text=confirm_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_campaign_confirm_keyboard(camp_id),
    )


async def handle_mkt_confirm_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirm and execute campaign broadcast."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()
    camp_id = int(query.data.split(":")[1])

    status_msg = await query.edit_message_text(
        "⏳ <b>Initiating broadcast engine...</b>\n"
        "Messages are sent in rate-controlled batches to respect Telegram API limits.",
        parse_mode=ParseMode.HTML,
    )

    # Launch broadcast asynchronously
    await broadcast_service.execute_campaign(
        bot=context.bot,
        campaign_id=camp_id,
        admin_chat_id=update.effective_chat.id,
        status_message_id=status_msg.message_id,
    )


async def handle_mkt_banner_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display previous banner campaigns for review and deletion management."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()

    with get_db() as db:
        banners = get_campaigns_by_type(db, campaign_type=CampaignType.BANNER.value, limit=10)

    if not banners:
        text = (
            "📜 <b>SENT BANNERS HISTORY</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>No banner campaigns have been sent yet.</i>"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Banners", callback_data="mkt_banner")]]
        await query.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    text = (
        "📜 <b>SENT BANNERS & DELETION MANAGEMENT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Select a previous campaign to inspect delivery statistics or attempt message deletion:"
    )
    keyboard = []
    for b in banners:
        date_str = format_dt(b.created_at)
        btn_label = f"🖼 {b.campaign_code} ({date_str[:12]})"
        keyboard.append([InlineKeyboardButton(btn_label, callback_data=f"mkt_view_banner:{b.id}")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Banners", callback_data="mkt_banner")])

    await query.edit_message_text(text=text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_mkt_view_banner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """View details of a specific sent banner campaign with deletion action."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()
    camp_id = int(query.data.split(":")[1])

    with get_db() as db:
        camp = get_campaign_by_id(db, camp_id)
        if not camp:
            await query.edit_message_text("Campaign not found.", reply_markup=get_back_to_admin_keyboard())
            return

        deliveries = camp.deliveries
        total_delivered = sum(1 for d in deliveries if d.status == "DELIVERED")
        total_failed = sum(1 for d in deliveries if d.status == "FAILED")
        deleted_count = sum(1 for d in deliveries if d.deleted_from_chat)
        failed_deletion_count = sum(1 for d in deliveries if d.deletion_attempted and not d.deleted_from_chat)
        remaining_in_chats = total_delivered - deleted_count

        detail_text = (
            f"🖼 <b>BANNER CAMPAIGN DETAILS</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 <b>Code:</b> <code>{camp.campaign_code}</code>\n"
            f"📅 <b>Date Sent:</b> {format_dt(camp.created_at)}\n"
            f"📊 <b>Status:</b> <b>{camp.status}</b>\n"
            f"📝 <b>Caption:</b> {camp.caption if camp.caption else '<i>None</i>'}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📤 <b>Delivery Audit:</b>\n"
            f"   • Total Targets: {camp.total_recipients}\n"
            f"   • Successfully Delivered: <b>{total_delivered}</b>\n"
            f"   • Failed Delivery: {total_failed}\n\n"
            f"🗑 <b>Message Deletion Status:</b>\n"
            f"   • Deleted from Users' Chats: <b>{deleted_count}</b>\n"
            f"   • Failed Deletions: <b>{failed_deletion_count}</b>\n"
            f"   • Active in Users' Chats: <b>{remaining_in_chats}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        media_id = camp.media_file_id

    # Send preview image if present
    if media_id:
        try:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=media_id,
                caption=f"Preview for <code>{camp.campaign_code}</code>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    await update.effective_message.reply_text(
        text=detail_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_banner_action_keyboard(camp.id, has_eligible_retries=bool(remaining_in_chats > 0)),
    )


async def handle_mkt_delete_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prompt admin for banner deletion confirmation and explain Telegram restrictions."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()
    camp_id = int(query.data.split(":")[1])

    with get_db() as db:
        camp = get_campaign_by_id(db, camp_id)
        if not camp:
            await query.edit_message_text("Campaign not found.", reply_markup=get_back_to_admin_keyboard())
            return
        delivered_count = sum(1 for d in camp.deliveries if d.status == "DELIVERED" and not d.deleted_from_chat)

    prompt_text = (
        f"⚠️ <b>CONFIRM BANNER DELETION</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Campaign: <code>{camp.campaign_code}</code>\n"
        f"Remaining In Chats: <b>{delivered_count}</b> messages\n\n"
        f"Are you sure you want to attempt deleting this banner from users' private chats?\n\n"
        f"<b>Telegram API Deletion Policies:</b>\n"
        f"• Telegram allows bots to delete messages sent within the <b>last 48 hours</b>.\n"
        f"• Messages older than 48 hours cannot be deleted via the Telegram API.\n"
        f"• Chats where users blocked the bot or cleared conversation will also fail.\n\n"
        f"Accurate counts of successful and failed deletions will be recorded."
    )
    await query.edit_message_text(
        text=prompt_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_banner_deletion_confirm_keyboard(camp_id),
    )


async def handle_mkt_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Execute message deletion attempt for banner campaign and report truthful results."""
    if not verify_admin(update):
        return
    query = update.callback_query
    await query.answer()
    camp_id = int(query.data.split(":")[1])

    status_msg = await query.edit_message_text(
        "⏳ <b>Attempting message deletions from user chats...</b>\n"
        "Querying delivery message IDs and requesting deletion from Telegram API.",
        parse_mode=ParseMode.HTML,
    )

    res = await broadcast_service.delete_campaign_messages(
        bot=context.bot,
        campaign_id=camp_id,
        admin_chat_id=update.effective_chat.id,
        status_message_id=status_msg.message_id,
    )

    reasons_str = ""
    if res["reasons"]:
        reasons_str = "<b>Failure Breakdown:</b>\n" + "\n".join(f"• {reason}: {count}" for reason, count in res["reasons"].items()) + "\n\n"

    report_text = (
        f"📊 <b>BANNER DELETION REPORT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Total Eligible Attempted:</b> {res['total_attempted']}\n"
        f"🟢 <b>Successfully Deleted:</b> <b>{res['successful']}</b>\n"
        f"🔴 <b>Failed to Delete:</b> <b>{res['failed']}</b>\n\n"
        f"{reasons_str}"
        f"<i>Important: In compliance with Telegram API security, messages delivered more than 48 hours ago cannot be revoked from private chats.</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await status_msg.edit_text(
        text=report_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_banner_action_keyboard(camp_id, has_eligible_retries=bool(res["failed"] > 0)),
    )


# ============================================================================
# ADMIN TEXT INPUT ROUTER
# ============================================================================
async def handle_admin_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Handle administrative textual inputs based on state machine.
    Returns True if handled, False otherwise.
    """
    if not verify_admin(update):
        return False

    state = context.user_data.get("admin_state")
    if not state:
        return False

    text = update.message.text.strip()
    chat_id = update.effective_chat.id

    if state == "AWAITING_IP_SEARCH":
        context.user_data.pop("admin_state", None)
        await display_proxy_credential_card(chat_id, text, context)
        return True

    elif state == "AWAITING_ANNOUNCEMENT_TEXT":
        context.user_data.pop("admin_state", None)
        with get_db() as db:
            admin_user = get_or_create_user(db=db, telegram_id=update.effective_user.id)
            target_count = len(get_broadcast_target_users(db))
            campaign = create_campaign(
                db=db,
                admin_id=admin_user.id,
                campaign_type=CampaignType.ANNOUNCEMENT.value,
                content_text=text,
                has_button=False,
            )
            camp_id = campaign.id

        preview_msg = (
            "📢 <b>ANNOUNCEMENT PREVIEW</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{text}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 <b>Target Recipients:</b> <b>{target_count}</b> registered users\n\n"
            "Ready to broadcast this announcement to all customers?"
        )
        await update.message.reply_text(
            text=preview_msg,
            parse_mode=ParseMode.HTML,
            reply_markup=get_campaign_confirm_keyboard(camp_id),
        )
        return True

    elif state == "AWAITING_PROMOTION_TEXT":
        context.user_data.pop("admin_state", None)
        with get_db() as db:
            admin_user = get_or_create_user(db=db, telegram_id=update.effective_user.id)
            target_count = len(get_broadcast_target_users(db))
            campaign = create_campaign(
                db=db,
                admin_id=admin_user.id,
                campaign_type=CampaignType.PROMOTION.value,
                content_text=text,
                has_button=True,
                button_text="🛒 Buy Now",
                button_url_or_cb="cust_buy",
            )
            camp_id = campaign.id

        preview_msg = (
            "🎯 <b>PROMOTION PREVIEW</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{text}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 <b>Target Recipients:</b> <b>{target_count}</b> registered users\n"
            "🔘 <b>Attached Button:</b> [🛒 Buy Now] (opens plans directly)\n\n"
            "Ready to broadcast this promotional message to all customers?"
        )
        await update.message.reply_text(
            text=preview_msg,
            parse_mode=ParseMode.HTML,
            reply_markup=get_campaign_confirm_keyboard(camp_id),
        )
        return True

    elif state == "AWAITING_CUSTOMER_SEARCH":
        context.user_data.pop("admin_state", None)
        await display_customer_profile(chat_id, text, context)
        return True

    elif state == "EDIT_PLAN_PRICE":
        context.user_data.pop("admin_state", None)
        plan_id = context.user_data.pop("edit_plan_id", None)
        try:
            new_price = float(text)
            if new_price <= 0:
                raise ValueError("Price must be greater than zero.")
            with get_db() as db:
                plan = update_plan_price(db, plan_id, new_price, admin_id=update.effective_user.id)
                await update.message.reply_text(
                    f"✅ Price for <b>{plan.name}</b> successfully updated to <b>{format_currency(plan.price_inr)}</b>!",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_admin_main_menu_keyboard(),
                )
        except Exception as e:
            await update.message.reply_text(f"❌ Invalid price format: {e}", reply_markup=get_back_to_admin_keyboard())
        return True

    elif state == "EDIT_UPI_ID":
        context.user_data.pop("admin_state", None)
        if "@" not in text:
            await update.message.reply_text("❌ Invalid UPI ID format (must contain @).", reply_markup=get_back_to_admin_keyboard())
            return True
        with get_db() as db:
            set_setting(db, "upi_id", text, "Admin configured UPI ID")
            await update.message.reply_text(
                f"✅ UPI ID successfully updated to <code>{text}</code>!",
                parse_mode=ParseMode.HTML,
                reply_markup=get_admin_main_menu_keyboard(),
            )
        return True

    elif state.startswith("EDIT_PROXY_"):
        field = state.replace("EDIT_PROXY_", "").lower()
        context.user_data.pop("admin_state", None)
        proxy_id = context.user_data.pop("edit_proxy_id", None)

        kwargs = {f"new_{field}": text}
        with get_db() as db:
            try:
                proxy = update_proxy_credentials(
                    db=db,
                    inventory_id=proxy_id,
                    admin_id=update.effective_user.id,
                    reason=f"Admin updated {field}",
                    **kwargs,
                )
                await update.message.reply_text(
                    f"✅ Successfully updated <b>{field}</b> for proxy <code>{proxy.ip}</code>!",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_admin_main_menu_keyboard(),
                )
            except Exception as e:
                await update.message.reply_text(f"❌ Error updating proxy: {e}", reply_markup=get_back_to_admin_keyboard())
        return True

    return False
