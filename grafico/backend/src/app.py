from pathlib import Path

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import service
from .db import SessionLocal, init_db
from .errors import ChronologyViolationError, LookbackExceededError, StationNotFoundError, TripNotFoundError
from .schemas import LookbackSetting, ScheduleOut, ShiftRequest, TemplateImportTrip, TripOut
from .scheduler import run_startup_catchup_if_needed, start_scheduler
from .ws_manager import ConnectionManager

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "src"

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
    finally:
        db.close()
    app.state.scheduler = start_scheduler()


@app.exception_handler(TripNotFoundError)
def _trip_not_found(request, exc: TripNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(StationNotFoundError)
def _station_not_found(request, exc: StationNotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ChronologyViolationError)
def _chronology_violation(request, exc: ChronologyViolationError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(LookbackExceededError)
def _lookback_exceeded(request, exc: LookbackExceededError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/api/schedule", response_model=ScheduleOut)
def get_schedule(db: Session = Depends(get_db)):
    return service.get_live_schedule(db)


@app.post("/api/template/import")
async def import_template(trips: list[TemplateImportTrip], db: Session = Depends(get_db)):
    count = service.import_template(db, trips)
    await manager.broadcast({"type": "schedule_reset"})
    return {"imported_trips": count}


@app.post("/api/stops/shift", response_model=TripOut)
async def shift_stop(payload: ShiftRequest, db: Session = Depends(get_db)):
    trip = service.shift_stop(db, payload.trip_id, payload.station_id, payload.new_time)
    await manager.broadcast({"type": "trip_updated", "trip": trip.model_dump()})
    return trip


@app.post("/api/trips/{trip_id}/reset", response_model=TripOut)
async def reset_trip(trip_id: str, db: Session = Depends(get_db)):
    trip = service.reset_trip(db, trip_id)
    await manager.broadcast({"type": "trip_updated", "trip": trip.model_dump()})
    return trip


@app.get("/api/settings/edit-lookback-minutes", response_model=LookbackSetting)
def get_lookback(db: Session = Depends(get_db)):
    return LookbackSetting(edit_lookback_minutes=service.get_edit_lookback_minutes(db))


@app.put("/api/settings/edit-lookback-minutes", response_model=LookbackSetting)
def put_lookback(payload: LookbackSetting, db: Session = Depends(get_db)):
    service.set_edit_lookback_minutes(db, payload.edit_lookback_minutes)
    return payload


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
