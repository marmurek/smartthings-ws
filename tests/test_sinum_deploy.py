"""The Sinum custom device definitions and their deployment."""

import io
import json
import re
from typing import Any

import pytest

from sinum import deploy
from sinum.deploy import APPLIANCES, LUA_PATH, Hub, device_definition, integration_uid

LUA = LUA_PATH.read_text(encoding="utf-8")


def elements_in(grid: dict[str, Any]) -> list[str]:
    """The element uuids a widget or dialog layout places"""
    return [e["uuid"] for row in grid["content"] for cell in row["cells"] for e in cell["elements"]]


@pytest.mark.parametrize("appliance", APPLIANCES, ids=lambda a: a.name)
def test_layouts_place_every_element_once(appliance: deploy.Appliance) -> None:
    """Test that the dialog shows every element and both layouts refer only to existing ones"""
    definition = device_definition(appliance, LUA)
    uuids = {e["uuid"] for e in definition["elements"]}

    assert sorted(elements_in(definition["dialog"])) == sorted(uuids)
    assert set(elements_in(definition["widget"])) <= uuids
    assert all(len(e["name"]) <= 32 and re.fullmatch(r"[a-z_]+", e["name"]) for e in definition["elements"])


@pytest.mark.parametrize("appliance", APPLIANCES, ids=lambda a: a.name)
def test_callbacks_exist_in_the_script(appliance: deploy.Appliance) -> None:
    """Test that every element callback is a method of the Lua script"""
    callbacks = {e.get("on_change") or e.get("on_press") for e in device_definition(appliance, LUA)["elements"]} - {
        "",
        None,
    }

    for callback in callbacks:
        assert f"function CustomDevice:{callback}(" in LUA


def test_identifiers_are_stable() -> None:
    """Test that a second build gives the same identifiers, so an update keeps the layout"""
    first, second = (device_definition(APPLIANCES[0], LUA) for _ in range(2))

    assert first["elements"] == second["elements"] and first["widget"] == second["widget"]


class Answer(io.BytesIO):
    """A urlopen response"""

    def __enter__(self) -> "Answer":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()


def test_deploy_creates_and_updates(monkeypatch: pytest.MonkeyPatch) -> None:
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

    deploy.deploy(Hub("http://hub/", "token"), APPLIANCES[:2], dry_run=False)

    assert [(m, u) for m, u, _ in sent] == [
        ("GET", "http://hub/api/v1/devices/virtual"),
        ("PATCH", "http://hub/api/v1/devices/virtual/7"),
        ("POST", "http://hub/api/v1/devices/virtual"),
    ]
    assert "type" not in sent[1][2] and sent[2][2]["type"] == "custom_device"


def test_main_needs_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that the script refuses to run without a token"""
    monkeypatch.delenv("SINUM_TOKEN", raising=False)

    assert deploy.main(["--dry-run"]) == 2
