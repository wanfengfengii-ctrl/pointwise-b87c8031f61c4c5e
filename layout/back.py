from dataclasses import dataclass

from editions.paper import Rect
from editions.proofs import DuplexProof
from layout.front import FrontPlacement


@dataclass(frozen=True)
class BackPlacement:
    print_number: str
    mark_id: str
    art: Rect
    number_box: Rect
    mark_box: Rect


def place_back(proof: DuplexProof, front: FrontPlacement) -> BackPlacement:
    return BackPlacement(front.print_number, front.mark_id, **proof.back_rectangles())
