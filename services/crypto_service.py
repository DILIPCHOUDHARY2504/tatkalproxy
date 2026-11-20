"""
Tatkal Proxy - Cryptography Service
Handles symmetric encryption and decryption of sensitive proxy credentials
using Fernet and MultiFernet for seamless multi-key and rotation support.
"""

from __future__ import annotations

import logging
from typing import List, Set
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from config import settings

logger = logging.getLogger("TatkalProxy.Crypto")

# Known default development fallback key
DEFAULT_FALLBACK_KEY = "uKz8h6w_xN3qJ8yD-Vb7F3z6Q2o0M8w4P5s1L7r4E2I="


class CryptoService:
    def __init__(self, key: str | None = None, fallback_keys: List[str] | None = None):
        self._keys: List[str] = []
        fernets: List[Fernet] = []
        seen_keys: Set[str] = set()

        primary_key = key or settings.ENCRYPTION_KEY
        candidate_keys = [primary_key]
        if fallback_keys:
            candidate_keys.extend(fallback_keys)
        candidate_keys.append(DEFAULT_FALLBACK_KEY)

        for raw_k in candidate_keys:
            if not raw_k or raw_k in seen_keys:
                continue
            try:
                k_bytes = raw_k.encode("utf-8") if isinstance(raw_k, str) else raw_k
                f = Fernet(k_bytes)
                fernets.append(f)
                seen_keys.add(raw_k)
                self._keys.append(raw_k)
            except Exception as e:
                logger.debug(f"Skipping invalid key candidate: {e}")

        if not fernets:
            generated = Fernet.generate_key().decode()
            fernets.append(Fernet(generated.encode()))
            self._keys.append(generated)
            logger.warning("No valid encryption keys provided. Using newly generated key.")

        self._multi = MultiFernet(fernets)

    def encrypt(self, plain_text: str | None) -> str:
        """Encrypt plain text using the primary encryption key."""
        if plain_text is None:
            return ""
        try:
            token = self._multi.encrypt(plain_text.encode("utf-8"))
            return token.decode("utf-8")
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise ValueError(f"Could not encrypt data: {e}")

    def decrypt(self, encrypted_text: str | None, safe: bool = False) -> str:
        """
        Decrypt ciphertext using MultiFernet (trying primary key, then fallback keys).
        If safe=True, returns fallback error string instead of raising.
        """
        if not encrypted_text:
            return ""

        clean_text = encrypted_text.strip()
        try:
            decrypted = self._multi.decrypt(clean_text.encode("utf-8"))
            return decrypted.decode("utf-8")
        except InvalidToken:
            logger.error("Failed to decrypt: Invalid token or wrong encryption key across all available keys.")
            if safe:
                return "[ENCRYPTED_CREDENTIAL_ERROR]"
            raise ValueError("Invalid encryption token or key mismatch.")
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            if safe:
                return "[DECRYPTION_FAILED]"
            raise ValueError(f"Could not decrypt data: {e}")

    def rotate(self, token: str) -> str:
        """Re-encrypt ciphertext with the current primary key."""
        try:
            rotated = self._multi.rotate(token.encode("utf-8"))
            return rotated.decode("utf-8")
        except Exception as e:
            logger.warning(f"Could not rotate token: {e}")
            return token

    @staticmethod
    def generate_new_key() -> str:
        """Helper to generate a new valid Fernet key."""
        return Fernet.generate_key().decode("utf-8")


# Global singleton instance
crypto_service = CryptoService()
