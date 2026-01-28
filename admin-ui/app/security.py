from __future__ import annotations

from passlib.context import CryptContext
import hashlib


_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    # bcrypt has a 72-byte input limit; to avoid surprises with long passwords,
    # hash the password first if needed.
    b = password.encode("utf-8")
    if len(b) > 72:
        password = hashlib.sha256(b).hexdigest()
    return _pwd.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    b = password.encode("utf-8")
    if len(b) > 72:
        password = hashlib.sha256(b).hexdigest()
    return _pwd.verify(password, password_hash)
