"""
security.py — encrypts/decrypts sensitive fields before they touch the
database (a user's app_secret, PIN, TOTP secret), and generates random
session tokens for the login cookie.

Why encrypt at all, given only trusted friends use this: if your VM or
database backup is ever compromised, plaintext broker secrets sitting
in a table would let an attacker log into your friends' real broker
accounts. Encrypting them means a DB leak alone isn't enough.
"""

import secrets

from cryptography.fernet import Fernet

from app.config import settings

_fernet = Fernet(settings.encryption_key.encode())


def encrypt(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet.decrypt(value.encode()).decode()


def generate_session_token() -> str:
    """A long random token used as the session cookie value."""
    return secrets.token_urlsafe(48)
