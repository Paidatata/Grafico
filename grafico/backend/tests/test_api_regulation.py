from datetime import datetime


def test_auto_regulation_setting_round_trip(app_client):
    get_response = app_client.get("/api/settings/auto-regulation")
    assert get_response.json() == {"enabled": False}

    put_response = app_client.put("/api/settings/auto-regulation", json={"enabled": True})
    assert put_response.status_code == 200

    assert app_client.get("/api/settings/auto-regulation").json() == {"enabled": True}


def test_apply_regulation_endpoint(app_client, monkeypatch):
    from tests.test_api import _freeze_service_now
    _freeze_service_now(monkeypatch, datetime(2026, 8, 16, 4, 30, 0))

    app_client.post("/api/template/import", json=[
        {"trip_id": "ARRIVAL", "direction": "BFU-RGS",
         "stops": [{"station": "RGS", "time": "05:20:00"}, {"station": "BFU", "time": "05:50:00"}]},
        {"trip_id": "D1", "direction": "RGS-BFU",
         "stops": [{"station": "BFU", "time": "06:15:00"}, {"station": "RGS", "time": "06:45:00"}]},
    ])
    app_client.put("/api/stations/BFU/turnaround", json={"turnaround_seconds": 1200})
    app_client.post("/api/stops/shift", json={"trip_id": "ARRIVAL", "station_id": "BFU", "new_time": "06:05:00"})

    response = app_client.post("/api/regulation/apply", json={"trip_id": "ARRIVAL", "station_id": "BFU"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["trip_id"] == "D1"
    assert body[0]["stops"][0]["time"] == "06:25:00"
