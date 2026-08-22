import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from .models import Base, Setting, Station, Schedule

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "railway.db")

STATIONS_METADATA = [
    {"id": "RGS", "name": "Rio Grande da Serra", "y_coordinate": 500.32, "line": "Line 10"},
    {"id": "RPI", "name": "Ribeirão Pires", "y_coordinate": 1100.32, "line": "Line 10"},
    {"id": "GPT", "name": "Guapituba", "y_coordinate": 1660.32, "line": "Line 10"},
    {"id": "MAU", "name": "Mauá", "y_coordinate": 2100.32, "line": "Line 10"},
    {"id": "CPV", "name": "Capuava", "y_coordinate": 2500.32, "line": "Line 10"},
    {"id": "SAN", "name": "Santo André", "y_coordinate": 2980.32, "line": "Line 10"},
    {"id": "PSA", "name": "Prefeito Saladino", "y_coordinate": 3220.32, "line": "Line 10"},
    {"id": "UTG", "name": "Utinga", "y_coordinate": 3420.32, "line": "Line 10"},
    {"id": "SCS", "name": "São Caetano do Sul", "y_coordinate": 3860.32, "line": "Line 10"},
    {"id": "TMD", "name": "Tamanduateí", "y_coordinate": 4180.32, "line": "Line 10"},
    {"id": "IPG", "name": "Ipiranga", "y_coordinate": 4380.32, "line": "Line 10"},
    {"id": "MOC", "name": "Juventus-Mooca", "y_coordinate": 4740.32, "line": "Line 10"},
    {"id": "BAS", "name": "Brás", "y_coordinate": 4980.32, "line": "Line 10"},
    {"id": "LUZ", "name": "Luz", "y_coordinate": 5380.32, "line": "Line 10"},
    {"id": "BFU", "name": "Barra Funda", "y_coordinate": 5860.32, "line": "Line 10"},
    {"id": "LUZ_L7", "name": "Luz (L7)", "y_coordinate": 6180.32, "line": "Line 7"},
    {"id": "ABR", "name": "Água Branca", "y_coordinate": 6420.32, "line": "Line 7"},
    {"id": "LPA", "name": "Lapa", "y_coordinate": 6700.32, "line": "Line 7"},
    {"id": "PQR", "name": "Piqueri", "y_coordinate": 6980.32, "line": "Line 7"},
    {"id": "PRU", "name": "Pirituba", "y_coordinate": 7300.32, "line": "Line 7"},
    {"id": "VCL", "name": "Vila Clarice", "y_coordinate": 7500.32, "line": "Line 7"},
    {"id": "JRG", "name": "Jaraguá", "y_coordinate": 7900.32, "line": "Line 7"},
    {"id": "VPL", "name": "Vila Aurora", "y_coordinate": 8260.32, "line": "Line 7"},
    {"id": "PRT", "name": "Perus", "y_coordinate": 8700.32, "line": "Line 7"},
    {"id": "CAI", "name": "Caieiras", "y_coordinate": 9260.32, "line": "Line 7"},
    {"id": "FMO", "name": "Franco da Rocha", "y_coordinate": 9500.32, "line": "Line 7"},
    {"id": "BFI", "name": "Baltazar Fidélis", "y_coordinate": 9940.32, "line": "Line 7"},
    {"id": "FDR", "name": "Francisco Morato", "y_coordinate": 10300.32, "line": "Line 7"},
    {"id": "BTJ", "name": "Botujuru", "y_coordinate": 10580.32, "line": "Line 7"},
    {"id": "CLP", "name": "Campo Limpo Paulista", "y_coordinate": 10900.32, "line": "Line 7"},
    {"id": "VAU", "name": "Várzea Paulista", "y_coordinate": 11220.32, "line": "Line 7"},
    {"id": "JUN", "name": "Jundiaí", "y_coordinate": 11520.32, "line": "Line 7"},
]

DEFAULT_LOOKBACK_MINUTES = "15"
DEFAULT_TURNAROUND_SECONDS = 180  # 3 min -- every station starts here; an operator's save overrides it until changed again


def make_session_factory(db_path: str):
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False)


DB_PATH = os.environ.get("GRAFICO_DB_PATH", DEFAULT_DB_PATH)
engine, SessionLocal = make_session_factory(DB_PATH)


def init_db(target_engine=None) -> None:
    bind = target_engine or engine
    Base.metadata.create_all(bind)

    Session = sessionmaker(bind=bind)
    db = Session()
    try:
        # Run column migrations first using raw SQL before any ORM queries on modified models
        try:
            existing_cols = {row[1] for row in db.execute(text("PRAGMA table_info(stations)"))}
            if "turnaround_seconds" not in existing_cols:
                db.execute(text("ALTER TABLE stations ADD COLUMN turnaround_seconds INTEGER"))
            # Backfill only -- an operator's explicit save is never overwritten by this, since
            # a saved value is never NULL again. One-time per station, idempotent on every call.
            db.execute(
                text("UPDATE stations SET turnaround_seconds = :default WHERE turnaround_seconds IS NULL"),
                {"default": DEFAULT_TURNAROUND_SECONDS},
            )
        except Exception as e:
            print(f"Erro ao verificar ou atualizar tabela stations: {e}")

        try:
            existing_cols = {row[1] for row in db.execute(text("PRAGMA table_info(trips)"))}
            if "active_first_seq" not in existing_cols:
                db.execute(text("ALTER TABLE trips ADD COLUMN active_first_seq INTEGER"))
            if "active_last_seq" not in existing_cols:
                db.execute(text("ALTER TABLE trips ADD COLUMN active_last_seq INTEGER"))
        except Exception as e:
            print(f"Erro ao verificar ou atualizar tabela trips: {e}")

        try:
            result = db.execute(text("PRAGMA table_info(template_trips)"))
            columns = [row[1] for row in result]
            if 'schedule_id' not in columns:
                db.execute(text("ALTER TABLE template_trips ADD COLUMN schedule_id INTEGER"))
                db.execute(text("UPDATE template_trips SET schedule_id = 1 WHERE schedule_id IS NULL"))
        except Exception as e:
            print(f"Erro ao verificar ou atualizar tabela template_trips: {e}")

        try:
            result = db.execute(text("PRAGMA table_info(template_planned_stops)"))
            columns = [row[1] for row in result]
            if 'schedule_id' not in columns:
                db.execute(text("ALTER TABLE template_planned_stops ADD COLUMN schedule_id INTEGER"))
                db.execute(text("UPDATE template_planned_stops SET schedule_id = 1 WHERE schedule_id IS NULL"))
        except Exception as e:
            print(f"Erro ao verificar ou atualizar tabela template_planned_stops: {e}")

        db.commit()

        if db.query(Station).count() == 0:
            for station in STATIONS_METADATA:
                db.add(Station(turnaround_seconds=DEFAULT_TURNAROUND_SECONDS, **station))

        if db.query(Setting).filter(Setting.key == "edit_lookback_minutes").first() is None:
            db.add(Setting(key="edit_lookback_minutes", value=DEFAULT_LOOKBACK_MINUTES))

        # Verifica se o Schedule 'Grade Base CPTM' existe, se não existir insere
        schedule = db.query(Schedule).filter(Schedule.name == "Grade Base CPTM").first()
        if not schedule:
            new_schedule = Schedule(id=1, name="Grade Base CPTM")
            db.add(new_schedule)
            db.commit()

        db.commit()
    finally:
        db.close()
