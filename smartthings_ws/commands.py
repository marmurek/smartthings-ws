"""Turning a command into resource writes.

Each requested field becomes one write. Fields whose requested value is already
the appliance's state are left out, so an empty plan means nothing to change.
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional

from smartthings_ws.connection import Resources
from smartthings_ws.errors import InvalidCommand
from smartthings_ws.models import ApplianceUpdate, ApplianceView, Kind, MachineState
from smartthings_ws.state import DA, OPERATIONAL_STATE, POWER, POWER_VENDOR, REFRIGERATION, TEMPERATURES
from smartthings_ws.state import as_float, temperature_item

OPERATION_STATES = {"start": "Run", "pause": "Pause", "stop": "Ready"}
OPERATION_RESULTS = {"start": MachineState.RUNNING, "pause": MachineState.PAUSED, "stop": MachineState.IDLE}
OPERABLE_KINDS = (Kind.WASHER, Kind.DRYER, Kind.OVEN, Kind.MICROWAVE)


@dataclass(frozen=True)
class Write:
    """One resource update"""

    href: str
    body: dict[str, Any]


def _power(resources: Resources, value: bool) -> Write:
    """Switch the appliance on or off, preferring the standard resource"""
    if POWER in resources:
        return Write(POWER, {"value": value})
    if POWER_VENDOR in resources:
        return Write(POWER_VENDOR, {DA + "power": "On" if value else "Off"})
    raise InvalidCommand("this appliance cannot be switched on or off")


def _operation(view: ApplianceView, resources: Resources, value: str) -> Optional[Write]:
    """Start, pause or stop the selected programme"""
    if view.kind not in OPERABLE_KINDS or OPERATIONAL_STATE not in resources:
        raise InvalidCommand(f"a {view.kind.value} has no programme to {value}")
    if view.machine_state is OPERATION_RESULTS[value]:
        return None
    return Write(OPERATIONAL_STATE, {DA + "state": OPERATION_STATES[value]})


def _setpoint(resources: Resources, compartment: str, value: int) -> Write:
    """Set one fridge compartment's temperature within its range"""
    item = temperature_item(resources, compartment)
    if item is None or item.get(DA + "id") is None:
        raise InvalidCommand(f"this appliance has no {compartment.lower()} compartment")

    low, high = as_float(item.get(DA + "minimum")), as_float(item.get(DA + "maximum"))
    if low is not None and high is not None and not low <= value <= high:
        raise InvalidCommand(f"the {compartment.lower()} accepts {low:g}..{high:g} °C, not {value}")

    return Write(TEMPERATURES, {DA + "items": [{DA + "id": item.get(DA + "id"), DA + "desired": str(value)}]})


def _rapid(resources: Resources, key: str, value: bool) -> Write:
    """Switch rapid cooling or rapid freezing"""
    if DA + key not in resources.get(REFRIGERATION, {}):
        raise InvalidCommand("this appliance has no rapid cooling or freezing")
    return Write(REFRIGERATION, {DA + key: "On" if value else "Off"})


def plan_writes(view: ApplianceView, resources: Resources, update: ApplianceUpdate) -> list[Write]:
    """The writes that bring the appliance to the requested state.

    Settings go before the operation, so a programme starts with them applied.
    Every field is validated before anything is sent.
    """
    steps: list[tuple[Any, Any, Callable[[Any], Optional[Write]]]] = [
        (update.power, view.power, lambda v: _power(resources, v)),
        (update.fridge_target, view.fridge_target, lambda v: _setpoint(resources, "Fridge", v)),
        (update.freezer_target, view.freezer_target, lambda v: _setpoint(resources, "Freezer", v)),
        (update.rapid_cooling, view.rapid_cooling, lambda v: _rapid(resources, "rapidFridge", v)),
        (update.rapid_freezing, view.rapid_freezing, lambda v: _rapid(resources, "rapidFreezing", v)),
        (update.operation, None, lambda v: _operation(view, resources, v)),
    ]

    writes = []
    for requested, current, build in steps:
        if requested is None:
            continue
        write = build(requested)
        if write is not None and requested != current:
            writes.append(write)
    return writes
