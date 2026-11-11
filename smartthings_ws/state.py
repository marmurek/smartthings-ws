"""Reading an appliance's state out of its resources.

Values come from Samsung's vendor resources (`/.../vs/0`, keys prefixed
`x.com.samsung.da.`), which carry every number as a string, and from the
standard OCF resources where those are the only source.
"""

import json
import re
from typing import Any, Optional

from smartthings_ws.connection import Resources
from smartthings_ws.models import ApplianceView, CookMode, Kind, MachineState

DA = "x.com.samsung.da."

OPERATIONAL_STATE = "/operational/state/vs/0"
ENERGY = "/energy/consumption/vs/0"
POWER = "/power/0"
POWER_VENDOR = "/power/vs/0"
REMOTE_CONTROL = "/remotectrl/vs/0"
KIDS_LOCK = "/kidslock/0"
DOORS = "/doors/vs/0"
COOLER_DOOR = "/door/cooler/0"
FREEZER_DOOR = "/door/freezer/0"
WASHER = "/washer/vs/0"
COURSE = "/course/vs/0"
# The SmartThings spelling of the selected programme, naming its code table.
COURSE_TABLES = ("/st/washercourse/vs/0", "/st/dryercourse/vs/0")
REFRIGERATION = "/refrigeration/vs/0"
TEMPERATURES = "/temperatures/vs/0"
OVEN = "/oven/vs/0"
MODE = "/mode/vs/0"
ALARMS = "/alarms/vs/0"
FIRMWARE = "/otninformation/vs/0"
DEMAND_RESPONSE = "/drlc/vs/0"
BUZZER = "/buzzersound/vs/0"
WATER = "/water/consumption/vs/0"
AI_LEVEL = "/energy/ailevel/vs/0"
SELF_CHECK = "/selfcheck/vs/0"
DOOR_ALERT = "/settings/sound/alert/door/vs/0"
STATUS_LOCK = "/status/lock/vs/0"

# The modeSpec control of a mode a remote may start, not only adjust.
START_CONTROL = "Start&Setting"

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


def _option_name(entry: Any) -> Any:
    """What an options entry sets: `Course` of `Course_2B`"""
    return entry.split("_", 1)[0] if isinstance(entry, str) else entry


def merge_notification(held: dict[str, Any], rep: dict[str, Any]) -> dict[str, Any]:
    """A representation with a notification applied.

    A notification carries only the keys that changed, and of an options list
    only the entries that changed, e.g. the dryer's `/course/vs/0` notifies
    `["Course_2B"]` alone. Each entry replaces the held one of the same name.
    """
    merged = {**held, **rep}
    old, new = held.get(DA + "options"), rep.get(DA + "options")
    if isinstance(old, list) and isinstance(new, list):
        changed = {_option_name(e): e for e in new}
        kept = [changed.pop(_option_name(e), e) for e in old]
        merged[DA + "options"] = kept + list(changed.values())
    return merged


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


def _option_bool(resources: Resources, href: str, prefix: str) -> Optional[bool]:
    """An `Prefix_On` / `Prefix_Off` entry of an options list"""
    return on_off(option(resources, href, prefix))


def _alarms(resources: Resources) -> Optional[list[str]]:
    """The codes of the alarms that are firing.

    The list also holds a placeholder per alarm type the board supports,
    coded `<Name>_OFF` while that alarm is not firing, and rows marked
    Deleted after an alarm cleared; neither is an alarm.
    """
    if ALARMS not in resources:
        return None
    items = vendor(resources, ALARMS, "items")
    if items is None:
        # Laundry boards leave the resource empty while no alarm fires.
        return []
    if not isinstance(items, list):
        return None
    return [
        str(item[DA + "code"])
        for item in items
        if isinstance(item, dict)
        and item.get(DA + "code")
        and str(item.get(DA + "state", "")).lower() != "deleted"
        and not str(item[DA + "code"]).lower().endswith("_off")
    ]


def text(value: Any) -> Optional[str]:
    """A value the API reports as a string, None if the appliance sent anything else"""
    return value if isinstance(value, str) else None


def _string_list(value: Any) -> Optional[list[str]]:
    """A list the appliance sent, as strings"""
    return [str(v) for v in value] if isinstance(value, list) else None


def _setting(value: Any) -> Optional[str]:
    """A laundry programme setting; `None` is what a programme without that setting reports"""
    return None if value == "None" else text(value)


def _choices(value: Any) -> Optional[list[str]]:
    """The values a setting offers, without the `None` placeholder the laundry lists start with"""
    values = _string_list(value)
    return None if values is None else [v for v in values if v != "None"]


def _int_list(value: Any) -> Optional[list[int]]:
    """A list of numbers the appliance sent as strings, skipping the ones that are not"""
    if not isinstance(value, list):
        return None
    return [n for n in (as_int(v) for v in value) if n is not None]


def _modes(resources: Resources) -> list[str]:
    """The active entries of the vendor mode resource"""
    modes = vendor(resources, MODE, "modes")
    return [m for m in modes if isinstance(m, str)] if isinstance(modes, list) else []


def _mode_token(resources: Resources, prefix: str) -> Optional[str]:
    """The value of the active `PREFIX_VALUE` mode"""
    return next((m[len(prefix) :] for m in _modes(resources) if m.startswith(prefix)), None)


def _drum_clean_due_in(resources: Resources) -> Optional[int]:
    """Cycles left until the drum clean the appliance recommends.

    `DrumCleanProposal_N` is the interval in cycles and `WashingTimes_N` the
    cycles since the last clean.
    """
    interval = as_int(option(resources, COURSE, "DrumCleanProposal_"))
    done = as_int(option(resources, COURSE, "WashingTimes_"))
    return None if interval is None or done is None else max(interval - done, 0)


def _drum_clean_last(resources: Resources) -> Optional[str]:
    """The time of the last drum clean; a dryer keeps the whole history joined with `|`"""
    log = option(resources, COURSE, "DrumCleanLog_")
    return log.rsplit("|", 1)[-1] if log else None


def _water_liters(resources: Resources) -> Optional[float]:
    """The lifetime water counter, which the appliance keeps in millilitres"""
    value = as_float(vendor(resources, WATER, "cumulativeWater"))
    return None if value is None else round(value / 1000, 1)


def _energy_saved_kwh(resources: Resources) -> Optional[float]:
    """The lifetime energy saved by the energy saving features, in kWh"""
    value = as_float(vendor(resources, ENERGY, "cumulativeSavedPower"))
    return None if value is None else round(value / 1000, 2)


def _sound(resources: Resources, kind: Kind) -> Optional[bool]:
    """Whether the appliance beeps; each family keeps it elsewhere"""
    if kind in (Kind.WASHER, Kind.DRYER):
        return on_off(resources.get(BUZZER, {}).get("setBuzzerSound"))
    if kind is Kind.FRIDGE:
        return on_off(vendor(resources, STATUS_LOCK, "device.sound"))
    return _option_bool(resources, MODE, "Sound_")


def _common(resources: Resources, kind: Kind) -> dict[str, Any]:
    """The fields every kind of appliance may have"""
    return {
        "power": _power(resources),
        "remote_control": on_off(vendor(resources, REMOTE_CONTROL, "remoteControlEnabled")),
        "child_lock": on_off(resources.get(KIDS_LOCK, {}).get("value")),
        "door_open": _door_open(resources),
        "power_w": _power_w(resources),
        "energy_kwh": _energy_kwh(resources),
        "energy_saved_kwh": _energy_saved_kwh(resources),
        "sound": _sound(resources, kind),
        "alarms": _alarms(resources),
        "firmware_update_available": on_off(vendor(resources, FIRMWARE, "newVersionAvailable")),
        "demand_response_level": as_int(vendor(resources, DEMAND_RESPONSE, "drlcLevel")),
        "machine_state": _machine_state(resources),
        "job": _job(resources),
        "progress": as_int(vendor(resources, OPERATIONAL_STATE, "progressPercentage")),
        "remaining_minutes": minutes(vendor(resources, OPERATIONAL_STATE, "remainingTime")),
    }


def _course_table(resources: Resources) -> Optional[str]:
    """The table the programme codes belong to; the same code names another programme in another table"""
    return next((t for t in (text(vendor(resources, href, "st.courseTable")) for href in COURSE_TABLES) if t), None)


def _laundry(resources: Resources) -> dict[str, Any]:
    """The fields washers and dryers share"""
    return {
        "course": option(resources, COURSE, "Course_"),
        "course_table": _course_table(resources),
        "delay_finish_minutes": minutes(vendor(resources, OPERATIONAL_STATE, "delayEndTime")),
        "drum_clean_due_in": _drum_clean_due_in(resources),
        "drum_clean_last": _drum_clean_last(resources),
    }


def _washer(resources: Resources) -> dict[str, Any]:
    """A washer's programme settings, detergent dosing and water use"""
    return {
        "water_temperature": _setting(vendor(resources, WASHER, "waterTemperature")),
        "spin_level": _setting(vendor(resources, WASHER, "spinLevel")),
        "rinse_cycles": as_int(vendor(resources, WASHER, "rinseCycles")),
        "supported_water_temperatures": _choices(vendor(resources, WASHER, "supportedWaterTemperature")),
        "supported_spin_levels": _choices(vendor(resources, WASHER, "supportedSpinLevel")),
        "supported_rinse_cycles": _int_list(vendor(resources, WASHER, "supportedRinseCycles")),
        "detergent_dose": as_int(option(resources, COURSE, "DetergentLevelCtrl_")),
        "softener_dose": as_int(option(resources, COURSE, "SoftenerLevelCtrl_")),
        "detergent_low": _dosing_low(option(resources, COURSE, "DetergentAlarm_")),
        "softener_low": _dosing_low(option(resources, COURSE, "SoftenerAlarm_")),
        "water_liters": _water_liters(resources),
    }


def _dosing_low(value: Optional[str]) -> Optional[bool]:
    """A detergent or softener alarm, which is `Off` unless the tank runs low"""
    return None if value is None else value != "Off"


def _dryer(resources: Resources) -> dict[str, Any]:
    """A dryer's programme settings"""
    supported_times = vendor(resources, WASHER, "supportedDryTime")
    return {
        "dry_level": _setting(vendor(resources, WASHER, "dryLevel")),
        "supported_dry_levels": _choices(vendor(resources, WASHER, "supportedDryLevel")),
        "dry_time_minutes": minutes(vendor(resources, WASHER, "dryTime")),
        "supported_dry_times": (
            [m for m in (minutes(t) for t in supported_times) if m is not None]
            if isinstance(supported_times, list)
            else None
        ),
        "wrinkle_prevent": on_off(vendor(resources, WASHER, "wrinklePrevent")),
        "drum_light": _option_bool(resources, COURSE, "DrumLight_"),
    }


def _fridge(resources: Resources) -> dict[str, Any]:
    """A fridge's compartments, modes and diagnostics"""
    fridge = temperature_item(resources, "Fridge")
    freezer = temperature_item(resources, "Freezer")
    vacation = _mode_token(resources, "RVACATION_")
    errors = _string_list(vendor(resources, SELF_CHECK, "error"))
    door_alert = resources.get(DOOR_ALERT, {})
    doors = [_door_open(resources, href) for href in (COOLER_DOOR, FREEZER_DOOR)]
    return {
        # The fridge notifies changes of its OCF door resources, not of the
        # vendor list the other kinds report their door in.
        "door_open": None if None in doors else any(doors),
        "fridge_temperature": _item_value(fridge, "current"),
        "fridge_target": _item_value(fridge, "desired"),
        "fridge_range": _item_range(fridge),
        "freezer_temperature": _item_value(freezer, "current"),
        "freezer_target": _item_value(freezer, "desired"),
        "freezer_range": _item_range(freezer),
        "fridge_door_open": doors[0],
        "freezer_door_open": doors[1],
        "rapid_cooling": on_off(vendor(resources, REFRIGERATION, "rapidFridge")),
        "rapid_freezing": on_off(vendor(resources, REFRIGERATION, "rapidFreezing")),
        "vacation_mode": None if vacation is None else vacation == "ON",
        "convertible_zone": (_mode_token(resources, "FCONVERT_") or "").lower() or None,
        "energy_saving_level": as_int(resources.get(AI_LEVEL, {}).get("aiLevel")),
        "supported_energy_saving_levels": _int_list(resources.get(AI_LEVEL, {}).get("supportedAiLevel")),
        "door_alarm_volume": as_int(door_alert.get("alert.door")),
        "supported_door_alarm_volumes": _int_list(door_alert.get("supportedAlert.door")),
        "self_check_result": text(vendor(resources, SELF_CHECK, "result")),
        "self_check_errors": None if errors is None else [e for e in errors if e != "ErrorCode_None"],
    }


def _item_range(item: Optional[dict[str, Any]]) -> Optional[list[float]]:
    """The minimum and maximum of a compartment's setpoint"""
    low, high = _item_value(item, "minimum"), _item_value(item, "maximum")
    return None if low is None or high is None else [low, high]


def _cook_mode(entry: Any) -> Optional[CookMode]:
    """One modeSpec entry as a mode a cook can start in, None if it cannot or declares no limits"""
    if not isinstance(entry, dict) or entry.get("control") != START_CONTROL or not isinstance(entry.get("mode"), str):
        return None
    limits = {
        "temperature_min": as_int(entry.get("tempMinC")),
        "temperature_max": as_int(entry.get("tempMaxC")),
        "temperature_default": as_int(entry.get("tempDefaultC")),
        "temperature_step": as_int(entry.get("tempIntervalC")) or 1,
        "minutes_min": minutes(entry.get("timeMin")),
        "minutes_max": minutes(entry.get("timeMax")),
        "minutes_default": minutes(entry.get("timeDefault")),
    }
    if None in limits.values():
        return None
    return CookMode(mode=entry["mode"], **limits)


def _cook_modes(resources: Resources) -> Optional[list[CookMode]]:
    """The modes a cook can be started in now.

    modeSpec, a JSON string, declares per mode whether a remote may start it
    and within which limits. It lists the modes of every cavity layout, so
    only the ones in supportedModes, which follows the divider, are offered.
    """
    raw = vendor(resources, MODE, "modeSpec")
    oven = temperature_item(resources, "Temperature")
    if not isinstance(raw, str) or oven is None or oven.get(DA + "unit") != "Celsius":
        return None
    try:
        spec = json.loads(raw)
    except ValueError:
        return None
    live = _string_list(vendor(resources, MODE, "supportedModes")) or []
    modes = [_cook_mode(entry) for entry in spec] if isinstance(spec, list) else []
    return [m for m in modes if m is not None and m.mode in live]


def _cooking(resources: Resources) -> dict[str, Any]:
    """An oven's or microwave's cooking state, timer and steam system"""
    oven = temperature_item(resources, "Temperature")
    supported = _string_list(vendor(resources, MODE, "supportedModes"))
    drain = option(resources, MODE, "drainRequired_")
    return {
        "oven_mode": _oven_mode(resources),
        "supported_modes": None if supported is None else [m for m in supported if m != "NoOperation"],
        "default_mode": text(vendor(resources, MODE, "defaultMode")),
        "cook_modes": _cook_modes(resources),
        "oven_temperature": as_int(oven.get(DA + "current")) if oven else None,
        "oven_target": as_int(oven.get(DA + "desired")) if oven else None,
        "elapsed_minutes": minutes(vendor(resources, OPERATIONAL_STATE, "operationTime")),
        "lamp": _option_bool(resources, MODE, "UpperLamp_"),
        "fast_preheat": _option_bool(resources, MODE, "fastpreheat_"),
        "timer_set": as_int(option(resources, MODE, "UpperTimerSet_")),
        "timer_remaining": as_int(option(resources, MODE, "UpperTimerCurrent_")),
        "timer_state": option(resources, MODE, "UpperTimerState_"),
        "steam_generator_level": option(resources, MODE, "steamGeneratorLevel_"),
        "steam_state": option(resources, MODE, "steamState_"),
        "water_inlet": option(resources, MODE, "waterInlet_"),
        "drain_required": None if drain is None else drain.strip("0") != "",
        "descale_state": option(resources, MODE, "descaleState_"),
        "descale_alarm": option(resources, MODE, "descaleAlarm_"),
        "descale_new_water_alarm": _option_bool(resources, MODE, "descaleNewWaterAlarm_"),
        "descale_empty_water_alarm": _option_bool(resources, MODE, "descaleEmptyWaterAlarm_"),
    }


def read_view(name: str, host: str, resources: Resources) -> ApplianceView:
    """Express an appliance's resources as the API reports them"""
    kind = detect_kind(resources)
    fields = _common(resources, kind)
    if kind in (Kind.WASHER, Kind.DRYER):
        fields |= _laundry(resources)
    if kind is Kind.WASHER:
        fields |= _washer(resources)
    if kind is Kind.DRYER:
        fields |= _dryer(resources)
    if kind is Kind.FRIDGE:
        fields |= _fridge(resources)
    if kind in (Kind.OVEN, Kind.MICROWAVE):
        fields |= _cooking(resources)
    return ApplianceView(name=name, host=host, kind=kind, available=True, **fields)
