"""
Tatkal Proxy - Inventory Service
Handles TXT/CSV batch importing, encryption at rest, duplicate detection,
and formatted customer delivery string generation.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Dict, List, Any, Tuple, Union
from sqlalchemy.orm import Session

from database.models import Inventory, DailyInventory, InventoryStatus, AdminLog
from database.crud import create_admin_log, ip_exists_in_any_inventory
from services.crypto_service import crypto_service
from utils.validators import parse_proxy_line, is_special_ip

logger = logging.getLogger("TatkalProxy.InventoryService")


class InventoryImportResult:
    def __init__(self):
        self.total_lines: int = 0
        self.valid_count: int = 0
        self.imported_count: int = 0
        self.duplicate_file_count: int = 0
        self.duplicate_db_count: int = 0
        self.special_count: int = 0
        self.standard_count: int = 0
        self.errors: List[str] = []

    @property
    def total_errors(self) -> int:
        return len(self.errors)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_lines": self.total_lines,
            "valid_count": self.valid_count,
            "imported_count": self.imported_count,
            "duplicate_file_count": self.duplicate_file_count,
            "duplicate_db_count": self.duplicate_db_count,
            "special_count": self.special_count,
            "standard_count": self.standard_count,
            "errors": self.errors[:10],  # Return up to first 10 errors for display
            "total_errors": len(self.errors),
        }


def process_txt_inventory(
    db: Session, content: str, admin_id: int | None = None
) -> InventoryImportResult:
    """
    Parse and import proxies from raw TXT file string.
    Expected format per line: ip:port:username:password
    """
    result = InventoryImportResult()
    lines = content.strip().splitlines()
    result.total_lines = len(lines)

    seen_ips_in_file = set()
    to_insert: List[Inventory] = []

    for idx, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        valid, data, err_msg = parse_proxy_line(line)
        if not valid:
            result.errors.append(f"Line {idx}: {err_msg}")
            continue

        result.valid_count += 1
        ip = data["ip"]

        if ip in seen_ips_in_file:
            result.duplicate_file_count += 1
            result.errors.append(f"Line {idx}: Duplicate IP '{ip}' inside file")
            continue
        seen_ips_in_file.add(ip)

        # Check existing in DB across all tables
        if ip_exists_in_any_inventory(db, ip):
            result.duplicate_db_count += 1
            result.errors.append(f"Line {idx}: IP '{ip}' already exists in database")
            continue

        # Encrypt username and password
        user_enc = crypto_service.encrypt(data["username"])
        pass_enc = crypto_service.encrypt(data["password"])

        inv_item = Inventory(
            ip=ip,
            host=data["host"],
            port=data["port"],
            username_enc=user_enc,
            password_enc=pass_enc,
            is_special=data["is_special"],
            status=InventoryStatus.AVAILABLE.value,
            credentials_updated=True,
        )
        to_insert.append(inv_item)

        if data["is_special"]:
            result.special_count += 1
        else:
            result.standard_count += 1

    if to_insert:
        db.add_all(to_insert)
        db.flush()
        result.imported_count = len(to_insert)

        create_admin_log(
            db=db,
            admin_id=admin_id,
            action="INVENTORY_IMPORT_TXT",
            target_type="inventory",
            target_id=f"{result.imported_count}_items",
            details=f"Imported {result.imported_count} proxies (Special: {result.special_count}, Standard: {result.standard_count})",
        )

    logger.info(
        f"TXT Import complete: {result.imported_count} imported, {result.duplicate_db_count} db duplicates, {len(result.errors)} errors."
    )
    return result


def process_csv_inventory(
    db: Session, content: str, admin_id: int | None = None
) -> InventoryImportResult:
    """
    Parse and import proxies from raw CSV file string.
    Supports CSV with or without headers (ip, port, username, password, host).
    """
    result = InventoryImportResult()
    reader = csv.reader(io.StringIO(content.strip()))
    lines = list(reader)
    result.total_lines = len(lines)

    if not lines:
        return result

    # Check if first line is header
    first_row = lines[0]
    has_header = False
    if any(h.lower() in ["ip", "host", "port", "user", "username", "password"] for h in first_row):
        has_header = True
        header = [h.strip().lower() for h in first_row]
        data_rows = lines[1:]
    else:
        data_rows = lines
        header = ["ip", "port", "username", "password"]

    seen_ips_in_file = set()
    to_insert: List[Inventory] = []

    for idx, row in enumerate(data_rows, start=2 if has_header else 1):
        if not row or not any(row):
            continue

        # Extract values
        if has_header:
            row_dict = {header[i]: row[i].strip() for i in range(min(len(header), len(row)))}
            ip = row_dict.get("ip", "")
            port_val = row_dict.get("port", "8080")
            user = row_dict.get("user") or row_dict.get("username", "")
            pwd = row_dict.get("password") or row_dict.get("pass", "")
            host = row_dict.get("host", ip)
        else:
            if len(row) < 4:
                result.errors.append(f"Row {idx}: Expected at least 4 columns, got {len(row)}")
                continue
            ip = row[0].strip()
            port_val = row[1].strip()
            user = row[2].strip()
            pwd = row[3].strip()
            host = row[4].strip() if len(row) > 4 else ip

        # Construct single line for parser validation
        synth_line = f"{ip}:{port_val}:{user}:{pwd}"
        valid, data, err_msg = parse_proxy_line(synth_line)
        if not valid:
            result.errors.append(f"Row {idx}: {err_msg}")
            continue

        result.valid_count += 1
        clean_ip = data["ip"]

        if clean_ip in seen_ips_in_file:
            result.duplicate_file_count += 1
            result.errors.append(f"Row {idx}: Duplicate IP '{clean_ip}' inside file")
            continue
        seen_ips_in_file.add(clean_ip)

        # Check DB duplicate across all tables
        if ip_exists_in_any_inventory(db, clean_ip):
            result.duplicate_db_count += 1
            result.errors.append(f"Row {idx}: IP '{clean_ip}' already in database")
            continue

        user_enc = crypto_service.encrypt(user)
        pass_enc = crypto_service.encrypt(pwd)

        inv_item = Inventory(
            ip=clean_ip,
            host=host or clean_ip,
            port=data["port"],
            username_enc=user_enc,
            password_enc=pass_enc,
            is_special=data["is_special"],
            status=InventoryStatus.AVAILABLE.value,
            credentials_updated=True,
        )
        to_insert.append(inv_item)

        if data["is_special"]:
            result.special_count += 1
        else:
            result.standard_count += 1

    if to_insert:
        db.add_all(to_insert)
        db.flush()
        result.imported_count = len(to_insert)

        create_admin_log(
            db=db,
            admin_id=admin_id,
            action="INVENTORY_IMPORT_CSV",
            target_type="inventory",
            target_id=f"{result.imported_count}_items",
            details=f"Imported {result.imported_count} CSV proxies (Special: {result.special_count}, Standard: {result.standard_count})",
        )

    return result


def process_daily_txt_inventory(
    db: Session, content: str, admin_id: int | None = None
) -> InventoryImportResult:
    """
    Parse and import proxies into isolated DAILY inventory from raw TXT file string.
    Expected format per line: ip:port:username:password (or ip:host:user:pass)
    """
    result = InventoryImportResult()
    lines = content.strip().splitlines()
    result.total_lines = len(lines)

    seen_ips_in_file = set()
    to_insert: List[DailyInventory] = []

    for idx, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        valid, data, err_msg = parse_proxy_line(line)
        if not valid:
            result.errors.append(f"Line {idx}: {err_msg}")
            continue

        result.valid_count += 1
        ip = data["ip"]

        if ip in seen_ips_in_file:
            result.duplicate_file_count += 1
            result.errors.append(f"Line {idx}: Duplicate IP '{ip}' inside file")
            continue
        seen_ips_in_file.add(ip)

        # Check existing in DB across both regular and daily tables
        if ip_exists_in_any_inventory(db, ip):
            result.duplicate_db_count += 1
            result.errors.append(f"Line {idx}: IP '{ip}' already exists in database")
            continue

        user_enc = crypto_service.encrypt(data["username"])
        pass_enc = crypto_service.encrypt(data["password"])

        daily_item = DailyInventory(
            ip=ip,
            host=data["host"],
            port=data["port"],
            username_enc=user_enc,
            password_enc=pass_enc,
            status=InventoryStatus.AVAILABLE.value,
        )
        to_insert.append(daily_item)

        if data["is_special"]:
            result.special_count += 1
        else:
            result.standard_count += 1

    if to_insert:
        db.add_all(to_insert)
        db.flush()
        result.imported_count = len(to_insert)

        create_admin_log(
            db=db,
            admin_id=admin_id,
            action="DAILY_INVENTORY_IMPORT_TXT",
            target_type="daily_inventory",
            target_id=f"{result.imported_count}_items",
            details=f"Imported {result.imported_count} Daily Proxies into isolated daily table.",
        )

    logger.info(
        f"Daily TXT Import complete: {result.imported_count} imported, {result.duplicate_db_count} db duplicates, {len(result.errors)} errors."
    )
    return result


def process_daily_csv_inventory(
    db: Session, content: str, admin_id: int | None = None
) -> InventoryImportResult:
    """
    Parse and import proxies into isolated DAILY inventory from raw CSV file string.
    Supports CSV with or without headers (ip, port, username, password, host).
    """
    result = InventoryImportResult()
    reader = csv.reader(io.StringIO(content.strip()))
    lines = list(reader)
    result.total_lines = len(lines)

    if not lines:
        return result

    first_row = lines[0]
    has_header = False
    if any(h.lower() in ["ip", "host", "port", "user", "username", "password"] for h in first_row):
        has_header = True
        header = [h.strip().lower() for h in first_row]
        data_rows = lines[1:]
    else:
        data_rows = lines
        header = ["ip", "port", "username", "password"]

    seen_ips_in_file = set()
    to_insert: List[DailyInventory] = []

    for idx, row in enumerate(data_rows, start=2 if has_header else 1):
        if not row or not any(row):
            continue

        if has_header:
            row_dict = {header[i]: row[i].strip() for i in range(min(len(header), len(row)))}
            ip = row_dict.get("ip", "")
            port_val = row_dict.get("port", "8080")
            user = row_dict.get("user") or row_dict.get("username", "")
            pwd = row_dict.get("password") or row_dict.get("pass", "")
            host = row_dict.get("host", ip)
        else:
            if len(row) < 4:
                result.errors.append(f"Row {idx}: Expected at least 4 columns, got {len(row)}")
                continue
            ip = row[0].strip()
            port_val = row[1].strip()
            user = row[2].strip()
            pwd = row[3].strip()
            host = row[4].strip() if len(row) > 4 else ip

        synth_line = f"{ip}:{port_val}:{user}:{pwd}"
        valid, data, err_msg = parse_proxy_line(synth_line)
        if not valid:
            result.errors.append(f"Row {idx}: {err_msg}")
            continue

        result.valid_count += 1
        clean_ip = data["ip"]

        if clean_ip in seen_ips_in_file:
            result.duplicate_file_count += 1
            result.errors.append(f"Row {idx}: Duplicate IP '{clean_ip}' inside file")
            continue
        seen_ips_in_file.add(clean_ip)

        if ip_exists_in_any_inventory(db, clean_ip):
            result.duplicate_db_count += 1
            result.errors.append(f"Row {idx}: IP '{clean_ip}' already in database")
            continue

        user_enc = crypto_service.encrypt(user)
        pass_enc = crypto_service.encrypt(pwd)

        daily_item = DailyInventory(
            ip=clean_ip,
            host=host or clean_ip,
            port=data["port"],
            username_enc=user_enc,
            password_enc=pass_enc,
            status=InventoryStatus.AVAILABLE.value,
        )
        to_insert.append(daily_item)

        if data["is_special"]:
            result.special_count += 1
        else:
            result.standard_count += 1

    if to_insert:
        db.add_all(to_insert)
        db.flush()
        result.imported_count = len(to_insert)

        create_admin_log(
            db=db,
            admin_id=admin_id,
            action="DAILY_INVENTORY_IMPORT_CSV",
            target_type="daily_inventory",
            target_id=f"{result.imported_count}_items",
            details=f"Imported {result.imported_count} CSV Daily Proxies into isolated daily table.",
        )

    return result


def format_proxy_delivery(inventory_item: Union[Inventory, DailyInventory]) -> str:
    """
    Format proxy exactly per prompt specification:
    ip:port:user:pass (Example: 103.10.20.30:8080:username:password)
    No extra formatting or markdown inside the proxy line.
    """
    user_plain = crypto_service.decrypt(inventory_item.username_enc, safe=True)
    pass_plain = crypto_service.decrypt(inventory_item.password_enc, safe=True)
    return f"{inventory_item.ip}:{inventory_item.port}:{user_plain}:{pass_plain}"
