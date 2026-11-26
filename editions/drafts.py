from dataclasses import dataclass

from editions.paper import PaperSpec, Rect, parse_paper_spec, parse_rect, require_fields


@dataclass(frozen=True)
class EditionDraft:
    draft_id: str
    paper: PaperSpec
    flip: str
    front_art: Rect
    back_art: Rect


def parse_draft(data) -> EditionDraft:
    require_fields(data, 'draft_id', 'paper', 'flip', 'front_art', 'back_art')
    draft_id = data['draft_id']
    if not isinstance(draft_id, str) or not draft_id.strip() or len(draft_id) > 80:
        raise ValueError('invalid_draft_id')
    if data['flip'] not in ('long', 'short'):
        raise ValueError('invalid_flip')
    return EditionDraft(draft_id, parse_paper_spec(data['paper']), data['flip'],
                        parse_rect(data['front_art']), parse_rect(data['back_art']))
