"""
Tatkal Proxy - Main Application Entrypoint
Wires Telegram bot handlers, scheduler lifecycle, and database initialization.
"""

from __future__ import annotations

import logging
import sys
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import settings
from database.connection import init_db
from services.scheduler_service import scheduler_service
from utils.logger import setup_logger
from handlers import (
    start_command,
    admin_command,
    upload_daily_command,
    handle_customer_home,
    handle_browse_plans,
    handle_plan_selected,
    handle_quantity_selected,
    handle_qty_out_of_stock,
    handle_order_confirm,
    handle_submit_utr_button,
    handle_cancel_utr_button,
    handle_customer_web_app_data,
    handle_user_text_input,
    handle_check_payment_status,
    handle_order_cancel,
    handle_my_subscriptions,
    handle_view_subscription,
    handle_renew_subscription_prompt,
    handle_payment_history,
    handle_customer_support,
    handle_admin_home,
    handle_admin_dashboard,
    handle_admin_sales_report,
    handle_admin_inventory_menu,
    handle_admin_upload_regular_menu,
    handle_admin_upload_daily_menu,
    handle_upload_daily_txt_prompt,
    handle_upload_daily_csv_prompt,
    handle_upload_txt_prompt,
    handle_upload_csv_prompt,
    handle_document_upload,
    handle_credential_manager_menu,
    handle_cred_change_prompt,
    handle_expired_proxies_menu,
    handle_expired_resale_action,
    handle_expired_disable_action,
    handle_admin_customers_menu,
    handle_admin_payments_menu,
    handle_pay_approve_callback,
    handle_pay_reject_callback,
    handle_pay_recover_callback,
    handle_admin_settings_menu,
    handle_set_price_plan_callback,
    handle_set_upi_id_callback,
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
)

logger = setup_logger("TatkalProxy.Bot")


async def post_init(application: Application) -> None:
    """Invoked after bot is initialized; starts background services and reconciles daily expiries."""
    logger.info("Starting ExpirySchedulerService...")
    scheduler_service.start(application.bot)
    try:
        reconciled = await scheduler_service.reconcile_overdue_daily_expiries(application.bot)
        if reconciled > 0:
            logger.info(f"Reconciled {reconciled} overdue daily subscriptions on startup.")
    except Exception as e:
        logger.error(f"Error during daily expiry startup reconciliation: {e}")
    logger.info("Tatkal Proxy services started successfully.")


async def post_shutdown(application: Application) -> None:
    """Invoked when bot is stopping; cleanly shuts down background jobs."""
    logger.info("Stopping ExpirySchedulerService...")
    scheduler_service.stop()


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and inform the user if possible."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ An unexpected error occurred while processing your request. Please try again or contact support."
            )
        except Exception:
            pass


def main() -> None:
    """Application bootstrap and runner."""
    print("=" * 60)
    print(f"   🚀 {settings.APP_NAME} - {settings.APP_TAGLINE}")
    print("=" * 60)

    # 1. Initialize Database Schema & Seed Data
    try:
        init_db()
    except Exception as e:
        logger.error(f"Fatal error initializing database: {e}", exc_info=True)
        sys.exit(1)

    # 2. Validate Bot Token
    token = settings.BOT_TOKEN.strip()
    if not token or "1234567890:" in token:
        logger.warning(
            "BOT_TOKEN is not configured or is using default placeholder in .env!\n"
            "Please obtain a token from @BotFather, set BOT_TOKEN in .env, and re-run start.ps1."
        )
        print("\n⚠️  BOT_TOKEN missing in .env. Exiting gracefully.")
        sys.exit(0)

    # 3. Build Application
    app = (
        ApplicationBuilder()
        .token(token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Global Error Handler
    app.add_error_handler(error_handler)

    # 4. Register Command Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("upload_daily", upload_daily_command))

    # 5. Register Customer Callbacks
    app.add_handler(CallbackQueryHandler(handle_customer_home, pattern="^cust_home$"))
    app.add_handler(CallbackQueryHandler(handle_browse_plans, pattern="^cust_buy$"))
    app.add_handler(CallbackQueryHandler(handle_plan_selected, pattern="^plan_select:"))
    app.add_handler(CallbackQueryHandler(handle_quantity_selected, pattern="^order_qty:"))
    app.add_handler(CallbackQueryHandler(handle_qty_out_of_stock, pattern="^qty_out_of_stock:"))
    app.add_handler(CallbackQueryHandler(handle_order_confirm, pattern="^order_confirm:"))
    app.add_handler(CallbackQueryHandler(handle_submit_utr_button, pattern="^pay_submit_utr:"))
    app.add_handler(CallbackQueryHandler(handle_cancel_utr_button, pattern="^pay_cancel_utr:"))
    app.add_handler(CallbackQueryHandler(handle_check_payment_status, pattern="^pay_check_status:"))
    app.add_handler(CallbackQueryHandler(handle_order_cancel, pattern="^order_cancel:"))
    app.add_handler(CallbackQueryHandler(handle_my_subscriptions, pattern="^cust_subs$"))
    app.add_handler(CallbackQueryHandler(handle_view_subscription, pattern="^sub_view:"))
    app.add_handler(CallbackQueryHandler(handle_renew_subscription_prompt, pattern="^(cust_renew|sub_renew:)"))
    app.add_handler(CallbackQueryHandler(handle_payment_history, pattern="^cust_history$"))
    app.add_handler(CallbackQueryHandler(handle_customer_support, pattern="^cust_support$"))

    # 6. Register Admin Callbacks
    app.add_handler(CallbackQueryHandler(handle_admin_home, pattern="^admin_home$"))
    app.add_handler(CallbackQueryHandler(handle_admin_dashboard, pattern="^admin_dashboard$"))
    app.add_handler(CallbackQueryHandler(handle_admin_sales_report, pattern="^admin_sales_report$"))
    app.add_handler(CallbackQueryHandler(handle_admin_inventory_menu, pattern="^(admin_inventory_menu|admin_inventory_stats)$"))
    app.add_handler(CallbackQueryHandler(handle_admin_upload_regular_menu, pattern="^admin_upload_regular_menu$"))
    app.add_handler(CallbackQueryHandler(handle_admin_upload_daily_menu, pattern="^admin_upload_daily_menu$"))
    app.add_handler(CallbackQueryHandler(handle_upload_daily_txt_prompt, pattern="^admin_upload_daily_txt$"))
    app.add_handler(CallbackQueryHandler(handle_upload_daily_csv_prompt, pattern="^admin_upload_daily_csv$"))
    app.add_handler(CallbackQueryHandler(handle_upload_txt_prompt, pattern="^admin_upload_txt$"))
    app.add_handler(CallbackQueryHandler(handle_upload_csv_prompt, pattern="^admin_upload_csv$"))
    app.add_handler(CallbackQueryHandler(handle_credential_manager_menu, pattern="^(admin_cred_menu|admin_search_ip)$"))
    app.add_handler(
        CallbackQueryHandler(
            lambda u, c: handle_cred_change_prompt(u, c, "password"),
            pattern="^cred_change_pass:",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            lambda u, c: handle_cred_change_prompt(u, c, "username"),
            pattern="^cred_change_user:",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            lambda u, c: handle_cred_change_prompt(u, c, "host"),
            pattern="^cred_change_host:",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            lambda u, c: handle_cred_change_prompt(u, c, "port"),
            pattern="^cred_change_port:",
        )
    )
    app.add_handler(CallbackQueryHandler(handle_expired_proxies_menu, pattern="^admin_expired_menu$"))
    app.add_handler(CallbackQueryHandler(handle_expired_resale_action, pattern="^exp_resale:"))
    app.add_handler(CallbackQueryHandler(handle_expired_disable_action, pattern="^exp_disable:"))
    app.add_handler(CallbackQueryHandler(handle_admin_customers_menu, pattern="^admin_customers_menu$"))
    app.add_handler(CallbackQueryHandler(handle_admin_payments_menu, pattern="^admin_payments_menu$"))
    app.add_handler(CallbackQueryHandler(handle_pay_approve_callback, pattern="^pay_approve:"))
    app.add_handler(CallbackQueryHandler(handle_pay_reject_callback, pattern="^pay_reject:"))
    app.add_handler(CallbackQueryHandler(handle_pay_recover_callback, pattern="^pay_recover:"))
    app.add_handler(CallbackQueryHandler(handle_admin_settings_menu, pattern="^admin_settings_menu$"))
    app.add_handler(CallbackQueryHandler(handle_set_price_plan_callback, pattern="^set_price_plan:"))
    app.add_handler(CallbackQueryHandler(handle_set_upi_id_callback, pattern="^set_upi_id$"))

    # Marketing & Broadcast Callbacks
    app.add_handler(CallbackQueryHandler(handle_admin_marketing_menu, pattern="^admin_marketing_menu$"))
    app.add_handler(CallbackQueryHandler(handle_mkt_announcement_prompt, pattern="^mkt_announcement$"))
    app.add_handler(CallbackQueryHandler(handle_mkt_promotion_prompt, pattern="^mkt_promotion$"))
    app.add_handler(CallbackQueryHandler(handle_mkt_banner_menu, pattern="^mkt_banner$"))
    app.add_handler(CallbackQueryHandler(handle_mkt_banner_upload_prompt, pattern="^mkt_banner_upload$"))
    app.add_handler(CallbackQueryHandler(handle_mkt_btn_add, pattern="^mkt_btn_add:"))
    app.add_handler(CallbackQueryHandler(handle_mkt_btn_skip, pattern="^mkt_btn_skip:"))
    app.add_handler(CallbackQueryHandler(handle_mkt_confirm_send, pattern="^mkt_confirm_send:"))
    app.add_handler(CallbackQueryHandler(handle_mkt_banner_history, pattern="^mkt_banner_history$"))
    app.add_handler(CallbackQueryHandler(handle_mkt_view_banner, pattern="^mkt_view_banner:"))
    app.add_handler(CallbackQueryHandler(handle_mkt_delete_prompt, pattern="^mkt_del_prompt:"))
    app.add_handler(CallbackQueryHandler(handle_mkt_delete_confirm, pattern="^mkt_del_confirm:"))

    # 7. Document Upload Handler (TXT / CSV)
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document_upload))

    # 8. Admin Banner Photo Handler
    app.add_handler(MessageHandler(filters.PHOTO, handle_admin_photo_upload))

    # 9. WebApp Data Handler (Mini App UTR submission)
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_customer_web_app_data))

    # 10. User Text Input Handler (UTR, Admin state inputs)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_text_input))

    # 11. Start Polling
    logger.info("Starting Telegram polling for local development...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
