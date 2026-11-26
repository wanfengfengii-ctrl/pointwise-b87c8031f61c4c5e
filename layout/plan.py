from dataclasses import asdict, dataclass

from editions.paper import parse_rect, require_fields, require_integer
from editions.releases import EditionRevision
from layout.back import BackPlacement, place_back
from layout.front import FrontPlacement, place_front
from layout.numbering import build_number_range


@dataclass(frozen=True)
class PlannedSheet:
    number: int
    print_number: str
    front: FrontPlacement
    back: BackPlacement


@dataclass(frozen=True)
class SheetPlan:
    revision_id: str
    fingerprint: str
    start: int
    count: int
    tolerance_mm: int
    sheets: tuple[PlannedSheet, ...]


def build_sheet_plan(revision: EditionRevision, start: int, count: int) -> SheetPlan:
    sheets = []
    for number in build_number_range(start, count):
        front = place_front(revision.proof, number, revision.revision_id)
        sheets.append(PlannedSheet(number.number, number.text, front, place_back(revision.proof, front)))
    return SheetPlan(revision.revision_id, revision.fingerprint, start, count,
                     revision.proof.template.tolerance_mm, tuple(sheets))


def plan_to_record(plan: SheetPlan) -> dict:
    record = asdict(plan)
    record['sheets'] = list(record['sheets'])
    return record


def _read_face(face, placement, number, mark_id):
    require_fields(face, 'print_number', 'mark_id', 'art', 'number_box', 'mark_box')
    if face['print_number'] != number or face['mark_id'] != mark_id:
        raise ValueError('invalid_plan_identity')
    return placement(number, mark_id, parse_rect(face['art']),
                     parse_rect(face['number_box']), parse_rect(face['mark_box']))


def plan_from_record(record) -> SheetPlan:
    require_fields(record, 'revision_id', 'fingerprint', 'start', 'count', 'tolerance_mm', 'sheets')
    revision_id = record['revision_id']
    fingerprint = record['fingerprint']
    if not isinstance(revision_id, str) or not revision_id:
        raise ValueError('invalid_plan_revision')
    if (not isinstance(fingerprint, str) or len(fingerprint) != 64
            or any(char not in '0123456789abcdef' for char in fingerprint)):
        raise ValueError('invalid_plan_fingerprint')
    numbers = build_number_range(record['start'], record['count'])
    rows = record['sheets']
    if not isinstance(rows, list) or len(rows) != len(numbers):
        raise ValueError('invalid_plan_coverage')
    sheets = []
    for row, number in zip(rows, numbers):
        require_fields(row, 'number', 'print_number', 'front', 'back')
        if (type(row['number']) is not int or row['number'] != number.number
                or row['print_number'] != number.text):
            raise ValueError('invalid_plan_order')
        mark_id = f'{revision_id}-{number.text}'
        front = _read_face(row['front'], FrontPlacement, number.text, mark_id)
        back = _read_face(row['back'], BackPlacement, number.text, mark_id)
        sheets.append(PlannedSheet(number.number, number.text, front, back))
    tolerance = require_integer(record['tolerance_mm'], 0, 'invalid_tolerance')
    return SheetPlan(revision_id, fingerprint, record['start'], record['count'], tolerance, tuple(sheets))
