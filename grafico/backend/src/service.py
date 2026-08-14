from datetime import datetime

from sqlalchemy.orm import Session

from . import models
from .errors import (
    ChronologyViolationError,
    InvalidTimeError,
    LookbackExceededError,
    StationNotFoundError,
    TripNotFoundError,
)
from .schemas import ScheduleOut, StopOut, TemplateImportTrip, TripOut
from .timeutils import (
    datetime_to_service_minutes,
    effective_reset_date,
    is_valid_time_str,
    minutes_to_time_str,
    time_str_to_minutes,
    time_str_to_service_minutes,
)

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

    # effective_reset_date (not now.strftime) so this agrees with should_run_catchup's
    # notion of a day: pre-03:00 still belongs to the previous reset cycle.
    _set_setting(db, "last_reset_date", effective_reset_date(now))
    db.commit()


def _trip_stops(db: Session, trip_id: str) -> list[models.PlannedStop]:
    return (
        db.query(models.PlannedStop)
        .filter(models.PlannedStop.trip_id == trip_id)
        .order_by(models.PlannedStop.sequence_order)
        .all()
    )


def _station_y_lookup(db: Session) -> dict[str, float]:
    """station_id -> DXF y_coordinate, used to populate StopOut.y_coord.

    Built once per request (never per trip) since every trip in a schedule shares it.
    """
    return {station.id: station.y_coordinate for station in db.query(models.Station).all()}


def get_live_schedule(db: Session) -> ScheduleOut:
    station_y = _station_y_lookup(db)
    trips_out = []
    for trip in db.query(models.Trip).all():
        stops = _trip_stops(db, trip.id)
        if not stops:
            continue
        trips_out.append(_trip_to_out(trip, stops, station_y))
    return ScheduleOut(trips=trips_out)


def get_trip(db: Session, trip_id: str) -> TripOut:
    stops = _trip_stops(db, trip_id)
    if not stops:
        raise TripNotFoundError(trip_id)
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    return _trip_to_out(trip, stops, _station_y_lookup(db))


def _trip_to_out(
    trip: models.Trip, stops: list[models.PlannedStop], station_y: dict[str, float],
) -> TripOut:
    return TripOut(
        trip_id=trip.id,
        direction=trip.direction,
        start_time=stops[0].departure_time,
        end_time=stops[-1].departure_time,
        stops=[
            StopOut(
                station=s.station_id,
                time=s.departure_time,
                # 0.0 only if a stop references a station missing from the table (SQLite
                # does not enforce the FK); the stop still renders rather than NaN-ing out.
                y_coord=station_y.get(s.station_id, 0.0),
            )
            for s in stops
        ],
    )


def _set_setting(db: Session, key: str, value: str) -> None:
    setting = db.query(models.Setting).filter(models.Setting.key == key).first()
    if setting:
        setting.value = value
    else:
        db.add(models.Setting(key=key, value=value))


def get_edit_lookback_minutes(db: Session) -> int:
    setting = db.query(models.Setting).filter(models.Setting.key == "edit_lookback_minutes").first()
    return int(setting.value) if setting else DEFAULT_LOOKBACK_MINUTES


def set_edit_lookback_minutes(db: Session, minutes: int) -> None:
    _set_setting(db, "edit_lookback_minutes", str(minutes))
    db.commit()


def get_last_reset_date(db: Session) -> str | None:
    setting = db.query(models.Setting).filter(models.Setting.key == "last_reset_date").first()
    return setting.value if setting else None


def shift_stop(
    db: Session, trip_id: str, station_id: str, new_time: str, now: datetime | None = None,
) -> TripOut:
    now = now or datetime.now()
    if not is_valid_time_str(new_time):
        raise InvalidTimeError(f"new_time must be HH:MM:SS between 00:00:00 and 23:59:59, got {new_time!r}")

    stops = _trip_stops(db, trip_id)
    if not stops:
        raise TripNotFoundError(trip_id)

    idx = next((i for i, s in enumerate(stops) if s.station_id == station_id), None)
    if idx is None:
        raise StationNotFoundError(station_id)

    target = stops[idx]
    new_minutes = time_str_to_minutes(new_time)

    # Ordering and elapsed-time comparisons run in service-day minutes (from 04:00), so a
    # trip whose stops straddle midnight stays monotonic: 00:02 sorts after 23:59, not before.
    if idx > 0:
        upstream_minutes = time_str_to_service_minutes(stops[idx - 1].departure_time)
        if time_str_to_service_minutes(new_time) < upstream_minutes:
            raise ChronologyViolationError(
                f"{new_time} is earlier than upstream stop departure {stops[idx - 1].departure_time}"
            )

    lookback_minutes = get_edit_lookback_minutes(db)
    current_minutes = time_str_to_minutes(target.departure_time)
    now_minutes = datetime_to_service_minutes(now)
    if (now_minutes - time_str_to_service_minutes(target.departure_time)) > lookback_minutes:
        raise LookbackExceededError(
            f"Stop at {target.departure_time} is more than {lookback_minutes} minutes in the past"
        )

    # Raw minutes are fine for the delta: it is only ever added back through
    # minutes_to_time_str, which reduces modulo 24h, so a midnight-crossing delta
    # (e.g. 23:55 -> 00:05 giving -1430) lands on the same clock time as +10 would.
    delta = new_minutes - current_minutes

    for stop in stops[idx:]:
        stop.arrival_time = minutes_to_time_str(time_str_to_minutes(stop.arrival_time) + delta)
        stop.departure_time = minutes_to_time_str(time_str_to_minutes(stop.departure_time) + delta)

    db.commit()
    return get_trip(db, trip_id)


def reset_trip(db: Session, trip_id: str) -> TripOut:
    template_stops = (
        db.query(models.TemplatePlannedStop)
        .filter(models.TemplatePlannedStop.trip_id == trip_id)
        .order_by(models.TemplatePlannedStop.sequence_order)
        .all()
    )
    if not template_stops:
        raise TripNotFoundError(trip_id)

    live_stops = {stop.station_id: stop for stop in _trip_stops(db, trip_id)}
    for template_stop in template_stops:
        live_stop = live_stops.get(template_stop.station_id)
        if live_stop is not None:
            live_stop.arrival_time = template_stop.arrival_time
            live_stop.departure_time = template_stop.departure_time
            live_stop.sequence_order = template_stop.sequence_order

    db.commit()
    return get_trip(db, trip_id)
