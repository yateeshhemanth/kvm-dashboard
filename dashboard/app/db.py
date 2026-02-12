import os
import threading
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


# Live-mode default: keep host inventory ephemeral in memory to avoid local DB files.
# Set PERSIST_LOCAL_DB=true to restore sqlite file persistence.
if os.getenv("PERSIST_LOCAL_DB", "false").strip().lower() in {"1", "true", "yes"}:
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./kvm_dashboard.db")
else:
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine_kwargs = {"connect_args": connect_args}
if DATABASE_URL.endswith(":memory:"):
    engine_kwargs["poolclass"] = StaticPool
engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_db_initialized = False
_init_lock = threading.Lock()


def init_db() -> None:
    global _db_initialized
    if _db_initialized:
        return

    with _init_lock:
        if _db_initialized:
            return
        Base.metadata.create_all(bind=engine)
        _db_initialized = True


def get_db() -> Generator[Session, None, None]:
    init_db()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
