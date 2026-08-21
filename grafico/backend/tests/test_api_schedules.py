def test_get_schedules_lists_base_schedule(app_client):
    response = app_client.get("/api/schedules")
    assert response.status_code == 200
    names = {s["name"] for s in response.json()}
    assert "Grade Base CPTM" in names


def test_post_schedules_creates_new_schedule(app_client):
    response = app_client.post("/api/schedules", json={"name": "Grade Pico"})
    assert response.status_code == 200
    assert response.json()["name"] == "Grade Pico"


def test_post_schedules_duplicate_name_returns_400(app_client):
    app_client.post("/api/schedules", json={"name": "Grade Pico"})
    response = app_client.post("/api/schedules", json={"name": "Grade Pico"})
    assert response.status_code == 400


def test_get_schedule_trips_returns_trips(app_client):
    created = app_client.post("/api/schedules", json={"name": "Grade Trips"}).json()
    response = app_client.get(f"/api/schedules/{created['id']}/trips")
    assert response.status_code == 200
    assert response.json()["trips"] == []


def test_patch_schedule_renames(app_client):
    created = app_client.post("/api/schedules", json={"name": "Grade To Rename"}).json()
    response = app_client.patch(f"/api/schedules/{created['id']}", json={"name": "Grade Renamed"})
    assert response.status_code == 200
    assert response.json()["name"] == "Grade Renamed"


def test_delete_schedule_removes_it(app_client):
    created = app_client.post("/api/schedules", json={"name": "Grade To Delete"}).json()
    response = app_client.delete(f"/api/schedules/{created['id']}")
    assert response.status_code == 200
    
    list_response = app_client.get("/api/schedules")
    names = {s["name"] for s in list_response.json()}
    assert "Grade To Delete" not in names
