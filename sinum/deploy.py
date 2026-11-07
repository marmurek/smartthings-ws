"""Create or update the Sinum custom devices of the appliances served by smartthings-ws.

    SINUM_TOKEN=<token> python3 -m sinum.deploy [--hub http://192.168.50.2:8008] [--dry-run]

Every device runs sinum/appliance.lua. A device is recognised again by its
integration UID, so running this a second time updates the devices instead of
adding new ones. Element and layout identifiers are derived from the appliance
name, so an update keeps them.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

INTEGRATION_MODEL = "smartthings-ws"
VERSION = "1.0.0"
LUA_PATH = Path(__file__).with_name("appliance.lua")

# smartthings-ws runs on the hub itself.
SERVICE_HTTP = "http://127.0.0.1:8124"
SERVICE_WS = "ws://127.0.0.1:8124/ws"

NAMESPACE = uuid.UUID("5a1e4c2e-8f0b-4f4e-9d55-2f6c1c9b7a10")

Json = dict[str, Any]


@dataclass(frozen=True)
class Appliance:
    """One appliance: its smartthings-ws name, its kind and how the hub shows it"""

    name: str
    kind: str
    title: str
    icon: str


APPLIANCES = (
    Appliance("microwave", "microwave", "Mikrofalówka", "heat"),
    Appliance("fridge", "fridge", "Lodówka", "snowflake"),
    Appliance("washer", "washer", "Pralka", "water-solid"),
    Appliance("oven", "oven", "Piekarnik", "fire-flame"),
    Appliance("dryer", "dryer", "Suszarka", "fan-2"),
)


class Builder:
    """The elements and layouts of one device, with identifiers stable across runs"""

    def __init__(self, appliance: str) -> None:
        self.appliance = appliance
        self.elements: list[Json] = []
        self._uuids: dict[str, str] = {}

    def stable_id(self, *parts: str) -> str:
        """An identifier derived from the appliance name and `parts`"""
        return str(uuid.uuid5(NAMESPACE, "/".join((self.appliance, *parts))))

    def _add(self, kind: str, name: str, **properties: Any) -> None:
        element_uuid = self.stable_id("element", name)
        self._uuids[name] = element_uuid
        self.elements.append(
            {"type": kind, "name": name, "uuid": element_uuid, "enabled": True, "visibility": "visible", **properties}
        )

    def text(self, name: str, value: str = "", bold: bool = False, size: str = "normal") -> None:
        """A text element"""
        self._add(
            "text",
            name,
            value=value,
            text_id=0,
            icon="",
            font_weight="bold" if bold else "normal",
            font_size=size,
            on_change="",
        )

    def progress(self, name: str) -> None:
        """A progress bar"""
        self._add("progress_bar", name, value=0, on_change="")

    def switcher(self, name: str, on_change: str) -> None:
        """A switch"""
        self._add("switcher", name, value=False, icon="", on_change=on_change)

    def button(self, name: str, text: str, icon: str, on_press: str) -> None:
        """A button"""
        self._add("button", name, text=text, text_id=0, icon=icon, on_press=on_press)

    def slider(self, name: str, label: str, *, span: tuple[int, int], value: int, on_change: str) -> None:
        """A slider with a label and a °C unit"""
        self._add(
            "slider",
            name,
            minimum=span[0],
            maximum=span[1],
            value=value,
            step=1,
            on_change=on_change,
            label_text=label,
            label_text_id=0,
            unit="°C",
        )

    def layout(self, grid: str, rows: list[list[tuple[str, list[str]]]]) -> Json:
        """A grid of rows, each a list of cells: (horizontal alignment, element names)"""
        content = []
        for r, row in enumerate(rows):
            cells = []
            for c, (alignment, names) in enumerate(row):
                cells.append(
                    {
                        "id": self.stable_id(grid, "cell", str(r), str(c)),
                        "horizontal_alignment": alignment,
                        "vertical_alignment": "center",
                        "orientation": "row",
                        "elements": [{"uuid": self._uuids[n], "variant": self._variant(n)} for n in names],
                    }
                )
            content.append({"id": self.stable_id(grid, "row", str(r)), "type": "row", "cells": cells})
        return {"version": 2, "content": content}

    def _variant(self, name: str) -> str:
        """The frontend representation of an element"""
        kind = next(e["type"] for e in self.elements if e["name"] == name)
        return {
            "text": "text-default",
            "progress_bar": "progress-bar-default",
            "switcher": "switch-default",
            "button": "button-default",
            "slider": "slider-with-label",
        }[kind]


def _laundry(b: Builder) -> tuple[Json, Json]:
    """Washer and dryer: programme state, power and start, pause, stop"""
    b.text("summary", "Odczytywanie…", bold=True)
    b.progress("progress")
    b.text("program")
    b.text("power_label", "Zasilanie")
    b.switcher("power", "onPower")
    b.button("start", "Start", "play", "onStart")
    b.button("pause", "Pauza", "pause", "onPause")
    b.button("stop", "Stop", "power-button", "onStop")
    b.text("remote", size="small")
    b.text("doors", size="small")
    b.text("energy", size="small")
    controls = [("start", ["power_label", "power"]), ("end", ["start", "pause", "stop"])]
    widget = b.layout("widget", [[("start", ["summary"])], [("start", ["progress"])], controls])
    dialog = b.layout(
        "dialog",
        [
            [("start", ["summary"])],
            [("start", ["progress"])],
            [("start", ["program"])],
            controls,
            [("start", ["remote"])],
            [("start", ["doors"])],
            [("start", ["energy"])],
        ],
    )
    return widget, dialog


def _cooking(b: Builder) -> tuple[Json, Json]:
    """Oven and microwave: cooking state, power and stop"""
    b.text("summary", "Odczytywanie…", bold=True)
    b.progress("progress")
    b.text("temperature")
    b.text("power_label", "Zasilanie")
    b.switcher("power", "onPower")
    b.button("stop", "Stop", "power-button", "onStop")
    b.text("remote", size="small")
    b.text("doors", size="small")
    controls = [("start", ["power_label", "power"]), ("end", ["stop"])]
    widget = b.layout("widget", [[("start", ["summary"])], [("start", ["progress"])], controls])
    dialog = b.layout(
        "dialog",
        [
            [("start", ["summary"])],
            [("start", ["progress"])],
            [("start", ["temperature"])],
            controls,
            [("start", ["remote"])],
            [("start", ["doors"])],
        ],
    )
    return widget, dialog


def _fridge(b: Builder) -> tuple[Json, Json]:
    """Fridge: temperatures, setpoints within the ranges it reports, rapid modes"""
    b.text("summary", "Odczytywanie…", bold=True)
    b.text("doors", size="small")
    b.slider("fridge_target", "Chłodziarka", span=(1, 7), value=3, on_change="onFridgeTarget")
    b.slider("freezer_target", "Zamrażarka", span=(-23, -15), value=-18, on_change="onFreezerTarget")
    b.text("rapid_cooling_label", "Szybkie chłodzenie")
    b.switcher("rapid_cooling", "onRapidCooling")
    b.text("rapid_freezing_label", "Szybkie zamrażanie")
    b.switcher("rapid_freezing", "onRapidFreezing")
    b.text("energy", size="small")
    widget = b.layout("widget", [[("start", ["summary"])], [("start", ["doors"])]])
    dialog = b.layout(
        "dialog",
        [
            [("start", ["summary"])],
            [("start", ["fridge_target"])],
            [("start", ["freezer_target"])],
            [("start", ["rapid_cooling_label"]), ("end", ["rapid_cooling"])],
            [("start", ["rapid_freezing_label"]), ("end", ["rapid_freezing"])],
            [("start", ["doors"])],
            [("start", ["energy"])],
        ],
    )
    return widget, dialog


LAYOUTS = {"washer": _laundry, "dryer": _laundry, "oven": _cooking, "microwave": _cooking, "fridge": _fridge}


def integration_uid(appliance: Appliance) -> str:
    """How a device is recognised as the one of this appliance"""
    return f"{INTEGRATION_MODEL}:{appliance.name}"


def device_definition(appliance: Appliance, lua: str) -> Json:
    """The custom device of one appliance, as the hub's REST API takes it"""
    builder = Builder(appliance.name)
    widget, dialog = LAYOUTS[appliance.kind](builder)
    return {
        "type": "custom_device",
        "variant": "generic",
        "name": appliance.title,
        "icon": appliance.icon,
        "enabled": True,
        "version": VERSION,
        "integration_model": INTEGRATION_MODEL,
        "integration_version": VERSION,
        "integration_uid": integration_uid(appliance),
        "lua": lua,
        "elements": builder.elements,
        "components": [
            {"type": "ws_client", "name": "ws", "url": SERVICE_WS, "headers": {}, "query_params": {}},
            {
                "type": "http_client",
                "name": "api",
                "url": SERVICE_HTTP,
                "body": "",
                "cookies": {},
                "headers": {},
                "query_params": {},
            },
            {"type": "variable_string", "name": "appliance", "value": appliance.name, "default_value": appliance.name},
        ],
        "widget": widget,
        "dialog": dialog,
        "config": {"version": 2, "content": []},
    }


class Hub:
    """The hub's REST API"""

    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/") + "/api/v1"
        self._token = token

    def request(self, method: str, path: str, body: Optional[Json] = None) -> Any:
        """Send one request, returning the `data` of the response"""
        request = urllib.request.Request(
            self.base_url + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response).get("data")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path} answered {e.code}: {e.read().decode(errors='replace')}") from e

    def custom_devices(self) -> dict[str, int]:
        """The IDs of the custom devices, by integration UID"""
        devices = self.request("GET", "/devices/virtual")
        return {
            d["integration_uid"]: d["id"]
            for d in devices
            if d.get("type") == "custom_device" and d.get("integration_uid")
        }


def deploy(hub: Hub, appliances: tuple[Appliance, ...], dry_run: bool) -> None:
    """Create the devices that do not exist yet and update the others"""
    lua = LUA_PATH.read_text(encoding="utf-8")
    existing = hub.custom_devices()

    for appliance in appliances:
        definition = device_definition(appliance, lua)
        device_id = existing.get(integration_uid(appliance))
        if dry_run:
            print(f"{appliance.name}: would {'update ' + str(device_id) if device_id else 'create'}")
            continue
        if device_id is None:
            created = hub.request("POST", "/devices/virtual", definition)
            print(f"{appliance.name}: created device {created['id']}")
        else:
            definition.pop("type")
            hub.request("PATCH", f"/devices/virtual/{device_id}", definition)
            print(f"{appliance.name}: updated device {device_id}")


def main(argv: Optional[list[str]] = None) -> int:
    """Deploy the devices to the hub named on the command line"""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hub", default=os.environ.get("SINUM_URL", "http://192.168.50.2:8008"))
    parser.add_argument("--only", nargs="*", help="Appliance names to deploy, all by default")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be done")
    args = parser.parse_args(argv)

    token = os.environ.get("SINUM_TOKEN", "").strip()
    if not token:
        print("Set SINUM_TOKEN to an API token of the hub", file=sys.stderr)
        return 2

    selected = tuple(a for a in APPLIANCES if not args.only or a.name in args.only)
    deploy(Hub(args.hub, token), selected, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
