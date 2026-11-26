from dataclasses import dataclass
import sqlite3

from desk.batches import DeskBatch, DeskConflict, get_batch
from desk.press_client import PressClient


@dataclass(frozen=True)
class BatchProgress:
    batch_id: str
    press_id: str | None
    run_id: str | None
    actual: tuple[dict, ...]
    missing: tuple[int, ...]


def partition_actual_sheets(batch: DeskBatch, events: list[dict]) -> BatchProgress:
    planned = {sheet.number for sheet in batch.plan.sheets}
    actual = {}
    ejection_ids = set()
    if not isinstance(events, list):
        raise DeskConflict('invalid_run_evidence')
    for event in events:
        if not isinstance(event, dict):
            raise DeskConflict('invalid_run_evidence')
        number = event.get('number')
        ejection_id = event.get('ejection_id')
        if (event.get('batch_id') != batch.batch_id or event.get('press_id') != batch.press_id
                or event.get('run_id') != batch.run_id or type(number) is not int
                or number not in planned or number in actual
                or not isinstance(ejection_id, str) or not ejection_id or ejection_id in ejection_ids):
            raise DeskConflict('invalid_run_evidence')
        actual[number] = event
        ejection_ids.add(ejection_id)
    return BatchProgress(batch.batch_id, batch.press_id, batch.run_id,
                         tuple(actual[number] for number in sorted(actual)),
                         tuple(sorted(planned.difference(actual))))


def read_progress(db: sqlite3.Connection, client: PressClient, batch_id: str) -> BatchProgress:
    batch = get_batch(db, batch_id)
    events = []
    if batch.run_id is not None:
        remote = client.read_run(batch.press_id, batch.run_id)
        if (remote.get('batch_id'), remote.get('press_id'), remote.get('run_id')) != (
                batch.batch_id, batch.press_id, batch.run_id):
            raise DeskConflict('invalid_run_evidence')
        events = remote.get('actual')
    return partition_actual_sheets(batch, events)
