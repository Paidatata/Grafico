from typing import List

from pydantic import BaseModel, Field

from .timeutils import TIME_PATTERN


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
    time: str = Field(pattern=TIME_PATTERN)


class TemplateImportTrip(BaseModel):
    trip_id: str
    direction: str
    stops: List[TemplateImportStop]


class ShiftRequest(BaseModel):
    trip_id: str
    station_id: str
    # Deliberately NOT a Pydantic pattern constraint: the design spec requires a 400 for
    # an unparseable new_time, and a schema-level rejection would surface as a 422.
    # service.shift_stop validates it against timeutils.TIME_PATTERN and raises
    # InvalidTimeError, which app.py maps to 400.
    new_time: str


class LookbackSetting(BaseModel):
    # A negative window would lock every node on the chart.
    edit_lookback_minutes: int = Field(ge=0)
