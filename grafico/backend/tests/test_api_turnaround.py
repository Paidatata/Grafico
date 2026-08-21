def test_put_turnaround_round_trip(app_client):
    response = app_client.put("/api/stations/RGS/turnaround", json={"turnaround_seconds": 600})
    assert response.status_code == 200
    assert response.json() == {"turnaround_seconds": 600}

    schedule = app_client.get("/api/schedule").json()
    assert schedule["station_turnarounds"] == {"RGS": 600}


def test_put_turnaround_unknown_station_returns_404(app_client):
    response = app_client.put("/api/stations/NOT_A_STATION/turnaround", json={"turnaround_seconds": 600})
    assert response.status_code == 404


def test_put_turnaround_negative_seconds_returns_422(app_client):
    response = app_client.put("/api/stations/RGS/turnaround", json={"turnaround_seconds": -5})
    assert response.status_code == 422
