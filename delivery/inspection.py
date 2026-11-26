from dataclasses import asdict
import sqlite3

from delivery.coverage import MatchedSheet, match_batch_coverage
from delivery.release import IssuedSheet, issue_batch
from desk.batches import get_batch
from desk.press_client import PressClient
from desk.progress import read_progress


def verify_registration(matches: tuple[MatchedSheet, ...], tolerance_mm: int):
    if any(abs(sheet.deviation_mm) > tolerance_mm for sheet in matches):
        raise ValueError('registration_out_of_tolerance')


def inspect_batch(db: sqlite3.Connection, client: PressClient, batch_id: str, measurements):
    batch = get_batch(db, batch_id)
    progress = read_progress(db, client, batch_id)
    matches = match_batch_coverage(batch, progress, measurements)
    verify_registration(matches, batch.plan.tolerance_mm)
    sheets = tuple(IssuedSheet(**asdict(sheet)) for sheet in matches)
    return issue_batch(db, batch_id, batch.plan.revision_id, sheets)
