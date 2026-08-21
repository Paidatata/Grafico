import pytest
from datetime import datetime

from src import service
from src.db import init_db
from src.errors import DuplicateScheduleNameError


def test_list_schedules_includes_the_seeded_base_schedule(db_session):
    init_db(db_session.get_bind())
    schedules = service.list_schedules(db_session)
    assert len(schedules) == 1
    assert schedules[0].name == "Grade Base CPTM"


def test_create_schedule_adds_a_new_empty_schedule(db_session):
    init_db(db_session.get_bind())
    created = service.create_schedule(db_session, "Grade Pico")
    assert created.name == "Grade Pico"

    names = {s.name for s in service.list_schedules(db_session)}
    assert names == {"Grade Base CPTM", "Grade Pico"}


def test_create_schedule_with_duplicate_name_raises(db_session):
    init_db(db_session.get_bind())
    service.create_schedule(db_session, "Grade Pico")
    with pytest.raises(DuplicateScheduleNameError):
        service.create_schedule(db_session, "Grade Pico")


def _seed_named_schedule(db_session, name="Grade Pico"):
    from src import models
    init_db(db_session.get_bind())
    created = service.create_schedule(db_session, name)
    db_session.add(models.TemplateTrip(
        id="TRIP_X", train_code="P1", direction="BFU-RGS", line="Line 710",
        schedule_id=created.id,
    ))
    db_session.add(models.TemplatePlannedStop(
        trip_id="TRIP_X", station_id="BFU", arrival_time="05:00:00",
        departure_time="05:00:00", sequence_order=0, schedule_id=created.id,
    ))
    db_session.add(models.TemplatePlannedStop(
        trip_id="TRIP_X", station_id="RGS", arrival_time="05:30:00",
        departure_time="05:30:00", sequence_order=1, schedule_id=created.id,
    ))
    db_session.commit()
    return created.id


def test_get_schedule_trips_returns_only_that_schedules_trips(db_session):
    schedule_id = _seed_named_schedule(db_session)

    result = service.get_schedule_trips(db_session, schedule_id)
    assert len(result.trips) == 1
    assert result.trips[0].trip_id == "TRIP_X"

    base_result = service.get_schedule_trips(db_session, 1)
    assert base_result.trips == []


from src.errors import LastScheduleDeletionError, ScheduleNotFoundError


def test_rename_schedule(db_session):
    init_db(db_session.get_bind())
    created = service.create_schedule(db_session, "Grade Pico")
    renamed = service.rename_schedule(db_session, created.id, "Grade Pico Renomeada")
    assert renamed.name == "Grade Pico Renomeada"


def test_rename_unknown_schedule_raises(db_session):
    init_db(db_session.get_bind())
    with pytest.raises(ScheduleNotFoundError):
        service.rename_schedule(db_session, 999, "X")


def test_delete_schedule(db_session):
    init_db(db_session.get_bind())
    created = service.create_schedule(db_session, "Grade Pico")
    service.delete_schedule(db_session, created.id)
    assert [s.name for s in service.list_schedules(db_session)] == ["Grade Base CPTM"]


def test_delete_the_only_remaining_schedule_raises(db_session):
    init_db(db_session.get_bind())
    with pytest.raises(LastScheduleDeletionError):
        service.delete_schedule(db_session, 1)


def test_clone_schedule_copies_trips_and_stops(db_session):
    from src import models
    schedule_id = _seed_named_schedule(db_session, "Grade Pico")

    cloned = service.clone_schedule(db_session, schedule_id, "Grade Pico Copia")
    assert cloned.name == "Grade Pico Copia"

    cloned_trips = service.get_schedule_trips(db_session, cloned.id)
    assert len(cloned_trips.trips) == 1
    assert cloned_trips.trips[0].trip_id == "TRIP_X"  # same trip_id, different schedule_id
    assert len(cloned_trips.trips[0].stops) == 2

    # Original schedule's trips are untouched
    original_trips = service.get_schedule_trips(db_session, schedule_id)
    assert len(original_trips.trips) == 1


def _add_template_trip(db_session, schedule_id, trip_id, train_code, direction, first_station, first_time, last_station="BFU"):
    from src import models
    db_session.add(models.TemplateTrip(
        id=trip_id, train_code=train_code, direction=direction, line="Line 710", schedule_id=schedule_id,
    ))
    db_session.add(models.TemplatePlannedStop(
        trip_id=trip_id, station_id=first_station, arrival_time=first_time,
        departure_time=first_time, sequence_order=0, schedule_id=schedule_id,
    ))
    db_session.add(models.TemplatePlannedStop(
        trip_id=trip_id, station_id=last_station, arrival_time="23:59:00",
        departure_time="23:59:00", sequence_order=1, schedule_id=schedule_id,
    ))
    db_session.commit()


def test_renumber_assigns_sequential_odd_numbers_to_bfu_terminating_trips(db_session):
    init_db(db_session.get_bind())
    created = service.create_schedule(db_session, "Grade Pico")
    # Both trips end at BFU (direction RGS-BFU) => odd group. Later departure gets the higher number.
    _add_template_trip(db_session, created.id, "T2", "P99", "RGS-BFU", "SAN", "06:00:00")
    _add_template_trip(db_session, created.id, "T1", "P1", "RGS-BFU", "SAN", "05:00:00")

    result = service.renumber_schedule(db_session, created.id)
    codes_by_trip = {t.trip_id: t.train_code for t in result.trips}
    assert codes_by_trip["T1"] == "P1"   # earlier departure -> smaller odd number
    assert codes_by_trip["T2"] == "P3"


def test_renumber_uses_each_trips_own_prefix_letter(db_session):
    init_db(db_session.get_bind())
    created = service.create_schedule(db_session, "Grade Pico")
    # Custom prefix "X" on a BFU-terminating (odd) trip must be preserved.
    _add_template_trip(db_session, created.id, "T1", "X7", "RGS-BFU", "SAN", "05:00:00")

    result = service.renumber_schedule(db_session, created.id)
    assert result.trips[0].train_code == "X1"


def test_renumber_ties_break_by_terminal_proximity(db_session):
    """Same departure_time, same direction (RGS-BFU) — closer-to-BFU origin wins the smaller number."""
    init_db(db_session.get_bind())
    created = service.create_schedule(db_session, "Grade Pico")
    _add_template_trip(db_session, created.id, "FAR", "P1", "RGS-BFU", "RGS", "05:00:00")   # far from BFU
    _add_template_trip(db_session, created.id, "NEAR", "P1", "RGS-BFU", "LUZ", "05:00:00")  # close to BFU

    result = service.renumber_schedule(db_session, created.id)
    codes_by_trip = {t.trip_id: t.train_code for t in result.trips}
    assert codes_by_trip["NEAR"] == "P1"
    assert codes_by_trip["FAR"] == "P3"


def test_create_trips_batch_expands_headway_and_offsets(db_session):
    from src.schemas import StopOffset, TripBatchCreate
    init_db(db_session.get_bind())
    created = service.create_schedule(db_session, "Grade Pico")

    payload = TripBatchCreate(
        direction="RGS-BFU",
        first_departure="05:00:00",
        last_station="BFU",
        count=2,
        headway_seconds=900,  # 15 min
        prefix="X",
        stop_offsets=[
            StopOffset(station="SAN", offset_seconds=0),
            StopOffset(station="BFU", offset_seconds=1800),  # +30 min
        ],
    )
    result = service.create_trips_batch(db_session, created.id, payload)

    assert len(result.trips) == 2
    first, second = sorted(result.trips, key=lambda t: t.start_time)
    assert first.start_time == "05:00:00"
    assert first.stops[-1].time == "05:30:00"
    assert second.start_time == "05:15:00"
    assert second.stops[-1].time == "05:45:00"
    # Renumbering ran automatically: both trips end at BFU => odd group, custom prefix X.
    assert {first.train_code, second.train_code} == {"X1", "X3"}


def test_update_trip_prefix_then_renumbers(db_session):
    init_db(db_session.get_bind())
    created = service.create_schedule(db_session, "Grade Pico")
    _add_template_trip(db_session, created.id, "T1", "P1", "RGS-BFU", "SAN", "05:00:00")

    result = service.update_trip_prefix(db_session, created.id, "T1", "X")
    assert result.trips[0].train_code == "X1"


def test_load_schedule_copies_template_to_live_and_sets_current(db_session):
    init_db(db_session.get_bind())
    created = service.create_schedule(db_session, "Grade Pico")
    _add_template_trip(db_session, created.id, "T1", "P1", "RGS-BFU", "SAN", "05:00:00")

    result = service.load_schedule(db_session, created.id)
    assert len(result.trips) == 1
    assert service.get_current_schedule_id() == created.id

    live = service.get_live_schedule(db_session)
    assert len(live.trips) == 1
    assert live.trips[0].trip_id == "T1"
