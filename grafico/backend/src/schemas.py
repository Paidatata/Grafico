from typing import List, Optional

from pydantic import BaseModel


class StopOut(BaseModel):
    station: str
    time: str


class TripOut(BaseModel):
    trip_id: str
    direction: str
    start_time: str
    end_time: str
    stops: List[StopOut]


class ScheduleOut(BaseModel):
    trips: List[TripOut]


class TemplateImportStop(BaseModel):
    station: str
    time: str


class TemplateImportTrip(BaseModel):
    trip_id: str
    direction: str
    stops: List[TemplateImportStop]


class ShiftRequest(BaseModel):
    trip_id: str
    station_id: str
    new_time: str


class LookbackSetting(BaseModel):
    edit_lookback_minutes: int
