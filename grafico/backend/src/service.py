import re
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from . import models, regulation, interdiction as interdiction_geometry

from .db import STATIONS_METADATA
from .errors import (
    ChronologyViolationError,
    DuplicateTripError,
    DuplicateScheduleNameError,
    InterdictionNotFoundError,
    InvalidTimeError,
    LastScheduleDeletionError,
    LookbackExceededError,
    ScheduleNotFoundError,
    StationNotFoundError,
    TripNotFoundError,
)
from .schemas import (
    InterdictionIn,
    InterdictionOut,
    InterdictionAffectedTrip,
    InterdictionResult,
    LookbackSetting,
    ScheduleCreate,
    ScheduleMetaOut,
    ScheduleOut,
    ShiftRequest,
    StopOut,
    TemplateImportTrip,
    TripBatchCreate,
    TripOut,
)

from .timeutils import (
    datetime_to_service_minutes,
    effective_reset_date,
    is_valid_time_str,
    minutes_to_time_str,
    time_str_to_minutes,
    time_str_to_service_minutes,
)

DEFAULT_LOOKBACK_MINUTES = 15

_current_schedule_id: int | None = None


def get_current_schedule_id() -> int | None:
    return _current_schedule_id


def set_current_schedule_id(schedule_id: int | None) -> None:
    global _current_schedule_id
    _current_schedule_id = schedule_id


def _validate_import_payload(trips: list[TemplateImportTrip]) -> None:
    """Reject payloads SQLite's primary keys would reject, with a message naming the culprit.

    Runs before any write so a bad payload leaves the existing template untouched
    instead of surfacing as an opaque IntegrityError 500 partway through the import.
    """
    seen_trip_ids: set[str] = set()
    duplicate_trip_ids: list[str] = []
    for trip in trips:
        if trip.trip_id in seen_trip_ids:
            if trip.trip_id not in duplicate_trip_ids:
                duplicate_trip_ids.append(trip.trip_id)
        seen_trip_ids.add(trip.trip_id)

    if duplicate_trip_ids:
        raise DuplicateTripError(
            "Duplicate trip_id in import payload: " + ", ".join(duplicate_trip_ids)
        )

    for trip in trips:
        seen_stations: set[str] = set()
        for stop in trip.stops:
            if stop.station in seen_stations:
                raise DuplicateTripError(
                    f"Trip {trip.trip_id} lists station {stop.station} more than once"
                )
            seen_stations.add(stop.station)


def import_template(db: Session, trips: list[TemplateImportTrip]) -> int:
    _validate_import_payload(trips)

    if get_current_schedule_id() is None:
        set_current_schedule_id(1)

    db.query(models.TemplatePlannedStop).filter(models.TemplatePlannedStop.schedule_id == 1).delete()
    db.query(models.TemplateTrip).filter(models.TemplateTrip.schedule_id == 1).delete()

    for trip in trips:
        train_code = trip.train_code or trip.trip_id.split("_")[-1]
        db.add(models.TemplateTrip(
            id=trip.trip_id, train_code=train_code, direction=trip.direction, line="Line 710", schedule_id=1,
        ))
        for idx, stop in enumerate(trip.stops):
            db.add(models.TemplatePlannedStop(
                trip_id=trip.trip_id, station_id=stop.station,
                arrival_time=stop.time, departure_time=stop.time, sequence_order=idx, schedule_id=1,
            ))

    db.commit()
    perform_daily_reset(db)
    return len(trips)


def perform_daily_reset(db: Session, now: datetime | None = None) -> None:
    now = now or datetime.now()
    schedule_id = get_current_schedule_id()
    if schedule_id is None:
        return

    db.query(models.RealizedEvent).delete()
    db.query(models.PlannedStop).delete()
    db.query(models.Trip).delete()
    db.flush()

    for template_trip in db.query(models.TemplateTrip).filter(models.TemplateTrip.schedule_id == schedule_id).all():
        db.add(models.Trip(
            id=template_trip.id, train_code=template_trip.train_code,
            direction=template_trip.direction, line=template_trip.line,
        ))

    for template_stop in db.query(models.TemplatePlannedStop).filter(models.TemplatePlannedStop.schedule_id == schedule_id).all():
        db.add(models.PlannedStop(
            trip_id=template_stop.trip_id, station_id=template_stop.station_id,
            arrival_time=template_stop.arrival_time, departure_time=template_stop.departure_time,
            sequence_order=template_stop.sequence_order,
        ))

    # effective_reset_date (not now.strftime) so this agrees with should_run_catchup's
    # notion of a day: pre-03:00 still belongs to the previous reset cycle.
    _set_setting(db, "last_reset_date", effective_reset_date(now))
    db.commit()


def load_schedule(db: Session, schedule_id: int, now: datetime | None = None) -> ScheduleOut:
    _get_schedule_or_raise(db, schedule_id)
    set_current_schedule_id(schedule_id)
    perform_daily_reset(db, now=now)

    schedule = db.query(models.Schedule).filter(models.Schedule.id == schedule_id).first()
    schedule.last_loaded_at = now or datetime.now()
    db.commit()

    return get_live_schedule(db)


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

    turnarounds = {
        s.id: s.turnaround_seconds
        for s in db.query(models.Station).filter(models.Station.turnaround_seconds.isnot(None)).all()
    }
    interdictions = [
        InterdictionOut(
            id=i.id, y_top=i.y_top, y_bottom=i.y_bottom,
            start_time=i.start_time, end_time=i.end_time, description=i.description,
            affected_trips=_current_interdiction_crossings(db, i),
        )
        for i in db.query(models.Interdiction).all()
    ]
    return ScheduleOut(trips=trips_out, station_turnarounds=turnarounds, interdictions=interdictions)



def set_station_turnaround(db: Session, station_id: str, turnaround_seconds: int | None) -> None:
    station = db.query(models.Station).filter(models.Station.id == station_id).first()
    if station is None:
        raise StationNotFoundError(station_id)
    station.turnaround_seconds = turnaround_seconds
    db.commit()



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
        train_code=trip.train_code,
        start_time=stops[0].departure_time,
        end_time=stops[-1].departure_time,
        active_first_seq=trip.active_first_seq,
        active_last_seq=trip.active_last_seq,
        stops=[
            StopOut(
                station=s.station_id,
                time=s.departure_time,
                arrival_time=s.arrival_time,
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


def get_auto_regulation_enabled(db: Session) -> bool:
    setting = db.query(models.Setting).filter(models.Setting.key == "auto_regulation_enabled").first()
    return setting.value == "true" if setting else False


def set_auto_regulation_enabled(db: Session, enabled: bool) -> None:
    _set_setting(db, "auto_regulation_enabled", "true" if enabled else "false")
    db.commit()



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

    _maybe_auto_regulate(db, trip_id, now)

    return get_trip(db, trip_id)


def _maybe_auto_regulate(db: Session, trip_id: str, now: datetime) -> None:
    """Re-runs the Spec 4 ramp for `trip_id`'s own arrival, if auto-regulation is on.

    Shared by every operation that can change a trip's effective arrival at its
    terminus (shift_stop, interdiction resolution) — spec: "toda vez que uma chegada
    pareada é alterada (via shift_stop, resolução de interdição, etc.)".
    """
    if not get_auto_regulation_enabled(db):
        return
    stops = _trip_stops(db, trip_id)
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    if trip is None:
        return
    arrival_stop = _effective_last_stop(trip, stops)
    if arrival_stop is not None:
        apply_regulation(db, trip_id, arrival_stop.station_id, now=now)


def _effective_stop_bounds(trip: models.Trip, stops: list[models.PlannedStop]) -> tuple[int, int]:
    first = trip.active_first_seq if trip.active_first_seq is not None else 0
    last = trip.active_last_seq if trip.active_last_seq is not None else len(stops) - 1
    return first, last


def _effective_first_stop(trip: models.Trip, stops: list[models.PlannedStop]):
    first, last = _effective_stop_bounds(trip, stops)
    return stops[first] if 0 <= first <= last < len(stops) else None


def _effective_last_stop(trip: models.Trip, stops: list[models.PlannedStop]):
    first, last = _effective_stop_bounds(trip, stops)
    return stops[last] if 0 <= first <= last < len(stops) else None


def apply_regulation(
    db: Session, arrival_trip_id: str, station_id: str, now: datetime | None = None,
) -> list[TripOut]:
    now = now or datetime.now()
    station = db.query(models.Station).filter(models.Station.id == station_id).first()
    if station is None or station.turnaround_seconds is None:
        return []
    turnaround_sec = station.turnaround_seconds

    arrival_trip = db.query(models.Trip).filter(models.Trip.id == arrival_trip_id).first()
    if arrival_trip is None:
        raise TripNotFoundError(arrival_trip_id)
    arrival_stops = _trip_stops(db, arrival_trip_id)
    arrival_stop = _effective_last_stop(arrival_trip, arrival_stops)
    if arrival_stop is None or arrival_stop.station_id != station_id:
        return []

    all_trips_with_stops = [(t, _trip_stops(db, t.id)) for t in db.query(models.Trip).all()]

    arrivals = sorted(
        (
            (t, s) for t, s in all_trips_with_stops
            if s and _effective_last_stop(t, s) and _effective_last_stop(t, s).station_id == station_id
            and t.direction == arrival_trip.direction
        ),
        key=lambda ts: time_str_to_service_minutes(_effective_last_stop(ts[0], ts[1]).arrival_time),
    )
    departures = sorted(
        (
            (t, s) for t, s in all_trips_with_stops
            if s and _effective_first_stop(t, s) and _effective_first_stop(t, s).station_id == station_id
            and t.direction != arrival_trip.direction
        ),
        key=lambda ts: time_str_to_service_minutes(_effective_first_stop(ts[0], ts[1]).departure_time),
    )
    arrival_idx = next((i for i, (t, _) in enumerate(arrivals) if t.id == arrival_trip_id), None)
    if arrival_idx is None or arrival_idx >= len(departures):
        return []
    departure_trip, departure_stops = departures[arrival_idx]

    target_sm = time_str_to_service_minutes(arrival_stop.arrival_time) + turnaround_sec / 60
    departure_stop = _effective_first_stop(departure_trip, departure_stops)
    current_departure_sm = time_str_to_service_minutes(departure_stop.departure_time)
    excess = target_sm - current_departure_sm
    if excess == 0:
        return []

    now_sm = datetime_to_service_minutes(now)
    lookback_minutes = get_edit_lookback_minutes(db)
    floor_sm = now_sm - lookback_minutes

    future_departures = [
        (t, s) for t, s in departures
        if time_str_to_service_minutes(_effective_first_stop(t, s).departure_time) > now_sm
    ]
    anchor_search = [i for i, (t, _) in enumerate(future_departures) if t.id == departure_trip.id]
    if not anchor_search:
        future_departures = departures
        anchor_search = [i for i, (t, _) in enumerate(future_departures) if t.id == departure_trip.id]
    if not anchor_search:
        return []
    anchor_idx = anchor_search[0]
    anchor_trip_id = departure_trip.id

    # Candidates that can't recede past the lookback floor stay put; the ramp is
    # recomputed over the rest so the anchor still lands exactly on target (Spec 4
    # "casos de borda": compression redistributes onto the movable candidates).
    active_candidates = list(future_departures[: anchor_idx + 1])
    deltas: dict[str, float] = {}
    while active_candidates:
        deltas = regulation.compute_ramp_deltas([t.id for t, _ in active_candidates], excess)
        stuck_ids = {
            trip.id
            for trip, stops in active_candidates
            if trip.id != anchor_trip_id
            and time_str_to_service_minutes(_effective_first_stop(trip, stops).departure_time) + deltas[trip.id] < floor_sm
        }
        if not stuck_ids:
            break
        active_candidates = [(t, s) for t, s in active_candidates if t.id not in stuck_ids]

    updated = []
    for trip, stops in active_candidates:
        delta = deltas[trip.id]
        first_idx, _ = _effective_stop_bounds(trip, stops)
        for stop in stops[first_idx:]:
            stop.arrival_time = minutes_to_time_str(time_str_to_minutes(stop.arrival_time) + delta)
            stop.departure_time = minutes_to_time_str(time_str_to_minutes(stop.departure_time) + delta)
        updated.append(trip.id)

    db.commit()
    return [get_trip(db, trip_id) for trip_id in updated]



def reset_trip(db: Session, trip_id: str, now: datetime | None = None) -> TripOut:
    now = now or datetime.now()
    template_stops = (
        db.query(models.TemplatePlannedStop)
        .filter(models.TemplatePlannedStop.trip_id == trip_id)
        .order_by(models.TemplatePlannedStop.sequence_order)
        .all()
    )
    if not template_stops:
        raise TripNotFoundError(trip_id)

    lookback_minutes = get_edit_lookback_minutes(db)
    now_sm = datetime_to_service_minutes(now)

    live_stops = {stop.station_id: stop for stop in _trip_stops(db, trip_id)}
    for template_stop in template_stops:
        live_stop = live_stops.get(template_stop.station_id)
        if live_stop is None:
            continue
        current_sm = time_str_to_service_minutes(live_stop.departure_time)
        if (now_sm - current_sm) > lookback_minutes:
            continue  # frozen: outside the editable window, leave as-is
        live_stop.arrival_time = template_stop.arrival_time
        live_stop.departure_time = template_stop.departure_time
        live_stop.sequence_order = template_stop.sequence_order

    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    ordered_stops = _trip_stops(db, trip_id)

    if trip and trip.active_last_seq is not None and trip.active_last_seq + 1 < len(ordered_stops):
        boundary_sm = time_str_to_service_minutes(ordered_stops[trip.active_last_seq + 1].departure_time)
        if (now_sm - boundary_sm) <= lookback_minutes:
            trip.active_last_seq = None
    if trip and trip.active_first_seq is not None and trip.active_first_seq < len(ordered_stops):
        boundary_sm = time_str_to_service_minutes(ordered_stops[trip.active_first_seq].departure_time)
        if (now_sm - boundary_sm) <= lookback_minutes:
            trip.active_first_seq = None

    db.commit()
    return get_trip(db, trip_id)



def list_schedules(db: Session) -> list[ScheduleMetaOut]:
    return [
        ScheduleMetaOut.model_validate(s)
        for s in db.query(models.Schedule).order_by(models.Schedule.id).all()
    ]


def create_schedule(db: Session, name: str) -> ScheduleMetaOut:
    schedule = models.Schedule(name=name)
    db.add(schedule)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateScheduleNameError(f"Schedule name already exists: {name!r}")
    db.refresh(schedule)
    return ScheduleMetaOut.model_validate(schedule)


def get_schedule_trips(db: Session, schedule_id: int) -> ScheduleOut:
    station_y = _station_y_lookup(db)
    trips_out = []
    for trip in db.query(models.TemplateTrip).filter(models.TemplateTrip.schedule_id == schedule_id).all():
        stops = (
            db.query(models.TemplatePlannedStop)
            .filter(
                models.TemplatePlannedStop.trip_id == trip.id,
                models.TemplatePlannedStop.schedule_id == schedule_id
            )
            .order_by(models.TemplatePlannedStop.sequence_order)
            .all()
        )
        if not stops:
            continue
        trips_out.append(TripOut(
            trip_id=trip.id,
            direction=trip.direction,
            train_code=trip.train_code,
            start_time=stops[0].departure_time,
            end_time=stops[-1].departure_time,
            stops=[
                StopOut(station=s.station_id, time=s.departure_time, arrival_time=s.arrival_time, y_coord=station_y.get(s.station_id, 0.0))
                for s in stops
            ],
        ))
    return ScheduleOut(trips=trips_out)


def _get_schedule_or_raise(db: Session, schedule_id: int) -> models.Schedule:
    schedule = db.query(models.Schedule).filter(models.Schedule.id == schedule_id).first()
    if schedule is None:
        raise ScheduleNotFoundError(schedule_id)
    return schedule


def rename_schedule(db: Session, schedule_id: int, name: str) -> ScheduleMetaOut:
    schedule = _get_schedule_or_raise(db, schedule_id)
    schedule.name = name
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateScheduleNameError(f"Schedule name already exists: {name!r}")
    db.refresh(schedule)
    return ScheduleMetaOut.model_validate(schedule)


def delete_schedule(db: Session, schedule_id: int) -> None:
    _get_schedule_or_raise(db, schedule_id)
    if db.query(models.Schedule).count() <= 1:
        raise LastScheduleDeletionError("Cannot delete the only remaining schedule")
    db.query(models.TemplatePlannedStop).filter(models.TemplatePlannedStop.schedule_id == schedule_id).delete()
    db.query(models.TemplateTrip).filter(models.TemplateTrip.schedule_id == schedule_id).delete()
    db.query(models.Schedule).filter(models.Schedule.id == schedule_id).delete()
    db.commit()


def clone_schedule(db: Session, schedule_id: int, new_name: str) -> ScheduleMetaOut:
    _get_schedule_or_raise(db, schedule_id)
    new_schedule = models.Schedule(name=new_name)
    db.add(new_schedule)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise DuplicateScheduleNameError(f"Schedule name already exists: {new_name!r}")

    for trip in db.query(models.TemplateTrip).filter(models.TemplateTrip.schedule_id == schedule_id).all():
        db.add(models.TemplateTrip(
            id=trip.id, train_code=trip.train_code, direction=trip.direction,
            line=trip.line, schedule_id=new_schedule.id,
        ))
    for stop in db.query(models.TemplatePlannedStop).filter(models.TemplatePlannedStop.schedule_id == schedule_id).all():
        db.add(models.TemplatePlannedStop(
            trip_id=stop.trip_id, station_id=stop.station_id, arrival_time=stop.arrival_time,
            departure_time=stop.departure_time, sequence_order=stop.sequence_order,
            schedule_id=new_schedule.id,
        ))
    db.commit()
    db.refresh(new_schedule)
    return ScheduleMetaOut.model_validate(new_schedule)


_TRAIN_CODE_RE = re.compile(r"^([A-Za-z]+)(\d+)$")
_STATION_ORDER = {s["id"]: i for i, s in enumerate(STATIONS_METADATA)}


def _split_prefix(train_code: str) -> tuple[str, int]:
    match = _TRAIN_CODE_RE.match(train_code)
    if not match:
        return train_code, 0
    return match.group(1), int(match.group(2))


def renumber_schedule(db: Session, schedule_id: int) -> ScheduleOut:
    trips = db.query(models.TemplateTrip).filter(models.TemplateTrip.schedule_id == schedule_id).all()

    def first_stop_and_last_stop(trip_id):
        stops = (
            db.query(models.TemplatePlannedStop)
            .filter(
                models.TemplatePlannedStop.trip_id == trip_id,
                models.TemplatePlannedStop.schedule_id == schedule_id
            )
            .order_by(models.TemplatePlannedStop.sequence_order)
            .all()
        )
        return stops[0], stops[-1]

    odd_group, even_group = [], []
    for trip in trips:
        first_stop, last_stop = first_stop_and_last_stop(trip.id)
        entry = (trip, first_stop, last_stop)
        (odd_group if last_stop.station_id == "BFU" else even_group).append(entry)

    def sort_key(entry):
        trip, first_stop, last_stop = entry
        first_idx = _STATION_ORDER.get(first_stop.station_id, len(_STATION_ORDER))
        last_idx = _STATION_ORDER.get(last_stop.station_id, len(_STATION_ORDER))
        distance_to_term = abs(last_idx - first_idx)
        return (
            time_str_to_service_minutes(first_stop.departure_time),
            distance_to_term,
        )

    for group, start_number in ((odd_group, 1), (even_group, 2)):
        group.sort(key=sort_key)
        for i, (trip, _, _) in enumerate(group):
            prefix, _ = _split_prefix(trip.train_code)
            trip.train_code = f"{prefix}{start_number + 2 * i}"

    db.commit()
    return get_schedule_trips(db, schedule_id)


def create_trips_batch(db: Session, schedule_id: int, payload: TripBatchCreate) -> ScheduleOut:
    _get_schedule_or_raise(db, schedule_id)
    first_departure_minutes = time_str_to_minutes(payload.first_departure)

    for i in range(payload.count):
        trip_departure_minutes = first_departure_minutes + (payload.headway_seconds / 60) * i
        trip_id = f"BATCH_{schedule_id}_{payload.direction}_{minutes_to_time_str(trip_departure_minutes).replace(':', '')}_{i}"
        db.add(models.TemplateTrip(
            id=trip_id, train_code=f"{payload.prefix}1", direction=payload.direction,
            line="Line 710", schedule_id=schedule_id,
        ))
        for seq, offset in enumerate(payload.stop_offsets):
            stop_time = minutes_to_time_str(trip_departure_minutes + offset.offset_seconds / 60)
            db.add(models.TemplatePlannedStop(
                trip_id=trip_id, station_id=offset.station, arrival_time=stop_time,
                departure_time=stop_time, sequence_order=seq, schedule_id=schedule_id,
            ))
    db.commit()

    renumber_schedule(db, schedule_id)
    return get_schedule_trips(db, schedule_id)


def update_trip_prefix(db: Session, schedule_id: int, trip_id: str, prefix: str) -> ScheduleOut:
    trip = (
        db.query(models.TemplateTrip)
        .filter(models.TemplateTrip.schedule_id == schedule_id, models.TemplateTrip.id == trip_id)
        .first()
    )
    if trip is None:
        raise TripNotFoundError(trip_id)
    _, number = _split_prefix(trip.train_code)
    trip.train_code = f"{prefix}{number}"
    db.commit()
    return renumber_schedule(db, schedule_id)


def suppress_from(db: Session, trip_id: str, station_id: str, now: datetime | None = None) -> TripOut:
    now = now or datetime.now()
    stops = _trip_stops(db, trip_id)
    if not stops:
        raise TripNotFoundError(trip_id)

    idx = next((i for i, s in enumerate(stops) if s.station_id == station_id), None)
    if idx is None:
        raise StationNotFoundError(station_id)

    target = stops[idx]
    lookback_minutes = get_edit_lookback_minutes(db)
    now_sm = datetime_to_service_minutes(now)
    target_sm = time_str_to_service_minutes(target.departure_time)
    if (now_sm - target_sm) > lookback_minutes:
        raise LookbackExceededError(
            f"Stop at {target.departure_time} is more than {lookback_minutes} minutes in the past"
        )

    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    trip.active_last_seq = idx - 1
    db.commit()
    return get_trip(db, trip_id)


def depart_from(db: Session, trip_id: str, station_id: str, now: datetime | None = None) -> TripOut:
    now = now or datetime.now()
    stops = _trip_stops(db, trip_id)
    if not stops:
        raise TripNotFoundError(trip_id)

    idx = next((i for i, s in enumerate(stops) if s.station_id == station_id), None)
    if idx is None:
        raise StationNotFoundError(station_id)

    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    current_first = trip.active_first_seq or 0
    current_last = trip.active_last_seq if trip.active_last_seq is not None else len(stops) - 1

    if idx <= current_first:
        raise ChronologyViolationError("New departure must be further along the route than the current origin")
    if idx > current_last:
        raise ChronologyViolationError("New departure must be within the currently active route")

    target = stops[idx]
    lookback_minutes = get_edit_lookback_minutes(db)
    now_sm = datetime_to_service_minutes(now)
    target_sm = time_str_to_service_minutes(target.departure_time)
    if (now_sm - target_sm) > lookback_minutes:
        raise LookbackExceededError(
            f"Stop at {target.departure_time} is more than {lookback_minutes} minutes in the past"
        )

    trip.active_first_seq = idx
    db.commit()
    return get_trip(db, trip_id)


def _direction_sign(stops, station_y: dict) -> int:
    first_y = station_y.get(stops[0].station_id, 0.0)
    last_y = station_y.get(stops[-1].station_id, 0.0)
    return 1 if last_y >= first_y else -1


def _service_minutes_to_time_str(service_minutes: float) -> str:
    from .timeutils import SERVICE_DAY_START_HOUR
    raw = (service_minutes + SERVICE_DAY_START_HOUR * 60) % (24 * 60)
    return minutes_to_time_str(raw)


def _current_interdiction_crossings(db: Session, interdiction: models.Interdiction) -> list[InterdictionAffectedTrip]:
    """Recomputes each affected trip's entry/exit window from *current* live state.

    Re-interpolating naively over the live stop times would give the wrong window once a
    trip has been delayed: the stop just before the band is intentionally left untouched
    while every stop from the first affected one onward shifts by a uniform delta, so a
    straight line between those two (now asymmetric) points is a different, wider/shifted
    segment than the original crossing. Instead this reconstructs each stop's *original*
    (pre-delay) time from the snapshot baseline where one exists, runs the same
    `crossing_window` geometry `_apply_interdiction` used to find the window, and re-applies
    the uniform delta the affected stop actually received — reproducing exactly what
    `_apply_interdiction` computed, so `GET /api/schedule` and the create/update response
    never disagree. Trips with no snapshot row were never delayed (delta stays 0) and this
    just reports their natural crossing.
    """
    snapshot_by_trip_station = {
        (s.trip_id, s.station_id): s
        for s in db.query(models.InterdictionStopSnapshot)
        .filter(models.InterdictionStopSnapshot.interdiction_id == interdiction.id)
        .all()
    }
    start_sm = time_str_to_service_minutes(interdiction.start_time)
    end_sm = time_str_to_service_minutes(interdiction.end_time)

    station_y = _station_y_lookup(db)
    affected = []
    for trip in db.query(models.Trip).all():
        stops = _trip_stops(db, trip.id)
        if len(stops) < 2:
            continue

        baseline_geometry = []
        for stop in stops:
            snap = snapshot_by_trip_station.get((trip.id, stop.station_id))
            arrival = snap.arrival_time if snap else stop.arrival_time
            departure = snap.departure_time if snap else stop.departure_time
            baseline_geometry.append((station_y.get(stop.station_id, 0.0), arrival, departure))

        window = interdiction_geometry.crossing_window(baseline_geometry, interdiction.y_top, interdiction.y_bottom)
        if window is None:
            continue
        original_entry_sm, original_exit_sm, first_idx = window
        if original_entry_sm >= end_sm or original_exit_sm <= start_sm:
            continue

        first_station = stops[first_idx].station_id
        snap = snapshot_by_trip_station.get((trip.id, first_station))
        delta = (
            time_str_to_minutes(stops[first_idx].departure_time) - time_str_to_minutes(snap.departure_time)
            if snap else 0.0
        )

        affected.append(InterdictionAffectedTrip(
            trip_id=trip.id,
            entry_time=_service_minutes_to_time_str(original_entry_sm + delta),
            exit_time=_service_minutes_to_time_str(original_exit_sm + delta),
            original_entry_time=_service_minutes_to_time_str(original_entry_sm),
        ))
    return affected


def _apply_interdiction(db: Session, interdiction: models.Interdiction, now: datetime) -> list[InterdictionAffectedTrip]:
    station_y = _station_y_lookup(db)
    now_service_minutes = datetime_to_service_minutes(now)
    start_sm = time_str_to_service_minutes(interdiction.start_time)
    end_sm = time_str_to_service_minutes(interdiction.end_time)

    candidates = []
    for trip in db.query(models.Trip).all():
        stops = _trip_stops(db, trip.id)
        if len(stops) < 2:
            continue
        geometry_stops = [(station_y.get(s.station_id, 0.0), s.arrival_time, s.departure_time) for s in stops]
        window = interdiction_geometry.crossing_window(geometry_stops, interdiction.y_top, interdiction.y_bottom)
        if window is None:
            continue
        entry_sm, exit_sm, first_idx = window
        if entry_sm >= end_sm or exit_sm <= start_sm:
            continue
        if entry_sm <= now_service_minutes < exit_sm:
            continue
        candidates.append((trip.id, _direction_sign(stops, station_y), entry_sm, exit_sm, first_idx, stops))

    sequenced = interdiction_geometry.sequence_crossings(
        [(c[0], c[1], c[2], c[3]) for c in candidates]
    )
    by_trip_id = {c[0]: c for c in candidates}

    all_trips_with_stops = [(t, _trip_stops(db, t.id)) for t in db.query(models.Trip).all()]
    direction_by_trip = {t.id: t.direction for t, _ in all_trips_with_stops}
    original_departure_by_key: dict[tuple[str, str], str] = {
        (t.id, s.station_id): s.departure_time
        for t, stops in all_trips_with_stops for s in stops
    }
    stop_index_by_trip_station: dict[tuple[str, str], int] = {
        (t.id, s.station_id): idx
        for t, stops in all_trips_with_stops for idx, s in enumerate(stops)
    }
    stops_by_trip = {t.id: stops for t, stops in all_trips_with_stops}

    def apply_delta_from_station(trip_id: str, stops: list[models.PlannedStop], station_idx: int, delta: float) -> None:
        # A held train can't wait mid-track -- it waits at S_prev's platform. S_prev's own
        # arrival stays original (it got there on time); only its departure and everything
        # downstream (both arrival and departure) shift, keeping every segment's speed
        # constant everywhere. Same rule for a cascade recipient, anchored at its own stop
        # matching the held train's S_prev station.
        for offset, stop in enumerate(stops[station_idx:]):
            existing = db.get(models.InterdictionStopSnapshot, (interdiction.id, trip_id, stop.station_id))
            if existing is None:
                db.add(models.InterdictionStopSnapshot(
                    interdiction_id=interdiction.id, trip_id=trip_id, station_id=stop.station_id,
                    arrival_time=stop.arrival_time, departure_time=stop.departure_time,
                ))
            if offset == 0:
                stop.departure_time = minutes_to_time_str(time_str_to_minutes(stop.departure_time) + delta)
            else:
                stop.arrival_time = minutes_to_time_str(time_str_to_minutes(stop.arrival_time) + delta)
                stop.departure_time = minutes_to_time_str(time_str_to_minutes(stop.departure_time) + delta)

    affected = []
    delayed_trip_ids: list[str] = []
    for trip_id, delta, new_entry_sm, new_exit_sm in sequenced:
        _, _, original_entry_sm, _, first_idx, stops = by_trip_id[trip_id]
        if delta:
            s_prev_idx = first_idx - 1
            apply_delta_from_station(trip_id, stops, s_prev_idx, delta)
            delayed_trip_ids.append(trip_id)
        affected.append(InterdictionAffectedTrip(
            trip_id=trip_id,
            entry_time=_service_minutes_to_time_str(new_entry_sm),
            exit_time=_service_minutes_to_time_str(new_exit_sm),
            original_entry_time=_service_minutes_to_time_str(original_entry_sm),
        ))

    db.commit()

    # A held train's delay can push its own terminus arrival past a configured
    # turnaround's minimum -- ramp the paired departure the same way shift_stop does.
    for trip_id in delayed_trip_ids:
        _maybe_auto_regulate(db, trip_id, now)

    return affected


def create_interdiction(
    db: Session, y_top: float, y_bottom: float, start_time: str, end_time: str,
    description: str, now: datetime | None = None,
) -> InterdictionResult:
    now = now or datetime.now()
    top, bottom = min(y_top, y_bottom), max(y_top, y_bottom)
    interdiction = models.Interdiction(
        y_top=top, y_bottom=bottom, start_time=start_time, end_time=end_time, description=description,
    )
    db.add(interdiction)
    db.flush()

    affected = _apply_interdiction(db, interdiction, now)
    return InterdictionResult(interdiction=InterdictionOut.model_validate(interdiction), affected_trips=affected)


def _get_interdiction_or_raise(db: Session, interdiction_id: int) -> models.Interdiction:
    interdiction = db.query(models.Interdiction).filter(models.Interdiction.id == interdiction_id).first()
    if interdiction is None:
        raise InterdictionNotFoundError(interdiction_id)
    return interdiction


def _revert_interdiction(db: Session, interdiction_id: int, now: datetime) -> None:
    lookback_minutes = get_edit_lookback_minutes(db)
    now_sm = datetime_to_service_minutes(now)

    snapshots = (
        db.query(models.InterdictionStopSnapshot)
        .filter(models.InterdictionStopSnapshot.interdiction_id == interdiction_id)
        .all()
    )
    for snapshot in snapshots:
        stop = (
            db.query(models.PlannedStop)
            .filter(
                models.PlannedStop.trip_id == snapshot.trip_id,
                models.PlannedStop.station_id == snapshot.station_id,
            )
            .first()
        )
        if stop is None:
            continue
        current_sm = time_str_to_service_minutes(stop.departure_time)
        if (now_sm - current_sm) > lookback_minutes:
            continue
        stop.arrival_time = snapshot.arrival_time
        stop.departure_time = snapshot.departure_time

    db.query(models.InterdictionStopSnapshot).filter(
        models.InterdictionStopSnapshot.interdiction_id == interdiction_id
    ).delete()
    db.commit()


def update_interdiction(
    db: Session, interdiction_id: int, y_top: float, y_bottom: float,
    start_time: str, end_time: str, description: str, now: datetime | None = None,
) -> InterdictionResult:
    now = now or datetime.now()
    interdiction = _get_interdiction_or_raise(db, interdiction_id)

    _revert_interdiction(db, interdiction_id, now)

    top, bottom = min(y_top, y_bottom), max(y_top, y_bottom)
    interdiction.y_top, interdiction.y_bottom = top, bottom
    interdiction.start_time, interdiction.end_time = start_time, end_time
    interdiction.description = description
    db.commit()

    affected = _apply_interdiction(db, interdiction, now)
    return InterdictionResult(interdiction=InterdictionOut.model_validate(interdiction), affected_trips=affected)


def delete_interdiction(db: Session, interdiction_id: int, now: datetime | None = None) -> None:
    now = now or datetime.now()
    _get_interdiction_or_raise(db, interdiction_id)
    _revert_interdiction(db, interdiction_id, now)
    db.query(models.Interdiction).filter(models.Interdiction.id == interdiction_id).delete()
    db.commit()
