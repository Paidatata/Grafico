from sqlalchemy import Column, Float, ForeignKey, Integer, String, ForeignKeyConstraint
from sqlalchemy.orm import declarative_base
from datetime import datetime
from sqlalchemy import DateTime

Base = declarative_base()


class Schedule(Base):
    __tablename__ = 'schedules'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    last_loaded_at = Column(DateTime, nullable=True)


class Station(Base):
    __tablename__ = "stations"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    y_coordinate = Column(Float, nullable=False)
    line = Column(String, nullable=False)
    turnaround_seconds = Column(Integer, nullable=True)



class TemplateTrip(Base):
    __tablename__ = "template_trips"
    id = Column(String, primary_key=True)
    train_code = Column(String, nullable=False)
    direction = Column(String, nullable=False)
    line = Column(String, nullable=False)
    schedule_id = Column(Integer, ForeignKey('schedules.id'), primary_key=True)


class TemplatePlannedStop(Base):
    __tablename__ = "template_planned_stops"
    trip_id = Column(String, primary_key=True)
    station_id = Column(String, ForeignKey("stations.id"), primary_key=True)
    arrival_time = Column(String, nullable=False)
    departure_time = Column(String, nullable=False)
    sequence_order = Column(Integer, nullable=False)
    schedule_id = Column(Integer, ForeignKey('schedules.id'), primary_key=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["trip_id", "schedule_id"],
            ["template_trips.id", "template_trips.schedule_id"],
            ondelete="CASCADE",
        ),
    )


class Trip(Base):
    __tablename__ = "trips"
    id = Column(String, primary_key=True)
    train_code = Column(String, nullable=False)
    direction = Column(String, nullable=False)
    line = Column(String, nullable=False)
    active_first_seq = Column(Integer, nullable=True)
    active_last_seq = Column(Integer, nullable=True)



class PlannedStop(Base):
    __tablename__ = "planned_stops"
    trip_id = Column(String, ForeignKey("trips.id", ondelete="CASCADE"), primary_key=True)
    station_id = Column(String, ForeignKey("stations.id"), primary_key=True)
    arrival_time = Column(String, nullable=False)
    departure_time = Column(String, nullable=False)
    sequence_order = Column(Integer, nullable=False)


class RealizedEvent(Base):
    __tablename__ = "realized_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trip_id = Column(String, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False)
    station_id = Column(String, ForeignKey("stations.id"), nullable=False)
    event_type = Column(String, nullable=False)
    actual_time = Column(String, nullable=False)


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)


class Interdiction(Base):
    __tablename__ = "interdictions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    y_top = Column(Float, nullable=False)
    y_bottom = Column(Float, nullable=False)
    start_time = Column(String, nullable=False)
    end_time = Column(String, nullable=False)
    description = Column(String, nullable=False, default="")


class InterdictionStopSnapshot(Base):
    __tablename__ = "interdiction_stop_snapshots"
    interdiction_id = Column(Integer, ForeignKey("interdictions.id", ondelete="CASCADE"), primary_key=True)
    trip_id = Column(String, primary_key=True)
    station_id = Column(String, primary_key=True)
    arrival_time = Column(String, nullable=False)
    departure_time = Column(String, nullable=False)