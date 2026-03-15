"""Encrypt/decrypt sensitive config values using Fernet (AES-128-CBC)."""
import base64
import hashlib
import os

from cryptography.fernet import Fernet


def _get_fernet():
    secret = os.environ.get('SECRET_KEY', 'fallback-dev-secret-key-change-me')
    # Derive a 32-byte key from the secret
    key = hashlib.sha256(secret.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key)
    return Fernet(fernet_key)


def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ''
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    if not ciphertext:
        return ''
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except Exception:
        return ''
