import threading

from .schemas import ImageRecord, NetworkRecord, SnapshotRecord, VMRecord


class AgentState:
    def __init__(self) -> None:
        self.last_push_at: str | None = None
        self.last_push_ok = False
        self.last_error: str | None = None
        self.push_count = 0
        self.vms: dict[str, VMRecord] = {}
        self.networks: dict[str, NetworkRecord] = {}
        self.snapshots: dict[str, dict[str, SnapshotRecord]] = {}
        self.images: dict[str, ImageRecord] = {}
        self.lock = threading.Lock()
