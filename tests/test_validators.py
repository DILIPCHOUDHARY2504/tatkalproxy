"""
Tests for IPv4 validation, special IP classification, port checking, and proxy line parsing.
"""

from utils.validators import is_valid_ipv4, is_special_ip, is_valid_port, parse_proxy_line


def test_ipv4_validation():
    assert is_valid_ipv4("103.10.20.30") is True
    assert is_valid_ipv4("192.168.1.1") is True
    assert is_valid_ipv4("256.1.1.1") is False
    assert is_valid_ipv4("abc.def.ghi.jkl") is False
    assert is_valid_ipv4("127.0.0.1") is False  # Loopback excluded
    assert is_valid_ipv4("") is False


def test_special_ip_classification():
    # Matches 103.x.x.x
    assert is_special_ip("103.10.20.30") is True
    assert is_special_ip("103.255.255.255") is True
    assert is_special_ip("103.0.0.1") is True

    # Standard IPs (non-103)
    assert is_special_ip("45.33.22.11") is False
    assert is_special_ip("104.10.20.30") is False
    assert is_special_ip("185.220.101.5") is False


def test_port_validation():
    assert is_valid_port(8080) is True
    assert is_valid_port(1) is True
    assert is_valid_port(65535) is True
    assert is_valid_port(0) is False
    assert is_valid_port(70000) is False
    assert is_valid_port("invalid") is False


def test_parse_proxy_line_valid():
    line = "103.10.20.30:8080:username:password"
    valid, data, err = parse_proxy_line(line)
    assert valid is True
    assert data["ip"] == "103.10.20.30"
    assert data["port"] == 8080
    assert data["username"] == "username"
    assert data["password"] == "password"
    assert data["is_special"] is True


def test_parse_proxy_line_invalid_formats():
    # Too few fields
    valid, _, err = parse_proxy_line("103.10.20.30:8080")
    assert valid is False

    # Invalid IP
    valid, _, err = parse_proxy_line("999.999.999.999:8080:user:pass")
    assert valid is False
    assert "Invalid IPv4" in err

    # Empty user
    valid, _, err = parse_proxy_line("103.10.20.30:8080::pass")
    assert valid is False
