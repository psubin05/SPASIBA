"""Atomic durable outbox and per-slot deduplication, shared by OCR/worker threads."""
import json
from pathlib import Path
import sqlite3
import threading
from .slots import Occupancy


class Store:
    def __init__(self, path, max_pending=10000):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=0.1, check_same_thread=False)
        self.lock = threading.RLock()
        self.max_pending = max_pending
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS outbox (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS slots (
                slot_id TEXT PRIMARY KEY, plate TEXT,
                occupancy TEXT NOT NULL DEFAULT 'UNKNOWN');
        ''')

    def occupancy(self, slot):
        with self.lock:
            row = self.db.execute("SELECT occupancy FROM slots WHERE slot_id=?", (slot,)).fetchone()
            return Occupancy(row[0]) if row else Occupancy.UNKNOWN

    def set_occupancy(self, slot, state):
        state = Occupancy(state)
        with self.lock, self.db:
            # Only explicit EMPTY clears consensus memory; detection loss never does.
            self.db.execute('''INSERT INTO slots(slot_id, occupancy) VALUES (?,?)
                ON CONFLICT(slot_id) DO UPDATE SET occupancy=excluded.occupancy,
                plate=CASE WHEN excluded.occupancy='EMPTY' THEN NULL ELSE slots.plate END''', (slot, state.value))

    def enqueue(self, event):
        with self.lock, self.db:
            row = self.db.execute("SELECT plate FROM slots WHERE slot_id=?", (event['slot_id'],)).fetchone()
            if row and row[0] == event['plate_number']:
                return False
            if self.count() >= self.max_pending:
                raise RuntimeError("outbox full; event deferred, dedup state unchanged")
            self.db.execute("INSERT INTO outbox(event_id,payload) VALUES (?,?)",
                            (event['event_id'], json.dumps(event, ensure_ascii=False)))
            self.db.execute('''INSERT INTO slots(slot_id,plate) VALUES (?,?)
                ON CONFLICT(slot_id) DO UPDATE SET plate=excluded.plate''',
                            (event['slot_id'], event['plate_number']))
            return True

    def peek(self):
        with self.lock:
            row = self.db.execute("SELECT payload FROM outbox ORDER BY seq LIMIT 1").fetchone()
            return json.loads(row[0]) if row else None

    def acknowledge(self, event_id):
        with self.lock, self.db:
            self.db.execute("DELETE FROM outbox WHERE event_id=?", (event_id,))

    def count(self):
        with self.lock:
            return self.db.execute("SELECT count(*) FROM outbox").fetchone()[0]

    def close(self):
        with self.lock:
            self.db.close()
