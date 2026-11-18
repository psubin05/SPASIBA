"""Subin map APIs. Uses the same DB as Suin's matching/parking APIs."""
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from ..models_map import QrLocation, ParkingSlot
from ..map_service import read_map, sample_data, ROOT
from ..map_route import route
from ..parking import ParkingError
from .parking import get_db

router = APIRouter(tags=['떵개: QR · 경로 · 지도'])


@router.get('/qr/{location_id}')
def qr(location_id: str, db: Session = Depends(get_db)):
    item = db.get(QrLocation, location_id)
    if item is None:
        raise ParkingError(404, 'NOT_FOUND', 'QR을 다시 스캔해주세요.')
    return {key:getattr(item,key) for key in ('location_id','name','floor','node_id')}


@router.get('/map')
def map_data(floor: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    data = read_map(db, floor)
    return {key:data[key] for key in ('floor','nodes','edges','slots')}


@router.get('/route')
def walking_route(origin: str = Query(..., alias='from', min_length=1),
                  destination: str = Query(..., alias='to', min_length=1), db: Session = Depends(get_db)):
    start, end = db.get(QrLocation, origin), db.get(ParkingSlot, destination)
    if start is None or end is None:
        raise ParkingError(404, 'NOT_FOUND', '출발 QR 또는 도착 주차면을 찾을 수 없습니다.')
    data = read_map(db, start.floor)
    try:
        return route(data, origin, destination)
    except (KeyError, ValueError) as exc:
        raise ParkingError(404, 'NO_ROUTE', '이동 가능한 경로가 없습니다.') from exc


@router.get('/simulator', include_in_schema=False)
def simulator():
    return FileResponse(ROOT / 'simulator/index.html')


@router.get('/simulator/layout', include_in_schema=False)
def simulator_layout(request: Request, floor: str = 'B2', db: Session = Depends(get_db)):
    data = read_map(db, floor)
    sample = sample_data(request.app.state.settings.map_file)
    # Decorative sample geometry is only offered for the matching sample floor.
    expected = {s['slot_id']:s for s in sample['slots']}
    expected_nodes = {n['node_id']:(n['x'],n['y']) for n in sample['nodes']}
    actual_nodes = {n['node_id']:(n['x'],n['y']) for n in data['nodes']}
    if floor != sample['floor'] or actual_nodes != expected_nodes or {s['slot_id'] for s in data['slots']} != set(expected) or any(s['polygon'] != expected[s['slot_id']]['polygon'] for s in data['slots']):
        raise ParkingError(503, 'LAYOUT_UNAVAILABLE', '현재 지도에 맞는 3D 배치 설정이 필요합니다.')
    return {'sample':True,'demo_enabled':request.app.state.settings.simulator_enabled,
            'vehicle_api_enabled':True,'matching_backend':'shared',
            'qr_locations':data['qr_locations'],'layout':sample['demo_layout']}
