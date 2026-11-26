from dataclasses import dataclass
import json
import sqlite3

from layout.plan import SheetPlan, plan_from_record, plan_to_record
from press.duplex import DuplexStage, RunConflict, validate_stage_result


@dataclass(frozen=True)
class QueuedRun:
    run_id: str
    batch_id: str
    press_id: str
    plan: SheetPlan

    def reference(self):
        return {'run_id': self.run_id, 'batch_id': self.batch_id, 'press_id': self.press_id}


@dataclass(frozen=True)
class SheetWork:
    number: int
    stage: DuplexStage
    pending_request: str | None


def init_queue(db: sqlite3.Connection):
    db.execute('''CREATE TABLE IF NOT EXISTS queued_runs (
        seq INTEGER PRIMARY KEY, batch_id TEXT NOT NULL UNIQUE, plan TEXT NOT NULL
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS sheet_work (
        run_id TEXT NOT NULL, number INTEGER NOT NULL, stage TEXT NOT NULL,
        pending_request TEXT, PRIMARY KEY(run_id, number)
    )''')


def enqueue_plan(db: sqlite3.Connection, press_id: str, batch_id: str, plan: SheetPlan) -> QueuedRun:
    body = json.dumps(plan_to_record(plan), sort_keys=True, separators=(',', ':'))
    with db:
        db.execute('BEGIN IMMEDIATE')
        found = db.execute('SELECT seq, plan FROM queued_runs WHERE batch_id = ?', (batch_id,)).fetchone()
        if found is not None:
            seq, original = found
            if original != body:
                raise RunConflict('queue_plan_conflict')
            return QueuedRun(f'{press_id}-R{seq}', batch_id, press_id, plan)
        cursor = db.execute('INSERT INTO queued_runs(batch_id, plan) VALUES (?, ?)', (batch_id, body))
        run_id = f'{press_id}-R{cursor.lastrowid}'
        db.executemany('INSERT INTO sheet_work(run_id, number, stage) VALUES (?, ?, ?)',
                       ((run_id, sheet.number, DuplexStage.QUEUED.value) for sheet in plan.sheets))
    return QueuedRun(run_id, batch_id, press_id, plan)


def read_queued_run(db: sqlite3.Connection, press_id: str, run_id: str) -> QueuedRun:
    row = db.execute("SELECT batch_id, plan FROM queued_runs WHERE (? || '-R' || seq) = ?",
                     (press_id, run_id)).fetchone()
    if row is None:
        raise KeyError('unknown_run')
    batch_id, body = row
    return QueuedRun(run_id, batch_id, press_id, plan_from_record(json.loads(body)))


def get_sheet_work(db: sqlite3.Connection, run_id: str, number: int) -> SheetWork:
    row = db.execute('SELECT stage, pending_request FROM sheet_work WHERE run_id = ? AND number = ?',
                     (run_id, number)).fetchone()
    if row is None:
        raise RunConflict('unknown_sheet_work')
    return SheetWork(number, DuplexStage(row[0]), row[1])


def reserve_next_action(db: sqlite3.Connection, run_id: str, request_id: str) -> SheetWork:
    row = db.execute('''SELECT number, stage FROM sheet_work
                        WHERE run_id = ? AND pending_request IS NULL AND stage != ?
                        ORDER BY number LIMIT 1''', (run_id, DuplexStage.EJECTED.value)).fetchone()
    if row is None:
        pending = db.execute('SELECT 1 FROM sheet_work WHERE run_id = ? AND stage != ? LIMIT 1',
                             (run_id, DuplexStage.EJECTED.value)).fetchone()
        raise RunConflict('no_available_action' if pending else 'run_complete')
    number, stage = row
    db.execute('UPDATE sheet_work SET pending_request = ? WHERE run_id = ? AND number = ?',
               (request_id, run_id, number))
    return SheetWork(number, DuplexStage(stage), request_id)


def settle_action(db: sqlite3.Connection, run_id: str, number: int,
                  request_id: str, stage: DuplexStage):
    work = get_sheet_work(db, run_id, number)
    if work.pending_request != request_id:
        raise RunConflict('action_not_reserved')
    validate_stage_result(work.stage, stage)
    db.execute('UPDATE sheet_work SET stage = ?, pending_request = NULL WHERE run_id = ? AND number = ?',
               (stage.value, run_id, number))
