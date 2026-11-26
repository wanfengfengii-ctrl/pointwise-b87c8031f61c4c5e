from dataclasses import dataclass

from desk.batches import DeskBatch, DeskConflict
from desk.progress import BatchProgress


@dataclass(frozen=True)
class MatchedSheet:
    number: int
    print_number: str
    press_id: str
    run_id: str
    ejection_id: str
    deviation_mm: int


def match_batch_coverage(batch: DeskBatch, progress: BatchProgress, measurements) -> tuple[MatchedSheet, ...]:
    if progress.missing:
        raise DeskConflict('incomplete')
    if progress.batch_id != batch.batch_id or not isinstance(measurements, list):
        raise DeskConflict('measurement_coverage')
    by_ejection = {}
    for entry in measurements:
        if not isinstance(entry, dict) or entry.keys() != {'ejection_id', 'deviation_mm'}:
            raise DeskConflict('measurement_coverage')
        ejection_id, deviation = entry['ejection_id'], entry['deviation_mm']
        if (not isinstance(ejection_id, str) or not ejection_id or ejection_id in by_ejection
                or type(deviation) is not int):
            raise DeskConflict('measurement_coverage')
        by_ejection[ejection_id] = deviation
    evidence = {event['number']: event for event in progress.actual}
    if (evidence.keys() != {sheet.number for sheet in batch.plan.sheets}
            or by_ejection.keys() != {event['ejection_id'] for event in evidence.values()}):
        raise DeskConflict('measurement_coverage')
    matches = []
    for sheet in batch.plan.sheets:
        event = evidence[sheet.number]
        ejection_id = event['ejection_id']
        matches.append(MatchedSheet(sheet.number, sheet.print_number, event['press_id'],
                                    event['run_id'], ejection_id, by_ejection[ejection_id]))
    return tuple(matches)
