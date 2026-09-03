"""Real authentication: PBKDF2-SHA256 password hashing (stdlib `hashlib`, no
plaintext ever stored), JWT session tokens (PyJWT), three roles.

Secret key comes from AERIONX_JWT_SECRET; a random one is generated at process
start if unset — meaning tokens issued in one process are invalid after a
restart unless the env var is set. That's the honest tradeoff of not hardcoding
a secret: documented in SECURITY.md, not hidden.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import jwt

PBKDF2_ITERATIONS = 600_000  # OWASP 2023 minimum recommendation for PBKDF2-HMAC-SHA256
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_SECONDS = 8 * 3600

_SECRET_KEY = os.environ.get("AERIONX_JWT_SECRET") or secrets.token_hex(32)
if "AERIONX_JWT_SECRET" not in os.environ:
    import warnings
    warnings.warn(
        "AERIONX_JWT_SECRET not set — using a random per-process secret. "
        "All sessions will be invalidated on restart. Set this env var for "
        "any deployment that needs to survive a process restart.",
        stacklevel=2,
    )


class Role(str, Enum):
    ADMIN = "ADMIN"
    ENGINEER = "ENGINEER"
    OPERATOR = "OPERATOR"


@dataclass
class User:
    user_id: str
    username: str
    role: Role


def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS)
    return digest.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    candidate, _ = hash_password(password, salt)
    return secrets.compare_digest(candidate, password_hash)


def create_user(conn: sqlite3.Connection, username: str, password: str, role: Role) -> User:
    existing = conn.execute("SELECT user_id FROM users WHERE username = ?", (username,)).fetchone()
    if existing:
        raise ValueError(f"Username already exists: {username}")
    password_hash, salt = hash_password(password)
    user_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO users (user_id, username, password_hash, salt, role, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, username, password_hash, salt, role.value, time.time()),
    )
    conn.commit()
    return User(user_id=user_id, username=username, role=role)


def authenticate(conn: sqlite3.Connection, username: str, password: str) -> Optional[User]:
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        return None
    if not verify_password(password, row["password_hash"], row["salt"]):
        return None
    return User(user_id=row["user_id"], username=row["username"], role=Role(row["role"]))


def issue_token(user: User) -> str:
    payload = {
        "sub": user.user_id,
        "username": user.username,
        "role": user.role.value,
        "exp": time.time() + JWT_EXPIRY_SECONDS,
        "iat": time.time(),
    }
    return jwt.encode(payload, _SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[User]:
    try:
        payload = jwt.decode(token, _SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    return User(user_id=payload["sub"], username=payload["username"], role=Role(payload["role"]))


ROLE_HIERARCHY = {Role.OPERATOR: 0, Role.ENGINEER: 1, Role.ADMIN: 2}


def role_at_least(user_role: Role, required: Role) -> bool:
    return ROLE_HIERARCHY[user_role] >= ROLE_HIERARCHY[required]
