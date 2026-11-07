"""Reading an appliance's state out of its resources.

Values come from Samsung's vendor resources (`/.../vs/0`, keys prefixed
`x.com.samsung.da.`), which carry every number as a string, and from the
standard OCF resources where those are the only source.
"""

import re
from typing import Any, Optional

from smartthings_ws.connection import Resources
from smartthings_ws.models import ApplianceView, Kind, MachineState

DA = "x.com.samsung.da."

OPERATIONAL_STATE = "/operational/state/vs/0"
ENERGY = "/energy/consumption/vs/0"
POWER = "/power/0"
POWER_VENDOR = "/power/vs/0"
REMOTE_CONTROL = "/remotectrl/vs/0"
KIDS_LOCK = "/kidslock/0"
DOORS = "/doors/vs/0"
WASHER = "/washer/vs/0"
COURSE = "/course/vs/0"
REFRIGERATION = "/refrigeration/vs/0"
TEMPERATURES = "/temperatures/vs/0"
OVEN = "/oven/vs/0"
MODE = "/mode/vs/0"

# The firmware reports this when it has no power reading.
NO_POWER_READING = -500

MACHINE_STATES = {"Ready": MachineState.IDLE, "Run": MachineState.RUNNING, "Pause": MachineState.PAUSED}

DURATION = re.compile(r"(\d+):(\d{2}):(\d{2})")


def vendor(resources: Resources, href: str, key: str) -> Any:
    """One value of a vendor resource, None if it is absent"""
    return resources.get(href, {}).get(DA + key)


def as_int(value: Any) -> Optional[int]:
    """A number the appliance sent as a string"""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def as_float(value: Any) -> Optional[float]:
    """A decimal number the appliance sent as a string"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def on_off(value: Any) -> Optional[bool]:
    """An On/Off or true/false flag"""
    if value in ("On", "true", True):
        return True
    if value in ("Off", "false", False):
        return False
    return None


def minutes(value: Any) -> Optional[int]:
    """An HH:MM:SS duration in whole minutes"""
    match = DURATION.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        return None
    hours, mins, _seconds = (int(g) for g in match.groups())
    return hours * 60 + mins


def option(resources: Resources, href: str, prefix: str) -> Optional[str]:
    """The value of a `Prefix_Value` entry in a resource's options list"""
    options = vendor(resources, href, "options")
    if not isinstance(options, list):
        return None
    return next((o[len(prefix) :] for o in options if isinstance(o, str) and o.startswith(prefix)), None)


def detect_kind(resources: Resources) -> Kind:
    """What the appliance is, from the resources only that kind exposes"""
    if REFRIGERATION in resources:
        return Kind.FRIDGE
    if WASHER in resources:
        return Kind.DRYER if DA + "dryLevel" in resources[WASHER] else Kind.WASHER
    if OVEN in resources:
        modes = vendor(resources, MODE, "supportedModes") or []
        return Kind.MICROWAVE if "MicroWave" in modes else Kind.OVEN
    return Kind.UNKNOWN


def temperature_item(resources: Resources, description: str) -> Optional[dict[str, Any]]:
    """One compartment of the vendor temperatures resource, by its description"""
    items = vendor(resources, TEMPERATURES, "items")
    if not isinstance(items, list):
        return None
    return next((i for i in items if isinstance(i, dict) and i.get(DA + "description") == description), None)


def _item_value(item: Optional[dict[str, Any]], key: str) -> Optional[float]:
    """One value of a temperatures item"""
    return as_float(item.get(DA + key)) if item is not None else None


def _power(resources: Resources) -> Optional[bool]:
    """The power state, preferring the standard resource"""
    if POWER in resources:
        value = resources[POWER].get("value")
        return value if isinstance(value, bool) else None
    return on_off(vendor(resources, POWER_VENDOR, "power"))


def _door_open(resources: Resources, href: Optional[str] = None) -> Optional[bool]:
    """Whether a door is open: one OCF door resource, or any door of the vendor list"""
    if href is not None:
        state = resources.get(href, {}).get("openState")
        return None if state is None else state == "Open"

    items = vendor(resources, DOORS, "items")
    if not isinstance(items, list):
        return None
    return any(isinstance(i, dict) and i.get(DA + "openState") == "Open" for i in items)


def _power_w(resources: Resources) -> Optional[float]:
    """The instantaneous power draw, None while the appliance does not measure it"""
    value = as_float(vendor(resources, ENERGY, "instantaneousPower"))
    return None if value is None or value <= NO_POWER_READING else value


def _energy_kwh(resources: Resources) -> Optional[float]:
    """The lifetime energy counter in kWh"""
    value = as_float(vendor(resources, ENERGY, "cumulativePower"))
    return None if value is None else round(value / 1000, 2)


def _job(resources: Resources) -> Optional[str]:
    """The phase of the running programme"""
    value = vendor(resources, OPERATIONAL_STATE, "progress")
    return value if isinstance(value, str) and value != "None" else None


def _oven_mode(resources: Resources) -> Optional[str]:
    """The cooking mode, None while the oven is not cooking"""
    modes = vendor(resources, MODE, "modes")
    if not isinstance(modes, list) or not modes or modes[0] == "NoOperation":
        return None
    return str(modes[0])


def _machine_state(resources: Resources) -> Optional[MachineState]:
    """Whether a programme is running"""
    state = vendor(resources, OPERATIONAL_STATE, "state")
    return MACHINE_STATES.get(state) if isinstance(state, str) else None


def read_view(name: str, host: str, resources: Resources) -> ApplianceView:
    """Express an appliance's resources as the API reports them"""
    kind = detect_kind(resources)
    view = ApplianceView(
        name=name,
        host=host,
        kind=kind,
        available=True,
        power=_power(resources),
        remote_control=on_off(vendor(resources, REMOTE_CONTROL, "remoteControlEnabled")),
        child_lock=on_off(resources.get(KIDS_LOCK, {}).get("value")),
        door_open=_door_open(resources),
        power_w=_power_w(resources),
        energy_kwh=_energy_kwh(resources),
        machine_state=_machine_state(resources),
        job=_job(resources),
        progress=as_int(vendor(resources, OPERATIONAL_STATE, "progressPercentage")),
        remaining_minutes=minutes(vendor(resources, OPERATIONAL_STATE, "remainingTime")),
    )

    if kind in (Kind.WASHER, Kind.DRYER):
        view.course = option(resources, COURSE, "Course_")
    if kind is Kind.WASHER:
        view.water_temperature = vendor(resources, WASHER, "waterTemperature")
        view.spin_level = vendor(resources, WASHER, "spinLevel")
        view.rinse_cycles = as_int(vendor(resources, WASHER, "rinseCycles"))
    if kind is Kind.DRYER:
        view.dry_level = vendor(resources, WASHER, "dryLevel")
        view.wrinkle_prevent = on_off(vendor(resources, WASHER, "wrinklePrevent"))

    if kind is Kind.FRIDGE:
        fridge = temperature_item(resources, "Fridge")
        freezer = temperature_item(resources, "Freezer")
        view.fridge_temperature = _item_value(fridge, "current")
        view.fridge_target = _item_value(fridge, "desired")
        view.freezer_temperature = _item_value(freezer, "current")
        view.freezer_target = _item_value(freezer, "desired")
        view.fridge_door_open = _door_open(resources, "/door/cooler/0")
        view.freezer_door_open = _door_open(resources, "/door/freezer/0")
        view.rapid_cooling = on_off(vendor(resources, REFRIGERATION, "rapidFridge"))
        view.rapid_freezing = on_off(vendor(resources, REFRIGERATION, "rapidFreezing"))

    if kind in (Kind.OVEN, Kind.MICROWAVE):
        oven = temperature_item(resources, "Temperature")
        view.oven_mode = _oven_mode(resources)
        view.oven_temperature = as_int(oven.get(DA + "current")) if oven else None
        view.oven_target = as_int(oven.get(DA + "desired")) if oven else None
        view.lamp = on_off(option(resources, MODE, "UpperLamp_"))

    return view
