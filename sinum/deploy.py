"""Create or update the Sinum custom devices of the appliances served by smartthings-ws.

    SINUM_TOKEN=<token> python3 -m sinum.deploy [--hub URL] [--service URL] [--only NAME ...] [--dry-run]

Every device runs sinum/appliance.lua. A device is recognised again by its
integration UID, so running this a second time updates the devices instead of
adding new ones. Element and layout identifiers are derived from the appliance
name, so an update keeps them.

The options of the setting lists are the values each appliance offers, read
from smartthings-ws when the devices are built.
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
from typing import Any, Callable, Optional

INTEGRATION_MODEL = "smartthings-ws"
VERSION = "2.0.0"
LUA_PATH = Path(__file__).with_name("appliance.lua")

# smartthings-ws runs on the hub itself.
SERVICE_HTTP = "http://127.0.0.1:8124"
SERVICE_WS = "ws://127.0.0.1:8124/ws"

NAMESPACE = uuid.UUID("5a1e4c2e-8f0b-4f4e-9d55-2f6c1c9b7a10")

Json = dict[str, Any]

# A layout block: a row of cells, each a horizontal alignment and element
# names, or a titled section of such rows.
Row = list[tuple[str, list[str]]]


@dataclass(frozen=True)
class Section:
    """A titled group of rows in a layout"""

    title: str
    rows: list[Row]


Block = Row | Section


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

# Delays offered for laundry, in hours. A delay shorter than the programme is
# refused by the appliance.
DELAY_HOURS = range(1, 25)


def _water_temperature_label(value: str) -> str:
    return "Zimna woda" if value == "Cold" else f"{value}°C"


def _spin_label(value: str) -> str:
    return {"NoSpin": "Bez wirowania", "RinseHold": "Stop z wodą"}.get(value, f"{value} obr/min")


def _dry_level_label(value: str) -> str:
    return {"Damp": "Wilgotne", "Less": "Lekkie", "Normal": "Normalne", "More": "Mocne"}.get(value, value)


def _duration_label(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h" if rest == 0 else f"{hours} h {rest:02d} min"


def _dry_time_label(minutes: int) -> str:
    return "Do poziomu suszenia" if minutes == 0 else _duration_label(minutes)


def _delay_options() -> list[tuple[str, str]]:
    return [("Bez opóźnienia", "0")] + [(f"Koniec za {h} h", str(h * 60)) for h in DELAY_HOURS]


def _options(values: Any, label: Callable[[Any], str]) -> list[tuple[str, str]]:
    """Combo box options from a list the appliance offers"""
    return [(label(v), str(v)) for v in values or []]


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

    def label(self, name: str, value: str) -> None:
        """A text naming the control next to it"""
        self.text(name + "_label", value)

    def progress(self, name: str) -> None:
        """A progress bar"""
        self._add("progress_bar", name, value=0, on_change="")

    def switcher(self, name: str, on_change: str) -> None:
        """A switch"""
        self._add("switcher", name, value=False, icon="", on_change=on_change)

    def button(self, name: str, text: str, icon: str, on_press: str) -> None:
        """A button"""
        self._add("button", name, text=text, text_id=0, icon=icon, on_press=on_press)

    def slider(self, name: str, label: str, *, span: tuple[float, float], value: float, on_change: str) -> None:
        """A slider with a label and a °C unit"""
        self._add(
            "slider",
            name,
            minimum=span[0],
            maximum=span[1],
            value=min(max(value, span[0]), span[1]),
            step=1,
            on_change=on_change,
            label_text=label,
            label_text_id=0,
            unit="°C",
        )

    def combo(self, name: str, label: str, options: list[tuple[str, str]], value: Any, on_change: str) -> None:
        """A labelled drop-down list; its value has to be one of the options.

        A setting the appliance offers no values for is left out.
        """
        if not options:
            return
        self.label(name, label)
        values = [v for _, v in options]
        selected = str(value) if str(value) in values else (values[0] if values else "")
        self._add(
            "combo_box",
            name,
            options=[{"label": label, "value": v, "text_id": 0} for label, v in options],
            value=selected,
            on_change=on_change,
        )

    def has(self, name: str) -> bool:
        """Whether the element exists"""
        return name in self._uuids

    def layout(self, grid: str, blocks: list[Block]) -> Json:
        """A grid of rows and sections, leaving out the elements that were not added"""
        content: list[Json] = []
        for b, block in enumerate(blocks):
            if isinstance(block, Section):
                rows = [r for r in (self._row(grid, f"{b}.{i}", row) for i, row in enumerate(block.rows)) if r]
                if rows:
                    content.append(
                        {
                            "id": self.stable_id(grid, "section", str(b)),
                            "type": "section",
                            "cells": [],
                            "rows": rows,
                            "text": block.title,
                            "text_id": 0,
                            "collapsible": True,
                            "collapsed_default": False,
                            "has_background": True,
                        }
                    )
            else:
                row = self._row(grid, str(b), block)
                if row:
                    content.append(row)
        return {"version": 2, "content": content}

    def _row(self, grid: str, index: str, row: Row) -> Optional[Json]:
        """One row, or None when none of its elements exists"""
        cells = []
        for c, (alignment, names) in enumerate(row):
            present = [n for n in names if self.has(n)]
            if present:
                cells.append(
                    {
                        "id": self.stable_id(grid, "cell", index, str(c)),
                        "horizontal_alignment": alignment,
                        "vertical_alignment": "center",
                        "orientation": "row",
                        "elements": [{"uuid": self._uuids[n], "variant": self._variant(n)} for n in present],
                    }
                )
        return {"id": self.stable_id(grid, "row", index), "type": "row", "cells": cells} if cells else None

    def _variant(self, name: str) -> str:
        """The frontend representation of an element"""
        kind = next(e["type"] for e in self.elements if e["name"] == name)
        return {
            "text": "text-default",
            "progress_bar": "progress-bar-default",
            "switcher": "switch-default",
            "button": "button-default",
            "slider": "slider-with-label",
            "combo_box": "combo-box-default",
        }[kind]


def _switch_row(name: str) -> Row:
    """A labelled switch"""
    return [("start", [name + "_label"]), ("end", [name])]


def _sound(b: Builder, state: Json) -> None:
    if state.get("sound") is not None:
        b.label("sound", "Dźwięki")
        b.switcher("sound", "onSound")


def _laundry(b: Builder, state: Json) -> tuple[Json, Json]:
    """Washer and dryer: programme state and settings, power and start, pause, stop"""
    b.text("summary", "Odczytywanie…", bold=True)
    b.progress("progress")
    b.text("program")
    b.label("power", "Zasilanie")
    b.switcher("power", "onPower")
    b.button("start", "Start", "play", "onStart")
    b.button("pause", "Pauza", "pause", "onPause")
    b.button("stop", "Stop", "power-button", "onStop")
    if state.get("kind") == "washer":
        b.combo(
            "water_temperature",
            "Temperatura",
            _options(state.get("supported_water_temperatures"), _water_temperature_label),
            state.get("water_temperature"),
            "onWaterTemperature",
        )
        b.combo(
            "spin_level",
            "Wirowanie",
            _options(state.get("supported_spin_levels"), _spin_label),
            state.get("spin_level"),
            "onSpinLevel",
        )
        b.combo(
            "rinse_cycles",
            "Płukania",
            _options(state.get("supported_rinse_cycles"), str),
            state.get("rinse_cycles"),
            "onRinseCycles",
        )
    else:
        b.combo(
            "dry_level",
            "Poziom suszenia",
            _options(state.get("supported_dry_levels"), _dry_level_label),
            state.get("dry_level"),
            "onDryLevel",
        )
        b.combo(
            "dry_time",
            "Czas suszenia",
            _options(state.get("supported_dry_times"), _dry_time_label),
            state.get("dry_time_minutes"),
            "onDryTime",
        )
        b.label("wrinkle_prevent", "Ochrona przed zagnieceniami")
        b.switcher("wrinkle_prevent", "onWrinklePrevent")
    b.combo("delay", "Opóźnienie", _delay_options(), state.get("delay_finish_minutes", 0), "onDelay")
    _sound(b, state)
    b.text("remote", size="small")
    b.text("lock", size="small")
    b.text("dosing", size="small")
    b.text("maintenance", size="small")
    b.text("energy", size="small")

    controls: Row = [("start", ["power_label", "power"]), ("end", ["start", "pause", "stop"])]
    widget = b.layout("widget", [[("start", ["summary"])], [("start", ["progress"])], controls])
    dialog = b.layout(
        "dialog",
        [
            [("start", ["summary"])],
            [("start", ["progress"])],
            [("start", ["program"])],
            controls,
            [("start", ["remote"])],
            Section(
                "Ustawienia programu",
                [
                    _combo_row("water_temperature"),
                    _combo_row("spin_level"),
                    _combo_row("rinse_cycles"),
                    _combo_row("dry_level"),
                    _combo_row("dry_time"),
                    _switch_row("wrinkle_prevent"),
                    _combo_row("delay"),
                ],
            ),
            Section("Urządzenie", [_switch_row("sound"), [("start", ["lock"])]]),
            Section(
                "Informacje",
                [[("start", ["dosing"])], [("start", ["maintenance"])], [("start", ["energy"])]],
            ),
        ],
    )
    return widget, dialog


def _combo_row(name: str) -> Row:
    """A labelled drop-down list"""
    return [("start", [name + "_label"]), ("end", [name])]


def _cooking(b: Builder, state: Json) -> tuple[Json, Json]:
    """Oven and microwave: cooking state, power, stop, lamp and the steam system"""
    b.text("summary", "Odczytywanie…", bold=True)
    b.progress("progress")
    b.text("temperature")
    b.label("power", "Zasilanie")
    b.switcher("power", "onPower")
    b.button("stop", "Stop", "power-button", "onStop")
    if state.get("lamp") is not None:
        b.label("lamp", "Oświetlenie")
        b.switcher("lamp", "onLamp")
    if state.get("fast_preheat") is not None and state.get("kind") == "oven":
        b.label("fast_preheat", "Szybkie nagrzewanie")
        b.switcher("fast_preheat", "onFastPreheat")
    _sound(b, state)
    b.text("remote", size="small")
    b.text("doors", size="small")
    b.text("timing", size="small")
    b.text("steam", size="small")
    b.text("modes", size="small")

    controls: Row = [("start", ["power_label", "power"]), ("end", ["stop"])]
    widget = b.layout("widget", [[("start", ["summary"])], [("start", ["progress"])], controls])
    dialog = b.layout(
        "dialog",
        [
            [("start", ["summary"])],
            [("start", ["progress"])],
            [("start", ["temperature"])],
            controls,
            [("start", ["remote"])],
            Section("Ustawienia", [_switch_row("lamp"), _switch_row("fast_preheat"), _switch_row("sound")]),
            Section(
                "Informacje",
                [[("start", ["doors"])], [("start", ["timing"])], [("start", ["steam"])], [("start", ["modes"])]],
            ),
        ],
    )
    return widget, dialog


def _fridge(b: Builder, state: Json) -> tuple[Json, Json]:
    """Fridge: temperatures, setpoints, rapid modes, settings and diagnostics"""
    fridge_range = state.get("fridge_range") or [1, 7]
    freezer_range = state.get("freezer_range") or [-23, -15]
    b.text("summary", "Odczytywanie…", bold=True)
    b.text("doors", size="small")
    b.slider(
        "fridge_target",
        "Chłodziarka",
        span=(fridge_range[0], fridge_range[1]),
        value=state.get("fridge_target") or fridge_range[0],
        on_change="onFridgeTarget",
    )
    b.slider(
        "freezer_target",
        "Zamrażarka",
        span=(freezer_range[0], freezer_range[1]),
        value=state.get("freezer_target") or freezer_range[1],
        on_change="onFreezerTarget",
    )
    b.label("rapid_cooling", "Szybkie chłodzenie")
    b.switcher("rapid_cooling", "onRapidCooling")
    b.label("rapid_freezing", "Szybkie zamrażanie")
    b.switcher("rapid_freezing", "onRapidFreezing")
    if state.get("supported_energy_saving_levels"):
        b.combo(
            "energy_saving",
            "Oszczędzanie energii AI",
            _options(state["supported_energy_saving_levels"], lambda v: f"Poziom {v}"),
            state.get("energy_saving_level"),
            "onEnergySaving",
        )
    if state.get("supported_door_alarm_volumes"):
        b.combo(
            "door_alarm",
            "Alarm otwartych drzwi",
            _options(state["supported_door_alarm_volumes"], lambda v: f"Głośność {v}"),
            state.get("door_alarm_volume"),
            "onDoorAlarm",
        )
    _sound(b, state)
    b.text("fridge_modes", size="small")
    b.text("self_check", size="small")
    b.text("energy", size="small")

    widget = b.layout("widget", [[("start", ["summary"])], [("start", ["doors"])]])
    dialog = b.layout(
        "dialog",
        [
            [("start", ["summary"])],
            [("start", ["fridge_target"])],
            [("start", ["freezer_target"])],
            _switch_row("rapid_cooling"),
            _switch_row("rapid_freezing"),
            [("start", ["doors"])],
            Section("Ustawienia", [_combo_row("energy_saving"), _combo_row("door_alarm"), _switch_row("sound")]),
            Section(
                "Informacje",
                [[("start", ["fridge_modes"])], [("start", ["self_check"])], [("start", ["energy"])]],
            ),
        ],
    )
    return widget, dialog


LAYOUTS = {"washer": _laundry, "dryer": _laundry, "oven": _cooking, "microwave": _cooking, "fridge": _fridge}


def integration_uid(appliance: Appliance) -> str:
    """How a device is recognised as the one of this appliance"""
    return f"{INTEGRATION_MODEL}:{appliance.name}"


def device_definition(appliance: Appliance, lua: str, state: Json) -> Json:
    """The custom device of one appliance, as the hub's REST API takes it.

    `state` is the appliance as smartthings-ws reports it; it decides which
    settings the device offers and with which options.
    """
    builder = Builder(appliance.name)
    widget, dialog = LAYOUTS[appliance.kind](builder, {"kind": appliance.kind, **state})
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
            {"type": "variable_string", "name": "warnings", "value": "[]", "default_value": "[]"},
        ],
        "widget": widget,
        "dialog": dialog,
        "config": {"version": 2, "content": []},
    }


def _read_json(request: urllib.request.Request, what: str) -> Any:
    """The decoded body of a request, with the server's own reason on an error status"""
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{what} answered {e.code}: {e.read().decode(errors='replace')}") from e


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
        return _read_json(request, f"{method} {path}").get("data")

    def custom_devices(self) -> dict[str, int]:
        """The IDs of the custom devices, by integration UID"""
        devices = self.request("GET", "/devices/virtual")
        return {
            d["integration_uid"]: d["id"]
            for d in devices
            if d.get("type") == "custom_device" and d.get("integration_uid")
        }


def service_states(service_url: str) -> dict[str, Json]:
    """Every appliance as smartthings-ws reports it, by name"""
    request = urllib.request.Request(service_url.rstrip("/") + "/appliances", headers={"Accept": "application/json"})
    return {a["name"]: a for a in _read_json(request, "smartthings-ws")}


def deploy(hub: Hub, appliances: tuple[Appliance, ...], states: dict[str, Json], dry_run: bool) -> None:
    """Create the devices that do not exist yet and update the others"""
    lua = LUA_PATH.read_text(encoding="utf-8")
    existing = hub.custom_devices()

    for appliance in appliances:
        state = states.get(appliance.name, {})
        if not state.get("available"):
            # Without a read the settings and their options are unknown.
            print(f"{appliance.name}: skipped, smartthings-ws has not read it", file=sys.stderr)
            continue
        definition = device_definition(appliance, lua, state)
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
    parser.add_argument(
        "--service",
        default=os.environ.get("SMARTTHINGS_WS_URL", "http://192.168.50.2:8124"),
        help="smartthings-ws as reachable from here, to read the settings the appliances offer",
    )
    parser.add_argument("--only", nargs="*", help="Appliance names to deploy, all by default")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be done")
    args = parser.parse_args(argv)

    token = os.environ.get("SINUM_TOKEN", "").strip()
    if not token:
        print("Set SINUM_TOKEN to an API token of the hub", file=sys.stderr)
        return 2

    selected = tuple(a for a in APPLIANCES if not args.only or a.name in args.only)
    deploy(Hub(args.hub, token), selected, service_states(args.service), args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
