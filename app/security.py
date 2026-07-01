"""Password hashing and JWT token helpers.

Password hashing uses ``bcrypt`` directly rather than ``passlib``: passlib is
effectively unmaintained and its bcrypt backend breaks against modern bcrypt
releases. Calling bcrypt directly is a few lines, fully supported, and avoids
the dependency-rot footgun.
"""

from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from app.config import settings

# bcrypt only considers the first 72 bytes of the input and raises on longer
# values. We truncate explicitly so hashing and verification stay consistent and
# a very long password can never trigger a 500.
_BCRYPT_MAX_BYTES = 72


def _encode(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    """Return a salted bcrypt hash for ``password``."""
    return bcrypt.hashpw(_encode(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Return ``True`` if ``password`` matches the stored ``hashed`` value."""
    return bcrypt.checkpw(_encode(password), hashed.encode("utf-8"))


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    """Mint a signed JWT whose ``sub`` claim identifies the authenticated user.

    An ``exp`` claim is always set so tokens cannot live forever; ``python-jose``
    validates it automatically on decode.
    """
    expire = datetime.now(UTC) + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> str | None:
    """Return the token ``sub`` if the token is valid, otherwise ``None``.

    The algorithm list is pinned to prevent ``alg=none`` / algorithm-confusion
    attacks, and any decoding failure (bad signature, expired, malformed) is
    collapsed to ``None`` for the caller to turn into a 401.
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) and subject else None
