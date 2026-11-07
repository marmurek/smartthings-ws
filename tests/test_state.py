"""Reading appliance state out of resources."""

from typing import Any

import pytest

from smartthings_ws.models import Kind, MachineState
from smartthings_ws.state import detect_kind, minutes, read_view
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
