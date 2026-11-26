from dataclasses import asdict, dataclass
import json
import sqlite3

from press.duplex import DuplexStage, RunConflict, next_stage, validate_stage_result
from press.ejection import eject_sheet, read_actual_ejections
from press.queue import get_sheet_work, read_queued_run, reserve_next_action, settle_action
from press.simulator import DeviceAction, SimulatedPress


@dataclass(frozen=True)
class AdvanceReceipt:
    request_id: str
    run_id: str
    number: int
    stage: DuplexStage
    action_id: str
    ejection_id: str | None
    actual: list[dict]


def init_runs(db: sqlite3.Connection):
    db.execute('''CREATE TABLE IF NOT EXISTS advance_requests (
        request_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, number INTEGER NOT NULL,
        stage TEXT NOT NULL, action_id TEXT NOT NULL UNIQUE, result TEXT
    )''')


def _read_request(db, request_id):
    return db.execute('''SELECT run_id, number, stage, action_id, result FROM advance_requests
                         WHERE request_id = ?''', (request_id,)).fetchone()


def _actual(device, run_id):
    return [asdict(record) for record in read_actual_ejections(device, run_id)]


def advance_run(db: sqlite3.Connection, device: SimulatedPress, run_id: str, request_id: str) -> dict:
    with db:
        db.execute('BEGIN IMMEDIATE')
        run = read_queued_run(db, device.press_id, run_id)
        prior = _read_request(db, request_id)
        if prior is None:
            work = reserve_next_action(db, run_id, request_id)
            stage = next_stage(work.stage)
            action_id = f'{run_id}/{work.number}/{stage.value}/{request_id}'
            db.execute('''INSERT INTO advance_requests(request_id, run_id, number, stage, action_id)
                          VALUES (?, ?, ?, ?, ?)''', (request_id, run_id, work.number, stage.value, action_id))
        else:
            original_run, number, target, action_id, response = prior
            if original_run != run_id:
                raise RunConflict('advance_request_conflict')
            if response is not None:
                return json.loads(response)
            work = get_sheet_work(db, run_id, number)
            stage = DuplexStage(target)
            if work.pending_request != request_id:
                raise RunConflict('action_not_reserved')
            validate_stage_result(work.stage, stage)

    sheet = run.plan.sheets[work.number - run.plan.start]
    placement = None
    if stage == DuplexStage.FRONT:
        placement = asdict(sheet.front)
    elif stage == DuplexStage.BACK:
        placement = asdict(sheet.back)
    action = DeviceAction(action_id, run.batch_id, run_id, request_id, work.number, stage, placement)
    if stage == DuplexStage.EJECTED:
        result = eject_sheet(device, action, work.stage)
    else:
        result = device.execute(action)
    if result.action_id != action_id or result.stage != stage:
        raise RunConflict('device_result_conflict')

    with db:
        db.execute('BEGIN IMMEDIATE')
        saved = _read_request(db, request_id)[4]
        if saved is not None:
            return json.loads(saved)
        settle_action(db, run_id, work.number, request_id, result.stage)
        receipt = AdvanceReceipt(request_id, run_id, work.number, result.stage,
                                 action_id, result.ejection_id, _actual(device, run_id))
        response = asdict(receipt)
        db.execute('UPDATE advance_requests SET result = ? WHERE request_id = ?',
                   (json.dumps(response), request_id))
    return response


def read_run_result(db: sqlite3.Connection, device: SimulatedPress, run_id: str) -> dict:
    run = read_queued_run(db, device.press_id, run_id)
    return {**run.reference(), 'actual': _actual(device, run_id)}
