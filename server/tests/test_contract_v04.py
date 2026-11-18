"""Regression checks against the user's supplied v0.4 interface."""
import base64
import io
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image

from app import parking as P
from app.models import ReviewQueue, MatchPending, ParkingEvent
from tools.fake_pi_messages import DUMMY_JPEG

T0 = datetime(2026,11,18,14,0,tzinfo=timezone(timedelta(hours=9)))
CAM = 'CAM-B2-01'
AUTH = {'Authorization':'Bearer test-token'}


def event(plate='12가3458', **extra):
    return {'event_id':str(uuid4()),'plate_number':plate,'camera_id':CAM,'slot_id':'B2-A-03',
            'recognized_at':T0.isoformat(),'votes':2,'frames':7,**extra}


def pending_review(client, db, *, enter=True):
    if enter:
        client.post('/entries',json={'plate_number':'12가3456','entered_at':T0.isoformat()})
    cfg = client.app.state.settings
    ev = event()
    assert P.handle_event(db,cfg,CAM,ev,T0) == 'pending'
    (_,request), = P.check_timeouts(db,cfg,T0+timedelta(seconds=121))
    review = db.query(ReviewQueue).one()
    return review, request


def crop_payload(request, image=DUMMY_JPEG, **changes):
    return {**request,'captured_at':T0.isoformat(),'image_jpeg_base64':base64.b64encode(image).decode(),**changes}


def jpeg(width,height):
    stream = io.BytesIO()
    Image.new('RGB',(width,height),'gray').save(stream,format='JPEG')
    return stream.getvalue()


def test_admin_bearer_auth_and_no_token_setting(app_client):
    assert app_client.get('/admin/reviews').status_code == 401
    assert app_client.get('/admin/reviews',headers={'Authorization':'Bearer wrong'}).status_code == 401
    assert app_client.get('/admin/reviews',headers=AUTH).json() == []
    assert app_client.get('/admin/reviews?status=BAD',headers=AUTH).status_code == 422
    app_client.app.state.settings = replace(app_client.app.state.settings,admin_token=None)
    assert app_client.get('/admin/reviews',headers=AUTH).status_code == 503


def test_admin_list_crop_resolve_and_remove_photo(app_client,db):
    review, request = pending_review(app_client,db)
    endpoint = f'/admin/reviews/{review.review_id}'
    assert app_client.get('/admin/reviews',headers=AUTH).json()[0]['has_crop'] is False
    assert app_client.get(endpoint+'/crop',headers=AUTH).status_code == 404
    assert P.handle_crop(db,app_client.app.state.settings,CAM,crop_payload(request))
    db.refresh(review)
    saved = Path(review.crop_path)
    response = app_client.get(endpoint+'/crop',headers=AUTH)
    assert response.status_code == 200 and response.content == DUMMY_JPEG
    assert response.headers['content-type'] == 'image/jpeg'
    sid = app_client.get('/entries?state=ACTIVE').json()[0]['session_id']
    assert app_client.post(endpoint+'/resolve',headers=AUTH,json={'action':'assign','session_id':sid}).json()['status'] == 'RESOLVED'
    assert not saved.exists()
    assert app_client.get(endpoint+'/crop',headers=AUTH).status_code == 404
    assert app_client.get('/vehicles/12가3456/last-location').json()['status'] == 'CONFIRMED'
    assert app_client.post(endpoint+'/resolve',headers=AUTH,json={'action':'dismiss'}).status_code == 409


def test_admin_dismiss_and_request_validation(app_client,db):
    review, _ = pending_review(app_client,db)
    url = f'/admin/reviews/{review.review_id}/resolve'
    for body in ({'action':'bad'},{'action':'assign'},{'action':'dismiss','session_id':str(uuid4())}):
        assert app_client.post(url,headers=AUTH,json=body).status_code == 422
    assert app_client.post(url,headers=AUTH,json={'action':'dismiss'}).json()['status'] == 'DISMISSED'


def test_edit1_is_marked_for_admin_review(app_client,db):
    app_client.post('/entries',json={'plate_number':'12가3456'})
    assert P.handle_event(db,app_client.app.state.settings,CAM,event(votes=5),T0) == 'assigned'
    data = app_client.get('/admin/auto-assignments',headers=AUTH).json()
    assert data[0]['method'] == 'EDIT1' and data[0]['review_recommended'] is True


@pytest.mark.parametrize('changes',[
    {'slot_id':'B2-A-04'},{'event_id':str(uuid4())},{'event_id':None},
    {'captured_at':None},{'captured_at':'2026-11-18T14:00:00'}, {'event_id':[]},
])
def test_crop_rejects_mismatched_request_fields(app_client,db,changes):
    _,request = pending_review(app_client,db)
    assert not P.handle_crop(db,app_client.app.state.settings,CAM,crop_payload(request,**changes))


@pytest.mark.parametrize('image',[
    b'\xff\xd8\xff\xd9', jpeg(641,10), DUMMY_JPEG+b'0'*100_000, DUMMY_JPEG[:-8],
])
def test_crop_rejects_invalid_jpeg_oversize_pixels_or_bytes(app_client,db,image):
    _,request = pending_review(app_client,db)
    assert not P.handle_crop(db,app_client.app.state.settings,CAM,crop_payload(request,image))


def test_crop_accepts_640px_boundary(app_client,db):
    _,request = pending_review(app_client,db)
    assert P.handle_crop(db,app_client.app.state.settings,CAM,crop_payload(request,jpeg(640,10)))


def test_exit_cleans_review_crop_and_unshared_pending(app_client,db):
    review,request = pending_review(app_client,db)
    assert P.handle_crop(db,app_client.app.state.settings,CAM,crop_payload(request))
    db.refresh(review)
    photo = Path(review.crop_path)
    # A separate low-vote read of the same car must not remain after exit.
    P.handle_event(db,app_client.app.state.settings,CAM,event(slot_id='B2-A-04'),T0)
    assert db.get(MatchPending,'B2-A-04') is not None
    assert app_client.post('/exits',json={'plate_number':'12가3456'}).status_code == 200
    db.expire_all()
    assert not photo.exists()
    assert db.get(ReviewQueue,review.review_id).status == 'DISMISSED'
    assert db.get(MatchPending,'B2-A-04') is None
    assert app_client.get('/vehicles/12가3456/last-location').status_code == 404


def test_invalid_latest_event_does_not_break_crop_correlation(app_client,db):
    cfg = app_client.app.state.settings
    valid = event()
    P.handle_event(db,cfg,CAM,valid,T0)
    P.handle_event(db,cfg,CAM,event(plate='invalid',recognized_at=(T0+timedelta(seconds=30)).isoformat()),T0)
    (_,request), = P.check_timeouts(db,cfg,T0+timedelta(seconds=121))
    assert request['event_id'] == valid['event_id']


def test_no_zone_is_required_and_legacy_zone_is_ignored(app_client,db):
    app_client.post('/entries',json={'plate_number':'12가3456'})
    assert P.handle_event(db,app_client.app.state.settings,CAM,event('12가3456',zone_id='WRONG'),T0) == 'assigned'
    assert db.query(ParkingEvent).one().zone_id == 'B2-A'


@pytest.mark.parametrize('changes',[
    {'event_id':str(uuid4()).replace('-','')[:-1]}, {'votes':11}, {'frames':11}, {'votes':8,'frames':7},
    {'camera_id':[]}, {'votes':2**100},
])
def test_invalid_id_or_vote_counts_are_saved_invalid(app_client,db,changes):
    ev = event(**changes)
    assert P.handle_event(db,app_client.app.state.settings,CAM,ev,T0) == 'invalid'
    assert not db.get(ParkingEvent,ev['event_id']).valid


def test_timeout_queue_works_without_mqtt_connection(app_client,db,monkeypatch):
    import time
    from app.mqtt_listener import MqttListener
    cfg = replace(app_client.app.state.settings,match_pending_seconds=0,mqtt_enabled=False)
    P.handle_event(db,cfg,CAM,event(),T0)
    monkeypatch.setattr('app.mqtt_listener.TICK_SECONDS',0.01)
    listener = MqttListener(cfg,app_client.app.state.db)
    listener.start()
    try:
        deadline = time.monotonic()+2
        while time.monotonic()<deadline:
            db.expire_all()
            if db.query(ReviewQueue).count():
                break
            time.sleep(0.01)
        assert not listener.connected
        assert db.query(ReviewQueue).one().status == 'OPEN'
    finally:
        listener.stop()


def test_post_exit_event_cannot_resurrect_vehicle_location(app_client,db):
    app_client.post('/entries',json={'plate_number':'12가3456','entered_at':T0.isoformat()})
    cfg = app_client.app.state.settings
    P.exit_session(db,cfg,now=T0+timedelta(minutes=1),plate_number='12가3456')
    P.handle_event(db,cfg,CAM,event('12가3456',recognized_at=(T0+timedelta(minutes=2)).isoformat()),T0+timedelta(minutes=2))
    assert app_client.get('/vehicles/12가3456/last-location').status_code == 404


def test_tls_uses_configured_ca_certificate(settings,app_client,monkeypatch,tmp_path):
    from unittest.mock import Mock
    from app.mqtt_listener import MqttListener
    cfg = replace(settings,mqtt_enabled=True,mqtt_tls=True,mqtt_ca_cert=str(tmp_path/'ca.crt'))
    client = Mock()
    monkeypatch.setattr('paho.mqtt.client.Client',lambda *args,**kwargs:client)
    listener = MqttListener(cfg,app_client.app.state.db)
    listener.start()
    try:
        client.tls_set.assert_called_once_with(ca_certs=cfg.mqtt_ca_cert)
        client.connect_async.assert_called_once()
    finally:
        listener.stop()


def test_openapi_reports_current_interface_version(app_client):
    assert app_client.get('/openapi.json').json()['info']['version'] == '0.4.0'
