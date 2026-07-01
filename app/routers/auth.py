"""Authentication endpoints: register, login (token issuance), and whoami.

The original prototype declared ``OAuth2PasswordBearer(tokenUrl="token")`` but
never implemented a login route and had no notion of a stored password. These
three endpoints close that gap and make the whole auth story real.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.dependencies import AdminUser, CurrentUser, DbSession
from app.models import User
from app.schemas import Token, UserCreate, UserOut
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: DbSession) -> User:
    """Create a new reviewer account. Passwords are stored only as bcrypt hashes.

    The new account is always an ``annotator``; the role is not client-settable.
    """
    if db.query(User).filter(User.email == payload.email).first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    # role intentionally omitted → the model default (annotator) applies.
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/token", response_model=Token)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession) -> Token:
    """Exchange email + password for a short-lived JWT access token."""
    user = db.query(User).filter(User.email == form.username).first()
    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(subject=str(user.id)))


@router.get("/me", response_model=UserOut)
def read_me(current_user: CurrentUser) -> User:
    """Return the currently authenticated user."""
    return current_user


@router.get("/users", response_model=list[UserOut])
def list_users(db: DbSession, _admin: AdminUser) -> list[User]:
    """List all users. Admin-only, the platform's oversight view."""
    return db.query(User).order_by(User.id).all()
