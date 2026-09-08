"""
security.py — Field-level encryption for sensitive data at rest.
Uses Fernet (AES-128-GCM) with a master key from settings.
"""
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from backend.config import settings


class EncryptionError(Exception):
    """Raised when encryption/decryption fails."""
    pass


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    master_key = settings.MASTER_KEY
    if not master_key:
        raise EncryptionError(
            "MASTER_KEY not set. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(master_key.encode())
    except Exception as e:
        raise EncryptionError(f"Invalid MASTER_KEY: {e}") from e


def encrypt_field(plaintext: str) -> bytes:
    """Encrypt a string for database storage. Returns bytes."""
    if not plaintext:
        return b""
    return _get_fernet().encrypt(plaintext.encode())


def decrypt_field(ciphertext: bytes) -> str:
    """Decrypt bytes from database. Returns plaintext string."""
    if not ciphertext:
        return ""
    try:
        return _get_fernet().decrypt(ciphertext).decode()
    except InvalidToken:
        raise EncryptionError("Decryption failed — key mismatch or corrupted data") from None
    except Exception as e:
        raise EncryptionError(f"Decryption error: {e}") from e