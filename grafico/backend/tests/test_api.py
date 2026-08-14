from datetime import datetime


class _FixedNow:
    """Stand-in for the `datetime` module attribute inside src.service.

    service.py calls `datetime.now()`; monkeypatching `src.service.datetime`
    with an instance of this class makes that call return a fixed value so
    shift_stop's lookback-window check doesn't depend on the wall-clock time
    the test suite happens to run at.
    """

    def __init__(self, value: datetime) -> None:
        self._value = value

    def now(self, tz=None):
        return self._value


def _freeze_service_now(monkeypatch, value: datetime) -> None:
    monkeypatch.setattr("src.service.datetime", _FixedNow(value))


def test_get_schedule_empty_when_nothing_imported(app_client):
    response = app_client.get("/api/schedule")
    assert response.status_code == 200
    assert response.json() == {"trips": []}


def test_import_then_get_schedule(app_client):
    payload = [
        {
            "trip_id": "TRIP_BFU-RGS_050000",
            "direction": "BFU-RGS",
            "stops": [
                {"station": "BFU", "time": "05:00:00"},
                {"station": "RGS", "time": "05:30:00"},
            ],
        }
    ]
    import_response = app_client.post("/api/template/import", json=payload)
    assert import_response.status_code == 200
    assert import_response.json() == {"imported_trips": 1}

    schedule_response = app_client.get("/api/schedule")
    trips = schedule_response.json()["trips"]
    assert len(trips) == 1
    assert trips[0]["trip_id"] == "TRIP_BFU-RGS_050000"


def test_shift_stop_endpoint_propagates_downstream(app_client, monkeypatch):
    _freeze_service_now(monkeypatch, datetime(2026, 8, 13, 5, 0, 0))
    payload = [
        {
            "trip_id": "TRIP_BFU-RGS_050000",
            "direction": "BFU-RGS",
            "stops": [
                {"station": "BFU", "time": "05:00:00"},
                {"station": "RGS", "time": "05:30:00"},
            ],
        }
    ]
    app_client.post("/api/template/import", json=payload)

    response = app_client.post("/api/stops/shift", json={
        "trip_id": "TRIP_BFU-RGS_050000", "station_id": "BFU", "new_time": "05:03:00",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["stops"][0]["time"] == "05:03:00"
    assert body["stops"][1]["time"] == "05:33:00"


def test_shift_stop_unknown_trip_returns_404(app_client):
    response = app_client.post("/api/stops/shift", json={
        "trip_id": "NOT_A_TRIP", "station_id": "BFU", "new_time": "05:03:00",
    })
    assert response.status_code == 404


def test_reset_trip_endpoint(app_client, monkeypatch):
    _freeze_service_now(monkeypatch, datetime(2026, 8, 13, 5, 0, 0))
    payload = [
        {
            "trip_id": "TRIP_BFU-RGS_050000",
            "direction": "BFU-RGS",
            "stops": [{"station": "BFU", "time": "05:00:00"}],
        }
    ]
    app_client.post("/api/template/import", json=payload)
    app_client.post("/api/stops/shift", json={
        "trip_id": "TRIP_BFU-RGS_050000", "station_id": "BFU", "new_time": "05:05:00",
    })

    response = app_client.post("/api/trips/TRIP_BFU-RGS_050000/reset")
    assert response.status_code == 200
    assert response.json()["stops"][0]["time"] == "05:00:00"


def test_lookback_setting_round_trip(app_client):
    put_response = app_client.put("/api/settings/edit-lookback-minutes", json={"edit_lookback_minutes": 45})
    assert put_response.status_code == 200

    get_response = app_client.get("/api/settings/edit-lookback-minutes")
    assert get_response.json() == {"edit_lookback_minutes": 45}


def test_websocket_receives_trip_updated_broadcast(app_client, monkeypatch):
    _freeze_service_now(monkeypatch, datetime(2026, 8, 13, 5, 0, 0))
    payload = [
        {
            "trip_id": "TRIP_BFU-RGS_050000",
            "direction": "BFU-RGS",
            "stops": [{"station": "BFU", "time": "05:00:00"}],
        }
    ]
    app_client.post("/api/template/import", json=payload)

    with app_client.websocket_connect("/ws") as websocket:
        app_client.post("/api/stops/shift", json={
            "trip_id": "TRIP_BFU-RGS_050000", "station_id": "BFU", "new_time": "05:05:00",
        })
        message = websocket.receive_json()
        assert message["type"] == "trip_updated"
        assert message["trip"]["stops"][0]["time"] == "05:05:00"
