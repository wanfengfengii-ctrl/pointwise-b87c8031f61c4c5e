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
    history: tuple[dict, ...] | None = None
    retired: tuple[str, ...] | None = None

    def to_record(self) -> dict:
        record = {'batch_id': self.batch_id, 'press_id': self.press_id, 'run_id': self.run_id,
                  'actual': [dict(event) for event in self.actual],
                  'missing': list(self.missing)}
        if self.retired:
            record['history'] = [dict(event) for event in self.history or ()]
            record['retired'] = list(self.retired)
        return record


def partition_actual_sheets(batch: DeskBatch, events: list[dict],
                            retired: object = ()) -> BatchProgress:
    planned = {sheet.number for sheet in batch.plan.sheets}
    if not isinstance(events, list):
        raise DeskConflict('invalid_run_evidence')
    if retired is None:
        retired = ()
    if not isinstance(retired, (list, tuple)) or not all(
            isinstance(item, str) and item for item in retired):
        raise DeskConflict('invalid_run_evidence')
    retired_ids = tuple(retired)
    retired_set = set(retired_ids)
    if len(retired_set) != len(retired_ids):
        raise DeskConflict('invalid_run_evidence')
    history: list[dict] = []
    seen_ejections = set()
    current: dict[int, dict] = {}
    for event in events:
        if not isinstance(event, dict):
            raise DeskConflict('invalid_run_evidence')
        number = event.get('number')
        ejection_id = event.get('ejection_id')
        if (event.get('batch_id') != batch.batch_id or event.get('press_id') != batch.press_id
                or event.get('run_id') != batch.run_id or type(number) is not int
                or number not in planned
                or not isinstance(ejection_id, str) or not ejection_id
                or ejection_id in seen_ejections):
            raise DeskConflict('invalid_run_evidence')
        seen_ejections.add(ejection_id)
        history.append(event)
        if ejection_id in retired_set:
            continue
        if number in current:
            raise DeskConflict('invalid_run_evidence')
        current[number] = event
    if not retired_set.issubset(seen_ejections):
        raise DeskConflict('invalid_run_evidence')
    return BatchProgress(batch.batch_id, batch.press_id, batch.run_id,
                         tuple(current[number] for number in sorted(current)),
                         tuple(sorted(planned.difference(current))),
                         tuple(history) if retired_ids else None,
                         retired_ids or None)


def read_progress(db: sqlite3.Connection, client: PressClient, batch_id: str) -> BatchProgress:
    batch = get_batch(db, batch_id)
    events = []
    retired: object = ()
    if batch.run_id is not None:
        remote = client.read_run(batch.press_id, batch.run_id)
        if (remote.get('batch_id'), remote.get('press_id'), remote.get('run_id')) != (
                batch.batch_id, batch.press_id, batch.run_id):
            raise DeskConflict('invalid_run_evidence')
        events = remote.get('actual')
        retired = remote.get('retired', ())
    return partition_actual_sheets(batch, events, retired)
