"""Session authentication."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.authz import SESSION_USER_KEY, CurrentUser, user_organizations
from app.core.envelope import ok
from app.core.security import verify_password
from app.core.settings import Settings, get_settings
from app.db.base import get_db
from app.models.identity import User

router = APIRouter(prefix="/api/v1/auth")


class LoginRequest(BaseModel):
    """The identifier is an account name, not a mail destination.

    Strict RFC validation is deliberately not applied: it rejects the reserved
    domains (``.test``, ``.invalid``) that local demo and test accounts should
    use, and this system never sends mail.
    """

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def _looks_like_an_account(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or v.startswith("@") or v.endswith("@"):
            raise ValueError("account identifier must look like name@domain")
        return v


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    # verify_password hashes against a decoy when the user is absent, so the
    # timing and the message are the same either way (B06).
    if not verify_password(payload.password, user.password_hash if user else None):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")

    request.session.clear()
    request.session[SESSION_USER_KEY] = str(user.id)
    return ok({"id": str(user.id), "email": user.email}, settings, request.state.request_id)


@router.post("/logout")
def logout(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    request.session.clear()
    return ok({"logged_out": True}, settings, request.state.request_id)


@router.get("/me")
def me(
    request: Request,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    orgs = user_organizations(db, user)
    return ok(
        {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "organizations": [{"id": str(o.id), "name": o.name, "slug": o.slug} for o in orgs],
        },
        settings,
        request.state.request_id,
    )
