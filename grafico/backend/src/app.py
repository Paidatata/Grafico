import logging
import os
import sys
from pathlib import Path

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import service
from .db import SessionLocal, init_db
from .errors import (
    ChronologyViolationError,
    DuplicateTripError,
    DuplicateScheduleNameError,
    InterdictionNotFoundError,
    InvalidTimeError,
    LastScheduleDeletionError,
    LookbackExceededError,
    ScheduleNotFoundError,
    StationNotFoundError,
    TripNotFoundError,
)
from .schemas import AutoRegulationSetting, InterdictionIn, InterdictionOut, InterdictionResult, LookbackSetting, RegulationRequest, ScheduleOut, ScheduleMetaOut, ScheduleCreate, ShiftRequest, TemplateImportTrip, TripBatchCreate, TripPrefixUpdate, TripOut, TurnaroundSetting



from .scheduler import run_startup_catchup_if_needed, start_scheduler
from .ws_manager import ConnectionManager

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "src"

logger = logging.getLogger(__name__)

app = FastAPI(title="Grafico Railway Schedule API")
manager = ConnectionManager()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    db = SessionLocal()
    try:
        run_startup_catchup_if_needed(db)
        # Auto-seed schedule.json on startup if DB has no trips (skip during automated pytest runs)
        import sys
        if "pytest" not in sys.modules and "PYTEST_CURRENT_TEST" not in os.environ:
            schedule_json_path = Path(__file__).resolve().parent.parent / "data" / "schedule.json"
            if schedule_json_path.exists():
                live_schedule = service.get_live_schedule(db)
                if not live_schedule.trips:
                    import json
                    try:
                        with open(schedule_json_path, "r", encoding="utf-8") as f:
                            raw_data = json.load(f)
                            trips_data = raw_data if isinstance(raw_data, list) else raw_data.get("trips", [])
                            if trips_data:
                                trips = [TemplateImportTrip(**t) for t in trips_data]
                                service.import_template(db, trips)
                                logger.info("Grade inicial (%d viagens de schedule.json) carregada com sucesso no banco de dados.", len(trips))
                    except Exception as e:
                        logger.error("Erro ao realizar auto-seed do schedule.json: %s", e)
    finally:
        db.close()
    app.state.scheduler = start_scheduler()


@app.exception_handler(Exception)
def _unhandled_error(request, exc: Exception):
    """Catch-all so an unexpected failure is a JSON 500, never a raw stack trace.

    The specific domain handlers below still take precedence — Starlette dispatches to
    the most specific registered handler for the raised type. The message is deliberately
    generic; the detail goes to the server log instead of the client.
    """
    logger.exception("Unhandled error serving %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.exception_handler(TripNotFoundError)
def _trip_not_found(request, exc: TripNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(StationNotFoundError)
def _station_not_found(request, exc: StationNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(InterdictionNotFoundError)
def _interdiction_not_found(request, exc: InterdictionNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})



@app.exception_handler(DuplicateTripError)
def _duplicate_trip(request, exc: DuplicateTripError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(InvalidTimeError)
def _invalid_time(request, exc: InvalidTimeError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(ChronologyViolationError)
def _chronology_violation(request, exc: ChronologyViolationError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(LookbackExceededError)
def _lookback_exceeded(request, exc: LookbackExceededError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/api/schedule", response_model=ScheduleOut)
def get_schedule(db: Session = Depends(get_db)):
    return service.get_live_schedule(db)


@app.get("/api/schedule/programmed")
def get_programmed_schedule():
    import json
    data_dir = Path(__file__).resolve().parent.parent / "data"
    with open(data_dir / "schedule.json", "r") as f:
        trips = json.load(f)
    return {"trips": trips}


@app.post("/api/template/import")
async def import_template(trips: list[TemplateImportTrip], db: Session = Depends(get_db)):
    count = service.import_template(db, trips)
    await manager.broadcast({"type": "schedule_reset"})
    return {"imported_trips": count}


@app.post("/api/stops/shift", response_model=TripOut)
async def shift_stop(payload: ShiftRequest, db: Session = Depends(get_db)):
    trip = service.shift_stop(db, payload.trip_id, payload.station_id, payload.new_time)
    await manager.broadcast({"type": "schedule_reset"})
    return trip


@app.post("/api/trips/{trip_id}/reset", response_model=TripOut)
async def reset_trip(trip_id: str, db: Session = Depends(get_db)):
    trip = service.reset_trip(db, trip_id)
    await manager.broadcast({"type": "trip_updated", "trip": trip.model_dump()})
    return trip


@app.post("/api/trips/{trip_id}/suppress-from/{station_id}", response_model=TripOut)
async def suppress_from(trip_id: str, station_id: str, db: Session = Depends(get_db)):
    trip = service.suppress_from(db, trip_id, station_id)
    await manager.broadcast({"type": "trip_updated", "trip": trip.model_dump()})
    return trip


@app.post("/api/trips/{trip_id}/depart-from/{station_id}", response_model=TripOut)
async def depart_from(trip_id: str, station_id: str, db: Session = Depends(get_db)):
    trip = service.depart_from(db, trip_id, station_id)
    await manager.broadcast({"type": "trip_updated", "trip": trip.model_dump()})
    return trip



@app.get("/api/settings/edit-lookback-minutes", response_model=LookbackSetting)
def get_lookback(db: Session = Depends(get_db)):
    return LookbackSetting(edit_lookback_minutes=service.get_edit_lookback_minutes(db))


@app.put("/api/settings/edit-lookback-minutes", response_model=LookbackSetting)
def put_lookback(payload: LookbackSetting, db: Session = Depends(get_db)):
    service.set_edit_lookback_minutes(db, payload.edit_lookback_minutes)
    return payload


@app.put("/api/stations/{station_id}/turnaround", response_model=TurnaroundSetting)
async def put_station_turnaround(station_id: str, payload: TurnaroundSetting, db: Session = Depends(get_db)):
    service.set_station_turnaround(db, station_id, payload.turnaround_seconds)
    await manager.broadcast({"type": "schedule_reset"})
    return payload


@app.get("/api/settings/auto-regulation", response_model=AutoRegulationSetting)
def get_auto_regulation(db: Session = Depends(get_db)):
    return AutoRegulationSetting(enabled=service.get_auto_regulation_enabled(db))



@app.put("/api/settings/auto-regulation", response_model=AutoRegulationSetting)
def put_auto_regulation(payload: AutoRegulationSetting, db: Session = Depends(get_db)):
    service.set_auto_regulation_enabled(db, payload.enabled)
    return payload


@app.post("/api/regulation/apply", response_model=list[TripOut])
async def post_apply_regulation(payload: RegulationRequest, db: Session = Depends(get_db)):
    updated = service.apply_regulation(db, payload.trip_id, payload.station_id)
    for trip in updated:
        await manager.broadcast({"type": "trip_updated", "trip": trip.model_dump()})
    return updated


@app.post("/api/interdictions", response_model=InterdictionResult)
async def post_interdiction(payload: InterdictionIn, db: Session = Depends(get_db)):
    result = service.create_interdiction(
        db, payload.y_top, payload.y_bottom, payload.start_time, payload.end_time, payload.description,
    )
    await manager.broadcast({"type": "interdiction_changed", "result": result.model_dump()})
    return result


@app.put("/api/interdictions/{interdiction_id}", response_model=InterdictionResult)
async def put_interdiction(interdiction_id: int, payload: InterdictionIn, db: Session = Depends(get_db)):
    result = service.update_interdiction(
        db, interdiction_id, payload.y_top, payload.y_bottom,
        payload.start_time, payload.end_time, payload.description,
    )
    await manager.broadcast({"type": "interdiction_changed", "result": result.model_dump()})
    return result


@app.delete("/api/interdictions/{interdiction_id}")
async def delete_interdiction(interdiction_id: int, db: Session = Depends(get_db)):
    service.delete_interdiction(db, interdiction_id)
    await manager.broadcast({"type": "interdiction_deleted", "interdiction_id": interdiction_id})
    return {"deleted": interdiction_id}





@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.exception_handler(DuplicateScheduleNameError)
def _duplicate_schedule_name(request, exc: DuplicateScheduleNameError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/api/schedules", response_model=list[ScheduleMetaOut])
def get_schedules(db: Session = Depends(get_db)):
    return service.list_schedules(db)


@app.post("/api/schedules", response_model=ScheduleMetaOut)
def post_schedule(payload: ScheduleCreate, db: Session = Depends(get_db)):
    return service.create_schedule(db, payload.name)


@app.get("/api/schedules/{schedule_id}/trips", response_model=ScheduleOut)
def get_schedule_trips(schedule_id: int, db: Session = Depends(get_db)):
    return service.get_schedule_trips(db, schedule_id)


@app.exception_handler(ScheduleNotFoundError)
def _schedule_not_found(request, exc: ScheduleNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(LastScheduleDeletionError)
def _last_schedule_deletion(request, exc: LastScheduleDeletionError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.patch("/api/schedules/{schedule_id}", response_model=ScheduleMetaOut)
def patch_schedule(schedule_id: int, payload: ScheduleCreate, db: Session = Depends(get_db)):
    return service.rename_schedule(db, schedule_id, payload.name)


@app.delete("/api/schedules/{schedule_id}")
def delete_schedule(schedule_id: int, db: Session = Depends(get_db)):
    service.delete_schedule(db, schedule_id)
    return {"deleted": schedule_id}


@app.post("/api/schedules/{schedule_id}/clone", response_model=ScheduleMetaOut)
def clone_schedule(schedule_id: int, payload: ScheduleCreate, db: Session = Depends(get_db)):
    return service.clone_schedule(db, schedule_id, payload.name)


@app.post("/api/schedules/{schedule_id}/renumber", response_model=ScheduleOut)
def renumber_schedule(schedule_id: int, db: Session = Depends(get_db)):
    return service.renumber_schedule(db, schedule_id)


@app.post("/api/schedules/{schedule_id}/trips/batch", response_model=ScheduleOut)
def post_trips_batch(schedule_id: int, payload: TripBatchCreate, db: Session = Depends(get_db)):
    return service.create_trips_batch(db, schedule_id, payload)


@app.post("/api/schedules/{schedule_id}/load", response_model=ScheduleOut)
async def load_schedule(schedule_id: int, db: Session = Depends(get_db)):
    result = service.load_schedule(db, schedule_id)
    await manager.broadcast({"type": "schedule_reset"})
    return result


@app.patch("/api/schedules/{schedule_id}/trips/{trip_id}", response_model=ScheduleOut)
def patch_trip_prefix(schedule_id: int, trip_id: str, payload: TripPrefixUpdate, db: Session = Depends(get_db)):
    return service.update_trip_prefix(db, schedule_id, trip_id, payload.prefix)


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
