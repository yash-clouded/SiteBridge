"""JWT auth with a role claim, plus FastAPI dependencies (Phase 2).

The role hierarchy lives ONLY here (`users.role` → token claim → guards).
It is never coupled to WBS levels: guards answer "which functions may
this role access", never "which level is this user assigned to".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Callable

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Role, User

bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "name": user.full_name,
        "role": user.role,  # role claim — drives client-side nav; server re-checks the DB
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def require_roles(*roles: Role) -> Callable:
    """Dependency factory: allow only the given roles.

    e.g. `Depends(require_roles(Role.PLANNER))` on schedule import.
    Authorization is checked against the DB role, not the token claim,
    so demotions take effect immediately.
    """
    allowed = {r.value for r in roles}

    def _dep(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Role '{user.role}' cannot perform this action (requires {sorted(allowed)})",
            )
        return user

    return _dep


ROLE_GROUPS: dict[str, tuple[Role, ...]] = {
    "submit": (Role.SITE_OPERATIVES, Role.CONTRACTOR, Role.SITE_ENGINEER, Role.DISCIPLINE_ENGINEER, Role.FIELD),
    "review": (Role.PLANNER, Role.SITE_ENGINEER, Role.DISCIPLINE_ENGINEER),
    "management": (Role.CLIENT, Role.PROJECT_MANAGER, Role.PM),
    "schedule_admin": (Role.PLANNER,),
    "read_all": (
        Role.CLIENT, Role.PROJECT_MANAGER, Role.CONTRACTOR,
        Role.SITE_ENGINEER, Role.SITE_OPERATIVES,
        Role.PLANNER, Role.DISCIPLINE_ENGINEER, Role.FIELD, Role.PM,
    ),
}

def roles_for(group: str) -> Callable:
    """Return a FastAPI dependency for a named business permission group."""
    try:
        return require_roles(*ROLE_GROUPS[group])
    except KeyError as exc:
        raise ValueError(f"Unknown role group: {group}") from exc

CurrentUser = Annotated[User, Depends(get_current_user)]
