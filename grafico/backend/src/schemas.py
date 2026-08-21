from datetime import datetime as _datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .timeutils import TIME_PATTERN


class StopOut(BaseModel):
    station: str
    time: str
    arrival_time: str
    y_coord: float


class TripOut(BaseModel):
    trip_id: str
    direction: str
    train_code: str
    start_time: str
    end_time: str
    stops: List[StopOut]
    active_first_seq: Optional[int] = None
    active_last_seq: Optional[int] = None


class InterdictionIn(BaseModel):
    y_top: float
    y_bottom: float
    start_time: str
    end_time: str
    description: str = ""


class InterdictionAffectedTrip(BaseModel):
    trip_id: str
    entry_time: str
    exit_time: str
    # entry_time already includes any wait (it's when the train may resume after the
    # segment frees up); original_entry_time is the *unimpeded* arrival at the border,
    # before any wait -- the frontend needs both to draw approach / flat-wait / departure
    # as three separate segments instead of smearing the wait into the approach's slope.
    original_entry_time: str


class InterdictionOut(BaseModel):
    id: int
    y_top: float
    y_bottom: float
    start_time: str
    end_time: str
    description: str
    affected_trips: List[InterdictionAffectedTrip] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class InterdictionResult(BaseModel):
    interdiction: InterdictionOut
    affected_trips: List[InterdictionAffectedTrip]


class ScheduleOut(BaseModel):
    trips: List[TripOut]
    station_turnarounds: dict[str, int] = Field(default_factory=dict)
    interdictions: List[InterdictionOut] = Field(default_factory=list)



class TurnaroundSetting(BaseModel):
    turnaround_seconds: Optional[int] = Field(default=None, ge=0)



class TemplateImportStop(BaseModel):
    station: str
    time: str = Field(pattern=TIME_PATTERN)


class TemplateImportTrip(BaseModel):
    trip_id: str
    direction: str
    train_code: Optional[str] = None
    stops: List[TemplateImportStop]


class ShiftRequest(BaseModel):
    trip_id: str
    station_id: str
    new_time: str


class LookbackSetting(BaseModel):
    edit_lookback_minutes: int = Field(ge=0)


class ScheduleMetaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: _datetime
    last_loaded_at: Optional[_datetime] = None


class StopOffset(BaseModel):
    station: str
    offset_seconds: int = Field(ge=0)


class TripPrefixUpdate(BaseModel):
    prefix: str = Field(min_length=1, max_length=3)


class TripBatchCreate(BaseModel):
    direction: str
    first_departure: str = Field(pattern=TIME_PATTERN)
    last_station: str
    count: int = Field(ge=1)
    headway_seconds: int = Field(ge=1)
    prefix: str = Field(min_length=1, max_length=3)
    stop_offsets: List[StopOffset] = Field(min_length=1)


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=1)


class AutoRegulationSetting(BaseModel):
    enabled: bool


class RegulationRequest(BaseModel):
    trip_id: str
    station_id: str

