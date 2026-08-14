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


def test_import_then_get_schedule_carries_parser_train_code(app_client):
    # train_code is what the frontend displays instead of the internal trip_id
    # (see parser.py's compute_train_codes for the P/R/M field convention).
    payload = [
        {
            "trip_id": "TRIP_RGS-BFU_043700",
            "direction": "RGS-BFU",
            "train_code": "P15",
            "stops": [
                {"station": "SAN", "time": "04:37:00"},
                {"station": "BFU", "time": "05:00:00"},
            ],
        }
    ]
    app_client.post("/api/template/import", json=payload)

    trips = app_client.get("/api/schedule").json()["trips"]
    assert trips[0]["train_code"] == "P15"


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


def _import_single_trip(app_client):
    app_client.post("/api/template/import", json=[
        {
            "trip_id": "TRIP_BFU-RGS_050000",
            "direction": "BFU-RGS",
            "stops": [
                {"station": "BFU", "time": "05:00:00"},
                {"station": "RGS", "time": "05:30:00"},
            ],
        }
    ])


def test_import_with_duplicate_trip_id_returns_400_not_500(app_client):
    """The documented onboarding path imports backend/data/schedule.json, which has a
    repeated trip_id. It must fail with a clear 400, not an IntegrityError-driven 500."""
    duplicated = [
        {
            "trip_id": "TRIP_RGS-BFU_043700", "direction": "RGS-BFU",
            "stops": [{"station": "RGS", "time": "04:37:00"}],
        },
        {
            "trip_id": "TRIP_RGS-BFU_043700", "direction": "RGS-BFU",
            "stops": [{"station": "RGS", "time": "04:37:00"}],
        },
    ]
    response = app_client.post("/api/template/import", json=duplicated)
    assert response.status_code == 400
    assert "TRIP_RGS-BFU_043700" in response.json()["detail"]

    # The rejected import left no partial state, so a valid one still succeeds.
    ok = app_client.post("/api/template/import", json=[
        {
            "trip_id": "TRIP_BFU-RGS_050000", "direction": "BFU-RGS",
            "stops": [{"station": "BFU", "time": "05:00:00"}],
        }
    ])
    assert ok.status_code == 200
    assert ok.json() == {"imported_trips": 1}
    assert len(app_client.get("/api/schedule").json()["trips"]) == 1


def test_shift_stop_with_unparseable_time_returns_400(app_client):
    """The design spec mandates 400 for an unparseable new_time, not an opaque 500."""
    _import_single_trip(app_client)

    response = app_client.post("/api/stops/shift", json={
        "trip_id": "TRIP_BFU-RGS_050000", "station_id": "BFU", "new_time": "not-a-time",
    })
    assert response.status_code == 400
    assert "new_time" in response.json()["detail"]


def test_shift_stop_with_out_of_range_time_returns_400(app_client):
    """"25:00:00" parses arithmetically but is not a real clock time — reject, don't normalize."""
    _import_single_trip(app_client)

    for bad_time in ["25:00:00", "12:60:00", "12:00:60", "5:00:00", "05:00"]:
        response = app_client.post("/api/stops/shift", json={
            "trip_id": "TRIP_BFU-RGS_050000", "station_id": "BFU", "new_time": bad_time,
        })
        assert response.status_code == 400, f"{bad_time} should be rejected with 400"


def test_template_import_with_malformed_time_is_rejected(app_client):
    response = app_client.post("/api/template/import", json=[
        {
            "trip_id": "TRIP_BFU-RGS_050000",
            "direction": "BFU-RGS",
            "stops": [{"station": "BFU", "time": "25:99:99"}],
        }
    ])
    assert response.status_code == 422


def test_negative_lookback_minutes_is_rejected(app_client):
    """A negative window would lock every node on the chart."""
    response = app_client.put("/api/settings/edit-lookback-minutes", json={"edit_lookback_minutes": -5})
    assert response.status_code == 422

    # The stored setting must be untouched by the rejected write.
    assert app_client.get("/api/settings/edit-lookback-minutes").json()["edit_lookback_minutes"] >= 0


def test_unhandled_exception_returns_json_500_not_a_stack_trace(monkeypatch):
    from fastapi.testclient import TestClient
    from src.app import app

    def _boom(*args, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr("src.service.get_live_schedule", _boom)

    # raise_server_exceptions=False so the client sees the response the catch-all
    # handler produced rather than the exception Starlette re-raises for the server log.
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/schedule")

    assert response.status_code == 500
    assert "detail" in response.json()
    assert "kaboom" not in response.text  # internals stay out of the client-facing body


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
