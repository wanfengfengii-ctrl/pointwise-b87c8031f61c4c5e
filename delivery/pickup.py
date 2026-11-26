import sqlite3

from delivery.release import get_issued_batch
from desk.batches import DeskConflict
from desk.press_client import PressClient
from desk.progress import read_progress


def pickup_batch(db: sqlite3.Connection, client: PressClient, batch_id: str):
    issued = get_issued_batch(db, batch_id)
    if issued is not None:
        return issued
    progress = read_progress(db, client, batch_id)
    if progress.missing:
        raise DeskConflict('incomplete')
    raise DeskConflict('not_inspected')
