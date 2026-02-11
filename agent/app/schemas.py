from enum import Enum

from pydantic import BaseModel, Field


class VMAction(str, Enum):
    start = "start"
    stop = "stop"
    reboot = "reboot"
    pause = "pause"
    resume = "resume"


class VMCreateRequest(BaseModel):
    name: str
    cpu_cores: int
    memory_mb: int
    image: str


class VMImportRequest(BaseModel):
    vm_id: str
    name: str
    cpu_cores: int
    memory_mb: int
    image: str
    power_state: str
    networks: list[str]
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    created_at: str


class VMResizeRequest(BaseModel):
    cpu_cores: int
    memory_mb: int


class VMActionRequest(BaseModel):
    action: VMAction


class VMRecord(BaseModel):
    vm_id: str
    name: str
    cpu_cores: int
    memory_mb: int
    image: str
    power_state: str
    networks: list[str]
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    created_at: str


class SnapshotCreateRequest(BaseModel):
    name: str


class VMCloneRequest(BaseModel):
    name: str


class VMMetadataRequest(BaseModel):
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)


class SnapshotRecord(BaseModel):
    snapshot_id: str
    vm_id: str
    name: str
    captured_power_state: str
    captured_cpu_cores: int
    captured_memory_mb: int
    created_at: str


class NetworkCreateRequest(BaseModel):
    name: str
    cidr: str
    vlan_id: int | None = None


class NetworkRecord(BaseModel):
    network_id: str
    name: str
    cidr: str
    vlan_id: int | None = None
    created_at: str


class NetworkAttachRequest(BaseModel):
    vm_id: str


class ImageCreateRequest(BaseModel):
    name: str
    source_url: str


class ImageRecord(BaseModel):
    image_id: str
    name: str
    source_url: str
    status: str
    created_at: str
