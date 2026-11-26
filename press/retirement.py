"""Retirement of a returned original sheet and its single reprint.

The press keeps retirement facts next to its queued runs so the desk can read
them back over the ordinary ``GET /runs/{id}`` route.  Retiring a sheet clears
that number's duplex work so the same run can print it again; physical ejection
events are never deleted, they only stop participating in current coverage.
"""
import json
import sqlite3

from press.duplex import DuplexStage, RunConflict
from press.queue import read_queued_run
from press.simulator import SimulatedPress


def init_retirement(db: sqlite3.Connection):
    db.execute('''CREATE TABLE IF NOT EXISTS retired_sheets (
        seq INTEGER PRIMARY KEY, run_id TEXT NOT NULL, number INTEGER NOT NULL,
        ejection_id TEXT NOT NULL UNIQUE, request_id TEXT NOT NULL UNIQUE,
        UNIQUE(run_id, number)
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS retire_requests (
        request_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
        ejection_id TEXT NOT NULL, result TEXT NOT NULL
    )''')


def read_retired(db: sqlite3.Connection, run_id: str) -> list[str]:
    rows = db.execute('SELECT ejection_id FROM retired_sheets WHERE run_id = ? ORDER BY seq',
                      (run_id,)).fetchall()
    return [row[0] for row in rows]


def retire_sheet(db: sqlite3.Connection, device: SimulatedPress, run_id: str,
                 request_id: str, ejection_id: str) -> dict:
    run = read_queued_run(db, device.press_id, run_id)
    events = device.ejection_events(run_id)
    with db:
        db.execute('BEGIN IMMEDIATE')
        prior = db.execute('''SELECT run_id, ejection_id, result FROM retire_requests
                              WHERE request_id = ?''', (request_id,)).fetchone()
        if prior is not None:
            original_run, original_ejection, result = prior
            if (original_run, original_ejection) != (run_id, ejection_id):
                raise RunConflict('retire_request_conflict')
            return json.loads(result)
        event = next((item for item in events if item['ejection_id'] == ejection_id), None)
        if event is None or event['run_id'] != run_id or event['batch_id'] != run.batch_id:
            raise RunConflict('sheet_not_in_run')
        number = event['number']
        if db.execute('SELECT 1 FROM retired_sheets WHERE ejection_id = ?',
                      (ejection_id,)).fetchone() is not None:
            raise RunConflict('sheet_already_retired')
        if db.execute('SELECT 1 FROM retired_sheets WHERE run_id = ? AND number = ?',
                      (run_id, number)).fetchone() is not None:
            raise RunConflict('sheet_already_retired')
        if db.execute('SELECT 1 FROM sheet_work WHERE run_id = ? AND number = ?',
                      (run_id, number)).fetchone() is None:
            raise RunConflict('unknown_sheet_work')
        result = {'request_id': request_id, 'run_id': run_id, 'batch_id': run.batch_id,
                  'press_id': device.press_id, 'number': number, 'ejection_id': ejection_id}
        db.execute('''INSERT INTO retire_requests(request_id, run_id, ejection_id, result)
                      VALUES (?, ?, ?, ?)''',
                   (request_id, run_id, ejection_id, json.dumps(result, sort_keys=True)))
        db.execute('''INSERT INTO retired_sheets(run_id, number, ejection_id, request_id)
                      VALUES (?, ?, ?, ?)''', (run_id, number, ejection_id, request_id))
        db.execute('''UPDATE sheet_work SET stage = ?, pending_request = NULL
                      WHERE run_id = ? AND number = ?''', (DuplexStage.QUEUED.value, run_id, number))
    return result
