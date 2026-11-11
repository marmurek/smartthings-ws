"""The Sinum custom device definitions and their deployment."""

import io
import json
import re
from typing import Any

import pytest

from sinum import deploy
from sinum.deploy import APPLIANCES, LUA_PATH, Hub, device_definition, integration_uid
from smartthings_ws.state import read_view
from tests.fixtures import resources

LUA = LUA_PATH.read_text(encoding="utf-8")


def state_of(appliance: deploy.Appliance) -> dict[str, Any]:
    """The appliance as smartthings-ws reports it, from the fixture resources"""
    return read_view(appliance.name, "10.0.0.1", resources(appliance.kind)).model_dump(mode="json")


def definition_of(appliance: deploy.Appliance) -> dict[str, Any]:
    """The device definition built from the fixture state"""
    return device_definition(appliance, LUA, state_of(appliance))


def elements_in(grid: dict[str, Any]) -> list[str]:
    """The element uuids a widget or dialog layout places"""
    rows = [r for block in grid["content"] for r in (block["rows"] if block["type"] == "section" else [block])]
    return [e["uuid"] for row in rows for cell in row["cells"] for e in cell["elements"]]


@pytest.mark.parametrize("appliance", APPLIANCES, ids=lambda a: a.name)
def test_layouts_place_every_element_once(appliance: deploy.Appliance) -> None:
    """Test that the dialog shows every element and both layouts refer only to existing ones"""
    definition = definition_of(appliance)
    uuids = {e["uuid"] for e in definition["elements"]}

    assert sorted(elements_in(definition["dialog"])) == sorted(uuids)
    assert set(elements_in(definition["widget"])) <= uuids
    assert all(len(e["name"]) <= 32 and re.fullmatch(r"[a-z_]+", e["name"]) for e in definition["elements"])


@pytest.mark.parametrize("appliance", APPLIANCES, ids=lambda a: a.name)
def test_elements_are_known_to_the_script(appliance: deploy.Appliance) -> None:
    """Test that every element the script drives is listed in its ELEMENTS table"""
    listed = set(
        re.findall(r'"([a-z_]+)"', LUA[LUA.index("local ELEMENTS") : LUA.index("}", LUA.index("local ELEMENTS"))])
    )
    driven = {e["name"] for e in definition_of(appliance)["elements"] if not e["name"].endswith("_label")}

    assert driven <= listed


@pytest.mark.parametrize(
    ("appliance", "name", "options", "value"),
    [
        (APPLIANCES[2], "water_temperature", ["Cold", "20", "30", "40", "60", "90"], "40"),
        (APPLIANCES[2], "rinse_cycles", ["0", "1", "2", "3", "4", "5"], "2"),
        (APPLIANCES[4], "dry_time", ["0", "30", "60", "240"], "0"),
        (APPLIANCES[1], "door_alarm", ["1", "2", "3", "4"], "1"),
    ],
    ids=lambda v: v.name if isinstance(v, deploy.Appliance) else None,
)
def test_combo_options_follow_the_state(appliance: deploy.Appliance, name: str, options: list[str], value: str) -> None:
    """Test that a setting list offers the values the appliance reports, with the current one selected"""
    element = next(e for e in definition_of(appliance)["elements"] if e["name"] == name)

    assert [o["value"] for o in element["options"]] == options and element["value"] == value


def test_combo_without_the_current_value() -> None:
    """Test that a value outside the options selects the first option instead of an invalid one"""
    state = state_of(APPLIANCES[2]) | {"delay_finish_minutes": 17}
    element = next(e for e in device_definition(APPLIANCES[2], LUA, state)["elements"] if e["name"] == "delay")

    assert element["value"] == "0" and element["options"][1] == {"label": "Koniec za 1 h", "value": "60", "text_id": 0}


def test_fridge_sliders_follow_the_reported_range() -> None:
    """Test that the setpoint sliders take the ranges the fridge reports"""
    state = state_of(APPLIANCES[1]) | {"fridge_range": [2.0, 8.0], "fridge_target": 9.0}
    element = next(e for e in device_definition(APPLIANCES[1], LUA, state)["elements"] if e["name"] == "fridge_target")

    assert (element["minimum"], element["maximum"], element["value"]) == (2.0, 8.0, 8.0)


def test_sections_hold_only_existing_elements() -> None:
    """Test that the dryer's dialog has no washer settings and an empty section is left out"""
    dialog = definition_of(APPLIANCES[4])["dialog"]
    titles = [block["text"] for block in dialog["content"] if block["type"] == "section"]

    assert titles == ["Ustawienia programu", "Urządzenie", "Informacje"]
    microwave = definition_of(APPLIANCES[0])
    assert "fast_preheat" not in {e["name"] for e in microwave["elements"]}


@pytest.mark.parametrize("appliance", APPLIANCES, ids=lambda a: a.name)
def test_callbacks_exist_in_the_script(appliance: deploy.Appliance) -> None:
    """Test that every element callback is a method of the Lua script"""
    callbacks = {e.get("on_change") or e.get("on_press") for e in definition_of(appliance)["elements"]} - {
        "",
        None,
    }

    for callback in callbacks:
        assert f"function CustomDevice:{callback}(" in LUA


def test_identifiers_are_stable() -> None:
    """Test that a second build gives the same identifiers, so an update keeps the layout"""
    first, second = (definition_of(APPLIANCES[0]) for _ in range(2))

    assert first["elements"] == second["elements"] and first["widget"] == second["widget"]


class Answer(io.BytesIO):
    """A urlopen response"""

    def __enter__(self) -> "Answer":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()


def test_deploy_creates_and_updates(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Test that a device already on the hub is updated and a missing one is created"""
    sent: list[tuple[str, str, Any]] = []
    existing = [
        {"id": 7, "type": "custom_device", "integration_uid": integration_uid(APPLIANCES[0])},
        {"id": 8, "type": "thermostat"},
    ]

    def urlopen(request: Any, timeout: float) -> Answer:
        assert timeout > 0 and request.headers["Authorization"] == "Bearer token"
        body = json.loads(request.data) if request.data else None
        sent.append((request.get_method(), request.full_url, body))
        data: Any = existing if request.get_method() == "GET" else {"id": 9}
        return Answer(json.dumps({"data": data}).encode())

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    states = {a.name: state_of(a) for a in APPLIANCES[:2]} | {"washer": {"available": False}}
    deploy.deploy(Hub("http://hub/", "token"), APPLIANCES[:3], states, dry_run=False)

    assert [(m, u) for m, u, _ in sent] == [
        ("GET", "http://hub/api/v1/devices/virtual"),
        ("PATCH", "http://hub/api/v1/devices/virtual/7"),
        ("POST", "http://hub/api/v1/devices/virtual"),
    ]
    assert "type" not in sent[1][2] and sent[2][2]["type"] == "custom_device"
    assert "washer: skipped" in capsys.readouterr().err


def test_service_states(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that the states are read from smartthings-ws by appliance name"""

    def urlopen(request: Any, timeout: float) -> Answer:
        assert request.full_url == "http://service/appliances" and timeout > 0
        return Answer(json.dumps([{"name": "oven", "available": True}]).encode())

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    assert deploy.service_states("http://service/") == {"oven": {"name": "oven", "available": True}}


def test_main_needs_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that the script refuses to run without a token"""
    monkeypatch.delenv("SINUM_TOKEN", raising=False)

    assert deploy.main(["--dry-run"]) == 2


def test_setting_without_a_list_is_left_out() -> None:
    """Test that a setting the appliance offers no values for gets neither a list nor a label"""
    state = state_of(APPLIANCES[2]) | {"supported_spin_levels": None}
    names = {e["name"] for e in device_definition(APPLIANCES[2], LUA, state)["elements"]}

    assert "spin_level" not in names and "spin_level_label" not in names and "rinse_cycles" in names


def test_oven_remote_start_follows_the_default_mode() -> None:
    """Test that the remote start offers the oven's startable modes with the default mode's limits"""
    elements = {e["name"]: e for e in definition_of(APPLIANCES[3])["elements"]}

    mode, slider, minutes = elements["cook_mode"], elements["cook_temperature"], elements["cook_time"]
    assert [o["value"] for o in mode["options"]] == [
        "UpperConvection",
        "UpperLargeGrill",
        "LowerConvection",
        "LowerBottom",
    ]
    assert mode["value"] == "UpperConvection"
    assert [o["label"] for o in mode["options"]][::2] == ["Góra: Termoobieg", "Dół: Termoobieg"]
    assert (slider["minimum"], slider["maximum"], slider["step"], slider["value"]) == (40, 250, 5, 160)
    assert minutes["value"] == "60" and "cook_start" in elements


def test_remote_start_needs_startable_modes() -> None:
    """Test that an appliance without startable modes gets no remote start section"""
    definition = definition_of(APPLIANCES[0])
    titles = [block["text"] for block in definition["dialog"]["content"] if block["type"] == "section"]

    assert "Zdalny start" not in titles and "cook_mode" not in {e["name"] for e in definition["elements"]}


@pytest.mark.parametrize(
    ("appliance", "names"),
    [
        (APPLIANCES[2], {"summary", "progress", "program", "power", "start", "pause", "stop", "remote"}),
        (
            APPLIANCES[3],
            {
                *("summary", "progress", "temperature", "timing", "power", "stop", "remote"),
                *("lower_summary", "lower_progress", "lower_temperature", "lower_stop"),
            },
        ),
        (APPLIANCES[0], {"summary", "progress", "temperature", "timing", "power", "stop", "remote"}),
        (APPLIANCES[1], {"summary", "doors"}),
    ],
    ids=lambda v: v.name if isinstance(v, deploy.Appliance) else None,
)
def test_widget_elements(appliance: deploy.Appliance, names: set[str]) -> None:
    """Test that the tile shows the state, what Start runs and why the controls may be disabled"""
    definition = definition_of(appliance)
    by_uuid = {e["uuid"]: e["name"] for e in definition["elements"]}

    assert {by_uuid[u] for u in elements_in(definition["widget"])} - {"power_label"} == names
