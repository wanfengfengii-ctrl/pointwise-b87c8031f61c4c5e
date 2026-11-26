from enum import StrEnum


class RunConflict(RuntimeError):
    pass


class DuplexStage(StrEnum):
    QUEUED = 'queued'
    FRONT = 'front'
    BACK = 'back'
    EJECTED = 'ejected'


_SUCCESSOR = {
    DuplexStage.QUEUED: DuplexStage.FRONT,
    DuplexStage.FRONT: DuplexStage.BACK,
    DuplexStage.BACK: DuplexStage.EJECTED,
}


def next_stage(current: DuplexStage) -> DuplexStage | None:
    return _SUCCESSOR.get(current)


def validate_stage_result(current: DuplexStage, completed: DuplexStage):
    if next_stage(current) != completed or completed is None:
        raise RunConflict('illegal_duplex_transition')


def can_eject(current: DuplexStage) -> bool:
    return current == DuplexStage.BACK
