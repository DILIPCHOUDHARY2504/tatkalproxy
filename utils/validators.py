"""
Tatkal Proxy - Input Validation Utilities
Validates proxy syntax, IPv4 addresses, ports, and special IP matching.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Dict, Any, Tuple


def is_valid_ipv4(ip_str: str) -> bool:
    """Validate IPv4 address format."""
    try:
        ip = ipaddress.IPv4Address(ip_str.strip())
        return not ip.is_loopback and not ip.is_multicast
    except Exception:
        return False


def is_special_ip(ip_str: str) -> bool:
    """Check if the IP belongs to the 103.x.x.x special subnet."""
    clean = ip_str.strip()
    return clean.startswith("103.")


def is_valid_port(port: int | str) -> bool:
    """Validate TCP port number range (1-65535)."""
    try:
        p = int(port)
        return 1 <= p <= 65535
    except (ValueError, TypeError):
        return False


def parse_proxy_line(line: str) -> Tuple[bool, Dict[str, Any], str]:
    """
    Parse a single proxy record line.
    Accepted formats:
    1) ip:port:user:pass (e.g. 103.10.20.30:8080:username:password)
    2) ip:host:port:user:pass
    3) Comma-separated or tab-separated equivalents

    Returns:
        (is_valid, parsed_dict, error_message)
    """
    clean_line = line.strip()
    if not clean_line or clean_line.startswith("#"):
        return False, {}, "Empty or comment line"

    # Split by colon first, or comma
    delimiters = [":", ",", "\t"]
    parts = []
    for d in delimiters:
        if d in clean_line:
            parts = [p.strip() for p in clean_line.split(d)]
            if len(parts) >= 4:
                break

    if len(parts) < 4:
        return False, {}, f"Invalid format (expected at least 4 colon-separated fields, got {len(parts)})"

    if len(parts) == 4:
        ip_candidate, port_or_host, username, password = parts[0], parts[1], parts[2], parts[3]
        ip = ip_candidate
        # Determine if second part is numeric port
        if port_or_host.isdigit():
            port = int(port_or_host)
            host = ip_candidate
        else:
            host = port_or_host
            port = 8080  # Default proxy port
    elif len(parts) >= 5:
        ip, host, port_str, username, password = parts[0], parts[1], parts[2], parts[3], parts[4]
        if not port_str.isdigit():
            return False, {}, f"Port '{port_str}' must be numeric"
        port = int(port_str)
    else:
        return False, {}, "Unable to parse proxy entry"

    if not is_valid_ipv4(ip):
        return False, {}, f"Invalid IPv4 address: '{ip}'"

    if not is_valid_port(port):
        return False, {}, f"Invalid port range: '{port}' (must be 1-65535)"

    if not username:
        return False, {}, "Username cannot be empty"

    if not password:
        return False, {}, "Password cannot be empty"

    special = is_special_ip(ip)

    return True, {
        "ip": ip,
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "is_special": special,
    }, ""


def validate_utr(utr: str | None) -> Tuple[bool, str, str]:
    """
    Validate customer-submitted UPI UTR / Transaction Reference Number.

    Requirements:
    - Reject empty input or whitespace-only input.
    - Trim leading/trailing whitespace.
    - Reject invalid characters (must be alphanumeric, no spaces, no symbols).
    - Length check: standard UPI UTR is 12 digits (accepts 8-22 alphanumeric reference IDs).

    Returns:
        (is_valid: bool, cleaned_utr: str, error_message: str)
    """
    if utr is None:
        return False, "", "UTR number cannot be empty. Please enter your 12-digit UPI reference number."

    clean = utr.strip()
    if not clean:
        return False, "", "UTR number cannot be empty. Please enter your 12-digit UPI reference number."

    # Reject invalid characters (spaces, symbols, punctuation)
    if not clean.isalnum():
        return False, "", "Invalid characters in UTR. Reference numbers must only contain letters and numbers without spaces or symbols."

    # Standard UPI reference numbers are 12 digits, banking reference IDs range between 8 and 22 characters
    if len(clean) < 8 or len(clean) > 22:
        return False, "", f"Invalid UTR length ({len(clean)} characters). Please enter your valid 12-digit UPI reference number."

    return True, clean, ""

