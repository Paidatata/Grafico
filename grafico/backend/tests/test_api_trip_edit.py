from datetime import datetime


def _seed(app_client, monkeypatch, now: datetime):
    from tests.test_api import _freeze_service_now
    _freeze_service_now(monkeypatch, now)

    app_client.post("/api/template/import", json=[
        {
            "trip_id": "TRIP_BFU-RGS_050000", "direction": "BFU-RGS",
            "stops": [
                {"station": "BFU", "time": "05:00:00"},
                {"station": "LUZ", "time": "05:10:00"},
                {"station": "BAS", "time": "05:20:00"},
                {"station": "RGS", "time": "05:30:00"},
            ],
        },
    ])


def test_suppress_from_endpoint_sets_active_last_seq(app_client, monkeypatch):
    _seed(app_client, monkeypatch, datetime(2026, 8, 13, 4, 30, 0))

    response = app_client.post("/api/trips/TRIP_BFU-RGS_050000/suppress-from/BAS")

    assert response.status_code == 200
    body = response.json()
    assert body["active_last_seq"] == 1  # LUZ (index 1) stays active; BAS/RGS suppressed


def test_suppress_from_endpoint_full_cancellation(app_client, monkeypatch):
    _seed(app_client, monkeypatch, datetime(2026, 8, 13, 4, 30, 0))

    response = app_client.post("/api/trips/TRIP_BFU-RGS_050000/suppress-from/BFU")

    assert response.status_code == 200
    assert response.json()["active_last_seq"] == -1


def test_suppress_from_endpoint_returns_404_for_unknown_trip(app_client, monkeypatch):
    _seed(app_client, monkeypatch, datetime(2026, 8, 13, 4, 30, 0))

    response = app_client.post("/api/trips/NOT_A_TRIP/suppress-from/BFU")

    assert response.status_code == 404


def test_suppress_from_endpoint_returns_404_for_unknown_station(app_client, monkeypatch):
    _seed(app_client, monkeypatch, datetime(2026, 8, 13, 4, 30, 0))

    response = app_client.post("/api/trips/TRIP_BFU-RGS_050000/suppress-from/NOT_A_STATION")

    assert response.status_code == 404


def test_suppress_from_endpoint_returns_400_beyond_lookback(app_client, monkeypatch):
    _seed(app_client, monkeypatch, datetime(2026, 8, 13, 6, 0, 0))

    response = app_client.post("/api/trips/TRIP_BFU-RGS_050000/suppress-from/BAS")

    assert response.status_code == 400


def test_depart_from_endpoint_sets_active_first_seq(app_client, monkeypatch):
    _seed(app_client, monkeypatch, datetime(2026, 8, 13, 4, 30, 0))

    response = app_client.post("/api/trips/TRIP_BFU-RGS_050000/depart-from/BAS")

    assert response.status_code == 200
    body = response.json()
    assert body["active_first_seq"] == 2
    assert body["stops"][0]["station"] == "BFU"


def test_depart_from_endpoint_returns_400_when_backward(app_client, monkeypatch):
    _seed(app_client, monkeypatch, datetime(2026, 8, 13, 4, 30, 0))
    app_client.post("/api/trips/TRIP_BFU-RGS_050000/depart-from/BAS")

    response = app_client.post("/api/trips/TRIP_BFU-RGS_050000/depart-from/LUZ")

    assert response.status_code == 400


def test_depart_from_endpoint_returns_400_beyond_lookback(app_client, monkeypatch):
    _seed(app_client, monkeypatch, datetime(2026, 8, 13, 6, 0, 0))

    response = app_client.post("/api/trips/TRIP_BFU-RGS_050000/depart-from/BAS")

    assert response.status_code == 400
