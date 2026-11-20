"""
Tests for credential encryption, decryption, and key management.
"""

import pytest
from services.crypto_service import CryptoService, crypto_service


def test_credential_encryption_and_decryption():
    raw_password = "SuperSecretProxyPassword123!@#"
    ciphertext = crypto_service.encrypt(raw_password)

    # Must be encrypted (not plaintext)
    assert ciphertext != raw_password
    assert len(ciphertext) > len(raw_password)

    # Decrypted value must match original
    decrypted = crypto_service.decrypt(ciphertext)
    assert decrypted == raw_password


def test_encryption_empty_and_none_values():
    assert crypto_service.encrypt(None) == ""
    assert crypto_service.decrypt("") == ""


def test_invalid_token_handling():
    with pytest.raises(ValueError, match="Invalid encryption token or key mismatch"):
        crypto_service.decrypt("invalid-non-fernet-token")


def test_different_keys_cannot_decrypt():
    key1 = CryptoService.generate_new_key()
    key2 = CryptoService.generate_new_key()

    service1 = CryptoService(key=key1)
    service2 = CryptoService(key=key2)

    secret = "ConfidentialData"
    token = service1.encrypt(secret)

    with pytest.raises(ValueError):
        service2.decrypt(token)


def test_multifernet_fallback_keys():
    old_key = CryptoService.generate_new_key()
    new_key = CryptoService.generate_new_key()

    old_service = CryptoService(key=old_key)
    secret = "SecretWithOldKey"
    token = old_service.encrypt(secret)

    # Multi-key service with new primary and old fallback
    multi_service = CryptoService(key=new_key, fallback_keys=[old_key])
    assert multi_service.decrypt(token) == secret
