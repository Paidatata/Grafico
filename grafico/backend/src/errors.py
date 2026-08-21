class TripNotFoundError(Exception):
    def __init__(self, trip_id: str):
        self.trip_id = trip_id
        super().__init__(f"Trip not found: {trip_id}")


class StationNotFoundError(Exception):
    def __init__(self, station_id: str):
        self.station_id = station_id
        super().__init__(f"Station not found on trip: {station_id}")


class DuplicateTripError(Exception):
    """An import payload repeats a trip_id, or a station within one trip (maps to 400)."""


class InvalidTimeError(Exception):
    """A caller-supplied clock time is unparseable or out of range (maps to 400)."""


class ChronologyViolationError(Exception):
    pass


class LookbackExceededError(Exception):
    pass


class DuplicateScheduleNameError(Exception):
    """A schedule name is not unique (maps to 400)."""


class ScheduleNotFoundError(Exception):
    def __init__(self, schedule_id: int):
        self.schedule_id = schedule_id
        super().__init__(f"Schedule not found: {schedule_id}")


class LastScheduleDeletionError(Exception):
    """Refuses to delete the only remaining schedule (maps to 400)."""


class InterdictionNotFoundError(Exception):
    def __init__(self, interdiction_id: int):
        self.interdiction_id = interdiction_id
        super().__init__(f"Interdiction not found: {interdiction_id}")

