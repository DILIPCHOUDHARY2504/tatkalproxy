"""
Tests for TXT/CSV inventory import, duplicate detection, and customer delivery format.
"""

from database.models import Inventory, InventoryStatus
from services.inventory_service import (
    process_txt_inventory,
    process_csv_inventory,
    format_proxy_delivery,
)


def test_txt_inventory_import_and_deduplication(db_session, test_admin):
    txt_content = """
    # Sample Import File
    103.10.20.30:8080:user1:pass1
    45.33.22.11:3128:user2:pass2
    103.10.20.30:8080:duplicate_in_file:pass
    invalid_proxy_line
    """
    res = process_txt_inventory(db_session, txt_content, admin_id=test_admin.id)

    assert res.total_lines == 5
    assert res.imported_count == 2
    assert res.duplicate_file_count == 1
    assert res.special_count == 1
    assert res.standard_count == 1
    assert res.total_errors == 2

    # Check imported record in DB
    special_item = db_session.query(Inventory).filter(Inventory.ip == "103.10.20.30").first()
    assert special_item is not None
    assert special_item.is_special is True
    assert special_item.status == InventoryStatus.AVAILABLE.value

    # Check delivered format
    delivery_str = format_proxy_delivery(special_item)
    assert delivery_str == "103.10.20.30:8080:user1:pass1"


def test_database_duplicate_detection(db_session, test_admin):
    # First import
    content1 = "103.50.60.70:8080:firstuser:firstpass"
    res1 = process_txt_inventory(db_session, content1, admin_id=test_admin.id)
    assert res1.imported_count == 1

    # Second import containing same IP
    content2 = "103.50.60.70:8080:seconduser:secondpass"
    res2 = process_txt_inventory(db_session, content2, admin_id=test_admin.id)
    assert res2.imported_count == 0
    assert res2.duplicate_db_count == 1


def test_csv_inventory_import(db_session, test_admin):
    csv_content = """ip,port,username,password,host
    103.99.88.77,8080,csvuser1,csvpass1,103.99.88.77
    55.66.77.88,3128,csvuser2,csvpass2,55.66.77.88
    """
    res = process_csv_inventory(db_session, csv_content, admin_id=test_admin.id)
    assert res.imported_count == 2
    assert res.special_count == 1
    assert res.standard_count == 1
