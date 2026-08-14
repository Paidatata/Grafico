from typing import List

from pydantic import BaseModel


class StopOut(BaseModel):
    station: str
    time: str
    # DXF Y coordinate of the stop's station. The frontend maps this to an SVG Y
    # pixel (`dxfYToSvg`) for every polyline point and drag node, so it must always
    # be present or the chart renders nothing.
    y_coord: float


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
