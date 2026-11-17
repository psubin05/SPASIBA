"""Local entry/parking simulator adapter. Replace with Suin's real backend at integration."""

from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
import re
import sqlite3
import unicodedata
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator, model_validator

REGIONS = ('서울','부산','대구','인천','광주','대전','울산','세종','경기','강원','충북','충남','전북','전남','경북','경남','제주')
PLATE = re.compile(r'^(?:' + '|'.join(REGIONS) + r')?[0-9]{2,3}[가-힣][0-9]{4}$')


def normalize_plate(value):
    value = unicodedata.normalize('NFKC', value)
    return re.sub(r'[\s\-·]', '', value)


def checked_plate(value):
    value = normalize_plate(value)
    if not PLATE.fullmatch(value):
        raise ValueError('차량번호 형식을 확인해주세요. 예: 12가3456')
    return value


def tokens(value):
    return [value[:2], *value[2:]] if value[:2] in REGIONS else list(value)


def edit_distance(a, b):
    a, b = tokens(a), tokens(b)
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        following = [i]
        for j, y in enumerate(b, 1):
            following.append(min(following[-1] + 1, row[j] + 1, row[j - 1] + (x != y)))
        row = following
    return row[-1]


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def moment(value):
    return datetime.fromisoformat(value).astimezone(timezone.utc)


class DemoError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


class EntryInput(BaseModel):
    plate_number: str = Field(max_length=32)
    entered_at: datetime | None = None

    @field_validator('plate_number')
    @classmethod
    def plate(cls, value):
        return checked_plate(value)

    @field_validator('entered_at')
    @classmethod
    def timestamp(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError('Timezone required')
        return value


class ExitInput(BaseModel):
    plate_number: str | None = Field(default=None, max_length=32)
    session_id: UUID | None = None

    @model_validator(mode='after')
    def one_identifier(self):
        if (self.plate_number is None) == (self.session_id is None):
            raise ValueError('Provide exactly one plate_number or session_id')
        if self.plate_number is not None:
            self.plate_number = checked_plate(self.plate_number)
        return self


class EventInput(BaseModel):
    event_id: UUID
    plate_number: str = Field(max_length=32)
    camera_id: str
    zone_id: str
    slot_id: str
    recognized_at: datetime
    votes: int | None = Field(default=None, ge=0, le=10)
    frames: int | None = Field(default=None, ge=0, le=10)
    kind: str = Field(default='confirm', pattern='^(confirm|recheck)$')

    @field_validator('recognized_at')
    @classmethod
    def timestamp(cls, value):
        if value.utcoffset() is None:
            raise ValueError('Timezone required')
        return value

    @model_validator(mode='after')
    def vote_count(self):
        if self.votes is not None and self.frames is not None and self.votes > self.frames:
            raise ValueError('votes exceeds frames')
        return self


class DemoParking:
    def __init__(self, path, maps):
        self.path, self.maps = str(path), maps
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS demo_entry (
                    session_id TEXT PRIMARY KEY, plate_number TEXT NOT NULL,
                    entered_at TEXT NOT NULL, exited_at TEXT,
                    state TEXT NOT NULL, slot_id TEXT, confirmed_at TEXT, last_seen_at TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS active_plate ON demo_entry(plate_number) WHERE state='ACTIVE';
                CREATE UNIQUE INDEX IF NOT EXISTS active_slot ON demo_entry(slot_id) WHERE state='ACTIVE' AND slot_id IS NOT NULL;
                CREATE TABLE IF NOT EXISTS demo_event (
                    event_id TEXT PRIMARY KEY, plate_number TEXT, slot_id TEXT,
                    recognized_at TEXT, received_at TEXT, valid INTEGER, reason TEXT
                );
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def enter(self, entry):
        if entry.entered_at and entry.entered_at > datetime.now(timezone.utc) + timedelta(seconds=30):
            raise DemoError(422, 'INVALID_REQUEST', '입차 시각이 현재보다 너무 미래입니다.')
        with self.db() as db:
            if db.execute("SELECT 1 FROM demo_entry WHERE plate_number=? AND state='ACTIVE'", (entry.plate_number,)).fetchone():
                raise DemoError(409, 'CONFLICT', '이미 입차 중인 차량입니다.')
            record = {'session_id': str(uuid4()), 'plate_number': entry.plate_number,
                      'entered_at': entry.entered_at.astimezone(timezone.utc).isoformat(timespec='microseconds') if entry.entered_at else now(), 'state': 'ACTIVE'}
            db.execute('INSERT INTO demo_entry(session_id,plate_number,entered_at,state) VALUES (:session_id,:plate_number,:entered_at,:state)', record)
            return record

    def entries(self, state):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM demo_entry WHERE state=? ORDER BY entered_at', (state,))]

    def exit(self, request):
        with self.db() as db:
            column, value = ('session_id', str(request.session_id)) if request.session_id else ('plate_number', request.plate_number)
            row = db.execute(f"SELECT * FROM demo_entry WHERE {column}=? AND state='ACTIVE'", (value,)).fetchone()
            if not row:
                raise DemoError(404, 'NOT_FOUND', '진행 중인 입차 기록이 없습니다.')
            timestamp = now()
            db.execute("UPDATE demo_entry SET state='EXITED',exited_at=?,slot_id=NULL WHERE session_id=?", (timestamp, row['session_id']))
            return {'session_id': row['session_id'], 'exited_at': timestamp, 'state': 'EXITED'}

    def location(self, plate):
        try:
            plate = checked_plate(plate)
        except ValueError as exc:
            raise DemoError(422, 'INVALID_REQUEST', str(exc)) from exc
        with self.db() as db:
            row = db.execute("SELECT * FROM demo_entry WHERE plate_number=? AND state='ACTIVE'", (plate,)).fetchone()
            if not row:
                raise DemoError(404, 'NOT_FOUND', '해당 차량의 주차 기록이 없습니다.')
            if not row['slot_id']:
                return {'plate_number': plate, 'status': 'PENDING', 'message': '주차 위치를 확인하고 있습니다.'}
            slot = self.maps.slots.get(row['slot_id'])
            if slot is None:
                return {'plate_number': plate, 'status': 'PENDING', 'message': '주차장 지도가 변경되어 위치를 다시 확인하고 있습니다.'}
            return {'plate_number': plate, 'status': 'CONFIRMED', 'slot_id': slot['slot_id'],
                    'slot_name': slot['name'], 'floor': self.maps.data['floor'], 'zone_id': slot['zone_id'],
                    'node_id': slot['node_id'], 'last_seen_at': row['last_seen_at'],
                    'confirmed_at': row['confirmed_at'], 'source': 'session'}

    def event(self, event):
        slot = self.maps.slots.get(event.slot_id)
        plate = normalize_plate(event.plate_number)
        timestamp = event.recognized_at.astimezone(timezone.utc).isoformat(timespec='microseconds')
        future = event.recognized_at > datetime.now(timezone.utc) + timedelta(seconds=30)
        valid = bool(not future and slot and slot['camera_id'] == event.camera_id and slot['zone_id'] == event.zone_id and PLATE.fullmatch(plate))
        with self.db() as db:
            if db.execute('SELECT 1 FROM demo_event WHERE event_id=?', (str(event.event_id),)).fetchone():
                return {'event_id': str(event.event_id), 'status': 'DUPLICATE'}
            db.execute('INSERT INTO demo_event VALUES (?,?,?,?,?,?,?)',
                       (str(event.event_id), plate, event.slot_id, timestamp, now(), int(valid), None if valid else 'Future observation' if future else 'Invalid plate or camera/zone/slot relationship'))
            if not valid:
                return {'event_id': str(event.event_id), 'status': 'INVALID'}
            candidates = [r for r in db.execute("SELECT * FROM demo_entry WHERE state='ACTIVE'").fetchall()
                          if moment(r['entered_at']) <= moment(timestamp)]
            exact = [r for r in candidates if r['plate_number'] == plate]
            similar = [r for r in candidates if edit_distance(r['plate_number'], plate) == 1]
            chosen, method = None, None
            if len(exact) == 1:
                chosen, method = exact[0], 'EXACT'
            elif not exact and len(similar) == 1 and event.votes is not None and event.votes >= 5:
                chosen, method = similar[0], 'EDIT1'
            if chosen is None:
                return {'event_id': str(event.event_id), 'status': 'PENDING'}
            # Late old events must not overwrite a newer observation of either the car or slot.
            occupant = db.execute("SELECT * FROM demo_entry WHERE state='ACTIVE' AND slot_id=?", (event.slot_id,)).fetchone()
            if any(r and r['last_seen_at'] and moment(r['last_seen_at']) > moment(timestamp) for r in (chosen, occupant)):
                return {'event_id': str(event.event_id), 'status': 'STALE'}
            if chosen['last_seen_at'] and moment(chosen['last_seen_at']) == moment(timestamp) and chosen['slot_id'] != event.slot_id:
                return {'event_id': str(event.event_id), 'status': 'STALE'}
            if occupant and occupant['session_id'] != chosen['session_id'] and occupant['last_seen_at'] and moment(occupant['last_seen_at']) == moment(timestamp):
                return {'event_id': str(event.event_id), 'status': 'STALE'}
            db.execute("UPDATE demo_entry SET slot_id=NULL,confirmed_at=NULL,last_seen_at=NULL WHERE state='ACTIVE' AND slot_id=? AND session_id<>?", (event.slot_id, chosen['session_id']))
            confirmed = chosen['confirmed_at'] if chosen['slot_id'] == event.slot_id else timestamp
            db.execute('UPDATE demo_entry SET slot_id=?,confirmed_at=?,last_seen_at=? WHERE session_id=?',
                       (event.slot_id, confirmed, timestamp, chosen['session_id']))
            return {'event_id': str(event.event_id), 'status': 'CONFIRMED', 'method': method,
                    'review_recommended': method == 'EDIT1', 'session_id': chosen['session_id']}


def demo_router():
    router = APIRouter(tags=['Local demo adapter'])

    @router.post('/entries', status_code=201)
    def entry(payload: EntryInput, request: Request):
        return request.app.state.parking.enter(payload)

    @router.get('/entries')
    def entries(request: Request, state: str = 'ACTIVE'):
        if state not in ('ACTIVE', 'EXITED'):
            raise DemoError(422, 'INVALID_REQUEST', 'state는 ACTIVE 또는 EXITED입니다.')
        return request.app.state.parking.entries(state)

    @router.post('/exits')
    def exit(payload: ExitInput, request: Request):
        return request.app.state.parking.exit(payload)

    @router.get('/vehicles/{plate}/last-location')
    def location(plate: str, request: Request):
        return request.app.state.parking.location(plate)

    @router.post('/simulator/events')
    def event(payload: EventInput, request: Request):
        return request.app.state.parking.event(payload)

    return router
