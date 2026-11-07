# SmartThings Local WebSocket + REST API

REST and WebSocket API for Samsung SmartThings appliances, talking to them directly on the local network. No SmartThings cloud account or hub is involved.

It is built for one household's appliances: a TP1X_REF_21K fridge, a WD7000B washer, a DV9400B dryer, an NV7000BS oven and an NQ7000B microwave. Other Samsung appliances with the same boards may work, but are not a goal.

## ✨ Features

- **Local control** - CoAP over DTLS to each appliance, using [smartthings-local](https://github.com/QuiteYellow/SmartThings-Local)
- **REST API** - State of every appliance, and commands
- **WebSocket** - The full state on connect, then every change as it is read
- **Availability** - An appliance that stops answering is reported unavailable and reconnected
- **Configurable** - Every setting in one YAML file, overridable from the environment
- **Optional authorisation** - Shared token on REST and WebSocket, off by default

### Application Access
- **API**: http://localhost:8124 (schema at `/docs`)
- **WebSocket**: ws://localhost:8124/ws

## 🔑 How access works

The appliances serve OCF resources over CoAP on DTLS, on UDP port 49154. They authorise a client by the UUID in its certificate subject, checked against an access control list set at the factory, and do not validate who signed the certificate. The service mints a self-signed certificate carrying the UUID that list grants full access to every time it starts, so there is nothing to provision or store.

This also means **anyone on the same network can do the same**: read every resource of the appliances, including their Wi-Fi provisioning data, and send them commands. Keep the appliances on a network segment untrusted devices cannot reach.

The service only writes the resources listed under [Commands](#commands); it never writes networking or provisioning resources.

An appliance serves one DTLS session at a time. While this service runs, other local clients such as the Home Assistant `localthings` integration cannot connect to the same appliance. The SmartThings app is unaffected: it goes through the cloud.

## ⚙️ Configuration

All settings live in [`config.yaml`](config.yaml). Each value can be overridden by an environment variable.

| Setting | Environment variable | Default | Meaning |
|---|---|---|---|
| `server.host` | `HOST` | `0.0.0.0` | Interface the API listens on |
| `server.port` | `PORT` | `8124` | Port the API listens on; differs from gree-ws so both can share a host |
| `server.dev_mode` | `DEV_MODE` | `false` | Reload on source changes, for development |
| `polling.interval` | `POLLING_INTERVAL` | `10` | How often to read each appliance, in seconds |
| `polling.response_timeout` | `RESPONSE_TIMEOUT` | `30` | How long to wait for an appliance, covering the handshake and a whole read |
| `logging.verbose` | `VERBOSE` | `false` | Log the library's exchanges with the appliances |
| `auth.enabled` | `AUTH_ENABLED` | `false` | Require a token on every request |
| `auth.token` | `AUTH_TOKEN` | *(empty)* | The shared token clients must present |
| `appliances` | `APPLIANCES` | *(none)* | The appliances, see below |
| | `CONFIG_FILE` | `config.yaml` | The configuration file the Docker image starts with |

Appliances are listed by a URL-safe name (`a-z`, `0-9`, `-`, `_`), which is how the API addresses them:

```yaml
appliances:
  - name: fridge
    host: 192.168.50.21
  - name: oven
    host: 192.168.50.23
    port: 49154        # optional, 49154 by default
```

In the environment, or as a string in the file: `APPLIANCES="fridge=192.168.50.21,oven=192.168.50.23:49154"`. An IPv6 address with a port goes in brackets: `oven=[fe80::1]:49154`. Give the appliances fixed addresses in the router.

An environment variable that cannot be used is ignored with a warning, and the file's value applies. Enabling authorisation without a token refuses to start.

### 🔐 Authorisation

Off by default. With `auth.enabled: true` every request needs the token, except `/health` and the API schema:

- REST: `Authorization: Bearer <token>` or `X-API-Key: <token>`, otherwise `401`
- WebSocket: the same headers, or `ws://host:8124/ws?token=<token>` for browsers; otherwise the socket is closed with code `1008`

## 🔌 REST API

| Method | Path | Meaning |
|---|---|---|
| `GET` | `/health` | Liveness probe |
| `GET` | `/` | API version and appliance names |
| `GET` | `/appliances` | Every appliance with its state |
| `GET` | `/appliances/{name}` | One appliance |
| `PATCH` | `/appliances/{name}` | Send a command |

Each appliance is read with a single request for its `/device/0` collection, which returns every resource at once: 6 to 26 KB, about 2 to 7 seconds per read.

### State

Fields an appliance does not have are `null`. `available` turns `false` after three failed reads in a row; the other fields then keep their last known values.

| Field | Appliances | Meaning |
|---|---|---|
| `kind` | all | `fridge`, `washer`, `dryer`, `oven`, `microwave` |
| `power` | laundry, oven, microwave | Switched on |
| `remote_control` | laundry, oven | Remote Control enabled on the appliance's panel |
| `child_lock` | laundry | Child lock engaged |
| `door_open` | all | Any door open |
| `power_w`, `energy_kwh`, `energy_saved_kwh` | fridge, laundry | Power draw, lifetime consumption and energy saved; laundry reports no power draw |
| `sound` | all | Key and end-of-programme sounds |
| `alarms` | all | Codes of the alarms that are firing, `[]` when none |
| `firmware_update_available` | all | A firmware update is waiting |
| `demand_response_level` | fridge, laundry | Demand response (DRLC) level set by the cloud |
| `machine_state` | laundry, oven, microwave | `idle`, `running`, `paused` |
| `job` | laundry | Phase of the programme, e.g. `Wash`, `Spin`, `AIDrying`, `Cooling` |
| `progress`, `remaining_minutes` | laundry, oven, microwave | Progress in %, time left. While idle a washer reports the selected programme's estimate |
| `course` | laundry | Programme code, e.g. `1C` |
| `delay_finish_minutes` | laundry | The programme ends this long after it is started, `0` without a delay |
| `drum_clean_due_in`, `drum_clean_last` | laundry | Cycles left until the recommended drum clean, time of the last one. On the dryer the counter reads 0 with 180 cycles against an interval of 25, so its meaning there is unconfirmed |
| `water_temperature`, `spin_level`, `rinse_cycles` | washer | Programme settings, with the values offered in `supported_water_temperatures`, `supported_spin_levels`, `supported_rinse_cycles` |
| `detergent_dose`, `softener_dose`, `detergent_low`, `softener_low` | washer | Automatic dosing level, and the tank running low |
| `water_liters` | washer | Lifetime water consumption |
| `dry_level`, `dry_time_minutes`, `wrinkle_prevent` | dryer | Programme settings, with `supported_dry_levels` and `supported_dry_times` |
| `drum_light` | dryer | Drum light |
| `fridge_temperature`, `fridge_target`, `freezer_temperature`, `freezer_target` | fridge | °C |
| `fridge_door_open`, `freezer_door_open` | fridge | Each door |
| `rapid_cooling`, `rapid_freezing` | fridge | Rapid modes |
| `fridge_range`, `freezer_range` | fridge | Minimum and maximum setpoint, °C |
| `vacation_mode`, `convertible_zone` | fridge | Vacation mode, and what the convertible compartment is set to (`freezer`) |
| `energy_saving_level` | fridge | AI energy saving level, one of `supported_energy_saving_levels` |
| `door_alarm_volume` | fridge | Volume of the open door alarm, one of `supported_door_alarm_volumes` |
| `self_check_result`, `self_check_errors` | fridge | Result of the last self check and its error codes |
| `oven_mode`, `oven_temperature`, `oven_target`, `lamp` | oven, microwave | Cooking mode while cooking, °C, oven light |
| `supported_modes`, `default_mode` | oven, microwave | Cooking modes the appliance offers |
| `elapsed_minutes` | oven, microwave | Cooking time so far |
| `fast_preheat` | oven, microwave | Fast preheat |
| `timer_set`, `timer_remaining`, `timer_state` | oven, microwave | Kitchen timer; the unit is unconfirmed, both read 0 while idle |
| `steam_generator_level`, `steam_state`, `water_inlet`, `drain_required` | oven | Steam system: water in the generator (`Empty`), state, water inlet, draining needed |
| `descale_state`, `descale_alarm`, `descale_new_water_alarm`, `descale_empty_water_alarm` | oven | Descaling: state, reminder (`Normal` when none is due), and the two water alarms of a descaling run |

### Commands

`PATCH /appliances/{name}` with the fields to change. Fields already in the requested state are not sent.

| Field | Appliances | Written to |
|---|---|---|
| `power` | laundry, oven, microwave | `/power/0`, or `/power/vs/0` where that is the only one |
| `operation`: `start`, `pause`, `stop` | laundry, oven, microwave | `/operational/state/vs/0` |
| `fridge_target`, `freezer_target` | fridge | `/temperatures/vs/0`, within the compartment's range |
| `rapid_cooling`, `rapid_freezing` | fridge | `/refrigeration/vs/0` |
| `energy_saving_level`, `door_alarm_volume` | fridge | `/energy/ailevel/vs/0`, `/settings/sound/alert/door/vs/0`, one of the supported values |
| `sound` | all | `/buzzersound/vs/0` on laundry, `/status/lock/vs/0` on the fridge, the `Sound` option of `/mode/vs/0` on the oven and microwave |
| `lamp`, `fast_preheat` | oven, microwave | The `UpperLamp` and `fastpreheat` options of `/mode/vs/0` |
| `water_temperature`, `spin_level`, `rinse_cycles` | washer | `/washer/vs/0`, one of the supported values |
| `dry_level`, `dry_time_minutes`, `wrinkle_prevent` | dryer | `/washer/vs/0`, one of the supported values |
| `delay_finish_minutes` | laundry | `/operational/state/vs/0`, 0 to 1440 minutes; `0` clears the delay |

```bash
curl -X PATCH http://localhost:8124/appliances/fridge -H 'Content-Type: application/json' -d '{"fridge_target": 4}'
```

| Status | Meaning |
|---|---|
| `204` | Accepted. The response does not wait for the appliance to be read again; the result arrives over WebSocket as a change report |
| `304` | Already in the requested state, nothing sent |
| `404` | No such appliance |
| `409` | The appliance refused, with its reason. Fields written before the refused one may have been applied; the appliance is read again either way |
| `422` | The appliance does not support the command, or a value is out of range |
| `503` | The appliance did not answer, or has not been read yet |

**Laundry and ovens refuse most commands while Remote Control is off** (`remote_control: false`), which is the default after every programme. Enable it on the appliance's panel first. Starting an oven programme needs the mode, temperature and time together and is not supported yet; `stop` is.

The writes of the settings follow the formats the Home Assistant `localthings` integration uses for these resources, and have not been tried on these appliances yet.

## 🔌 WebSocket API

Connect to `ws://localhost:8124/ws`. Every message is a JSON object.

On connect the server sends the state of every appliance:

```json
{"type": "list", "data": [{"name": "dryer", "kind": "dryer", "available": true, "progress": 57, "...": "..."}]}
```

Then each change as it is read:

```json
{"type": "report", "name": "dryer", "data": {"progress": {"old": 87, "new": 88}, "remaining_minutes": {"old": 9, "new": 8}}}
```

Commands take the same fields as `PATCH`; `message_id` is optional and echoed back:

```json
{"type": "update", "name": "fridge", "message_id": 1, "data": {"rapid_freezing": true}}
```

The answer is `{"type": "applied", ...}`, `{"type": "not_changed", ...}` or `{"type": "error", "message": "..."}`, each carrying the `name` and `message_id`. An error leaves the connection open.

## 🏠 Sinum custom devices

[`sinum/`](sinum) turns each appliance into a custom device on a Sinum central unit that runs smartthings-ws itself:

- [`appliance.lua`](sinum/appliance.lua) is the script of every device. It receives the state over the WebSocket (`ws://127.0.0.1:8124/ws`), sends commands over it, and reads the state over HTTP once after each rebuild of the interpreter. A command the appliance refuses shows a toast and puts the control back.
- [`deploy.py`](sinum/deploy.py) builds the elements, the tile and the details dialog for each kind of appliance and creates the devices through the hub's REST API, or updates the ones it created before (recognised by their integration UID `smartthings-ws:<name>`):

```bash
SINUM_TOKEN=<API token> .venv/bin/python -m sinum.deploy --hub http://192.168.50.2:8008
```

`--only fridge washer` limits it to some appliances, `--dry-run` reports what it would do. The API does not set the room of a device; assign it in the Sinum app.

Scenes and automations control the devices with commands: `virtual[ID]:call("start")`, `"pause"`, `"stop"`, `"power_on"`, `"power_off"`, `"set_fridge_target"` and `"set_freezer_target"` with a number, `"set_rapid_cooling"` and `"set_rapid_freezing"` with a boolean.

The Lua interpreter of the hub has no `select`; [`.stylua.toml`](.stylua.toml) formats the script (`stylua sinum/appliance.lua`), and `luac5.4 -p sinum/appliance.lua` checks its syntax.

## 🛠️ Build and run in Docker

```bash
docker build -t smartthings-ws .
```

```bash
docker run -d --name smartthings-ws --network host --restart unless-stopped smartthings-ws
```

Host networking keeps the UDP source port fixed per appliance (61000 plus the last octet of its address). The appliance firmware never forgets a DTLS peer, and a reconnection from the same port replaces the old one instead of piling up new ones.

To configure it, mount a file over the shipped one, or set environment variables:

```bash
docker run -d --name smartthings-ws --network host -v ./my-config.yaml:/app/config.yaml:ro smartthings-ws
```

## 🧑‍💻 Development

```bash
./boot_python.sh
```

```bash
.venv/bin/black --check . && .venv/bin/mypy && .venv/bin/pylint main.py smartthings_ws sinum tests && .venv/bin/pytest
```

```bash
.venv/bin/python main.py
```

The tests need no network: a fake DTLS session answers with resources taken from real reads of the appliances above, with identifiers removed.
