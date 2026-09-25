"""Auth endpoints (Phase 2): login, current user."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import LoginRequest, TokenResponse, UserOut
from ..security import CurrentUser, create_access_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        # uniform error — don't reveal whether the email exists
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password.")
    return TokenResponse(access_token=create_access_token(user), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
