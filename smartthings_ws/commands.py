"""Turning a command into resource writes.

Each requested field becomes one write. Fields whose requested value is already
the appliance's state are left out, so an empty plan means nothing to change.
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional

from smartthings_ws.connection import DEVICE_COLLECTION, Resources
from smartthings_ws.errors import InvalidCommand
from smartthings_ws.models import ApplianceUpdate, ApplianceView, CookStart, Kind, MachineState
from smartthings_ws.state import (
    AI_LEVEL,
    BUZZER,
    DA,
    DOOR_ALERT,
    MODE,
    OPERATIONAL_STATE,
    POWER,
    POWER_VENDOR,
    REFRIGERATION,
    STATUS_LOCK,
    TEMPERATURES,
    WASHER,
    as_float,
    option,
    temperature_item,
)

OPERATION_STATES = {"start": "Run", "pause": "Pause", "stop": "Ready"}
OPERATION_RESULTS = {"start": MachineState.RUNNING, "pause": MachineState.PAUSED, "stop": MachineState.IDLE}
OPERABLE_KINDS = (Kind.WASHER, Kind.DRYER, Kind.OVEN, Kind.MICROWAVE)


@dataclass(frozen=True)
class Write:
    """One resource update"""

    href: str
    # A representation, or a list of them for a write to a collection.
    body: dict[str, Any] | list[dict[str, Any]]


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


def _on_off(value: bool) -> str:
    """A flag as the vendor resources spell it"""
    return "On" if value else "Off"


def _duration(minutes: int) -> str:
    """Whole minutes as the HH:MM:SS the appliances use"""
    return f"{minutes // 60:02d}:{minutes % 60:02d}:00"


def _one_of(name: str, value: Any, supported: Optional[list[Any]]) -> None:
    """Refuse a value outside the list the appliance reports"""
    if supported is None:
        raise InvalidCommand(f"this appliance has no {name}")
    if value not in supported:
        raise InvalidCommand(f"{name} accepts {', '.join(str(s) for s in supported)}, not {value}")


def _sound(view: ApplianceView, resources: Resources, value: bool) -> Write:
    """Switch the sounds, which each family keeps in its own resource"""
    if view.kind in (Kind.WASHER, Kind.DRYER):
        if BUZZER not in resources:
            raise InvalidCommand(f"this {view.kind.value} has no buzzer setting")
        return Write(BUZZER, {"setBuzzerSound": _on_off(value)})
    if view.kind is Kind.FRIDGE:
        if STATUS_LOCK not in resources:
            raise InvalidCommand("this fridge has no sound setting")
        return Write(STATUS_LOCK, {DA + "device.sound": _on_off(value)})
    if view.kind in (Kind.OVEN, Kind.MICROWAVE):
        return _mode_option(resources, "Sound", value)
    raise InvalidCommand(f"a {view.kind.value} appliance has no sound setting")


def _mode_option(resources: Resources, prefix: str, value: bool) -> Write:
    """Switch an On/Off entry of an oven's options list.

    The appliance merges the entries it is sent into the list, so the write
    carries the changed entry alone.
    """
    if option(resources, MODE, prefix + "_") is None:
        raise InvalidCommand(f"this appliance has no {prefix} option")
    return Write(MODE, {DA + "options": [f"{prefix}_{_on_off(value)}"]})


def _laundry_setting(view: ApplianceView, kind: Kind, key: str, value: str) -> Write:
    """Change one setting of the selected laundry programme"""
    if view.kind is not kind:
        raise InvalidCommand(f"a {view.kind.value} has no {key}")
    return Write(WASHER, {DA + key: value})


def _delay(view: ApplianceView, value: int) -> Write:
    """Delay the end of the selected laundry programme"""
    if view.delay_finish_minutes is None:
        raise InvalidCommand(f"a {view.kind.value} cannot delay its programme")
    return Write(OPERATIONAL_STATE, {DA + "delayEndTime": _duration(value)})


def _energy_saving(view: ApplianceView, value: int) -> Write:
    """Set the fridge's AI energy saving level"""
    _one_of("energy saving level", value, view.supported_energy_saving_levels)
    return Write(AI_LEVEL, {"aiLevel": str(value)})


def _door_alarm(view: ApplianceView, value: int) -> Write:
    """Set the volume of the fridge's open door alarm"""
    _one_of("door alarm volume", value, view.supported_door_alarm_volumes)
    return Write(DOOR_ALERT, {"alert.door": str(value)})


def _washer_setting(view: ApplianceView, key: str, value: Any, supported: Optional[list[Any]]) -> Write:
    """Change a washer setting to one of the values the appliance offers"""
    _one_of(key, value, supported)
    return _laundry_setting(view, Kind.WASHER, key, str(value))


def _dry_level(view: ApplianceView, value: str) -> Write:
    """Set how dry a dryer programme leaves the laundry"""
    _one_of("dry level", value, view.supported_dry_levels)
    return _laundry_setting(view, Kind.DRYER, "dryLevel", value)


def _dry_time(view: ApplianceView, value: int) -> Write:
    """Set the drying time of a timed programme"""
    _one_of("dry time", value, view.supported_dry_times)
    return _laundry_setting(view, Kind.DRYER, "dryTime", _duration(value))


def _cook(view: ApplianceView, cook: CookStart) -> Write:
    """Start a cook in one write to the device collection.

    Written one resource at a time from idle, the mode, setpoint and cooking
    time are accepted and then discarded. With Remote Control off the
    appliance answers 2.04 and silently drops the start, so that is refused
    here.
    """
    mode = next((m for m in view.cook_modes or [] if m.mode == cook.mode), None)
    if mode is None:
        offered = ", ".join(m.mode for m in view.cook_modes or []) or "none"
        raise InvalidCommand(f"this appliance cannot start a cook in {cook.mode}; it offers {offered}")
    if view.remote_control is not True:
        raise InvalidCommand("Remote Control is off on the appliance's panel")
    if view.machine_state is not MachineState.IDLE or view.oven_mode is not None:
        raise InvalidCommand("the appliance is already cooking")

    temperature = mode.temperature_default if cook.temperature is None else cook.temperature
    if not mode.temperature_min <= temperature <= mode.temperature_max:
        raise InvalidCommand(
            f"{mode.mode} accepts {mode.temperature_min}..{mode.temperature_max} °C, not {temperature}"
        )
    if (temperature - mode.temperature_min) % mode.temperature_step:
        raise InvalidCommand(f"{mode.mode} sets the temperature in steps of {mode.temperature_step} °C")
    duration = mode.minutes_default if cook.minutes is None else cook.minutes
    if not mode.minutes_min <= duration <= mode.minutes_max:
        raise InvalidCommand(f"{mode.mode} cooks {mode.minutes_min}..{mode.minutes_max} minutes, not {duration}")

    setpoint = {DA + "id": "0", DA + "desired": str(temperature), DA + "unit": "Celsius"}
    return Write(
        "/" + "/".join(DEVICE_COLLECTION),
        [
            {"href": "/devices/0"},
            {"href": MODE, "rep": {DA + "modes": [mode.mode]}},
            {"href": TEMPERATURES, "rep": {DA + "items": [setpoint]}},
            {"href": OPERATIONAL_STATE, "rep": {DA + "operationTime": _duration(duration), DA + "state": "Run"}},
        ],
    )


def plan_writes(view: ApplianceView, resources: Resources, update: ApplianceUpdate) -> list[Write]:
    """The writes that bring the appliance to the requested state.

    Power goes first and the operation last, so a programme starts with the
    settings applied. Every field is validated before anything is sent.
    """
    steps: list[tuple[Any, Any, Callable[[Any], Optional[Write]]]] = [
        (update.power, view.power, lambda v: _power(resources, v)),
        (update.fridge_target, view.fridge_target, lambda v: _setpoint(resources, "Fridge", v)),
        (update.freezer_target, view.freezer_target, lambda v: _setpoint(resources, "Freezer", v)),
        (update.rapid_cooling, view.rapid_cooling, lambda v: _rapid(resources, "rapidFridge", v)),
        (update.rapid_freezing, view.rapid_freezing, lambda v: _rapid(resources, "rapidFreezing", v)),
        (update.energy_saving_level, view.energy_saving_level, lambda v: _energy_saving(view, v)),
        (update.door_alarm_volume, view.door_alarm_volume, lambda v: _door_alarm(view, v)),
        (update.sound, view.sound, lambda v: _sound(view, resources, v)),
        (update.lamp, view.lamp, lambda v: _mode_option(resources, "UpperLamp", v)),
        (update.fast_preheat, view.fast_preheat, lambda v: _mode_option(resources, "fastpreheat", v)),
        (
            update.water_temperature,
            view.water_temperature,
            lambda v: _washer_setting(view, "waterTemperature", v, view.supported_water_temperatures),
        ),
        (
            update.spin_level,
            view.spin_level,
            lambda v: _washer_setting(view, "spinLevel", v, view.supported_spin_levels),
        ),
        (
            update.rinse_cycles,
            view.rinse_cycles,
            lambda v: _washer_setting(view, "rinseCycles", v, view.supported_rinse_cycles),
        ),
        (
            update.dry_level,
            view.dry_level,
            lambda v: _dry_level(view, v),
        ),
        (update.dry_time_minutes, view.dry_time_minutes, lambda v: _dry_time(view, v)),
        (
            update.wrinkle_prevent,
            view.wrinkle_prevent,
            lambda v: _laundry_setting(view, Kind.DRYER, "wrinklePrevent", _on_off(v)),
        ),
        (update.delay_finish_minutes, view.delay_finish_minutes, lambda v: _delay(view, v)),
        (update.operation, None, lambda v: _operation(view, resources, v)),
        (update.cook, None, lambda v: _cook(view, v)),
    ]

    writes = []
    for requested, current, build in steps:
        if requested is None:
            continue
        write = build(requested)
        if write is not None and requested != current:
            writes.append(write)
    return writes
