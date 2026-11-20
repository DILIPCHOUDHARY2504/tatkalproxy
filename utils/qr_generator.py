"""
Tatkal Proxy - UPI QR Generator
Generates dynamic UPI QR codes with order references and exact amounts.
"""

from __future__ import annotations

import io
import urllib.parse
from pathlib import Path
import qrcode
from qrcode.image.pil import PilImage

from config import settings


def generate_upi_uri(
    upi_id: str,
    payee_name: str,
    amount: float,
    order_code: str,
    currency: str = "INR",
) -> str:
    """Construct standard UPI URI string."""
    encoded_name = urllib.parse.quote(payee_name)
    encoded_note = urllib.parse.quote(f"TatkalProxy {order_code}")
    formatted_amount = f"{amount:.2f}"

    return (
        f"upi://pay?pa={upi_id}&pn={encoded_name}"
        f"&am={formatted_amount}&cu={currency}&tn={encoded_note}"
    )


def generate_upi_qr_bytes(
    upi_id: str,
    payee_name: str,
    amount: float,
    order_code: str,
) -> bytes:
    """Generate PNG bytes of UPI QR code."""
    uri = generate_upi_uri(upi_id, payee_name, amount, order_code)
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(uri)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def save_upi_qr_file(
    upi_id: str,
    payee_name: str,
    amount: float,
    order_code: str,
    output_path: Path,
) -> Path:
    """Generate and save PNG QR code file to disk."""
    png_bytes = generate_upi_qr_bytes(upi_id, payee_name, amount, order_code)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(png_bytes)
    return output_path
