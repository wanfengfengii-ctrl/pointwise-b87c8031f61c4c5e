import sqlite3

from desk.batches import DeskConflict, bind_press, get_batch, record_run_ref
from desk.press_client import PressClient
from desk.receipts import get_dispatch_request, save_dispatch_intent, save_dispatch_result
from layout.plan import plan_to_record


def dispatch_batch(db: sqlite3.Connection, client: PressClient, batch_id: str,
                   press_id: str, request_id: str) -> dict:
    with db:
        db.execute('BEGIN IMMEDIATE')
        batch = get_batch(db, batch_id)
        request = get_dispatch_request(db, request_id)
        if request is not None:
            if (request.batch_id, request.press_id) != (batch_id, press_id):
                raise DeskConflict('dispatch_request_conflict')
            if request.result is not None:
                return request.result
        if not client.knows_press(press_id):
            raise KeyError('unknown_press')
        bind_press(db, batch, press_id)
        if request is None:
            save_dispatch_intent(db, request_id, batch_id, press_id)

    if batch.run_id is None:
        remote = client.enqueue(press_id, batch_id, plan_to_record(batch.plan))
        if remote.get('batch_id') != batch_id or remote.get('press_id') != press_id:
            raise DeskConflict('run_reference_conflict')
        run_id = remote.get('run_id')
        if not isinstance(run_id, str) or not run_id:
            raise DeskConflict('run_reference_conflict')
    else:
        run_id = batch.run_id
    result = {'batch_id': batch_id, 'press_id': press_id, 'run_id': run_id}
    with db:
        db.execute('BEGIN IMMEDIATE')
        record_run_ref(db, batch_id, press_id, run_id)
        save_dispatch_result(db, request_id, result)
    return result
