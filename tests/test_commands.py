"""Turning commands into resource writes."""

from typing import Any

import pytest

from smartthings_ws.commands import Write, plan_writes
from smartthings_ws.connection import Resources
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


@pytest.mark.parametrize(
    ("kind", "command", "expected"),
    [
        ("washer", {"sound": False}, [Write("/buzzersound/vs/0", {"setBuzzerSound": "Off"})]),
        ("fridge", {"sound": False}, [Write("/status/lock/vs/0", {DA + "device.sound": "Off"})]),
        ("oven", {"sound": False}, [Write("/mode/vs/0", {DA + "options": ["Sound_Off"]})]),
        ("oven", {"lamp": True}, [Write("/mode/vs/0", {DA + "options": ["UpperLamp_On"]})]),
        ("oven", {"fast_preheat": True}, [Write("/mode/vs/0", {DA + "options": ["fastpreheat_On"]})]),
        ("washer", {"water_temperature": "60"}, [Write("/washer/vs/0", {DA + "waterTemperature": "60"})]),
        ("washer", {"spin_level": "800"}, [Write("/washer/vs/0", {DA + "spinLevel": "800"})]),
        ("washer", {"rinse_cycles": 3}, [Write("/washer/vs/0", {DA + "rinseCycles": "3"})]),
        ("dryer", {"dry_level": "More"}, [Write("/washer/vs/0", {DA + "dryLevel": "More"})]),
        ("dryer", {"dry_time_minutes": 60}, [Write("/washer/vs/0", {DA + "dryTime": "01:00:00"})]),
        ("dryer", {"wrinkle_prevent": True}, [Write("/washer/vs/0", {DA + "wrinklePrevent": "On"})]),
        (
            "washer",
            {"delay_finish_minutes": 330},
            [Write("/operational/state/vs/0", {DA + "delayEndTime": "05:30:00"})],
        ),
        ("fridge", {"energy_saving_level": 2}, [Write("/energy/ailevel/vs/0", {"aiLevel": "2"})]),
        ("fridge", {"door_alarm_volume": 3}, [Write("/settings/sound/alert/door/vs/0", {"alert.door": "3"})]),
    ],
)
def test_plan_setting_writes(kind: str, command: dict[str, Any], expected: list[Write]) -> None:
    """Test that each setting becomes the write the appliance expects"""
    assert plan(kind, **command) == expected


@pytest.mark.parametrize(
    ("kind", "command", "message"),
    [
        ("washer", {"spin_level": "1600"}, "spinLevel accepts RinseHold"),
        ("washer", {"rinse_cycles": 9}, "rinseCycles accepts 0, 1"),
        ("dryer", {"water_temperature": "40"}, "no waterTemperature"),
        ("washer", {"dry_level": "More"}, "no dry level"),
        ("dryer", {"dry_time_minutes": 45}, "dry time accepts 0, 30"),
        ("washer", {"wrinkle_prevent": True}, "a washer has no wrinklePrevent"),
        ("fridge", {"delay_finish_minutes": 60}, "cannot delay"),
        ("fridge", {"energy_saving_level": 5}, "energy saving level accepts 1, 2"),
        ("washer", {"door_alarm_volume": 2}, "no door alarm volume"),
        ("fridge", {"lamp": True}, "no UpperLamp option"),
        ("microwave", {"fast_preheat": False}, "no fastpreheat option"),
    ],
)
def test_plan_setting_writes_invalid(kind: str, command: dict[str, Any], message: str) -> None:
    """Test that a setting the appliance does not offer is refused before anything is sent"""
    with pytest.raises(InvalidCommand, match=message):
        plan(kind, **command)


@pytest.mark.parametrize(
    ("kind", "href", "message"),
    [("dryer", "/buzzersound/vs/0", "dryer has no buzzer"), ("fridge", "/status/lock/vs/0", "fridge has no sound")],
)
def test_sound_without_its_resource(kind: str, href: str, message: str) -> None:
    """Test that a sound write uses only the appliance's own resource"""
    appliance = resources(kind)
    del appliance[href]

    with pytest.raises(InvalidCommand, match=message):
        plan_writes(read_view(kind, "10.0.0.1", appliance), appliance, ApplianceUpdate(sound=False))


def test_sound_of_an_unknown_appliance() -> None:
    """Test that an unrecognised appliance gets no sound write"""
    appliance: Resources = {"/power/0": {"value": True}, "/mode/vs/0": {DA + "options": ["Sound_On"]}}

    with pytest.raises(InvalidCommand, match="unknown appliance has no sound"):
        plan_writes(read_view("x", "10.0.0.1", appliance), appliance, ApplianceUpdate(sound=False))


@pytest.mark.parametrize(
    ("kind", "command"), [("washer", {"water_temperature": "None"}), ("dryer", {"dry_level": "None"})]
)
def test_placeholder_is_not_a_setting(kind: str, command: dict[str, Any]) -> None:
    """Test that the None placeholder of a laundry list cannot be written"""
    with pytest.raises(InvalidCommand, match="accepts"):
        plan(kind, **command)


def test_delay_out_of_range() -> None:
    """Test that a delay longer than a day is refused by the command model"""
    with pytest.raises(ValueError):
        ApplianceUpdate(delay_finish_minutes=24 * 60 + 1)


REMOTE_ON = {"remotectrl_vs_0": {DA + "remoteControlEnabled": "true"}}


def cook_plan(cook: dict[str, Any], **changes: dict[str, Any]) -> list[Write]:
    """The writes a cook start produces on the fixture oven, Remote Control on unless changed"""
    oven = resources("oven", **{**REMOTE_ON, **changes})
    return plan_writes(read_view("oven", "10.0.0.1", oven), oven, ApplianceUpdate(cook=cook))


@pytest.mark.parametrize(
    ("cook", "temperature", "duration"),
    [
        ({"mode": "UpperConvection", "temperature": 180, "minutes": 75}, "180", "01:15:00"),
        ({"mode": "UpperLargeGrill"}, "220", "01:00:00"),
    ],
)
def test_cook_start(cook: dict[str, Any], temperature: str, duration: str) -> None:
    """Test that a cook starts in one collection write, the mode's defaults filling what is left out"""
    assert cook_plan(cook) == [
        Write(
            "/device/0",
            [
                {"href": "/devices/0"},
                {"href": "/mode/vs/0", "rep": {DA + "modes": [cook["mode"]]}},
                {
                    "href": "/temperatures/vs/0",
                    "rep": {DA + "items": [{DA + "id": "0", DA + "desired": temperature, DA + "unit": "Celsius"}]},
                },
                {"href": "/operational/state/vs/0", "rep": {DA + "operationTime": duration, DA + "state": "Run"}},
            ],
        )
    ]


@pytest.mark.parametrize(
    ("cook", "changes", "message"),
    [
        ({"mode": "Convection"}, {}, "cannot start a cook in Convection; it offers UpperConvection, UpperLargeGrill"),
        ({"mode": "UpperAutocook"}, {}, "cannot start a cook in UpperAutocook"),
        ({"mode": "UpperConvection"}, {"remotectrl_vs_0": {DA + "remoteControlEnabled": "false"}}, "Remote Control"),
        ({"mode": "UpperConvection"}, {"mode_vs_0": {DA + "modes": ["UpperConvection"]}}, "already cooking"),
        ({"mode": "UpperConvection"}, {"operational_state_vs_0": {DA + "state": "Run"}}, "already cooking"),
        ({"mode": "UpperConvection", "temperature": 260}, {}, "40..250 °C, not 260"),
        ({"mode": "UpperConvection", "temperature": 182}, {}, "steps of 5 °C"),
        ({"mode": "UpperConvection", "minutes": 0}, {}, "1..1439 minutes, not 0"),
    ],
)
def test_cook_start_invalid(cook: dict[str, Any], changes: dict[str, Any], message: str) -> None:
    """Test that a cook the oven does not offer or cannot start now is refused before anything is sent"""
    with pytest.raises(InvalidCommand, match=message):
        cook_plan(cook, **changes)


def test_cook_start_without_mode_spec() -> None:
    """Test that an appliance declaring no startable modes refuses a cook"""
    with pytest.raises(InvalidCommand, match="it offers none"):
        plan("microwave", cook={"mode": "MicroWave"})
