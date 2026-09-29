"""Deny-by-default authorization resolved server-side on every request (D008).

Hiding a button is not authorization. Every route that touches case data resolves
``(session user -> membership -> organization -> case)`` here. A case belonging to
another organization returns 404, not 403, so existence is not disclosed.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.models.casework import Case
from app.models.identity import Membership, Organization, User

SESSION_USER_KEY = "user_id"


def current_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> User:
    raw = request.session.get(SESSION_USER_KEY)
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unauthenticated")
    try:
        user_id = uuid.UUID(raw)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unauthenticated") from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unauthenticated")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def user_organizations(db: Session, user: User) -> list[Organization]:
    rows = db.execute(
        select(Organization)
        .join(Membership, Membership.organization_id == Organization.id)
        .where(Membership.user_id == user.id)
    ).scalars()
    return list(rows)


def current_organization(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Organization:
    orgs = user_organizations(db, user)
    if not orgs:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no organization membership")
    return orgs[0]


CurrentOrganization = Annotated[Organization, Depends(current_organization)]


def authorized_case(
    case_id: uuid.UUID,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Case:
    org_ids = [org.id for org in user_organizations(db, user)]
    case = db.execute(
        select(Case).where(Case.id == case_id, Case.organization_id.in_(org_ids))
    ).scalar_one_or_none()
    if case is None:
        # 404 rather than 403: a foreign case must not be distinguishable from a
        # non-existent one.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
    return case


AuthorizedCase = Annotated[Case, Depends(authorized_case)]
