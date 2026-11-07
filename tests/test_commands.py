"""Turning commands into resource writes."""

from typing import Any

import pytest

from smartthings_ws.commands import Write, plan_writes
from smartthings_ws.errors import InvalidCommand
from smartthings_ws.models import ApplianceUpdate
from smartthings_ws.state import read_view
from tests.fixtures import DA, resources


def plan(kind: str, **command: Any) -> list[Write]:
    """The writes a command to one fixture appliance produces"""
    appliance = resources(kind)
    return plan_writes(read_view(kind, "10.0.0.1", appliance), appliance, ApplianceUpdate(**command))


@pytest.mark.parametrize(
    ("kind", "command", "expected"),
    [
        ("washer", {"power": True}, [Write("/power/0", {"value": True})]),
        ("oven", {"power": True}, [Write("/power/vs/0", {DA + "power": "On"})]),
        ("washer", {"operation": "start"}, [Write("/operational/state/vs/0", {DA + "state": "Run"})]),
        ("dryer", {"operation": "pause"}, [Write("/operational/state/vs/0", {DA + "state": "Pause"})]),
        ("dryer", {"operation": "stop"}, [Write("/operational/state/vs/0", {DA + "state": "Ready"})]),
        (
            "fridge",
            {"fridge_target": 5},
            [Write("/temperatures/vs/0", {DA + "items": [{DA + "id": "1", DA + "desired": "5"}]})],
        ),
        (
            "fridge",
            {"freezer_target": -20},
            [Write("/temperatures/vs/0", {DA + "items": [{DA + "id": "0", DA + "desired": "-20"}]})],
        ),
        ("fridge", {"rapid_cooling": True}, [Write("/refrigeration/vs/0", {DA + "rapidFridge": "On"})]),
        ("fridge", {"rapid_freezing": True}, [Write("/refrigeration/vs/0", {DA + "rapidFreezing": "On"})]),
        (
            "washer",
            {"operation": "start", "power": True},
            [Write("/power/0", {"value": True}), Write("/operational/state/vs/0", {DA + "state": "Run"})],
        ),
    ],
)
def test_plan_writes(kind: str, command: dict[str, Any], expected: list[Write]) -> None:
    """Test that each command field becomes the write the appliance expects, settings first"""
    assert plan(kind, **command) == expected


@pytest.mark.parametrize(
    ("kind", "command"),
    [
        ("washer", {}),
        ("washer", {"power": False}),
        ("dryer", {"operation": "start"}),
        ("washer", {"operation": "stop"}),
        ("fridge", {"fridge_target": 3, "rapid_cooling": False}),
    ],
)
def test_plan_writes_nothing_to_change(kind: str, command: dict[str, Any]) -> None:
    """Test that a command matching the current state needs no writes"""
    assert not plan(kind, **command)


def test_setpoint_without_compartment_id() -> None:
    """Test that a compartment the appliance gives no id cannot be set"""
    fridge = resources("fridge")
    del fridge["/temperatures/vs/0"][DA + "items"][1][DA + "id"]

    with pytest.raises(InvalidCommand, match="no fridge compartment"):
        plan_writes(read_view("fridge", "10.0.0.1", fridge), fridge, ApplianceUpdate(fridge_target=4))


@pytest.mark.parametrize(
    ("kind", "command", "message"),
    [
        ("fridge", {"power": True}, "cannot be switched"),
        ("fridge", {"operation": "start"}, "no programme"),
        ("washer", {"fridge_target": 3}, "no fridge compartment"),
        ("washer", {"rapid_freezing": True}, "no rapid"),
        ("fridge", {"fridge_target": 8}, "1..7"),
        ("fridge", {"freezer_target": -24}, "-23..-15"),
        ("fridge", {"rapid_cooling": True, "fridge_target": 0}, "1..7"),
    ],
)
def test_plan_writes_invalid(kind: str, command: dict[str, Any], message: str) -> None:
    """Test that a command the appliance cannot carry out is refused before anything is sent"""
    with pytest.raises(InvalidCommand, match=message):
        plan(kind, **command)
