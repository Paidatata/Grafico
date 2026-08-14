from datetime import datetime

from sqlalchemy.orm import Session

from . import models
from .errors import TripNotFoundError
from .schemas import ScheduleOut, StopOut, TemplateImportTrip, TripOut

DEFAULT_LOOKBACK_MINUTES = 15


def import_template(db: Session, trips: list[TemplateImportTrip]) -> int:
    db.query(models.TemplatePlannedStop).delete()
    db.query(models.TemplateTrip).delete()

    for trip in trips:
        train_code = trip.trip_id.split("_")[-1]
        db.add(models.TemplateTrip(
            id=trip.trip_id, train_code=train_code, direction=trip.direction, line="Line 710",
        ))
        for idx, stop in enumerate(trip.stops):
            db.add(models.TemplatePlannedStop(
                trip_id=trip.trip_id, station_id=stop.station,
                arrival_time=stop.time, departure_time=stop.time, sequence_order=idx,
            ))

    db.commit()
    perform_daily_reset(db)
    return len(trips)


def perform_daily_reset(db: Session, now: datetime | None = None) -> None:
    now = now or datetime.now()

    db.query(models.RealizedEvent).delete()
    db.query(models.PlannedStop).delete()
    db.query(models.Trip).delete()
    db.flush()

    for template_trip in db.query(models.TemplateTrip).all():
        db.add(models.Trip(
            id=template_trip.id, train_code=template_trip.train_code,
            direction=template_trip.direction, line=template_trip.line,
        ))

    for template_stop in db.query(models.TemplatePlannedStop).all():
        db.add(models.PlannedStop(
            trip_id=template_stop.trip_id, station_id=template_stop.station_id,
            arrival_time=template_stop.arrival_time, departure_time=template_stop.departure_time,
            sequence_order=template_stop.sequence_order,
        ))

    _set_setting(db, "last_reset_date", now.strftime("%Y-%m-%d"))
    db.commit()


def _trip_stops(db: Session, trip_id: str) -> list[models.PlannedStop]:
    return (
        db.query(models.PlannedStop)
        .filter(models.PlannedStop.trip_id == trip_id)
        .order_by(models.PlannedStop.sequence_order)
        .all()
    )


def get_live_schedule(db: Session) -> ScheduleOut:
    trips_out = []
    for trip in db.query(models.Trip).all():
        stops = _trip_stops(db, trip.id)
        if not stops:
            continue
        trips_out.append(_trip_to_out(trip, stops))
    return ScheduleOut(trips=trips_out)


def get_trip(db: Session, trip_id: str) -> TripOut:
    stops = _trip_stops(db, trip_id)
    if not stops:
        raise TripNotFoundError(trip_id)
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    return _trip_to_out(trip, stops)


def _trip_to_out(trip: models.Trip, stops: list[models.PlannedStop]) -> TripOut:
    return TripOut(
        trip_id=trip.id,
        direction=trip.direction,
        start_time=stops[0].departure_time,
        end_time=stops[-1].departure_time,
        stops=[StopOut(station=s.station_id, time=s.departure_time) for s in stops],
    )


def _set_setting(db: Session, key: str, value: str) -> None:
    setting = db.query(models.Setting).filter(models.Setting.key == key).first()
    if setting:
        setting.value = value
    else:
        db.add(models.Setting(key=key, value=value))
