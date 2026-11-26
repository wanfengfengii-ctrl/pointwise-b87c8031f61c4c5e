"""Desk-side handling of a confirmed return of an out-of-tolerance sheet.

A scrap request is only accepted for a sheet that the press physically ejected
from this batch's run, and only once per original sheet.  The desk keeps its own
receipt so that replaying the same request (same request id and parameters)
re-delivers the first success, and so that an answer lost in transit can be
resumed after a restart.  The press remains the authority on which ejections are
already retired; the desk only refuses early when it can prove a conflict.
"""
import sqlite3

from delivery.release import get_issued_batch
from desk.batches import DeskConflict, get_batch
from desk.press_client import PressClient, PressResponseError
from desk.receipts import (
    drop_scrap_intent, get_scrap_request, save_scrap_intent, save_scrap_result,
)


def _run_evidence(client: PressClient, batch):
    remote = client.read_run(batch.press_id, batch.run_id)
    if (remote.get('batch_id'), remote.get('press_id'), remote.get('run_id')) != (
            batch.batch_id, batch.press_id, batch.run_id):
        raise DeskConflict('invalid_run_evidence')
    events = remote.get('actual')
    if not isinstance(events, list) or not all(isinstance(item, dict) for item in events):
        raise DeskConflict('invalid_run_evidence')
    retired = remote.get('retired', ())
    if not isinstance(retired, (list, tuple)) or not all(
            isinstance(item, str) and item for item in retired):
        raise DeskConflict('invalid_run_evidence')
    return events, frozenset(retired)


def scrap_batch(db: sqlite3.Connection, client: PressClient, batch_id: str,
                request_id: str, ejection_id: str, deviation_mm: int) -> dict:
    # Phase 1: local identity and precondition checks, before any press call.
    with db:
        db.execute('BEGIN IMMEDIATE')
        batch = get_batch(db, batch_id)
        request = get_scrap_request(db, request_id)
        if request is not None:
            if (request.batch_id, request.ejection_id, request.deviation_mm) != (
                    batch_id, ejection_id, deviation_mm):
                raise DeskConflict('scrap_request_conflict')
            # A saved result is re-delivered even after the batch later signed
            # out; an unresolved intent, however, loses to the signed-out sheet.
            if request.result is not None:
                return request.result
        else:
            if type(deviation_mm) is not int or abs(deviation_mm) <= batch.plan.tolerance_mm:
                raise ValueError('scrap_deviation_out_of_tolerance')
        if batch.run_id is None:
            raise DeskConflict('sheet_not_in_batch')
        if get_issued_batch(db, batch_id) is not None:
            raise DeskConflict('sheet_already_issued')

    # Phase 2: prove the paper belongs to this batch and is still returnable.
    events, retired = _run_evidence(client, batch)
    event = next((item for item in events if item.get('ejection_id') == ejection_id), None)
    planned = {sheet.number for sheet in batch.plan.sheets}
    if event is None or event.get('number') not in planned:
        raise DeskConflict('sheet_not_in_batch')
    number = event['number']
    if request is None:
        retired_numbers = {item.get('number') for item in events
                           if item.get('ejection_id') in retired}
        if ejection_id in retired or number in retired_numbers:
            raise DeskConflict('sheet_already_retired')

    # Phase 3: record the intent, then let the press commit the retirement.
    with db:
        db.execute('BEGIN IMMEDIATE')
        current = get_scrap_request(db, request_id)
        if current is not None and current.result is not None:
            return current.result
        if get_issued_batch(db, batch_id) is not None:
            raise DeskConflict('sheet_already_issued')
        if current is None:
            save_scrap_intent(db, request_id, batch_id, ejection_id, deviation_mm)
    try:
        result = client.retire(batch.press_id, batch.run_id, request_id, ejection_id)
    except PressResponseError as exc:
        if exc.status in (404, 409, 422):
            # A definite refusal: the press will not act on this request, so the
            # intent must not linger.  Other statuses (notably 503) may still be
            # in flight, so keep it for the same-request replay to resume.
            with db:
                db.execute('BEGIN IMMEDIATE')
                drop_scrap_intent(db, request_id)
        raise
    if (result.get('batch_id'), result.get('press_id'), result.get('run_id'),
            result.get('number'), result.get('ejection_id')) != (
                batch.batch_id, batch.press_id, batch.run_id, number, ejection_id):
        raise DeskConflict('invalid_run_evidence')
    with db:
        db.execute('BEGIN IMMEDIATE')
        save_scrap_result(db, request_id, result)
    return result
