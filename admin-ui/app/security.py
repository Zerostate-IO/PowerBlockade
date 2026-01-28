from __future__ import annotations

import hashlib

import bcrypt


def _prehash_if_needed(password: str) -> bytes:
    """Pre-hash passwords > 72 bytes to avoid bcrypt truncation."""
    b = password.encode("utf-8")
    if len(b) > 72:
        return hashlib.sha256(b).hexdigest().encode("utf-8")
    return b


def hash_password(password: str) -> str:
    """Hash a password using bcrypt with automatic pre-hashing for long passwords."""
    pw_bytes = _prehash_if_needed(password)
    hashed = bcrypt.hashpw(pw_bytes, bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a bcrypt hash."""
    pw_bytes = _prehash_if_needed(password)
    try:
        return bcrypt.checkpw(pw_bytes, password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False
