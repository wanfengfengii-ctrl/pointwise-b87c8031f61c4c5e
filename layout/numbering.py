from dataclasses import dataclass

from editions.paper import require_integer


@dataclass(frozen=True)
class NumberedSheet:
    number: int
    text: str


def format_print_number(number: int) -> str:
    require_integer(number, 1, 'invalid_number_range')
    if number > 999_999:
        raise ValueError('invalid_number_range')
    return f'{number:03d}'


def build_number_range(start: int, count: int) -> tuple[NumberedSheet, ...]:
    require_integer(start, 1, 'invalid_number_range')
    require_integer(count, 1, 'invalid_number_range')
    if count > 500 or start + count - 1 > 999_999:
        raise ValueError('invalid_number_range')
    return tuple(NumberedSheet(number, format_print_number(number))
                 for number in range(start, start + count))
