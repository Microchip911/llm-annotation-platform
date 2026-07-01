"""Reusable FastAPI dependencies: DB session, current user, and role guards.

Centralising these here keeps the routers declarative: a handler simply asks
for a ``CurrentUser`` and trusts that a valid, authenticated ``User`` row has
already been resolved (or a 401 raised).
"""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Role, User
from app.security import decode_access_token

# ``tokenUrl`` points at the real login route so the Swagger "Authorize" button
# works end to end. The original prototype pointed it at a non-existent "token".
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    token: Annotated[str, Depends(oauth2_scheme)],
) -> User:
    """Resolve the bearer token to the concrete ``User`` it identifies."""
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    subject = decode_access_token(token)
    if subject is None or not subject.isdigit():
        raise credentials_error

    user = db.get(User, int(subject))
    if user is None:
        raise credentials_error
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(current_user: CurrentUser) -> User:
    """Dependency that allows only admins through."""
    if current_user.role != Role.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user


AdminUser = Annotated[User, Depends(require_admin)]
