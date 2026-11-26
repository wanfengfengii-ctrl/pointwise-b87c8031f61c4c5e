from dataclasses import dataclass
import json
import sqlite3


@dataclass(frozen=True)
class DispatchRequestRecord:
    request_id: str
    batch_id: str
    press_id: str
    result: dict | None


@dataclass(frozen=True)
class ScrapRequestRecord:
    request_id: str
    batch_id: str
    ejection_id: str
    deviation_mm: int
    result: dict | None


def init_dispatch_receipts(db: sqlite3.Connection):
    db.execute('''CREATE TABLE IF NOT EXISTS dispatch_requests (
        request_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL,
        press_id TEXT NOT NULL, result TEXT
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS scrap_requests (
        request_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL,
        ejection_id TEXT NOT NULL, deviation_mm INTEGER NOT NULL, result TEXT
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


def get_scrap_request(db: sqlite3.Connection, request_id: str) -> ScrapRequestRecord | None:
    row = db.execute('''SELECT batch_id, ejection_id, deviation_mm, result
                        FROM scrap_requests WHERE request_id = ?''', (request_id,)).fetchone()
    if row is None:
        return None
    batch_id, ejection_id, deviation_mm, result = row
    return ScrapRequestRecord(request_id, batch_id, ejection_id, deviation_mm,
                              None if result is None else json.loads(result))


def save_scrap_intent(db: sqlite3.Connection, request_id: str, batch_id: str,
                      ejection_id: str, deviation_mm: int):
    db.execute('''INSERT INTO scrap_requests(request_id, batch_id, ejection_id, deviation_mm)
                  VALUES (?, ?, ?, ?)''', (request_id, batch_id, ejection_id, deviation_mm))


def save_scrap_result(db: sqlite3.Connection, request_id: str, result: dict):
    db.execute('UPDATE scrap_requests SET result = ? WHERE request_id = ? AND result IS NULL',
               (json.dumps(result), request_id))


def drop_scrap_intent(db: sqlite3.Connection, request_id: str):
    """Forget an uncommitted intent the press definitively rejected."""
    db.execute('DELETE FROM scrap_requests WHERE request_id = ? AND result IS NULL', (request_id,))
