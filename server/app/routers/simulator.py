"""Explicitly enabled local input; delegates to the real matching handler."""
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from ..parking import handle_event, ParkingError
from .parking import get_db

router = APIRouter(tags=['로컬 시뮬레이터 입력'])


@router.post('/simulator/events', include_in_schema=False)
def simulate_event(body: dict, request: Request, db: Session = Depends(get_db)):
    if not request.app.state.settings.simulator_enabled:
        raise ParkingError(404, 'NOT_FOUND', '로컬 관측 입력이 비활성화되어 있습니다.')
    status = handle_event(db, request.app.state.settings, body.get('camera_id',''), body,
                          datetime.now(ZoneInfo(request.app.state.settings.timezone)))
    return {'event_id':body.get('event_id'), 'status':status}
