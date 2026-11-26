from dataclasses import dataclass

from editions.drafts import EditionDraft
from editions.paper import (
    PaperSpec, Rect, fits_printable, flip_rect, parse_paper_spec, parse_rect,
    require_fields, require_integer,
)


@dataclass(frozen=True)
class ProofTemplate:
    number_box: Rect
    mark_box: Rect
    tolerance_mm: int

    @classmethod
    def from_record(cls, data):
        require_fields(data, 'number_box', 'mark_box', 'tolerance_mm')
        return cls(parse_rect(data['number_box']), parse_rect(data['mark_box']),
                   require_integer(data['tolerance_mm'], 0, 'invalid_tolerance'))


@dataclass(frozen=True)
class DuplexProof:
    paper: PaperSpec
    flip: str
    front_art: Rect
    back_art: Rect
    template: ProofTemplate

    @classmethod
    def from_record(cls, data):
        return cls(parse_paper_spec(data['paper']), data['flip'],
                   parse_rect(data['front_art']), parse_rect(data['back_art']),
                   ProofTemplate.from_record(data['template']))

    def back_rectangles(self):
        return {name: flip_rect(self.paper, rect, self.flip)
                for name, rect in [('art', self.back_art),
                                   ('number_box', self.template.number_box),
                                   ('mark_box', self.template.mark_box)]}


def build_proof(draft: EditionDraft, template: ProofTemplate) -> DuplexProof:
    proof = DuplexProof(draft.paper, draft.flip, draft.front_art, draft.back_art, template)
    front_rectangles = (proof.front_art, template.number_box, template.mark_box)
    if not all(fits_printable(proof.paper, rect) for rect in front_rectangles):
        raise ValueError('front_outside_printable_area')
    if not all(fits_printable(proof.paper, rect) for rect in proof.back_rectangles().values()):
        raise ValueError('back_outside_printable_area')
    return proof
