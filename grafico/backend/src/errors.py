class TripNotFoundError(Exception):
    def __init__(self, trip_id: str):
        self.trip_id = trip_id
        super().__init__(f"Trip not found: {trip_id}")


class StationNotFoundError(Exception):
    def __init__(self, station_id: str):
        self.station_id = station_id
        super().__init__(f"Station not found on trip: {station_id}")


class ChronologyViolationError(Exception):
    pass


class LookbackExceededError(Exception):
    pass
