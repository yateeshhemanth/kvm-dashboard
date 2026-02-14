from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class HostRegisterRequest(BaseModel):
    host_id: str = Field(..., description="Unique ID for hypervisor host")
    name: str
    address: str
    cpu_cores: int = 0
    memory_mb: int = 0
    libvirt_uri: str = "qemu+ssh://root@10.110.17.153/system"
    tags: list[str] = Field(default_factory=list)
    project_id: str | None = None


class HeartbeatRequest(BaseModel):
    status: str = "ready"
    cpu_cores: int = 0
    memory_mb: int = 0


class HostAction(str, Enum):
    mark_ready = "mark_ready"
    mark_maintenance = "mark_maintenance"
    mark_draining = "mark_draining"
    disable = "disable"


class HostActionRequest(BaseModel):
    action: HostAction


class VMAction(str, Enum):
    start = "start"
    stop = "stop"
    reboot = "reboot"
    pause = "pause"
    resume = "resume"


class VMProvisionRequest(BaseModel):
    host_id: str
    name: str
    cpu_cores: int
    memory_mb: int
    image: str
    network: str = "default"


class VMHostActionRequest(BaseModel):
    host_id: str
    action: VMAction


class VMImportRequest(BaseModel):
    host_id: str
    vm_id: str
    name: str
    cpu_cores: int
    memory_mb: int
    image: str
    power_state: str = "stopped"
    networks: list[str] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    created_at: str


class VMResizeRequest(BaseModel):
    host_id: str
    cpu_cores: int
    memory_mb: int


class VMCloneRequest(BaseModel):
    host_id: str
    name: str


class VMMetadataRequest(BaseModel):
    host_id: str
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)


class VMMigrateRequest(BaseModel):
    source_host_id: str
    target_host_id: str


class VMSnapshotCreateRequest(BaseModel):
    host_id: str
    name: str


class VMSnapshotHostRequest(BaseModel):
    host_id: str


class NetworkCreateRequest(BaseModel):
    host_id: str
    name: str
    cidr: str
    vlan_id: int | None = None


class NetworkAttachRequest(BaseModel):
    host_id: str
    vm_id: str


class NetworkDetachRequest(BaseModel):
    host_id: str
    vm_id: str




class ImageCreateRequest(BaseModel):
    host_id: str
    name: str
    source_url: str


class ImageRecord(BaseModel):
    image_id: str
    name: str
    source_url: str
    status: str
    created_at: str



class PolicyCreateRequest(BaseModel):
    name: str
    category: str = "governance"
    spec: dict[str, str] = Field(default_factory=dict)


class PolicyRecord(BaseModel):
    policy_id: str
    name: str
    category: str
    spec: dict[str, str]
    created_at: str


class PolicyBindingRequest(BaseModel):
    host_id: str | None = None
    project_id: str | None = None

class ProjectCreateRequest(BaseModel):
    name: str
    description: str = ""


class ProjectQuotaRequest(BaseModel):
    cpu_cores: int = 0
    memory_mb: int = 0
    vm_limit: int = 0


class ProjectRecord(BaseModel):
    project_id: str
    name: str
    description: str
    cpu_cores_quota: int
    memory_mb_quota: int
    vm_limit: int
    created_at: str


class ProjectMemberRequest(BaseModel):
    user_id: str
    role: str = "viewer"


class ProjectMemberRecord(BaseModel):
    member_id: str
    project_id: str
    user_id: str
    role: str
    created_at: str


class EventRecord(BaseModel):
    event_id: str
    type: str
    message: str
    created_at: str


class ConsoleTicketResponse(BaseModel):
    host_id: str
    vm_id: str
    ticket: str
    noVNC_url: str


class RunbookExecuteRequest(BaseModel):
    host_id: str | None = None
    vm_id: str | None = None
    parameters: dict[str, str] = Field(default_factory=dict)


class TaskRecord(BaseModel):
    task_id: str
    task_type: str
    status: str
    target: str
    detail: str
    created_at: str
    completed_at: str | None = None


class HostResponse(BaseModel):
    host_id: str
    name: str
    address: str
    status: str
    cpu_cores: int
    memory_mb: int
    libvirt_uri: str
    tags: list[str] = Field(default_factory=list)
    project_id: str | None = None
    last_heartbeat: datetime

    class Config:
        from_attributes = True
