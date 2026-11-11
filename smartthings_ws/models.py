"""The shapes the API reports and accepts."""

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class Kind(str, Enum):
    """What an appliance is, as told by the resources it exposes"""

    FRIDGE = "fridge"
    WASHER = "washer"
    DRYER = "dryer"
    OVEN = "oven"
    MICROWAVE = "microwave"
    UNKNOWN = "unknown"


class MachineState(str, Enum):
    """Whether a programme is running"""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"


class CookMode(BaseModel):
    """A mode an oven can be started in remotely, with the limits it declares"""

    mode: str
    temperature_min: int = Field(description="°C")
    temperature_max: int = Field(description="°C")
    temperature_default: int = Field(description="°C")
    temperature_step: int = Field(description="°C")
    minutes_min: int
    minutes_max: int
    minutes_default: int


class ApplianceView(BaseModel):
    """One appliance's state. A field the appliance does not have is null."""

    name: str
    host: str
    kind: Kind = Kind.UNKNOWN
    available: bool = False

    power: Optional[bool] = None
    remote_control: Optional[bool] = Field(None, description="Remote Control enabled on the appliance's panel")
    child_lock: Optional[bool] = None
    door_open: Optional[bool] = None
    power_w: Optional[float] = Field(None, description="Instantaneous power draw, W")
    energy_kwh: Optional[float] = Field(None, description="Lifetime energy consumption, kWh")
    energy_saved_kwh: Optional[float] = Field(None, description="Lifetime energy saved by energy saving, kWh")
    sound: Optional[bool] = Field(None, description="Key and end-of-programme sounds")
    alarms: Optional[list[str]] = Field(
        None, description="Codes of the alarms that are firing, as the appliance names them"
    )
    firmware_update_available: Optional[bool] = None
    demand_response_level: Optional[int] = Field(None, description="Demand response (DRLC) level set by the cloud")

    machine_state: Optional[MachineState] = None
    job: Optional[str] = Field(None, description="The phase of the running programme, as the appliance names it")
    progress: Optional[int] = Field(None, description="Programme progress, %")
    remaining_minutes: Optional[int] = Field(
        None, description="Time left; while a washer is idle, the estimate of the selected programme"
    )
    delay_finish_minutes: Optional[int] = Field(
        None, description="Laundry delay: the programme ends this long after it is started; 0 is no delay"
    )

    course: Optional[str] = Field(None, description="Laundry programme code")
    course_table: Optional[str] = Field(None, description="The table the programme codes belong to, e.g. Table_02")
    water_temperature: Optional[str] = None
    spin_level: Optional[str] = None
    rinse_cycles: Optional[int] = None
    supported_water_temperatures: Optional[list[str]] = None
    supported_spin_levels: Optional[list[str]] = None
    supported_rinse_cycles: Optional[list[int]] = None
    detergent_dose: Optional[int] = Field(None, description="Automatic detergent dosing level")
    softener_dose: Optional[int] = Field(None, description="Automatic softener dosing level")
    detergent_low: Optional[bool] = Field(None, description="The automatic detergent tank runs low")
    softener_low: Optional[bool] = Field(None, description="The automatic softener tank runs low")
    water_liters: Optional[float] = Field(None, description="Lifetime water consumption, l")
    drum_clean_due_in: Optional[int] = Field(None, description="Cycles left until the recommended drum clean")
    drum_clean_last: Optional[str] = Field(None, description="Time of the last drum clean, ISO 8601 in UTC")
    dry_level: Optional[str] = None
    supported_dry_levels: Optional[list[str]] = None
    dry_time_minutes: Optional[int] = Field(None, description="Drying time of a timed programme; 0 dries to a level")
    supported_dry_times: Optional[list[int]] = None
    wrinkle_prevent: Optional[bool] = None
    drum_light: Optional[bool] = None

    fridge_temperature: Optional[float] = None
    fridge_target: Optional[float] = None
    freezer_temperature: Optional[float] = None
    freezer_target: Optional[float] = None
    fridge_door_open: Optional[bool] = None
    freezer_door_open: Optional[bool] = None
    rapid_cooling: Optional[bool] = None
    rapid_freezing: Optional[bool] = None
    fridge_range: Optional[list[float]] = Field(None, description="Minimum and maximum of fridge_target, °C")
    freezer_range: Optional[list[float]] = Field(None, description="Minimum and maximum of freezer_target, °C")
    vacation_mode: Optional[bool] = None
    convertible_zone: Optional[str] = Field(None, description="What the convertible compartment is set to")
    energy_saving_level: Optional[int] = Field(None, description="AI energy saving level")
    supported_energy_saving_levels: Optional[list[int]] = None
    door_alarm_volume: Optional[int] = Field(None, description="Volume of the open door alarm")
    supported_door_alarm_volumes: Optional[list[int]] = None
    self_check_result: Optional[str] = None
    self_check_errors: Optional[list[str]] = None

    oven_mode: Optional[str] = None
    supported_modes: Optional[list[str]] = None
    default_mode: Optional[str] = None
    cook_modes: Optional[list[CookMode]] = Field(
        None, description="The modes a cook can be started in now; they need Remote Control enabled on the panel"
    )
    oven_temperature: Optional[int] = None
    oven_target: Optional[int] = None
    elapsed_minutes: Optional[int] = Field(None, description="Cooking time so far")
    lower_machine_state: Optional[MachineState] = Field(
        None, description="The lower cavity of a dual-cavity oven; the fields above describe the upper one"
    )
    lower_mode: Optional[str] = None
    lower_supported_modes: Optional[list[str]] = Field(
        None, description="The modes the lower cavity can run now; empty while the divider is out"
    )
    lower_temperature: Optional[int] = None
    lower_target: Optional[int] = None
    lower_progress: Optional[int] = Field(None, description="%")
    lower_remaining_minutes: Optional[int] = None
    lower_elapsed_minutes: Optional[int] = None
    lamp: Optional[bool] = None
    fast_preheat: Optional[bool] = None
    timer_set: Optional[int] = Field(None, description="Kitchen timer setting, in the appliance's own unit")
    timer_remaining: Optional[int] = Field(None, description="Kitchen timer remaining, in the appliance's own unit")
    timer_state: Optional[str] = None
    steam_generator_level: Optional[str] = Field(None, description="Water in the steam generator, e.g. Empty")
    steam_state: Optional[str] = None
    water_inlet: Optional[str] = None
    drain_required: Optional[bool] = Field(None, description="The steam system's water has to be drained")
    descale_state: Optional[str] = None
    descale_alarm: Optional[str] = Field(None, description="Descaling reminder, Normal when none is due")
    descale_new_water_alarm: Optional[bool] = None
    descale_empty_water_alarm: Optional[bool] = None


Operation = Literal["start", "pause", "stop"]


class CookStart(BaseModel):
    """A cook to start; the values left out are the mode's defaults"""

    model_config = ConfigDict(extra="forbid")

    mode: str = Field(description="One of the cook_modes; a Lower mode starts the lower cavity")
    temperature: Optional[int] = Field(None, description="°C")
    minutes: Optional[int] = Field(None, description="Cooking time, including the preheat")


class ApplianceUpdate(BaseModel):
    """A command. Only the fields present are sent to the appliance."""

    model_config = ConfigDict(extra="forbid")

    power: Optional[bool] = None
    operation: Optional[Operation] = Field(
        None, description="Start, pause or stop the selected programme of a washer, dryer or oven"
    )
    lower_operation: Optional[Operation] = Field(
        None, description="The same for the lower cavity of a dual-cavity oven"
    )
    fridge_target: Optional[int] = None
    freezer_target: Optional[int] = None
    rapid_cooling: Optional[bool] = None
    rapid_freezing: Optional[bool] = None
    sound: Optional[bool] = None
    lamp: Optional[bool] = None
    fast_preheat: Optional[bool] = None
    water_temperature: Optional[str] = Field(None, description="One of supported_water_temperatures")
    spin_level: Optional[str] = Field(None, description="One of supported_spin_levels")
    rinse_cycles: Optional[int] = Field(None, description="One of supported_rinse_cycles")
    dry_level: Optional[str] = Field(None, description="One of supported_dry_levels")
    dry_time_minutes: Optional[int] = Field(None, description="One of supported_dry_times")
    wrinkle_prevent: Optional[bool] = None
    delay_finish_minutes: Optional[int] = Field(None, ge=0, le=24 * 60, description="Whole minutes; 0 clears the delay")
    energy_saving_level: Optional[int] = Field(None, description="One of supported_energy_saving_levels")
    door_alarm_volume: Optional[int] = Field(None, description="One of supported_door_alarm_volumes")
    cook: Optional[CookStart] = Field(None, description="Start an oven cook")


class RootResponse(BaseModel):
    """What GET / reports"""

    app: str
    version: str
    appliances: list[str]
