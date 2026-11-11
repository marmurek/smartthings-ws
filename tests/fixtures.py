"""Resources of the appliances this service supports, trimmed to what it reads.

Taken from real reads of a TP1X_REF_21K fridge, a WD7000B washer, a DV9400B
dryer, an NV7000BS oven and an NQ7000B microwave, with identifiers removed.
"""

import copy
import json
from typing import Any

from smartthings_ws.connection import Resources

DA = "x.com.samsung.da."

_COMMON: Resources = {
    "/timezone/vs/0": {"timezoneid": "Europe/Warsaw", "offset": "+01:00", "DST": "OFF"},
    "/configuration/vs/0": {DA + "countryCode": "PL"},
    "/otninformation/vs/0": {DA + "newVersionAvailable": "false", "otnStatus": "None"},
}

_FRIDGE: Resources = {
    "/door/freezer/0": {"openState": "Close"},
    "/door/cooler/0": {"openState": "Close"},
    "/doors/vs/0": {
        DA
        + "items": [
            {DA + "openState": "Close", DA + "id": "0", DA + "description": "Door"},
            {DA + "openState": "Close", DA + "id": "1", DA + "description": "Door"},
        ]
    },
    "/energy/consumption/vs/0": {
        DA + "instantaneousPower": "3",
        DA + "cumulativePower": "424870",
        DA + "cumulativeSavedPower": "49123",
        DA + "cumulativeUnit": "Wh",
        DA + "instantaneousPowerUnit": "W",
    },
    "/refrigeration/vs/0": {DA + "rapidFridge": "Off", DA + "rapidFreezing": "Off"},
    "/drlc/vs/0": {DA + "drlcLevel": "2", DA + "durationminutes": "1441"},
    "/energy/ailevel/vs/0": {"aiLevel": "1", "supportedAiLevel": ["1", "2"]},
    "/settings/sound/alert/door/vs/0": {"alert.door": "1", "supportedAlert.door": ["1", "2", "3", "4"]},
    "/status/lock/vs/0": {DA + "device.sound": "On"},
    "/mode/vs/0": {DA + "modes": ["RVACATION_OFF", "FCONVERT_FREEZER"], DA + "supportedModes": ["HOMECARE_WIZARD_V2"]},
    "/selfcheck/vs/0": {
        DA + "supportedActions": ["Start"],
        DA + "status": "Ready",
        DA + "result": "Success",
        DA + "error": ["ErrorCode_None"],
    },
    "/temperature/desired/cooler/0": {"temperature": 3.0, "range": [1.0, 7.0], "units": "C"},
    "/temperatures/vs/0": {
        DA
        + "items": [
            {
                DA + "id": "0",
                DA + "description": "Freezer",
                DA + "desired": "-18",
                DA + "current": "-18",
                DA + "maximum": "-15",
                DA + "minimum": "-23",
                DA + "unit": "Celsius",
            },
            {
                DA + "id": "1",
                DA + "description": "Fridge",
                DA + "desired": "3",
                DA + "current": "4",
                DA + "maximum": "7",
                DA + "minimum": "1",
                DA + "unit": "Celsius",
            },
        ]
    },
}

_LAUNDRY: Resources = {
    "/energy/consumption/vs/0": {
        DA + "instantaneousPower": "-500",
        DA + "instantaneousPowerUnit": "W",
        DA + "cumulativePower": "304200",
        DA + "cumulativeUnit": "Wh",
        DA + "cumulativeSavedPower": "62694",
    },
    "/buzzersound/vs/0": {"supportedBuzzerSound": ["Off", "On"], "setBuzzerSound": "On"},
    "/drlc/vs/0": {DA + "drlcLevel": "2", DA + "durationminutes": "724"},
    "/alarms/vs/0": {},
    "/power/vs/0": {DA + "power": "Off"},
    "/power/0": {"value": False},
    "/kidslock/vs/0": {DA + "kidsLock": "Ready"},
    "/kidslock/0": {"value": False},
    "/remotectrl/vs/0": {DA + "remoteControlEnabled": "false"},
    "/remotectrl/0": {"value": False},
}

_WASHER: Resources = {
    "/course/vs/0": {
        DA
        + "options": [
            "DeviceType_0167",
            "Course_1C",
            "AiOption_On",
            "WashingTimes_12",
            "DrumCleanProposal_40",
            "DrumCleanLog_2026-11-03T15:34:56",
            "DetergentAlarm_Off",
            "SoftenerAlarm_Off",
            "DetergentLevelCtrl_2",
            "SoftenerLevelCtrl_2",
            "SupportedDetergentLevelCtrl_00010203",
        ]
    },
    "/water/consumption/vs/0": {DA + "cumulativeWater": "19311700"},
    "/operational/state/vs/0": {
        DA + "state": "Ready",
        DA + "remainingTime": "02:49:00",
        DA + "progressPercentage": "1",
        DA + "progress": "None",
        DA + "delayEndTime": "00:00:00",
        DA + "supportedProgress": ["None", "Weightsensing", "Wash", "Rinse", "Spin", "Finish"],
    },
    "/washer/vs/0": {
        DA + "detergentLevel": "1",
        DA + "waterTemperature": "40",
        DA + "supportedWaterTemperature": ["None", "Cold", "20", "30", "40", "60", "90"],
        DA + "spinLevel": "1400",
        DA + "supportedSpinLevel": ["RinseHold", "NoSpin", "400", "800", "1000", "1200", "1400"],
        DA + "rinseCycles": "2",
        DA + "supportedRinseCycles": ["0", "1", "2", "3", "4", "5"],
    },
    "/st/washercourse/vs/0": {DA + "st.washerMode": "Table_02_Course_1C", DA + "st.courseTable": "Table_02"},
}

_DRYER: Resources = {
    "/course/vs/0": {
        DA
        + "options": [
            "DeviceType_0165",
            "Course_29",
            "WashingTimes_180",
            "DrumCleanProposal_25",
            "DrumCleanLog_2025-11-15T15:23:20|2026-10-05T22:09:39",
            "DrumLight_Off",
        ]
    },
    "/power/vs/0": {DA + "power": "On"},
    "/power/0": {"value": True},
    "/operational/state/vs/0": {
        DA + "state": "Run",
        DA + "remainingTime": "00:28:00",
        DA + "progressPercentage": "57",
        DA + "progress": "AIDrying",
        DA + "delayEndTime": "00:00:00",
        DA + "supportedProgress": ["None", "AIDrying", "Cooling", "Finish"],
    },
    "/washer/vs/0": {
        DA + "wrinklePrevent": "Off",
        DA + "dryLevel": "Normal",
        DA + "supportedDryLevel": ["None", "Damp", "Less", "Normal", "More"],
        DA + "dryTime": "00:00:00",
        DA + "supportedDryTime": ["00:00:00", "00:30:00", "01:00:00", "04:00:00"],
        DA + "dryerType": "Electricity",
    },
    "/st/dryercourse/vs/0": {DA + "st.dryerMode": "Table_03_Course_29", DA + "st.courseTable": "Table_03"},
}

_COOKING: Resources = {
    "/connected/vs/0": {DA + "connected": "On"},
    "/doors/vs/0": {DA + "items": [{DA + "id": "0", DA + "description": "Door", DA + "openState": "Close"}]},
    "/operational/state/vs/0": {
        DA + "state": "Ready",
        DA + "operationTime": "00:00:00",
        DA + "remainingTime": "00:00:00",
        DA + "progressPercentage": "0",
    },
    "/oven/vs/0": {DA + "state": "Ready", DA + "recipe": "00000000000000"},
    "/alarms/vs/0": {
        DA
        + "items": [
            {
                DA + "id": "0",
                DA + "description": "Alarm",
                DA + "alarmType": "Device",
                DA + "code": "OV_E_OFF",
                DA + "triggeredTime": "2026-11-07T21:30:00",
            }
        ]
    },
    "/kidslock/vs/0": {DA + "kidsLock": "Ready"},
    "/power/vs/0": {DA + "power": "Off"},
}


def _mode_spec(mode: str, control: str, temperatures: tuple[str, str, str]) -> dict[str, str]:
    """One entry of an oven's modeSpec, trimmed to the keys the application reads"""
    low, high, default = temperatures
    timed = temperatures[0] != "NotSupported"
    return {
        "mode": mode,
        "control": control,
        "cavity": next((c for c in ("Upper", "Lower") if mode.startswith(c)), "Single"),
        "tempMinC": low,
        "tempMaxC": high,
        "tempDefaultC": default,
        "tempIntervalC": "5",
        "timeMin": "00:01:00" if timed else "NotSupported",
        "timeMax": "23:59:00" if timed else "NotSupported",
        "timeDefault": "01:00:00" if timed else "NotSupported",
    }


_OVEN: Resources = {
    "/mode/vs/0": {
        DA + "supportedModes": ["UpperAirFry", "UpperConvection", "UpperTopConvection", "UpperLargeGrill"],
        DA + "modes": ["NoOperation"],
        DA
        + "options": [
            "DeviceType_NV7000BS/EU9",
            "fastpreheat_Off",
            "UpperTimerCurrent_0",
            "UpperTimerSet_0",
            "UpperTimerState_Ready",
            "UpperLamp_Off",
            "waterInlet_Closed",
            "descaleAlarm_Normal",
            "descaleNewWaterAlarm_Off",
            "descaleEmptyWaterAlarm_Off",
            "steamGeneratorLevel_Empty",
            "drainRequired_00",
            "steamState_Standby",
            "descaleState_Standby",
            "Sound_On",
        ],
        DA + "defaultMode": "UpperConvection",
        DA
        + "modeSpec": json.dumps(
            [
                _mode_spec("Convection", "Start&Setting", ("30", "250", "160")),
                _mode_spec("UpperConvection", "Start&Setting", ("40", "250", "160")),
                _mode_spec("UpperLargeGrill", "Start&Setting", ("40", "250", "220")),
                _mode_spec("UpperAutocook", "Setting", ("NotSupported",) * 3),
                _mode_spec("Drain", "Start&Setting", ("NotSupported",) * 3),
                _mode_spec("LowerConvection", "Start&Setting", ("40", "250", "160")),
                _mode_spec("LowerBottom", "Start&Setting", ("100", "230", "180")),
                _mode_spec("LowerAutocook", "Setting", ("NotSupported",) * 3),
            ]
        ),
    },
    "/temperatures/vs/0": {
        DA
        + "items": [
            {
                DA + "id": "0",
                DA + "description": "Temperature",
                DA + "desired": "0",
                DA + "current": "0",
                DA + "increment": "5",
                DA + "unit": "Celsius",
            }
        ]
    },
    "/remotectrl/vs/0": {DA + "remoteControlEnabled": "false"},
    # The lower cavity, which the oven serves as the `/device/1` collection.
    "/connected/vs/1": {DA + "connected": "On"},
    "/mode/vs/1": {
        DA + "supportedModes": ["LowerConvection", "LowerBottom", "LowerAutocook", "LowerDrain"],
        DA + "modes": ["NoOperation"],
        DA + "options": ["LowerSteamAddLevel_0"],
        DA + "defaultMode": "LowerConvection",
    },
    "/operational/state/vs/1": {
        DA + "state": "Ready",
        DA + "operationTime": "00:00:00",
        DA + "remainingTime": "00:00:00",
        DA + "progressPercentage": "0",
    },
    "/temperatures/vs/1": {
        DA
        + "items": [
            {
                DA + "id": "0",
                DA + "description": "Temperature",
                DA + "desired": "0",
                DA + "current": "0",
                DA + "increment": "5",
                DA + "unit": "Celsius",
            }
        ]
    },
    "/oven/vs/1": {DA + "state": "Ready", DA + "recipe": "00000000000000"},
}

_MICROWAVE: Resources = {
    "/mode/vs/0": {
        DA + "supportedModes": ["Autocook", "KeepWarm", "NoOperation", "MicroWave", "Deodorization", "SteamClean"],
        DA + "modes": ["NoOperation"],
        DA + "options": ["DeviceType_NQ7000B-/EU1", "UpperLamp_Off", "Sound_Off"],
    },
}

APPLIANCES: dict[str, Resources] = {
    "fridge": {**_COMMON, **_FRIDGE},
    "washer": {**_COMMON, **_LAUNDRY, **_WASHER},
    "dryer": {**_COMMON, **_LAUNDRY, **_DRYER},
    "oven": {**_COMMON, **_COOKING, **_OVEN},
    "microwave": {**_COMMON, **_COOKING, **_MICROWAVE},
}

HOSTS = {
    "microwave": "192.168.50.20",
    "fridge": "192.168.50.21",
    "washer": "192.168.50.22",
    "oven": "192.168.50.23",
    "dryer": "192.168.50.24",
}


def resources(kind: str, **changes: dict[str, Any]) -> Resources:
    """A deep copy of one appliance's resources, with some representations merged in.

    Keyword names are hrefs with `/` replaced by `_`, e.g. `operational_state_vs_0`.
    """
    result = copy.deepcopy(APPLIANCES[kind])
    for key, rep in changes.items():
        href = "/" + key.replace("_", "/")
        result[href] = {**result.get(href, {}), **rep}
    return result
