from dataclasses import dataclass

from editions.paper import Rect
from editions.proofs import DuplexProof
from layout.numbering import NumberedSheet


@dataclass(frozen=True)
class FrontPlacement:
    print_number: str
    mark_id: str
    art: Rect
    number_box: Rect
    mark_box: Rect


def place_front(proof: DuplexProof, sheet: NumberedSheet, revision_id: str) -> FrontPlacement:
    mark_id = f'{revision_id}-{sheet.text}'
    return FrontPlacement(sheet.text, mark_id, proof.front_art,
                          proof.template.number_box, proof.template.mark_box)
