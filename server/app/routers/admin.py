"""Authenticated review endpoints, server_interface section 3.3."""
from datetime import datetime
import secrets
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from .. import parking as P
from .parking import get_db


def require_admin(request: Request, authorization: str | None = Header(default=None)):
    expected = request.app.state.settings.admin_token
    if not expected:
        raise P.ParkingError(503, 'ADMIN_NOT_CONFIGURED', '관리자 인증이 설정되지 않았습니다.')
    supplied = authorization[7:] if authorization and authorization.startswith('Bearer ') else ''
    if not secrets.compare_digest(supplied.encode('utf-8'), expected.encode('utf-8')):
        raise P.ParkingError(401, 'UNAUTHORIZED', '관리자 인증이 필요합니다.')


router = APIRouter(tags=['수꽝: 관리자 확인'], dependencies=[Depends(require_admin)])


class ResolveInput(BaseModel):
    action: Literal['assign','dismiss']
    session_id: UUID | None = None

    @model_validator(mode='after')
    def assignment_needs_session(self):
        if self.action == 'assign' and self.session_id is None:
            raise ValueError('assign requires session_id')
        if self.action == 'dismiss' and self.session_id is not None:
            raise ValueError('dismiss does not accept session_id')
        return self


@router.get('/admin/reviews')
def reviews(request: Request, status: Literal['OPEN','RESOLVED','DISMISSED'] | None = 'OPEN',
            db: Session = Depends(get_db)):
    return P.list_reviews(db, request.app.state.settings, status)


@router.get('/admin/reviews/{review_id}/crop')
def crop(review_id: UUID, db: Session = Depends(get_db)):
    return FileResponse(P.review_crop_path(db, review_id), media_type='image/jpeg')


@router.post('/admin/reviews/{review_id}/resolve')
def resolve(review_id: UUID, body: ResolveInput, request: Request, db: Session = Depends(get_db)):
    cfg = request.app.state.settings
    return P.resolve_review(db, cfg, review_id, body.action, body.session_id, datetime.now(ZoneInfo(cfg.timezone)))


@router.get('/admin/auto-assignments')
def auto_assignments(request: Request, db: Session = Depends(get_db)):
    return [{**item, 'method':'EDIT1', 'review_recommended':True, 'message':'자동 확정 · 검토 권장'}
            for item in P.list_auto_assignments(db, request.app.state.settings)]
