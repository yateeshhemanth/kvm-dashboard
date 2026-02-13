import os
import threading
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


DEFAULT_POSTGRES_URL = "postgresql+psycopg://kvm:kvm@postgres:5432/kvm_dashboard"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_POSTGRES_URL)
ALLOW_SQLITE_FOR_TESTS = os.getenv("ALLOW_SQLITE_FOR_TESTS", "false").strip().lower() in {"1", "true", "yes"}

if not DATABASE_URL.startswith("postgresql") and not (ALLOW_SQLITE_FOR_TESTS and DATABASE_URL.startswith("sqlite")):
    raise RuntimeError("DATABASE_URL must be a PostgreSQL URL (postgresql+psycopg://...) for this build")

try:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
except ModuleNotFoundError as exc:
    raise RuntimeError("PostgreSQL driver missing. Install dashboard dependencies (psycopg[binary]).") from exc

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
