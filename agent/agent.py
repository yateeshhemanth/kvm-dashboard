import os
import socket
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


@dataclass
class AgentConfig:
    dashboard_url: str
    host_id: str
    host_name: str
    host_address: str
    libvirt_uri: str
    interval_seconds: int = 15


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
    created_at: str


class SnapshotCreateRequest(BaseModel):
    name: str


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


def detect_cpu_memory() -> tuple[int, int]:
    cpu_cores = os.cpu_count() or 0
    memory_mb = 0
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    kb = int(line.split()[1])
                    memory_mb = kb // 1024
                    break
    except FileNotFoundError:
        pass
    return cpu_cores, memory_mb


def load_config() -> AgentConfig:
    host_name = socket.gethostname()
    host_address = socket.gethostbyname(host_name)
    return AgentConfig(
        dashboard_url=os.getenv("DASHBOARD_URL", "http://127.0.0.1:8000"),
        host_id=os.getenv("HOST_ID", host_name),
        host_name=os.getenv("HOST_NAME", host_name),
        host_address=os.getenv("HOST_ADDRESS", host_address),
        libvirt_uri=os.getenv("LIBVIRT_URI", "qemu:///system"),
        interval_seconds=int(os.getenv("HEARTBEAT_INTERVAL", "15")),
    )


def register(config: AgentConfig, cpu_cores: int, memory_mb: int) -> None:
    payload = {
        "host_id": config.host_id,
        "name": config.host_name,
        "address": config.host_address,
        "cpu_cores": cpu_cores,
        "memory_mb": memory_mb,
        "libvirt_uri": config.libvirt_uri,
    }
    url = f"{config.dashboard_url}/api/v1/hosts/register"
    response = requests.post(url, json=payload, timeout=10)
    response.raise_for_status()


def send_heartbeat(config: AgentConfig, cpu_cores: int, memory_mb: int) -> None:
    payload = {
        "status": "ready",
        "cpu_cores": cpu_cores,
        "memory_mb": memory_mb,
    }
    url = f"{config.dashboard_url}/api/v1/hosts/{config.host_id}/heartbeat"
    response = requests.post(url, json=payload, timeout=10)
    response.raise_for_status()


class AgentState:
    def __init__(self) -> None:
        self.last_push_at: str | None = None
        self.last_push_ok = False
        self.last_error: str | None = None
        self.push_count = 0
        self.vms: dict[str, VMRecord] = {}
        self.networks: dict[str, NetworkRecord] = {}
        self.snapshots: dict[str, dict[str, SnapshotRecord]] = {}
        self.lock = threading.Lock()


CONFIG = load_config()
STATE = AgentState()
STOP_EVENT = threading.Event()
app = FastAPI(title="KVM Host Agent API", version="0.5.0")


def push_to_dashboard() -> None:
    cpu_cores, memory_mb = detect_cpu_memory()
    register(CONFIG, cpu_cores, memory_mb)
    send_heartbeat(CONFIG, cpu_cores, memory_mb)

    with STATE.lock:
        STATE.last_push_ok = True
        STATE.last_error = None
        STATE.push_count += 1
        STATE.last_push_at = datetime.now(timezone.utc).isoformat()


def heartbeat_loop() -> None:
    while not STOP_EVENT.is_set():
        try:
            push_to_dashboard()
            print(f"heartbeat sent for {CONFIG.host_id}")
        except requests.RequestException as exc:
            with STATE.lock:
                STATE.last_push_ok = False
                STATE.last_error = str(exc)
                STATE.last_push_at = datetime.now(timezone.utc).isoformat()
            print(f"agent warning: {exc}")

        STOP_EVENT.wait(CONFIG.interval_seconds)


@app.on_event("startup")
def startup() -> None:
    threading.Thread(target=heartbeat_loop, daemon=True).start()


@app.on_event("shutdown")
def shutdown() -> None:
    STOP_EVENT.set()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "host_id": CONFIG.host_id}


@app.get("/agent/status")
def agent_status() -> dict[str, str | bool | int | None]:
    with STATE.lock:
        return {
            "host_id": CONFIG.host_id,
            "host_name": CONFIG.host_name,
            "host_address": CONFIG.host_address,
            "dashboard_url": CONFIG.dashboard_url,
            "last_push_at": STATE.last_push_at,
            "last_push_ok": STATE.last_push_ok,
            "last_error": STATE.last_error,
            "push_count": STATE.push_count,
            "interval_seconds": CONFIG.interval_seconds,
            "vm_count": len(STATE.vms),
            "network_count": len(STATE.networks),
        }


@app.post("/agent/push-now")
def push_now() -> dict[str, str]:
    try:
        push_to_dashboard()
    except requests.RequestException as exc:
        with STATE.lock:
            STATE.last_push_ok = False
            STATE.last_error = str(exc)
            STATE.last_push_at = datetime.now(timezone.utc).isoformat()
        return {"status": "error", "detail": str(exc)}

    return {"status": "ok"}


@app.get("/agent/vms", response_model=list[VMRecord])
def list_vms() -> list[VMRecord]:
    with STATE.lock:
        return list(STATE.vms.values())


@app.post("/agent/vms", response_model=VMRecord)
def create_vm(payload: VMCreateRequest) -> VMRecord:
    vm = VMRecord(
        vm_id=str(uuid4()),
        name=payload.name,
        cpu_cores=payload.cpu_cores,
        memory_mb=payload.memory_mb,
        image=payload.image,
        power_state="stopped",
        networks=[],
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    with STATE.lock:
        STATE.vms[vm.vm_id] = vm
        STATE.snapshots[vm.vm_id] = {}
    return vm


@app.get("/agent/vms/{vm_id}/export", response_model=VMRecord)
def export_vm(vm_id: str) -> VMRecord:
    with STATE.lock:
        vm = STATE.vms.get(vm_id)
        if not vm:
            raise HTTPException(status_code=404, detail="vm not found")
        return vm


@app.post("/agent/vms/import", response_model=VMRecord)
def import_vm(payload: VMImportRequest) -> VMRecord:
    vm = VMRecord(**payload.model_dump())
    with STATE.lock:
        if vm.vm_id in STATE.vms:
            raise HTTPException(status_code=409, detail="vm already exists")
        STATE.vms[vm.vm_id] = vm
        STATE.snapshots[vm.vm_id] = {}
    return vm


@app.post("/agent/vms/{vm_id}/action", response_model=VMRecord)
def vm_action(vm_id: str, payload: VMActionRequest) -> VMRecord:
    with STATE.lock:
        vm = STATE.vms.get(vm_id)
        if not vm:
            raise HTTPException(status_code=404, detail="vm not found")

        if payload.action == VMAction.start:
            vm.power_state = "running"
        elif payload.action == VMAction.stop:
            vm.power_state = "stopped"
        elif payload.action == VMAction.reboot:
            vm.power_state = "running"
        elif payload.action == VMAction.pause:
            vm.power_state = "paused"
        elif payload.action == VMAction.resume:
            vm.power_state = "running"

        STATE.vms[vm_id] = vm
        return vm


@app.post("/agent/vms/{vm_id}/resize", response_model=VMRecord)
def resize_vm(vm_id: str, payload: VMResizeRequest) -> VMRecord:
    with STATE.lock:
        vm = STATE.vms.get(vm_id)
        if not vm:
            raise HTTPException(status_code=404, detail="vm not found")
        vm.cpu_cores = payload.cpu_cores
        vm.memory_mb = payload.memory_mb
        STATE.vms[vm_id] = vm
        return vm


@app.delete("/agent/vms/{vm_id}")
def delete_vm(vm_id: str) -> dict[str, str]:
    with STATE.lock:
        vm = STATE.vms.get(vm_id)
        if not vm:
            raise HTTPException(status_code=404, detail="vm not found")
        del STATE.vms[vm_id]
        STATE.snapshots.pop(vm_id, None)

    return {"status": "deleted", "vm_id": vm_id}


@app.post("/agent/vms/{vm_id}/snapshots", response_model=SnapshotRecord)
def create_snapshot(vm_id: str, payload: SnapshotCreateRequest) -> SnapshotRecord:
    with STATE.lock:
        vm = STATE.vms.get(vm_id)
        if not vm:
            raise HTTPException(status_code=404, detail="vm not found")

        snapshot = SnapshotRecord(
            snapshot_id=str(uuid4()),
            vm_id=vm_id,
            name=payload.name,
            captured_power_state=vm.power_state,
            captured_cpu_cores=vm.cpu_cores,
            captured_memory_mb=vm.memory_mb,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        vm_snapshots = STATE.snapshots.setdefault(vm_id, {})
        vm_snapshots[snapshot.snapshot_id] = snapshot
        return snapshot


@app.get("/agent/vms/{vm_id}/snapshots", response_model=list[SnapshotRecord])
def list_snapshots(vm_id: str) -> list[SnapshotRecord]:
    with STATE.lock:
        if vm_id not in STATE.vms:
            raise HTTPException(status_code=404, detail="vm not found")
        return list(STATE.snapshots.get(vm_id, {}).values())


@app.post("/agent/vms/{vm_id}/snapshots/{snapshot_id}/revert", response_model=VMRecord)
def revert_snapshot(vm_id: str, snapshot_id: str) -> VMRecord:
    with STATE.lock:
        vm = STATE.vms.get(vm_id)
        if not vm:
            raise HTTPException(status_code=404, detail="vm not found")

        snapshot = STATE.snapshots.get(vm_id, {}).get(snapshot_id)
        if not snapshot:
            raise HTTPException(status_code=404, detail="snapshot not found")

        vm.power_state = snapshot.captured_power_state
        vm.cpu_cores = snapshot.captured_cpu_cores
        vm.memory_mb = snapshot.captured_memory_mb
        STATE.vms[vm_id] = vm
        return vm


@app.delete("/agent/vms/{vm_id}/snapshots/{snapshot_id}")
def delete_snapshot(vm_id: str, snapshot_id: str) -> dict[str, str]:
    with STATE.lock:
        if vm_id not in STATE.vms:
            raise HTTPException(status_code=404, detail="vm not found")

        vm_snapshots = STATE.snapshots.get(vm_id, {})
        if snapshot_id not in vm_snapshots:
            raise HTTPException(status_code=404, detail="snapshot not found")

        del vm_snapshots[snapshot_id]

    return {"status": "deleted", "snapshot_id": snapshot_id, "vm_id": vm_id}


@app.get("/agent/networks", response_model=list[NetworkRecord])
def list_networks() -> list[NetworkRecord]:
    with STATE.lock:
        return list(STATE.networks.values())


@app.post("/agent/networks", response_model=NetworkRecord)
def create_network(payload: NetworkCreateRequest) -> NetworkRecord:
    network = NetworkRecord(
        network_id=str(uuid4()),
        name=payload.name,
        cidr=payload.cidr,
        vlan_id=payload.vlan_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    with STATE.lock:
        STATE.networks[network.network_id] = network
    return network


@app.post("/agent/networks/{network_id}/attach")
def attach_network(network_id: str, payload: NetworkAttachRequest) -> dict[str, str]:
    with STATE.lock:
        network = STATE.networks.get(network_id)
        if not network:
            raise HTTPException(status_code=404, detail="network not found")

        vm = STATE.vms.get(payload.vm_id)
        if not vm:
            raise HTTPException(status_code=404, detail="vm not found")

        if network_id not in vm.networks:
            vm.networks.append(network_id)
            STATE.vms[vm.vm_id] = vm

    return {"status": "attached", "vm_id": payload.vm_id, "network_id": network_id}


@app.post("/agent/networks/{network_id}/detach")
def detach_network(network_id: str, payload: NetworkAttachRequest) -> dict[str, str]:
    with STATE.lock:
        network = STATE.networks.get(network_id)
        if not network:
            raise HTTPException(status_code=404, detail="network not found")

        vm = STATE.vms.get(payload.vm_id)
        if not vm:
            raise HTTPException(status_code=404, detail="vm not found")

        vm.networks = [attached_id for attached_id in vm.networks if attached_id != network_id]
        STATE.vms[vm.vm_id] = vm

    return {"status": "detached", "vm_id": payload.vm_id, "network_id": network_id}


@app.delete("/agent/networks/{network_id}")
def delete_network(network_id: str) -> dict[str, str]:
    with STATE.lock:
        network = STATE.networks.get(network_id)
        if not network:
            raise HTTPException(status_code=404, detail="network not found")

        for vm_id, vm in STATE.vms.items():
            if network_id in vm.networks:
                vm.networks = [attached_id for attached_id in vm.networks if attached_id != network_id]
                STATE.vms[vm_id] = vm

        del STATE.networks[network_id]

    return {"status": "deleted", "network_id": network_id}
