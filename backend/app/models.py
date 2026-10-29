import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, Column, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATA_DIR = Path(os.environ.get("MYFLOW_DATA_DIR", "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "artifacts").mkdir(exist_ok=True)
engine = create_engine(f"sqlite:///{DATA_DIR / 'myflow.db'}", connect_args={"check_same_thread": False, "timeout": 30})
Session = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()


def now():
    return datetime.now(timezone.utc).isoformat()


class Workflow(Base):
    __tablename__ = "workflows"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    graph = Column(JSON, nullable=False)
    version = Column(Integer, default=1)
    updated_at = Column(String, default=now)


class Run(Base):
    __tablename__ = "runs"
    id = Column(String, primary_key=True)
    workflow_id = Column(String, index=True)
    workflow_version = Column(Integer)
    graph = Column(JSON)
    inputs = Column(JSON)
    status = Column(String, default="running")
    outputs = Column(JSON, default=dict)
    error = Column(String, nullable=True)
    created_at = Column(String, default=now)
    finished_at = Column(String, nullable=True)


class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, ForeignKey("runs.id"), index=True)
    type = Column(String)
    data = Column(JSON)
    created_at = Column(String, default=now)


class Setting(Base):
    __tablename__ = "settings"
    id = Column(String, primary_key=True)
    base_url = Column(String)
    encrypted_key = Column(String)


def emit(run_id, kind, data):
    with Session.begin() as db:
        db.add(Event(run_id=run_id, type=kind, data=data))


def run_dict(run):
    return {key: getattr(run, key) for key in (
        "id", "workflow_id", "workflow_version", "graph", "inputs", "status", "outputs", "error", "created_at", "finished_at"
    )}
