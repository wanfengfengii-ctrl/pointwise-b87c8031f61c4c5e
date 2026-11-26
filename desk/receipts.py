from dataclasses import dataclass
import json
import sqlite3


@dataclass(frozen=True)
class DispatchRequestRecord:
    request_id: str
    batch_id: str
    press_id: str
    result: dict | None


def init_dispatch_receipts(db: sqlite3.Connection):
    db.execute('''CREATE TABLE IF NOT EXISTS dispatch_requests (
        request_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL,
        press_id TEXT NOT NULL, result TEXT
    )''')


def get_dispatch_request(db: sqlite3.Connection, request_id: str) -> DispatchRequestRecord | None:
    row = db.execute('SELECT batch_id, press_id, result FROM dispatch_requests WHERE request_id = ?',
                     (request_id,)).fetchone()
    if row is None:
        return None
    batch_id, press_id, result = row
    return DispatchRequestRecord(request_id, batch_id, press_id, None if result is None else json.loads(result))


def save_dispatch_intent(db: sqlite3.Connection, request_id: str, batch_id: str, press_id: str):
    db.execute('INSERT INTO dispatch_requests(request_id, batch_id, press_id) VALUES (?, ?, ?)',
               (request_id, batch_id, press_id))


def save_dispatch_result(db: sqlite3.Connection, request_id: str, result: dict):
    db.execute('UPDATE dispatch_requests SET result = ? WHERE request_id = ? AND result IS NULL',
               (json.dumps(result), request_id))
