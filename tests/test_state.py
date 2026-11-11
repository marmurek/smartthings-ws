"""Reading appliance state out of resources."""

from typing import Any, Optional

import pytest

from smartthings_ws.models import Kind, MachineState
from smartthings_ws.state import detect_kind, merge_notification, minutes, read_view
from tests.fixtures import DA, resources


@pytest.mark.parametrize("kind", ["fridge", "washer", "dryer", "oven", "microwave"])
def test_detect_kind(kind: str) -> None:
    """Test that each appliance is recognised by its resources"""
    assert detect_kind(resources(kind)) is Kind(kind)


def test_detect_kind_unknown() -> None:
    """Test that an appliance with none of the known resources is unknown"""
    assert detect_kind({"/power/0": {"value": True}}) is Kind.UNKNOWN


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (
            "fridge",
            {
                "power": None,
                "door_open": False,
                "power_w": 3.0,
                "energy_kwh": 424.87,
                "fridge_temperature": 4.0,
                "fridge_target": 3.0,
                "freezer_temperature": -18.0,
                "freezer_target": -18.0,
                "fridge_door_open": False,
                "freezer_door_open": False,
                "rapid_cooling": False,
                "rapid_freezing": False,
                "machine_state": None,
                "course": None,
            },
        ),
        (
            "washer",
            {
                "power": False,
                "remote_control": False,
                "child_lock": False,
                "power_w": None,
                "energy_kwh": 304.2,
                "machine_state": MachineState.IDLE,
                "job": None,
                "progress": 1,
                "remaining_minutes": 169,
                "course": "1C",
                "water_temperature": "40",
                "spin_level": "1400",
                "rinse_cycles": 2,
                "dry_level": None,
                "fridge_target": None,
            },
        ),
        (
            "dryer",
            {
                "power": True,
                "machine_state": MachineState.RUNNING,
                "job": "AIDrying",
                "progress": 57,
                "remaining_minutes": 28,
                "course": "29",
                "dry_level": "Normal",
                "wrinkle_prevent": False,
                "water_temperature": None,
            },
        ),
        (
            "oven",
            {
                "power": False,
                "remote_control": False,
                "door_open": False,
                "machine_state": MachineState.IDLE,
                "oven_mode": None,
                "oven_temperature": 0,
                "oven_target": 0,
                "lamp": False,
            },
        ),
        ("microwave", {"power": False, "oven_temperature": None, "lamp": False, "remote_control": None}),
    ],
)
def test_read_view(kind: str, expected: dict[str, Any]) -> None:
    """Test that each appliance's fields are read from its resources"""
    view = read_view(kind, "10.0.0.1", resources(kind))

    assert view.name == kind and view.host == "10.0.0.1" and view.kind is Kind(kind) and view.available
    assert {name: getattr(view, name) for name in expected} == expected


@pytest.mark.parametrize(
    ("changes", "field", "expected"),
    [
        ({"mode_vs_0": {DA + "modes": ["UpperConvection"]}}, "oven_mode", "UpperConvection"),
        ({"mode_vs_0": {DA + "options": ["UpperLamp_On"]}}, "lamp", True),
        ({"mode_vs_0": {DA + "options": "broken"}}, "lamp", None),
        ({"doors_vs_0": {DA + "items": [{DA + "openState": "Open"}]}}, "door_open", True),
        ({"doors_vs_0": {DA + "items": None}}, "door_open", None),
        ({"temperatures_vs_0": {DA + "items": None}}, "oven_temperature", None),
        ({"power_vs_0": {DA + "power": "Unknown"}}, "power", None),
        ({"operational_state_vs_0": {DA + "state": "Pause"}}, "machine_state", MachineState.PAUSED),
        ({"operational_state_vs_0": {DA + "state": 5}}, "machine_state", None),
        ({"operational_state_vs_0": {DA + "progressPercentage": "n/a"}}, "progress", None),
        ({"energy_consumption_vs_0": {DA + "instantaneousPower": "1200"}}, "power_w", 1200.0),
    ],
)
def test_read_view_variants(changes: dict[str, Any], field: str, expected: Any) -> None:
    """Test that unusual values of the oven's resources read as expected"""
    view = read_view("oven", "10.0.0.1", resources("oven", **changes))

    assert getattr(view, field) == expected


@pytest.mark.parametrize(
    ("changes", "field", "expected"),
    [
        ({"power_0": {"value": "yes"}}, "power", None),
        ({"energy_consumption_vs_0": {DA + "cumulativePower": None}}, "energy_kwh", None),
        ({"course_vs_0": {DA + "options": [1, "Course_20"]}}, "course", "20"),
        ({"door_freezer_0": {"openState": "Open"}}, "freezer_door_open", True),
    ],
)
def test_read_view_other_variants(changes: dict[str, Any], field: str, expected: Any) -> None:
    """Test that unusual values of laundry and fridge resources read as expected"""
    kind = "fridge" if field == "freezer_door_open" else "washer"
    view = read_view(kind, "10.0.0.1", resources(kind, **changes))

    assert getattr(view, field) == expected


def test_read_view_fridge_without_compartments() -> None:
    """Test that a fridge without the vendor temperatures resource reports no temperatures"""
    fridge = resources("fridge")
    del fridge["/temperatures/vs/0"]

    assert read_view("fridge", "10.0.0.1", fridge).fridge_temperature is None


@pytest.mark.parametrize(
    ("value", "expected"), [("02:49:00", 169), ("00:00:59", 0), ("2:05:00", 125), ("", None), (None, None)]
)
def test_minutes(value: Any, expected: Any) -> None:
    """Test that HH:MM:SS durations read as whole minutes"""
    assert minutes(value) == expected


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (
            "washer",
            {
                "sound": True,
                "alarms": [],
                "firmware_update_available": False,
                "demand_response_level": 2,
                "energy_saved_kwh": 62.69,
                "delay_finish_minutes": 0,
                "drum_clean_due_in": 28,
                "drum_clean_last": "2026-11-03T15:34:56",
                "detergent_dose": 2,
                "softener_dose": 2,
                "detergent_low": False,
                "softener_low": False,
                "water_liters": 19311.7,
                "supported_water_temperatures": ["Cold", "20", "30", "40", "60", "90"],
                "supported_spin_levels": ["RinseHold", "NoSpin", "400", "800", "1000", "1200", "1400"],
                "supported_rinse_cycles": [0, 1, 2, 3, 4, 5],
            },
        ),
        (
            "dryer",
            {
                "drum_clean_due_in": 0,
                "drum_clean_last": "2026-10-05T22:09:39",
                "supported_dry_times": [0, 30, 60, 240],
                "supported_dry_levels": ["Damp", "Less", "Normal", "More"],
                "drum_light": False,
                "water_liters": None,
            },
        ),
        (
            "fridge",
            {
                "sound": True,
                "energy_saved_kwh": 49.12,
                "vacation_mode": False,
                "convertible_zone": "freezer",
                "energy_saving_level": 1,
                "supported_energy_saving_levels": [1, 2],
                "door_alarm_volume": 1,
                "supported_door_alarm_volumes": [1, 2, 3, 4],
                "self_check_result": "Success",
                "self_check_errors": [],
            },
        ),
        (
            "oven",
            {
                "sound": True,
                "alarms": [],
                "default_mode": "UpperConvection",
                "fast_preheat": False,
                "timer_set": 0,
                "timer_remaining": 0,
                "timer_state": "Ready",
                "steam_generator_level": "Empty",
                "steam_state": "Standby",
                "water_inlet": "Closed",
                "drain_required": False,
                "descale_state": "Standby",
                "descale_alarm": "Normal",
                "descale_new_water_alarm": False,
                "descale_empty_water_alarm": False,
            },
        ),
        (
            "microwave",
            {"sound": False, "supported_modes": ["Autocook", "KeepWarm", "MicroWave", "Deodorization", "SteamClean"]},
        ),
    ],
)
def test_read_view_details(kind: str, expected: dict[str, Any]) -> None:
    """Test that diagnostics, maintenance and settings are read for each appliance"""
    view = read_view(kind, "10.0.0.1", resources(kind))

    assert {name: getattr(view, name) for name in expected} == expected


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        ([{DA + "code": "OV_E_OFF"}, {DA + "code": "FilterAlarm"}], ["FilterAlarm"]),
        ([{DA + "code": "DoorA_Opened", DA + "state": "Deleted"}, {DA + "id": "1"}, "x"], []),
        (None, []),
        ("broken", None),
    ],
)
def test_alarms(items: Any, expected: Any) -> None:
    """Test that only firing alarms are reported, without placeholders and cleared rows"""
    view = read_view("oven", "10.0.0.1", resources("oven", alarms_vs_0={DA + "items": items}))

    assert view.alarms == expected


@pytest.mark.parametrize(
    ("changes", "field", "expected"),
    [
        ({"course_vs_0": {DA + "options": ["DetergentAlarm_Notice_0"]}}, "detergent_low", True),
        ({"course_vs_0": {DA + "options": ["WashingTimes_x", "DrumCleanProposal_40"]}}, "drum_clean_due_in", None),
        ({"washer_vs_0": {DA + "waterTemperature": 40}}, "water_temperature", None),
        ({"washer_vs_0": {DA + "waterTemperature": "None"}}, "water_temperature", None),
        ({"washer_vs_0": {DA + "spinLevel": "None"}}, "spin_level", None),
        ({"washer_vs_0": {DA + "supportedRinseCycles": "2"}}, "supported_rinse_cycles", None),
        ({"operational_state_vs_0": {DA + "delayEndTime": "05:00:00"}}, "delay_finish_minutes", 300),
    ],
)
def test_read_view_washer_variants(changes: dict[str, Any], field: str, expected: Any) -> None:
    """Test that unusual laundry values read as expected"""
    view = read_view("washer", "10.0.0.1", resources("washer", **changes))

    assert getattr(view, field) == expected


@pytest.mark.parametrize(
    ("changes", "field", "expected"),
    [
        ({"mode_vs_0": {DA + "modes": ["RVACATION_ON"]}}, "vacation_mode", True),
        ({"mode_vs_0": {DA + "modes": "broken"}}, "convertible_zone", None),
        (
            {"selfcheck_vs_0": {DA + "error": ["ErrorCode_None", "ErrorCode_22E"]}},
            "self_check_errors",
            ["ErrorCode_22E"],
        ),
    ],
)
def test_read_view_fridge_variants(changes: dict[str, Any], field: str, expected: Any) -> None:
    """Test that unusual fridge values read as expected"""
    view = read_view("fridge", "10.0.0.1", resources("fridge", **changes))

    assert getattr(view, field) == expected


@pytest.mark.parametrize(("drain", "expected"), [("00", False), ("01", True)])
def test_drain_required(drain: str, expected: bool) -> None:
    """Test that any non-zero drain code means draining is required"""
    view = read_view("oven", "10.0.0.1", resources("oven", mode_vs_0={DA + "options": [f"drainRequired_{drain}"]}))

    assert view.drain_required is expected


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, False),
        ({"door_cooler_0": {"openState": "Open"}}, True),
        ({"door_freezer_0": {"openState": "Open"}}, True),
        ({"door_cooler_0": {"openState": None}}, None),
        # The vendor door list does not decide a fridge's door_open.
        ({"doors_vs_0": {DA + "items": [{DA + "openState": "Open"}]}}, False),
    ],
)
def test_fridge_door_open(changes: dict[str, Any], expected: Optional[bool]) -> None:
    """Test that a fridge reports a door open when its cooler or freezer door is open"""
    assert read_view("fridge", "10.0.0.1", resources("fridge", **changes)).door_open is expected


def test_cook_modes() -> None:
    """Test that only the modes declared startable and offered by the current cavity layout are reported"""
    modes = read_view("oven", "10.0.0.1", resources("oven")).cook_modes
    assert modes is not None
    assert [m.model_dump() for m in modes] == [
        {
            "mode": "UpperConvection",
            "temperature_min": 40,
            "temperature_max": 250,
            "temperature_default": 160,
            "temperature_step": 5,
            "minutes_min": 1,
            "minutes_max": 1439,
            "minutes_default": 60,
        },
        {
            "mode": "UpperLargeGrill",
            "temperature_min": 40,
            "temperature_max": 250,
            "temperature_default": 220,
            "temperature_step": 5,
            "minutes_min": 1,
            "minutes_max": 1439,
            "minutes_default": 60,
        },
    ]


@pytest.mark.parametrize(
    ("kind", "changes"),
    [
        ("microwave", {}),
        ("oven", {"mode_vs_0": {DA + "modeSpec": "not json"}}),
        (
            "oven",
            {
                "temperatures_vs_0": {
                    DA + "items": [{DA + "id": "0", DA + "description": "Temperature", DA + "unit": "Fahrenheit"}]
                }
            },
        ),
    ],
)
def test_cook_modes_unknown(kind: str, changes: dict[str, Any]) -> None:
    """Test that no cook modes are reported without a readable modeSpec in Celsius"""
    assert read_view(kind, "10.0.0.1", resources(kind, **changes)).cook_modes is None


@pytest.mark.parametrize(("kind", "table"), [("washer", "Table_02"), ("dryer", "Table_03")])
def test_course_table(kind: str, table: str) -> None:
    """Test that the table naming the laundry programme codes is reported"""
    assert read_view(kind, "10.0.0.1", resources(kind)).course_table == table


@pytest.mark.parametrize(
    ("held", "rep", "expected"),
    [
        (
            {DA + "options": ["Course_16", "WashingTimes_180", "GeoFenceAlarm"], "other": 1},
            {DA + "options": ["Course_2B", "QuickDrive_On"]},
            {DA + "options": ["Course_2B", "WashingTimes_180", "GeoFenceAlarm", "QuickDrive_On"], "other": 1},
        ),
        ({DA + "options": ["Course_16"]}, {"other": 2}, {DA + "options": ["Course_16"], "other": 2}),
        ({}, {DA + "options": ["Course_2B"]}, {DA + "options": ["Course_2B"]}),
    ],
)
def test_merge_notification(held: dict[str, Any], rep: dict[str, Any], expected: dict[str, Any]) -> None:
    """Test that a notification replaces the keys and option entries it carries and keeps the rest"""
    assert merge_notification(held, rep) == expected


def test_dry_level_of_a_programme_without_one() -> None:
    """Test that a dryer programme without a dry level reports none rather than the text None"""
    assert read_view("dryer", "10.0.0.1", resources("dryer", washer_vs_0={DA + "dryLevel": "None"})).dry_level is None
