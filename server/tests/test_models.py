"""DB 스키마 (인터페이스 5장) 검사. 같은 테스트를 SQLite와 PostgreSQL에서 돌린다.

PostgreSQL은 TEST_DATABASE_URL(기본: docker compose의 localhost:5432)에 붙을 때만 돈다.
테스트마다 임시 스키마를 만들어 수빈의 db/map_schema.sql → 우리 모델 순으로 만들고, 끝나면 지운다.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from app.db import Base, make_engine
from app.models import EntrySession, MatchPending, ParkingEvent, ReviewQueue, SlotAssignment
from tests.map_seed import seed_map

KST = timezone(timedelta(hours=9))
T0 = datetime(2026, 11, 18, 14, 0, 0, tzinfo=KST)
PG_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://spasiba:spasiba@localhost:5432/spasiba")
MAP_SQL = Path(__file__).parents[1] / "db" / "map_schema.sql"

OUR_TABLES = {"parking_event", "entry_session", "slot_assignment", "match_pending", "review_queue"}
MAP_COLUMNS = {  # 수빈의 db/map_schema.sql 그대로. 우리 미러 모델(SQLite)과 원본 SQL(PostgreSQL)이 같아야 함
    "zone": {"zone_id", "floor", "name"},
    "camera": {"camera_id", "zone_id", "description"},
    "map_node": {"node_id", "floor", "x", "y", "type"},
    "parking_slot": {"slot_id", "zone_id", "camera_id", "name", "roi", "node_id", "polygon"},
    "map_edge": {"from_node", "to_node", "length_m"},
    "qr_location": {"location_id", "node_id", "floor", "name"},
}


def _sqlite_engine(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/models.db")
    Base.metadata.create_all(engine)
    return engine, None


def _pg_engine():
    try:
        probe = create_engine(PG_URL, connect_args={"connect_timeout": 2})
        with probe.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # 연결 안 되면 PostgreSQL 쪽만 건너뜀
        pytest.skip(f"PostgreSQL 없음 ({type(exc).__name__})")
    schema = f"t_{uuid.uuid4().hex[:12]}"
    with probe.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(PG_URL, connect_args={"options": f"-csearch_path={schema}"})
    with engine.begin() as conn:
        conn.exec_driver_sql(MAP_SQL.read_text(encoding="utf-8"))
    Base.metadata.create_all(engine)  # 지도 표는 이미 있으므로 건너뛰고 우리 표만 만든다
    return engine, (probe, schema)


@pytest.fixture(params=["sqlite", "postgresql"])
def engine(request, tmp_path):
    engine, cleanup = _sqlite_engine(tmp_path) if request.param == "sqlite" else _pg_engine()
    yield engine
    engine.dispose()
    if cleanup:
        probe, schema = cleanup
        with probe.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        probe.dispose()


@pytest.fixture
def db(engine):
    with Session(engine) as s:
        seed_map(s)
        yield s


def _session(plate="12가3456", state="ACTIVE", **kw) -> EntrySession:
    return EntrySession(session_id=uuid.uuid4(), plate_number=plate, plate_norm=plate,
                        entered_at=T0, state=state, **kw)


def _assign(session_id, slot_id="B2-A-03", **kw) -> SlotAssignment:
    return SlotAssignment(session_id=session_id, slot_id=slot_id, method="EXACT", event_ids=["e1"],
                          assigned_at=T0, last_seen_at=T0, **kw)


def _event(event_id="e1", slot_id="B2-A-03", zone_id="B2-A", recognized_at=T0, **kw) -> ParkingEvent:
    return ParkingEvent(event_id=event_id, plate_number="12가3456", plate_norm="12가3456",
                        camera_id="CAM-B2-A-01", zone_id=zone_id, slot_id=slot_id,
                        recognized_at=recognized_at, **kw)


def _fails(db, *objs):
    db.add_all(objs)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ---- 표 구성 ----
def test_tables_exist(engine):
    tables = set(inspect(engine).get_table_names())
    assert OUR_TABLES | set(MAP_COLUMNS) <= tables


def test_map_columns_match_subin_sql(engine):
    insp = inspect(engine)
    for table, columns in MAP_COLUMNS.items():
        assert {c["name"] for c in insp.get_columns(table)} == columns, table


# ---- 부분 유니크 인덱스 3개 ----
def test_one_active_session_per_plate(db):
    _fails(db, _session(), _session())


def test_exited_session_does_not_block_new_entry(db):
    db.add_all([_session(state="EXITED", exited_at=T0), _session(state="EXITED", exited_at=T0), _session()])
    db.commit()


def test_one_open_assignment_per_session(db):
    s = _session()
    db.add(s)
    db.commit()
    _fails(db, _assign(s.session_id, "B2-A-01"), _assign(s.session_id, "B2-A-02"))


def test_one_open_car_per_slot(db):
    a, b = _session("12가3456"), _session("34나5678")
    db.add_all([a, b])
    db.commit()
    _fails(db, _assign(a.session_id), _assign(b.session_id))


def test_ended_assignments_keep_history(db):
    a, b = _session("12가3456"), _session("34나5678")
    db.add_all([a, b])
    db.commit()
    db.add_all([_assign(a.session_id, ended_at=T0), _assign(a.session_id, "B2-A-01", ended_at=T0),
                _assign(a.session_id, "B2-A-02"), _assign(b.session_id)])
    db.commit()


# ---- FK ----
def test_event_for_unknown_slot_is_stored(db):
    db.add(_event(slot_id="B2-Z-99", zone_id=None, valid=False, invalid_reason="등록 안 된 칸"))
    db.commit()
    e = db.get(ParkingEvent, "e1")
    assert e.valid is False and e.zone_id is None


def test_assignment_requires_known_slot(db):
    s = _session()
    db.add(s)
    db.commit()
    _fails(db, _assign(s.session_id, "B2-Z-99"))


def test_assignment_requires_known_session(db):
    _fails(db, _assign(uuid.uuid4()))


def test_pending_and_review_require_known_slot(db):
    _fails(db, MatchPending(slot_id="B2-Z-99", first_event_at=T0, reads=[]))
    _fails(db, ReviewQueue(review_id=uuid.uuid4(), slot_id="B2-Z-99", read_plates=[], candidates=[],
                           status="OPEN", created_at=T0))


# ---- 값 검사 ----
def test_check_constraints(db):
    _fails(db, _session(state="PARKED"))
    s = _session()
    db.add(s)
    db.commit()
    bad = _assign(s.session_id)
    bad.method = "GUESS"
    _fails(db, bad)
    _fails(db, ReviewQueue(review_id=uuid.uuid4(), slot_id="B2-A-03", read_plates=[], candidates=[],
                           status="MAYBE", created_at=T0))


def test_event_defaults(db):
    db.add(_event())
    db.commit()
    db.expire_all()
    e = db.get(ParkingEvent, "e1")
    assert e.kind == "confirm" and e.valid is True and e.received_at is not None
    assert e.received_at.tzinfo is not None


def test_duplicate_event_id_rejected(db):
    db.add(_event())
    db.commit()
    _fails(db, _event())


# ---- 시각·JSON ----
def test_timestamps_round_trip_with_timezone(db):
    db.add(_event(recognized_at=datetime(2026, 11, 18, 14, 3, 21, 123000, tzinfo=KST)))
    db.commit()
    db.expire_all()
    got = db.get(ParkingEvent, "e1").recognized_at
    assert got.tzinfo is not None
    assert got == datetime(2026, 11, 18, 5, 3, 21, 123000, tzinfo=timezone.utc)


def test_naive_datetime_rejected(db):
    db.add(_event(recognized_at=datetime(2026, 11, 18, 14, 0, 0)))
    with pytest.raises(StatementError):
        db.commit()
    db.rollback()


def test_json_columns_round_trip(db):
    s = _session()
    db.add(s)
    db.commit()
    reads = [{"event_id": "e1", "plate_norm": "12가3458", "recognized_at": "2026-11-18T14:00:00+09:00"}]
    candidates = [{"session_id": str(s.session_id), "plate_number": "12가3456", "distance": 1}]
    db.add_all([_assign(s.session_id),
                MatchPending(slot_id="B2-A-01", first_event_at=T0, reads=reads),
                ReviewQueue(review_id=uuid.uuid4(), slot_id="B2-A-02", read_plates=["12가3458"],
                            candidates=candidates, status="OPEN", created_at=T0)])
    db.commit()
    db.expire_all()
    assert db.get(MatchPending, "B2-A-01").reads == reads
    assert db.query(SlotAssignment).one().event_ids == ["e1"]
    review = db.query(ReviewQueue).one()
    assert review.candidates == candidates and review.crop_path is None


def test_json_list_append_is_saved(db):
    """매칭 엔진이 보류 목록에 읽기를 덧붙일 때(append) 저장돼야 함."""
    s = _session()
    db.add_all([s, MatchPending(slot_id="B2-A-01", first_event_at=T0, reads=[{"event_id": "e1"}])])
    db.commit()
    db.add(_assign(s.session_id))
    db.commit()
    # 주의: db.get(...).reads.append(...)처럼 한 줄로 쓰면 행 객체가 바로 사라져 변경이 저장되지 않음
    pending = db.get(MatchPending, "B2-A-01")
    pending.reads.append({"event_id": "e2"})
    assignment = db.query(SlotAssignment).one()
    assignment.event_ids.append("e2")
    db.commit()
    db.expire_all()
    assert [r["event_id"] for r in db.get(MatchPending, "B2-A-01").reads] == ["e1", "e2"]
    assert db.query(SlotAssignment).one().event_ids == ["e1", "e2"]


def test_session_id_is_uuid(db):
    s = _session()
    db.add(s)
    db.commit()
    db.expire_all()
    assert isinstance(db.get(EntrySession, s.session_id).session_id, uuid.UUID)


# ---- 앱 시작 ----
def test_app_startup_creates_tables(client):
    tables = set(inspect(client.app.state.db.engine).get_table_names())
    assert OUR_TABLES | set(MAP_COLUMNS) <= tables
