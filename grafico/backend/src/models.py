from sqlalchemy import Column, Float, ForeignKey, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Station(Base):
    __tablename__ = "stations"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    y_coordinate = Column(Float, nullable=False)
    line = Column(String, nullable=False)


class TemplateTrip(Base):
    __tablename__ = "template_trips"
    id = Column(String, primary_key=True)
    train_code = Column(String, nullable=False)
    direction = Column(String, nullable=False)
    line = Column(String, nullable=False)


class TemplatePlannedStop(Base):
    __tablename__ = "template_planned_stops"
    trip_id = Column(String, ForeignKey("template_trips.id", ondelete="CASCADE"), primary_key=True)
    station_id = Column(String, ForeignKey("stations.id"), primary_key=True)
    arrival_time = Column(String, nullable=False)
    departure_time = Column(String, nullable=False)
    sequence_order = Column(Integer, nullable=False)


class Trip(Base):
    __tablename__ = "trips"
    id = Column(String, primary_key=True)
    train_code = Column(String, nullable=False)
    direction = Column(String, nullable=False)
    line = Column(String, nullable=False)


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
