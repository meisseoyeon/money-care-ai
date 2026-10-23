from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthPrincipal, get_current_user
from app.db.session import get_db
from app.supporters import service
from app.users.roles import user_role


def no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(tags=["supporters"], dependencies=[Depends(no_store)])
DB = Annotated[Session, Depends(get_db)]
Current = Annotated[AuthPrincipal, Depends(get_current_user)]
Identifier = Annotated[int, Path(gt=0, le=9223372036854775807)]


def require_role(principal, role):
    if user_role(principal.user.user_id) != role:
        raise HTTPException(403, "이 기능을 사용할 권한이 없어요.")
    return principal.user.user_id


@router.get("/supporter-links")
def links(db: DB, principal: Current):
    return service.list_links(db, require_role(principal, "OWNER"))


@router.get("/alert-shares")
def shares(db: DB, principal: Current):
    return service.list_shares(db, require_role(principal, "OWNER"))


@router.get("/shared-alerts")
def shared_alerts(db: DB, principal: Current):
    return service.list_shared_alerts(db, require_role(principal, "SUPPORTER"))


@router.post("/alert-shares/{share_id}/revoke")
def revoke_share(share_id: Identifier, db: DB, principal: Current):
    result = service.revoke_share(db, require_role(principal, "OWNER"), share_id)
    db.commit()
    return result


@router.post("/supporter-links/{link_id}/revoke")
def revoke_link(link_id: Identifier, db: DB, principal: Current):
    result = service.revoke_link(db, require_role(principal, "OWNER"), link_id)
    db.commit()
    return result
