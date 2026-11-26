from dataclasses import dataclass
import json
import sqlite3

from editions.releases import get_revision
from layout.plan import SheetPlan, build_sheet_plan, plan_from_record, plan_to_record


class DeskConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class DeskBatch:
    batch_id: str
    plan: SheetPlan
    press_id: str | None
    run_id: str | None

    def to_record(self):
        return {'batch_id': self.batch_id, 'plan': plan_to_record(self.plan),
                'press_id': self.press_id, 'run_id': self.run_id}


def init_batches(db: sqlite3.Connection):
    db.execute('''CREATE TABLE IF NOT EXISTS batches (
        seq INTEGER PRIMARY KEY, plan TEXT NOT NULL,
        press_id TEXT, run_id TEXT, CHECK(run_id IS NULL OR press_id IS NOT NULL)
    )''')


def create_batch(db: sqlite3.Connection, revision_id: str, start: int, count: int) -> DeskBatch:
    if not isinstance(revision_id, str) or not revision_id:
        raise ValueError('invalid_revision_id')
    revision = get_revision(db, revision_id)
    plan = build_sheet_plan(revision, start, count)
    with db:
        cursor = db.execute('INSERT INTO batches(plan) VALUES (?)', (json.dumps(plan_to_record(plan)),))
    return DeskBatch(f'B{cursor.lastrowid}', plan, None, None)


def get_batch(db: sqlite3.Connection, batch_id: str) -> DeskBatch:
    row = db.execute("SELECT plan, press_id, run_id FROM batches WHERE 'B' || seq = ?", (batch_id,)).fetchone()
    if row is None:
        raise KeyError('unknown_batch')
    plan, press_id, run_id = row
    return DeskBatch(batch_id, plan_from_record(json.loads(plan)), press_id, run_id)


def bind_press(db: sqlite3.Connection, batch: DeskBatch, press_id: str):
    if batch.press_id is not None and batch.press_id != press_id:
        raise DeskConflict('batch_press_conflict')
    if batch.press_id is None:
        db.execute("UPDATE batches SET press_id = ? WHERE 'B' || seq = ?", (press_id, batch.batch_id))


def record_run_ref(db: sqlite3.Connection, batch_id: str, press_id: str, run_id: str):
    batch = get_batch(db, batch_id)
    if batch.press_id != press_id or batch.run_id not in (None, run_id):
        raise DeskConflict('run_reference_conflict')
    if batch.run_id is None:
        db.execute("UPDATE batches SET run_id = ? WHERE 'B' || seq = ?", (run_id, batch_id))
