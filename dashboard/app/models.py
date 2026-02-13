from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Host(Base):
    __tablename__ = "hosts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    host_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    address: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="unknown")
    cpu_cores: Mapped[int] = mapped_column(Integer, default=0)
    memory_mb: Mapped[int] = mapped_column(Integer, default=0)
    libvirt_uri: Mapped[str] = mapped_column(String(255), default="qemu+ssh://root@10.110.17.153/system")
    last_heartbeat: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
