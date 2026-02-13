from pydantic import BaseModel, Field


class VMOperationTaskRequest(BaseModel):
    task_type: str
    vm_id: str | None = None
    host_id: str | None = None


class VMRecoveryISORequest(BaseModel):
    host_id: str
    iso_path: str = Field(..., description="Host path or storage URI of recovery ISO")
    boot_once: bool = True


class VMRecoveryISOReleaseRequest(BaseModel):
    host_id: str
