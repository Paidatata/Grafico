from datetime import datetime


def test_create_interdiction_endpoint(app_client, monkeypatch):
    from tests.test_api import _freeze_service_now
    _freeze_service_now(monkeypatch, datetime(2026, 8, 16, 4, 30, 0))

    app_client.post("/api/template/import", json=[
        {
            "trip_id": "TRIP_BFU-RGS_050000", "direction": "BFU-RGS",
            "stops": [{"station": "BFU", "time": "05:00:00"}, {"station": "RGS", "time": "05:40:00"}],
        },
    ])

    response = app_client.post("/api/interdictions", json={
        "y_top": 1000.0, "y_bottom": 6000.0,
        "start_time": "05:00:00", "end_time": "06:00:00", "description": "Obra",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["interdiction"]["description"] == "Obra"
    assert len(body["affected_trips"]) == 1


def test_delete_interdiction_endpoint(app_client, monkeypatch):
    from tests.test_api import _freeze_service_now
    _freeze_service_now(monkeypatch, datetime(2026, 8, 16, 4, 30, 0))

    app_client.post("/api/template/import", json=[
        {
            "trip_id": "TRIP_BFU-RGS_050000", "direction": "BFU-RGS",
            "stops": [{"station": "BFU", "time": "05:00:00"}, {"station": "RGS", "time": "05:40:00"}],
        },
    ])

    res = app_client.post("/api/interdictions", json={
        "y_top": 1000.0, "y_bottom": 6000.0,
        "start_time": "05:00:00", "end_time": "06:00:00", "description": "Obra",
    }).json()

    interdiction_id = res["interdiction"]["id"]
    del_res = app_client.delete(f"/api/interdictions/{interdiction_id}")
    assert del_res.status_code == 200
    assert del_res.json() == {"deleted": interdiction_id}
