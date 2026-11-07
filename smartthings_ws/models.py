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

    machine_state: Optional[MachineState] = None
    job: Optional[str] = Field(None, description="The phase of the running programme, as the appliance names it")
    progress: Optional[int] = Field(None, description="Programme progress, %")
    remaining_minutes: Optional[int] = None

    course: Optional[str] = Field(None, description="Laundry programme code")
    water_temperature: Optional[str] = None
    spin_level: Optional[str] = None
    rinse_cycles: Optional[int] = None
    dry_level: Optional[str] = None
    wrinkle_prevent: Optional[bool] = None

    fridge_temperature: Optional[float] = None
    fridge_target: Optional[float] = None
    freezer_temperature: Optional[float] = None
    freezer_target: Optional[float] = None
    fridge_door_open: Optional[bool] = None
    freezer_door_open: Optional[bool] = None
    rapid_cooling: Optional[bool] = None
    rapid_freezing: Optional[bool] = None

    oven_mode: Optional[str] = None
    oven_temperature: Optional[int] = None
    oven_target: Optional[int] = None
    lamp: Optional[bool] = None


Operation = Literal["start", "pause", "stop"]


class ApplianceUpdate(BaseModel):
    """A command. Only the fields present are sent to the appliance."""

    model_config = ConfigDict(extra="forbid")

    power: Optional[bool] = None
    operation: Optional[Operation] = Field(
        None, description="Start, pause or stop the selected programme of a washer, dryer or oven"
    )
    fridge_target: Optional[int] = None
    freezer_target: Optional[int] = None
    rapid_cooling: Optional[bool] = None
    rapid_freezing: Optional[bool] = None


class RootResponse(BaseModel):
    """What GET / reports"""

    app: str
    version: str
    appliances: list[str]
