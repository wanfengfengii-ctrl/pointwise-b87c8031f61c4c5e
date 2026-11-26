from dataclasses import dataclass

from press.duplex import DuplexStage, RunConflict, can_eject
from press.simulator import DeviceAction, DeviceResult, SimulatedPress


@dataclass(frozen=True)
class EjectionRecord:
    ejection_id: str
    action_id: str
    batch_id: str
    run_id: str
    press_id: str
    number: int


def eject_sheet(device: SimulatedPress, action: DeviceAction, current: DuplexStage) -> DeviceResult:
    if action.stage != DuplexStage.EJECTED or not can_eject(current):
        raise RunConflict('duplex_required_for_ejection')
    result = device.execute(action)
    if not result.ejection_id:
        raise RunConflict('missing_ejection_result')
    return result


def read_actual_ejections(device: SimulatedPress, run_id: str) -> tuple[EjectionRecord, ...]:
    events = device.ejection_events(run_id)
    return tuple(EjectionRecord(**event) for event in sorted(events, key=lambda event: event['number']))
