from dataclasses import asdict, dataclass
import json
import sqlite3

from desk.batches import DeskConflict


@dataclass(frozen=True)
class IssuedSheet:
    number: int
    print_number: str
    press_id: str
    run_id: str
    ejection_id: str
    deviation_mm: int


@dataclass(frozen=True)
class IssuedBatch:
    batch_id: str
    delivery_id: str
    revision_id: str
    sheets: tuple[IssuedSheet, ...]


def init_issued_batches(db: sqlite3.Connection):
    db.execute('''CREATE TABLE IF NOT EXISTS issued_batches (
        seq INTEGER PRIMARY KEY, batch_id TEXT NOT NULL UNIQUE,
        revision_id TEXT NOT NULL, sheets TEXT NOT NULL
    )''')


def get_issued_batch(db: sqlite3.Connection, batch_id: str) -> IssuedBatch | None:
    row = db.execute('SELECT seq, revision_id, sheets FROM issued_batches WHERE batch_id = ?',
                     (batch_id,)).fetchone()
    if row is None:
        return None
    seq, revision_id, body = row
    return IssuedBatch(batch_id, f'D{seq}', revision_id, tuple(IssuedSheet(**sheet) for sheet in json.loads(body)))


def issue_batch(db: sqlite3.Connection, batch_id: str, revision_id: str,
                sheets: tuple[IssuedSheet, ...]) -> IssuedBatch:
    with db:
        db.execute('BEGIN IMMEDIATE')
        existing = get_issued_batch(db, batch_id)
        if existing is not None:
            if existing.revision_id != revision_id or existing.sheets != sheets:
                raise DeskConflict('inspection_already_issued')
            return existing
        body = json.dumps([asdict(sheet) for sheet in sheets])
        cursor = db.execute('INSERT INTO issued_batches(batch_id, revision_id, sheets) VALUES (?, ?, ?)',
                            (batch_id, revision_id, body))
    return IssuedBatch(batch_id, f'D{cursor.lastrowid}', revision_id, sheets)
