from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class PaperSpec:
    width: int
    height: int
    margins: tuple[int, int, int, int]


def require_fields(data, *names):
    if not isinstance(data, dict) or data.keys() != set(names):
        raise ValueError('invalid_fields')
    return data


def require_integer(value, minimum, error):
    if type(value) is not int or value < minimum:
        raise ValueError(error)
    return value


def parse_rect(data):
    require_fields(data, 'x', 'y', 'w', 'h')
    return Rect(*(require_integer(data[key], minimum, 'invalid_rectangle')
                  for key, minimum in [('x', 0), ('y', 0), ('w', 1), ('h', 1)]))


def parse_paper_spec(data):
    require_fields(data, 'width', 'height', 'margins')
    width = require_integer(data['width'], 1, 'invalid_paper')
    height = require_integer(data['height'], 1, 'invalid_paper')
    margins = data['margins']
    if not isinstance(margins, (list, tuple)) or len(margins) != 4:
        raise ValueError('invalid_margins')
    left, top, right, bottom = (require_integer(n, 0, 'invalid_margins') for n in margins)
    if left + right >= width or top + bottom >= height:
        raise ValueError('empty_printable_area')
    return PaperSpec(width, height, (left, top, right, bottom))


def fits_printable(paper: PaperSpec, rect: Rect) -> bool:
    left, top, right, bottom = paper.margins
    return (rect.w > 0 and rect.h > 0 and left <= rect.x and top <= rect.y
            and rect.x + rect.w <= paper.width - right
            and rect.y + rect.h <= paper.height - bottom)


def flip_rect(paper: PaperSpec, rect: Rect, flip: str) -> Rect:
    if flip not in ('long', 'short'):
        raise ValueError('invalid_flip')
    vertical_axis = (paper.width <= paper.height) == (flip == 'long')
    if vertical_axis:
        return Rect(paper.width - rect.x - rect.w, rect.y, rect.w, rect.h)
    return Rect(rect.x, paper.height - rect.y - rect.h, rect.w, rect.h)
