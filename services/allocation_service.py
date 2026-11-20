"""
Tatkal Proxy - Allocation Service
Handles atomic allocation of proxies, renewal flows, and stock availability checks.
"""

from __future__ import annotations

import logging
from typing import Tuple, Dict, Any, Optional
from sqlalchemy.orm import Session

from database.models import Order, Subscription, Inventory, DailyInventory, Plan, User, InventoryStatus
from database.crud import allocate_proxy_and_activate_subscription, get_inventory_stats
from services.inventory_service import format_proxy_delivery

logger = logging.getLogger("TatkalProxy.AllocationService")


class AllocationService:
    @staticmethod
    def check_plan_stock(db: Session, plan_id: int) -> Tuple[bool, int]:
        """
        Check if inventory is available for the given plan.
        Returns: (has_stock, available_count)
        """
        plan = db.query(Plan).filter(Plan.id == plan_id).first()
        if not plan:
            return False, 0

        # Isolated stock query for Daily Proxy plan
        if plan.code == "daily_proxy":
            count = (
                db.query(DailyInventory)
                .filter(DailyInventory.status == InventoryStatus.AVAILABLE.value)
                .count()
            )
            return (count > 0), count

        count = (
            db.query(Inventory)
            .filter(
                Inventory.status == InventoryStatus.AVAILABLE.value,
                Inventory.is_special == plan.is_special,
            )
            .count()
        )
        return (count > 0), count

    @staticmethod
    def fulfill_order(
        db: Session, order_id: int, verified_by_id: int | None = None
    ) -> Tuple[Any, Any, str]:
        """
        Atomically fulfill an order by allocating proxy (or proxies) and activating subscription(s).
        Returns: (primary_sub_or_list, primary_inv_or_list, formatted_delivery_line)
        """
        subs, items = allocate_proxy_and_activate_subscription(
            db=db, order_id=order_id, verified_by_id=verified_by_id
        )
        if isinstance(subs, list):
            primary_sub = subs[0]
            primary_inv = items[0]
            delivery_line = "\n".join(format_proxy_delivery(item) for item in items)
        else:
            primary_sub = subs
            primary_inv = items
            delivery_line = format_proxy_delivery(items)

        return primary_sub, primary_inv, delivery_line


allocation_service = AllocationService()
