from datetime import datetime, timezone
import os
import time
from typing import Any
from uuid import uuid4
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from .db import get_db, init_db
from .models import Host
from .schemas import (
    HeartbeatRequest,
    HostAction,
    HostActionRequest,
    HostRegisterRequest,
    HostResponse,
    VMHostActionRequest,
    VMImportRequest,
    VMProvisionRequest,
    VMResizeRequest,
    VMCloneRequest,
    VMMetadataRequest,
    VMMigrateRequest,
    VMSnapshotCreateRequest,
    VMSnapshotHostRequest,
    NetworkAttachRequest,
    NetworkDetachRequest,
    NetworkCreateRequest,
    ImageCreateRequest,
    ProjectCreateRequest,
    ProjectQuotaRequest,
    ProjectRecord,
    PolicyCreateRequest,
    PolicyRecord,
    PolicyBindingRequest,
    EventRecord,
    ConsoleTicketResponse,
    ProjectMemberRequest,
    ProjectMemberRecord,
    RunbookExecuteRequest,
    TaskRecord,
)
from .schemas_day2 import VMOperationTaskRequest, VMRecoveryISOReleaseRequest, VMRecoveryISORequest
from .day2_services import SUPPORTED_VM_TASK_TYPES, normalize_task_type
from .ui_pages import render_dashboard_page
from .libvirt_remote import LibvirtRemote, LibvirtRemoteError
from .libvirt_cache import LibvirtCacheStore
from .vmware_compat import build_vmware_router
from .auth import ensure_default_admin, login_get, login_post, logout_post, require_ui_auth
from .console_service import build_console_urls

app = FastAPI(title="KVM Dashboard API", version="0.7.1")

LIBVIRT_CACHE_TTL_S = int(os.getenv("LIBVIRT_CACHE_TTL_S", "60"))
LIVE_STATUS_TTL_S = int(os.getenv("LIVE_STATUS_TTL_S", "15"))
CONSOLE_SESSION_TTL_S = int(os.getenv("CONSOLE_SESSION_TTL_S", "30"))
NOVNC_BASE_URL = os.getenv("NOVNC_BASE_URL", "/console/noVNC/viewer")
NOVNC_WS_BASE = os.getenv("NOVNC_WS_BASE", "/console/noVNC/websockify")
BASE_PATH = os.getenv("DASHBOARD_BASE_PATH", "").strip()
if BASE_PATH and not BASE_PATH.startswith("/"):
    BASE_PATH = f"/{BASE_PATH}"
if BASE_PATH.endswith("/") and BASE_PATH != "/":
    BASE_PATH = BASE_PATH[:-1]

PROJECTS: dict[str, ProjectRecord] = {}
PROJECT_MEMBERS: dict[str, list[ProjectMemberRecord]] = {}
POLICIES: dict[str, PolicyRecord] = {}
HOST_POLICY_BINDINGS: dict[str, list[str]] = {}
PROJECT_POLICY_BINDINGS: dict[str, list[str]] = {}
EVENTS: list[EventRecord] = []
TASKS: dict[str, TaskRecord] = {}
CONSOLE_SESSIONS: list[dict[str, str]] = []
IMAGE_IMPORT_JOBS: list[dict[str, str]] = []
RUNBOOK_TEMPLATES: dict[str, dict[str, Any]] = {}
RUNBOOK_SCHEDULES: dict[str, dict[str, Any]] = {}
EVENT_RETENTION_DAYS = 30
VM_LIFECYCLE_POLICIES: dict[str, dict[str, Any]] = {}
ADVANCED_NETWORK_CONFIG: dict[str, list[dict[str, Any]]] = {"vlan_trunks": [], "bridge_automation": [], "ipam": [], "security_policies": []}
IMAGE_DEPLOYMENTS: list[dict[str, Any]] = []
VM_METADATA_OVERRIDES: dict[str, dict[str, dict[str, Any]]] = {}

ROADMAP_PHASES: list[dict[str, object]] = [
    {
        "phase": "Phase 6 - Execution Backend",
        "status": "next",
        "goals": [
            "Replace in-memory VM/network actions with libvirt-backed execution",
            "Implement qcow2 image import pipeline with checksum validation",
            "Add host capability discovery for CPU flags and storage pools",
        ],
    },
    {
        "phase": "Phase 7 - Console + UX",
        "status": "planned",
        "goals": [
            "Integrate real noVNC websocket proxy flow",
            "Add operations timeline filtering and task retry actions",
            "Add project-scoped dashboards and health widgets",
        ],
    },
    {
        "phase": "Phase 8 - Policy Enforcement",
        "status": "planned",
        "goals": [
            "Enforce policy checks before VM/network actions",
            "Add audit export and event retention controls",
            "Add runbook templates and schedule support",
        ],
    },
]

PENDING_TASKS: list[dict[str, str]] = [
    {"id": "PEND-001", "area": "Agent", "task": "Wire VM provision/action/resize APIs to libvirt domain operations", "priority": "high"},
    {"id": "PEND-002", "area": "Agent", "task": "Implement host network CRUD against bridge/VLAN backend", "priority": "high"},
    {"id": "PEND-003", "area": "Dashboard", "task": "Add authn/authz for API and dashboard routes", "priority": "high"},
    {"id": "PEND-004", "area": "Dashboard", "task": "Add pagination/filtering for events and tasks", "priority": "medium"},
    {"id": "PEND-005", "area": "Console", "task": "Replace noVNC placeholder with live tokenized console session", "priority": "high"},
    {"id": "PEND-006", "area": "Images", "task": "Add image versioning, checksum, and storage location metadata", "priority": "medium"},
    {"id": "PEND-007", "area": "Platform", "task": "Add metrics endpoint and Prometheus export", "priority": "medium"},
]

CACHE_STORE = LibvirtCacheStore(ttl_s=LIBVIRT_CACHE_TTL_S)
LIVE_STATUS_CACHE: dict[str, Any] = {"updated_at": 0.0, "payload": None}


def _with_base(path: str) -> str:
    return f"{BASE_PATH}{path}" if BASE_PATH else path


def _dashboard_route_hints() -> list[str]:
    return [
        _with_base("/"),
        _with_base("/dashboard"),
        _with_base("/vms"),
        _with_base("/storage"),
        _with_base("/console"),
        _with_base("/networks"),
        _with_base("/images"),
        _with_base("/policies"),
        _with_base("/events"),
        _with_base("/tasks"),
        _with_base("/healthz"),
        _with_base("/api/v1/overview"),
        _with_base("/api/v1/capabilities"),
        _with_base("/api/v1/routes"),
    ]


def _is_api_or_reserved_path(path: str) -> bool:
    normalized = path.strip("/")
    if not normalized:
        return False
    if normalized.startswith("api/"):
        return True
    if normalized.startswith("healthz/") or normalized.startswith("docs/") or normalized.startswith("redoc/"):
        return True
    return normalized in {"openapi.json", "docs", "docs/oauth2-redirect", "redoc", "healthz"}


def _record_event(event_type: str, message: str) -> EventRecord:
    event = EventRecord(
        event_id=str(uuid4()),
        type=event_type,
        message=message,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    EVENTS.insert(0, event)
    if len(EVENTS) > 200:
        del EVENTS[200:]
    return event




def _create_completed_task(task_type: str, target: str, detail: str) -> TaskRecord:
    now = datetime.now(timezone.utc).isoformat()
    task = TaskRecord(
        task_id=str(uuid4()),
        task_type=task_type,
        status="completed",
        target=target,
        detail=detail,
        created_at=now,
        completed_at=now,
    )
    TASKS[task.task_id] = task
    return task


def _resolve_effective_policies(host_id: str | None = None, project_id: str | None = None) -> list[PolicyRecord]:
    host_policy_ids = HOST_POLICY_BINDINGS.get(host_id or "", [])
    project_policy_ids = PROJECT_POLICY_BINDINGS.get(project_id or "", [])
    resolved_ids = list(dict.fromkeys(host_policy_ids + project_policy_ids))
    return [POLICIES[policy_id] for policy_id in resolved_ids if policy_id in POLICIES]


def _enforce_policies(action: str, host_id: str | None = None, project_id: str | None = None) -> None:
    for policy in _resolve_effective_policies(host_id=host_id, project_id=project_id):
        deny_actions = policy.spec.get("deny_actions") if isinstance(policy.spec, dict) else None
        if isinstance(deny_actions, str):
            blocked = {item.strip() for item in deny_actions.split(",") if item.strip()}
        elif isinstance(deny_actions, list):
            blocked = {str(item).strip() for item in deny_actions if str(item).strip()}
        else:
            blocked = set()
        if action in blocked:
            raise HTTPException(status_code=403, detail=f"policy {policy.name} blocks action '{action}'")



def _actor_role(request: Request) -> str:
    return request.headers.get("x-role", "admin").strip().lower() or "admin"


def _require_roles(request: Request, allowed: set[str]) -> str:
    role = _actor_role(request)
    if role not in allowed:
        raise HTTPException(status_code=403, detail=f"rbac denied for role={role}; allowed={sorted(allowed)}")
    return role
def _tags_to_csv(tags: list[str] | None) -> str:
    if not tags:
        return ""
    return ",".join(sorted({t.strip() for t in tags if t and t.strip()}))


def _csv_to_tags(tags_csv: str | None) -> list[str]:
    if not tags_csv:
        return []
    return [item.strip() for item in tags_csv.split(",") if item.strip()]


def _host_to_response(host: Host) -> HostResponse:
    return HostResponse(
        host_id=host.host_id,
        name=host.name,
        address=host.address,
        status=host.status,
        cpu_cores=host.cpu_cores,
        memory_mb=host.memory_mb,
        libvirt_uri=host.libvirt_uri,
        tags=_csv_to_tags(getattr(host, "tags", "")),
        project_id=getattr(host, "project_id", None),
        last_heartbeat=host.last_heartbeat,
    )


def _project_quota_summary() -> tuple[int, int, int]:
    total_cpu = sum(project.cpu_cores_quota for project in PROJECTS.values())
    total_memory = sum(project.memory_mb_quota for project in PROJECTS.values())
    total_vm_limit = sum(project.vm_limit for project in PROJECTS.values())
    return total_cpu, total_memory, total_vm_limit


@app.on_event("startup")
def startup() -> None:
    init_db()
    db_gen = get_db()
    try:
        db = next(db_gen)
        CACHE_STORE.ensure_table(db)
        db.execute(text("ALTER TABLE hosts ADD COLUMN IF NOT EXISTS tags VARCHAR(1024) DEFAULT ''"))
        db.execute(text("ALTER TABLE hosts ADD COLUMN IF NOT EXISTS project_id VARCHAR(128)"))
        db.commit()
        ensure_default_admin(db)
    except Exception:
        pass
    finally:
        try:
            next(db_gen)
        except StopIteration:
            pass


@app.middleware("http")
async def strip_base_path_middleware(request: Request, call_next):
    if BASE_PATH and BASE_PATH != "/":
        path = request.scope.get("path", "")
        if path == BASE_PATH or path.startswith(f"{BASE_PATH}/"):
            rewritten = path[len(BASE_PATH):] or "/"
            request.scope["path"] = rewritten
            request.scope["raw_path"] = rewritten.encode("utf-8")
    return await call_next(request)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "base_path": BASE_PATH or "/"}




@app.get("/login", response_class=HTMLResponse)
def dashboard_login_page(db: Session = Depends(get_db)) -> HTMLResponse:
    return login_get(db)


@app.post("/login")
def dashboard_login_submit(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    return login_post(username=username, password=password, db=db)


@app.post("/logout")
def dashboard_logout(request: Request, db: Session = Depends(get_db)):
    return logout_post(request=request, db=db)

def _apply_host_action(host: Host, action: HostAction) -> None:
    if action == HostAction.mark_ready:
        host.status = "ready"
    elif action == HostAction.mark_maintenance:
        host.status = "maintenance"
    elif action == HostAction.mark_draining:
        host.status = "draining"
    elif action == HostAction.disable:
        host.status = "disabled"




def _libvirt_or_502(host: Host) -> LibvirtRemote:
    try:
        return LibvirtRemote(host.libvirt_uri)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"libvirt init failed: {exc}") from exc


def _libvirt_call(host: Host, fn_name: str, *args):
    executor = _libvirt_or_502(host)
    fn = getattr(executor, fn_name)
    try:
        return fn(*args)
    except LibvirtRemoteError as exc:
        raise HTTPException(status_code=502, detail=f"libvirt call failed: {exc}") from exc



def _refresh_host_cache(db: Session, host: Host) -> dict[str, Any]:
    return CACHE_STORE.refresh(db, host, _libvirt_call)


def _host_cached_state(db: Session, host: Host, *, force_refresh: bool = False) -> dict[str, Any]:
    return CACHE_STORE.get(db, host, _libvirt_call, force_refresh=force_refresh)


def _get_host_or_404(db: Session, host_id: str) -> Host:
    host = db.query(Host).filter(Host.host_id == host_id).first()
    if not host:
        raise HTTPException(status_code=404, detail="host not found")
    return host


def _render_ui_page(page: str, db: Session) -> str:
    hosts = db.query(Host).order_by(Host.id.desc()).all()
    stats = {
        "hosts": len(hosts),
        "ready_hosts": len([host for host in hosts if host.status in {"ready", "registered"}]),
        "policies": len(POLICIES),
    }
    return render_dashboard_page(page, base_path=BASE_PATH, stats=stats)


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/dashboard/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
@app.get("/ui/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
@app.get("/home", response_class=HTMLResponse)
def dashboard_home(_user=Depends(require_ui_auth), db: Session = Depends(get_db)) -> str:
    return _render_ui_page("dashboard", db)


@app.get("/vms", response_class=HTMLResponse)
@app.get("/storage", response_class=HTMLResponse)
@app.get("/console", response_class=HTMLResponse)
@app.get("/networks", response_class=HTMLResponse)
@app.get("/images", response_class=HTMLResponse)
@app.get("/policies", response_class=HTMLResponse)
@app.get("/events", response_class=HTMLResponse)
@app.get("/tasks", response_class=HTMLResponse)
@app.get("/guide", response_class=HTMLResponse)
def dashboard_sections(request: Request, _user=Depends(require_ui_auth), db: Session = Depends(get_db)) -> str:
    page = request.url.path.strip("/").split("/")[0] or "dashboard"
    return _render_ui_page(page, db)


@app.post("/hosts/{host_id}/action-web")
def host_action_web(host_id: str, action: HostAction = Form(...), db: Session = Depends(get_db)) -> RedirectResponse:
    host = _get_host_or_404(db, host_id)
    _apply_host_action(host, action)
    host.last_heartbeat = datetime.now(timezone.utc)
    db.commit()
    return RedirectResponse(url="/", status_code=303)


@app.post("/api/v1/hosts/register", response_model=HostResponse)
def register_host(payload: HostRegisterRequest, db: Session = Depends(get_db)) -> Host:
    host = db.query(Host).filter(Host.host_id == payload.host_id).first()

    if host:
        host.name = payload.name
        host.address = payload.address
        host.cpu_cores = payload.cpu_cores
        host.memory_mb = payload.memory_mb
        host.libvirt_uri = payload.libvirt_uri
        host.tags = _tags_to_csv(payload.tags)
        host.project_id = payload.project_id
        host.status = "registered"
        host.last_heartbeat = datetime.now(timezone.utc)
    else:
        host = Host(
            host_id=payload.host_id,
            name=payload.name,
            address=payload.address,
            status="registered",
            cpu_cores=payload.cpu_cores,
            memory_mb=payload.memory_mb,
            libvirt_uri=payload.libvirt_uri,
            tags=_tags_to_csv(payload.tags),
            project_id=payload.project_id,
            last_heartbeat=datetime.now(timezone.utc),
        )
        db.add(host)

    db.commit()
    db.refresh(host)
    return _host_to_response(host)


@app.post("/api/v1/hosts/{host_id}/heartbeat", response_model=HostResponse)
def heartbeat(host_id: str, payload: HeartbeatRequest, db: Session = Depends(get_db)) -> Host:
    host = _get_host_or_404(db, host_id)
    host.status = payload.status
    host.cpu_cores = payload.cpu_cores
    host.memory_mb = payload.memory_mb
    host.last_heartbeat = datetime.now(timezone.utc)
    db.commit()
    db.refresh(host)
    return _host_to_response(host)


@app.post("/api/v1/hosts/{host_id}/action", response_model=HostResponse)
def host_action(host_id: str, payload: HostActionRequest, db: Session = Depends(get_db)) -> Host:
    host = _get_host_or_404(db, host_id)
    _apply_host_action(host, payload.action)
    host.last_heartbeat = datetime.now(timezone.utc)
    db.commit()
    db.refresh(host)
    return _host_to_response(host)


@app.delete("/api/v1/hosts/{host_id}")
def remove_host(host_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    host = _get_host_or_404(db, host_id)
    db.delete(host)
    db.commit()
    return {"status": "deleted", "host_id": host_id}


@app.get("/api/v1/hosts", response_model=list[HostResponse])
def list_hosts(project_id: str | None = Query(default=None), tag: str | None = Query(default=None), db: Session = Depends(get_db)) -> list[HostResponse]:
    query = db.query(Host)
    if project_id:
        query = query.filter(Host.project_id == project_id)
    hosts = query.order_by(Host.id.desc()).all()
    if tag:
        token = tag.strip().lower()
        hosts = [h for h in hosts if token in {t.lower() for t in _csv_to_tags(getattr(h, "tags", ""))}]
    return [_host_to_response(h) for h in hosts]


@app.post("/api/v1/vms/provision")
def provision_vm(payload: VMProvisionRequest, db: Session = Depends(get_db)) -> dict:
    _enforce_policies("vm.provision", host_id=payload.host_id)
    host = _get_host_or_404(db, payload.host_id)
    vm = _libvirt_call(host, "create_vm", payload.name, payload.cpu_cores, payload.memory_mb, payload.image, payload.network)
    _refresh_host_cache(db, host)
    _record_event("vm.provision", f"vm {payload.name} created on host {payload.host_id}")
    _create_completed_task("vm.provision", payload.name, f"created cpu={payload.cpu_cores},mem={payload.memory_mb},image={payload.image},network={payload.network}")
    return {"host_id": payload.host_id, "vm": vm, "status": "created"}


@app.post("/api/v1/vms/import")
def import_vm(payload: VMImportRequest, db: Session = Depends(get_db)) -> dict:
    _enforce_policies("vm.import", host_id=payload.host_id)
    _get_host_or_404(db, payload.host_id)
    _record_event("vm.import", f"vm {payload.name} import requested on host {payload.host_id}")
    _create_completed_task("vm.import", payload.vm_id, "manual libvirt import required (domain XML + disk)")
    return {"host_id": payload.host_id, "vm": payload.model_dump(), "note": "import metadata recorded"}


@app.get("/api/v1/hosts/{host_id}/vms")
def list_host_vms(host_id: str, refresh: bool = False, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, host_id)
    state = _host_cached_state(db, host, force_refresh=refresh)
    return {"host_id": host_id, "vms": state["vms"], "cache": state["cache"], "cached_at": state["updated_at"], "last_error": state.get("last_error"), "last_success_at": state.get("last_success_at")}


@app.get("/api/v1/hosts/{host_id}/inventory-live")
def host_inventory_live(host_id: str, refresh: bool = False, include_snapshots: bool = False, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, host_id)
    state = _host_cached_state(db, host, force_refresh=refresh)
    vms, networks, images = state["vms"], state["networks"], state["images"]
    vm_snapshots: dict[str, Any] = {}
    if include_snapshots:
        for vm in vms:
            vm_id = vm.get("vm_id")
            if vm_id:
                vm_snapshots[vm_id] = _libvirt_call(host, "snapshot_list", vm_id)
    attachments = {vm.get("vm_id"): {"networks": vm.get("networks", []), "image": {"name": vm.get("image")}, "snapshots": vm_snapshots.get(vm.get("vm_id"), [])} for vm in vms if vm.get("vm_id")}
    return {"host_id": host_id, "cache": state["cache"], "cached_at": state["updated_at"], "last_error": state.get("last_error"), "last_success_at": state.get("last_success_at"), "state": {"vm_count": len(vms), "network_count": len(networks), "image_count": len(images), "snapshot_count": sum(len(items) for items in vm_snapshots.values())}, "vms": vms, "networks": networks, "images": images, "attachments": attachments}


@app.get("/api/v1/vms/{vm_id}/attachments")
def vm_attachments(vm_id: str, host_id: str, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, host_id)
    state = _host_cached_state(db, host)
    vm = next((item for item in state["vms"] if item.get("vm_id") == vm_id), None)
    if not vm:
        raise HTTPException(status_code=404, detail="vm not found")

    snapshots = _libvirt_call(host, "snapshot_list", vm_id)
    networks = state["networks"]
    images = state["images"]

    attached_networks = [net for net in networks if net.get("name") in vm.get("networks", [])]
    image_record = next((img for img in images if img.get("name") in {vm.get("image"), f"{vm.get('image', '')}.qcow2"}), None)

    override = VM_METADATA_OVERRIDES.get(host_id, {}).get(vm_id, {"labels": {}, "annotations": {}})
    volume_name = f"{vm.get('name', 'vm')}-{vm_id[:8]}.qcow2"
    current_iso = _libvirt_call(host, "current_iso", vm_id)
    return {
        "host_id": host_id,
        "vm_id": vm_id,
        "power_state": vm.get("power_state"),
        "vm": {**vm, **override},
        "attachments": {
            "image": image_record,
            "networks": attached_networks,
            "snapshots": snapshots,
            "volumes": [{"name": volume_name, "format": "qcow2", "size_gb": 20}],
            "recovery_iso": current_iso or None,
        },
    }


@app.post("/api/v1/vms/{vm_id}/action")
def vm_action(vm_id: str, payload: VMHostActionRequest, db: Session = Depends(get_db)) -> dict:
    _enforce_policies(f"vm.action.{payload.action.value}", host_id=payload.host_id)
    host = _get_host_or_404(db, payload.host_id)
    _libvirt_call(host, "vm_action", vm_id, payload.action.value)
    state = _refresh_host_cache(db, host)
    vm = next((item for item in state["vms"] if item.get("vm_id") == vm_id), None)
    if not vm:
        raise HTTPException(status_code=404, detail="vm not found")
    _record_event("vm.action", f"vm {vm_id} action={payload.action.value} on host {payload.host_id}")
    return {"host_id": payload.host_id, "vm": vm}


@app.delete("/api/v1/vms/{vm_id}")
def delete_vm(vm_id: str, host_id: str, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, host_id)
    _libvirt_call(host, "delete_vm", vm_id)
    _refresh_host_cache(db, host)
    return {"host_id": host_id, "result": {"status": "deleted", "vm_id": vm_id}}


@app.post("/api/v1/networks")
def create_network(payload: NetworkCreateRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    _require_roles(request, {"admin", "operator"})
    _enforce_policies("network.create", host_id=payload.host_id)
    host = _get_host_or_404(db, payload.host_id)
    network = _libvirt_call(host, "create_network", payload.name, payload.cidr, payload.vlan_id)
    _refresh_host_cache(db, host)
    _record_event("network.create", f"network {payload.name} created on host {payload.host_id}")
    _create_completed_task("network.create", payload.name, f"cidr={payload.cidr},vlan={payload.vlan_id}")
    return {"host_id": payload.host_id, "network": network}


@app.get("/api/v1/hosts/{host_id}/networks")
def list_host_networks(host_id: str, refresh: bool = False, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, host_id)
    state = _host_cached_state(db, host, force_refresh=refresh)
    return {"host_id": host_id, "networks": state["networks"], "cache": state["cache"], "cached_at": state["updated_at"], "last_error": state.get("last_error"), "last_success_at": state.get("last_success_at")}


@app.post("/api/v1/networks/{network_id}/attach")
def attach_network(network_id: str, payload: NetworkAttachRequest, db: Session = Depends(get_db)) -> dict:
    _get_host_or_404(db, payload.host_id)
    _record_event("network.attach", f"network {network_id} attached to vm {payload.vm_id} on {payload.host_id}")
    return {"host_id": payload.host_id, "result": {"status": "attached", "network_id": network_id, "vm_id": payload.vm_id}}


@app.delete("/api/v1/networks/{network_id}")
def delete_network(network_id: str, host_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    _require_roles(request, {"admin", "operator"})
    host = _get_host_or_404(db, host_id)
    _libvirt_call(host, "delete_network", network_id)
    _refresh_host_cache(db, host)
    _record_event("network.delete", f"network {network_id} deleted on {host_id}")
    return {"host_id": host_id, "result": {"status": "deleted", "network_id": network_id}}


@app.post("/api/v1/vms/{vm_id}/resize")
def resize_vm(vm_id: str, payload: VMResizeRequest, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, payload.host_id)
    _libvirt_call(host, "resize", vm_id, payload.cpu_cores, payload.memory_mb)
    state = _refresh_host_cache(db, host)
    vm = next((item for item in state["vms"] if item.get("vm_id") == vm_id), None)
    if not vm:
        raise HTTPException(status_code=404, detail="vm not found")
    _record_event("vm.resize", f"vm {vm_id} resized on host {payload.host_id}")
    return {"host_id": payload.host_id, "vm": vm}


@app.post("/api/v1/vms/{vm_id}/clone")
def clone_vm(vm_id: str, payload: VMCloneRequest, db: Session = Depends(get_db)) -> dict:
    _get_host_or_404(db, payload.host_id)
    _record_event("vm.clone", f"vm {vm_id} clone requested as {payload.name} on host {payload.host_id}")
    _create_completed_task("vm.clone", vm_id, f"clone_name={payload.name}; execute via virt-clone")
    return {"host_id": payload.host_id, "vm": {"vm_id": vm_id, "requested_clone": payload.name}, "status": "queued"}


@app.post("/api/v1/vms/{vm_id}/metadata")
def set_vm_metadata(vm_id: str, payload: VMMetadataRequest, db: Session = Depends(get_db)) -> dict:
    _get_host_or_404(db, payload.host_id)
    VM_METADATA_OVERRIDES.setdefault(payload.host_id, {})[vm_id] = {"labels": payload.labels, "annotations": payload.annotations}
    _record_event("vm.metadata", f"vm {vm_id} metadata updated on host {payload.host_id}")
    return {"host_id": payload.host_id, "vm": {"vm_id": vm_id, "labels": payload.labels, "annotations": payload.annotations}}




@app.post("/api/v1/vms/{vm_id}/recovery/attach-iso")
def attach_recovery_iso(vm_id: str, payload: VMRecoveryISORequest, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, payload.host_id)
    result = _libvirt_call(host, "attach_iso", vm_id, payload.iso_path, payload.boot_once)
    _refresh_host_cache(db, host)
    _record_event("vm.recovery.iso.attach", f"recovery ISO attached for vm {vm_id} on host {payload.host_id}")
    _create_completed_task("vm.recovery.iso.attach", vm_id, f"iso={payload.iso_path}")
    return {"host_id": payload.host_id, "vm_id": vm_id, "status": "attached", "result": result}


@app.post("/api/v1/vms/{vm_id}/recovery/detach-iso")
def detach_recovery_iso(vm_id: str, payload: VMRecoveryISOReleaseRequest, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, payload.host_id)
    result = _libvirt_call(host, "detach_iso", vm_id)
    _refresh_host_cache(db, host)
    _record_event("vm.recovery.iso.detach", f"recovery ISO detached for vm {vm_id} on host {payload.host_id}")
    _create_completed_task("vm.recovery.iso.detach", vm_id, "recovery iso detached")
    return {"host_id": payload.host_id, "vm_id": vm_id, "status": "detached", "result": result}

@app.post("/api/v1/vms/{vm_id}/migrate")
def migrate_vm(vm_id: str, payload: VMMigrateRequest, db: Session = Depends(get_db)) -> dict:
    source_host = _get_host_or_404(db, payload.source_host_id)
    _get_host_or_404(db, payload.target_host_id)
    _libvirt_call(source_host, "migrate", vm_id, _get_host_or_404(db, payload.target_host_id).libvirt_uri, False)
    _record_event("vm.migrate", f"vm {vm_id} migrated from {payload.source_host_id} to {payload.target_host_id}")
    return {"vm_id": vm_id, "source_host_id": payload.source_host_id, "target_host_id": payload.target_host_id, "vm": {"vm_id": vm_id}}


@app.post("/api/v1/vms/{vm_id}/snapshots")
def create_snapshot(vm_id: str, payload: VMSnapshotCreateRequest, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, payload.host_id)
    snap = _libvirt_call(host, "snapshot_create", vm_id, payload.name)
    _refresh_host_cache(db, host)
    return {"host_id": payload.host_id, "snapshot": snap}


@app.get("/api/v1/vms/{vm_id}/snapshots")
def list_snapshots(vm_id: str, host_id: str, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, host_id)
    return {"host_id": host_id, "vm_id": vm_id, "snapshots": _libvirt_call(host, "snapshot_list", vm_id)}


@app.post("/api/v1/vms/{vm_id}/snapshots/{snapshot_id}/revert")
def revert_snapshot(vm_id: str, snapshot_id: str, payload: VMSnapshotHostRequest, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, payload.host_id)
    _libvirt_call(host, "snapshot_revert", vm_id, snapshot_id)
    state = _refresh_host_cache(db, host)
    vm = next((item for item in state["vms"] if item.get("vm_id") == vm_id), None)
    if not vm:
        raise HTTPException(status_code=404, detail="vm not found")
    return {"host_id": payload.host_id, "vm": vm}


@app.delete("/api/v1/vms/{vm_id}/snapshots/{snapshot_id}")
def delete_snapshot(vm_id: str, snapshot_id: str, host_id: str, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, host_id)
    _libvirt_call(host, "snapshot_delete", vm_id, snapshot_id)
    _refresh_host_cache(db, host)
    return {"host_id": host_id, "result": {"status": "deleted", "snapshot_id": snapshot_id, "vm_id": vm_id}}


@app.post("/api/v1/networks/{network_id}/detach")
def detach_network(network_id: str, payload: NetworkDetachRequest, db: Session = Depends(get_db)) -> dict:
    _get_host_or_404(db, payload.host_id)
    _record_event("network.detach", f"network {network_id} detached from vm {payload.vm_id} on {payload.host_id}")
    return {"host_id": payload.host_id, "result": {"status": "detached", "network_id": network_id, "vm_id": payload.vm_id}}


@app.get("/api/v1/hosts/{host_id}/libvirt-health")
def host_libvirt_health(host_id: str, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, host_id)
    status = _libvirt_call(host, "health")
    _record_event("libvirt.health.ok", f"libvirt health check ok for host {host_id}")
    return {"host_id": host_id, "libvirt": status}


@app.get("/api/v1/backbone/check")
def api_backbone_check(db: Session = Depends(get_db)) -> dict:
    hosts = db.query(Host).all()
    return {
        "status": "ok",
        "api_version": "0.7.1",
        "features": {
            "hosts": len(hosts),
                "events": len(EVENTS),
            "tasks": len(TASKS),
            "runbooks": "enabled",
            "console": "enabled",
        },
    }


@app.get("/api/v1/hosts/{host_id}/images")
def list_host_images(host_id: str, refresh: bool = False, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, host_id)
    state = _host_cached_state(db, host, force_refresh=refresh)
    return {"host_id": host_id, "images": state["images"], "cache": state["cache"], "cached_at": state["updated_at"], "last_error": state.get("last_error"), "last_success_at": state.get("last_success_at")}


@app.get("/api/v1/hosts/{host_id}/storage-pools")
def list_storage_pools(host_id: str, refresh: bool = False, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, host_id)
    state = _host_cached_state(db, host, force_refresh=refresh)
    return {"host_id": host_id, "storage_pools": state["pools"], "cache": state["cache"], "cached_at": state["updated_at"], "last_error": state.get("last_error"), "last_success_at": state.get("last_success_at")}


@app.post("/api/v1/images")
def create_image(payload: ImageCreateRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    _require_roles(request, {"admin", "operator"})
    _enforce_policies("image.create", host_id=payload.host_id)
    host = _get_host_or_404(db, payload.host_id)
    image = _libvirt_call(host, "create_image", payload.name, payload.source_url or "default", 20)
    _refresh_host_cache(db, host)
    _record_event("image.created", f"image {payload.name} created on host {payload.host_id}")
    _create_completed_task("image.create", payload.name, f"pool={payload.source_url or 'default'}")
    return {"host_id": payload.host_id, "image": image}


@app.delete("/api/v1/images/{image_id}")
def delete_image(image_id: str, host_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    _require_roles(request, {"admin", "operator"})
    host = _get_host_or_404(db, host_id)
    result = _libvirt_call(host, "delete_image", image_id)
    _refresh_host_cache(db, host)
    _record_event("image.deleted", f"image {image_id} deleted from host {host_id}")
    return {"host_id": host_id, "result": result}


@app.post("/api/v1/projects", response_model=ProjectRecord)
def create_project(payload: ProjectCreateRequest) -> ProjectRecord:
    project = ProjectRecord(
        project_id=str(uuid4()),
        name=payload.name,
        description=payload.description,
        cpu_cores_quota=0,
        memory_mb_quota=0,
        vm_limit=0,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    PROJECTS[project.project_id] = project
    _record_event("project.created", f"project {project.name} created")
    _create_completed_task("project.create", project.project_id, f"project {project.name} created")
    return project


@app.get("/api/v1/projects", response_model=list[ProjectRecord])
def list_projects() -> list[ProjectRecord]:
    return list(PROJECTS.values())


@app.post("/api/v1/projects/{project_id}/quota", response_model=ProjectRecord)
def set_project_quota(project_id: str, payload: ProjectQuotaRequest) -> ProjectRecord:
    project = PROJECTS.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")

    updated = project.model_copy(
        update={
            "cpu_cores_quota": payload.cpu_cores,
            "memory_mb_quota": payload.memory_mb,
            "vm_limit": payload.vm_limit,
        }
    )
    PROJECTS[project_id] = updated
    _record_event("project.quota.updated", f"quota updated for project {updated.name}")
    _create_completed_task("project.quota", project_id, f"quota updated for {updated.name}")
    return updated


@app.get("/api/v1/roadmap")
def roadmap() -> dict:
    return {"current": "Phase 5 complete", "next": "Phase 6 - Execution Backend", "phases": ROADMAP_PHASES}


@app.get("/api/v1/pending-tasks")
def pending_tasks() -> dict:
    grouped: dict[str, list[dict[str, str]]] = {}
    for item in PENDING_TASKS:
        grouped.setdefault(item["area"], []).append(item)
    return {"count": len(PENDING_TASKS), "items": PENDING_TASKS, "grouped": grouped}


@app.get("/api/v1/dashboard/diagnostics")
def dashboard_diagnostics(db: Session = Depends(get_db)) -> dict:
    hosts = db.query(Host).all()
    return {
        "base_path": BASE_PATH or "/",
        "ui_routes": _dashboard_route_hints(),
        "host_count": len(hosts),
        "ready_hosts": len([host for host in hosts if host.status in {"ready", "registered"}]),
        "policy_count": len(POLICIES),
        "event_count": len(EVENTS),
        "task_count": len(TASKS),
        "pending_task_count": len(PENDING_TASKS),
        "next_phase": ROADMAP_PHASES[0]["phase"],
    }


@app.get("/api/v1/phase6/execution")
def phase6_execution_status(db: Session = Depends(get_db)) -> dict:
    hosts = db.query(Host).all()
    capabilities: list[dict[str, Any]] = []
    for host in hosts:
        capabilities.append(
            {
                "host_id": host.host_id,
                "cpu_cores": host.cpu_cores,
                "memory_mb": host.memory_mb,
                "libvirt_uri": host.libvirt_uri,
                "features": ["vm_lifecycle", "networking", "images"],
            }
        )
    return {
        "phase": "Phase 6 - Execution Backend",
        "status": "implemented-foundation",
        "host_capabilities": capabilities,
        "image_import_jobs": IMAGE_IMPORT_JOBS,
    }


@app.post("/api/v1/images/import")
def import_image(payload: ImageCreateRequest) -> dict:
    job = {
        "job_id": str(uuid4()),
        "host_id": payload.host_id,
        "name": payload.name,
        "source_url": payload.source_url,
        "checksum_status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    IMAGE_IMPORT_JOBS.insert(0, job)
    _record_event("image.import.requested", f"image import requested: {payload.name} on host {payload.host_id}")
    _create_completed_task("image.import", payload.host_id, f"import pipeline staged for {payload.name}")
    return {"status": "queued", "job": job}


@app.get("/api/v1/images/import-jobs")
def list_import_jobs(limit: int = 50) -> dict:
    return {"count": len(IMAGE_IMPORT_JOBS), "items": IMAGE_IMPORT_JOBS[: min(limit, 200)]}


@app.get("/api/v1/console/sessions")
def list_console_sessions(limit: int = 50) -> dict:
    return {"count": len(CONSOLE_SESSIONS), "items": CONSOLE_SESSIONS[: min(limit, 200)]}


@app.post("/api/v1/tasks/{task_id}/retry", response_model=TaskRecord)
def retry_task(task_id: str) -> TaskRecord:
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    retried = _create_completed_task(f"{task.task_type}.retry", task.target, f"retried task {task_id}")
    _record_event("task.retried", f"task {task_id} retried")
    return retried


@app.get("/api/v1/audit/export")
def export_audit() -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events": [event.model_dump() for event in EVENTS],
        "tasks": [task.model_dump() for task in TASKS.values()],
        "policies": [policy.model_dump() for policy in POLICIES.values()],
    }


@app.get("/api/v1/events/retention")
def get_event_retention() -> dict:
    return {"retention_days": EVENT_RETENTION_DAYS}


@app.post("/api/v1/events/retention")
def set_event_retention(days: int) -> dict:
    global EVENT_RETENTION_DAYS
    if days < 1:
        raise HTTPException(status_code=400, detail="days must be > 0")
    EVENT_RETENTION_DAYS = days
    _record_event("events.retention.updated", f"event retention changed to {days} days")
    return {"retention_days": EVENT_RETENTION_DAYS}


@app.get("/api/v1/runbooks/templates")
def list_runbook_templates() -> dict:
    return {"count": len(RUNBOOK_TEMPLATES), "items": list(RUNBOOK_TEMPLATES.values())}


@app.post("/api/v1/runbooks/templates")
def create_runbook_template(name: str, description: str = "") -> dict:
    template = {"template_id": str(uuid4()), "name": name, "description": description, "created_at": datetime.now(timezone.utc).isoformat()}
    RUNBOOK_TEMPLATES[template["template_id"]] = template
    return template


@app.get("/api/v1/runbooks/schedules")
def list_runbook_schedules() -> dict:
    return {"count": len(RUNBOOK_SCHEDULES), "items": list(RUNBOOK_SCHEDULES.values())}


@app.post("/api/v1/runbooks/schedules")
def create_runbook_schedule(runbook_name: str, cron: str, host_id: str | None = None, vm_id: str | None = None) -> dict:
    schedule = {
        "schedule_id": str(uuid4()),
        "runbook_name": runbook_name,
        "cron": cron,
        "host_id": host_id,
        "vm_id": vm_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    RUNBOOK_SCHEDULES[schedule["schedule_id"]] = schedule
    return schedule



app.include_router(build_vmware_router(_get_host_or_404, _libvirt_call, _refresh_host_cache))

@app.get("/api/v1/routes")
def list_routes() -> dict:
    routes = sorted(
        {
            route.path
            for route in app.routes
            if hasattr(route, "path") and str(route.path).startswith("/")
        }
    )
    return {"count": len(routes), "routes": routes, "dashboard_hints": _dashboard_route_hints(), "base_path": BASE_PATH or "/"}


@app.get("/api/v1/rbac/roles")
def rbac_roles() -> dict:
    return {
        "roles": {
            "admin": ["*"] ,
            "operator": ["vm.*", "network.*", "image.*", "console.*", "task.retry"],
            "viewer": ["read.*"],
        },
        "header": "x-role",
    }


@app.get("/api/v1/capabilities")
def capabilities() -> dict:
    return {
        "platform": "kvm-dashboard",
        "mode": "libvirt-live-proxmox-style",
        "features": {
            "host_lifecycle": True,
            "vm_lifecycle": True,
            "network_operations": True,
            "image_lifecycle": True,
            "runbooks_tasks_events": True,
            "policies": True,
            "console_ticket_placeholder": False,
            "multi_page_dashboard": True,
            "phase6_execution_backend_foundation": True,
            "vm_create_libvirt_live": True,
            "vm_attachments_libvirt_live": True,
            "console_libvirt_display_discovery": True,
            "network_crud_libvirt_live": True,
            "image_crud_libvirt_live": True,
            "rbac_header_enforcement": True,
            "phase7_timeline_and_retry": True,
            "phase8_policy_enforcement_foundation": True,
        },
    }


@app.post("/api/v1/policies", response_model=PolicyRecord)
def create_policy(payload: PolicyCreateRequest) -> PolicyRecord:
    policy = PolicyRecord(
        policy_id=str(uuid4()),
        name=payload.name,
        category=payload.category,
        spec=payload.spec,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    POLICIES[policy.policy_id] = policy
    _record_event("policy.created", f"policy {policy.name} created")
    _create_completed_task("policy.create", policy.policy_id, f"policy {policy.name} created")
    return policy


@app.get("/api/v1/policies", response_model=list[PolicyRecord])
def list_policies() -> list[PolicyRecord]:
    return list(POLICIES.values())


@app.post("/api/v1/policies/{policy_id}/bind-host")
def bind_policy_to_host(policy_id: str, payload: PolicyBindingRequest, db: Session = Depends(get_db)) -> dict:
    policy = POLICIES.get(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="policy not found")
    if not payload.host_id:
        raise HTTPException(status_code=400, detail="host_id is required")

    _get_host_or_404(db, payload.host_id)
    bindings = HOST_POLICY_BINDINGS.setdefault(payload.host_id, [])
    if policy_id not in bindings:
        bindings.append(policy_id)
    _record_event("policy.bind.host", f"policy {policy.name} bound to host {payload.host_id}")
    return {"policy_id": policy_id, "host_id": payload.host_id, "bindings": bindings}


@app.post("/api/v1/policies/{policy_id}/bind-project")
def bind_policy_to_project(policy_id: str, payload: PolicyBindingRequest) -> dict:
    policy = POLICIES.get(policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="policy not found")
    if not payload.project_id:
        raise HTTPException(status_code=400, detail="project_id is required")
    if payload.project_id not in PROJECTS:
        raise HTTPException(status_code=404, detail="project not found")

    bindings = PROJECT_POLICY_BINDINGS.setdefault(payload.project_id, [])
    if policy_id not in bindings:
        bindings.append(policy_id)
    _record_event("policy.bind.project", f"policy {policy.name} bound to project {payload.project_id}")
    return {"policy_id": policy_id, "project_id": payload.project_id, "bindings": bindings}


@app.get("/api/v1/policies/effective")
def effective_policies(host_id: str | None = None, project_id: str | None = None) -> dict:
    host_policy_ids = HOST_POLICY_BINDINGS.get(host_id or "", [])
    project_policy_ids = PROJECT_POLICY_BINDINGS.get(project_id or "", [])

    resolved_ids = list(dict.fromkeys(host_policy_ids + project_policy_ids))
    resolved = [POLICIES[policy_id] for policy_id in resolved_ids if policy_id in POLICIES]
    return {
        "host_id": host_id,
        "project_id": project_id,
        "policies": resolved,
    }


@app.get("/api/v1/events", response_model=list[EventRecord])
def list_events(limit: int = 50, event_type: str | None = None, since: str | None = None) -> list[EventRecord]:
    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit must be > 0")
    events = EVENTS
    if event_type:
        events = [event for event in events if event.type == event_type]
    if since:
        events = [event for event in events if event.created_at >= since]
    return events[: min(limit, 200)]


@app.get("/api/v1/operations-guide")
def operations_guide() -> dict:
    return {
        "summary": "Live libvirt + PostgreSQL cache workflow. No host-agent dependency.",
        "sections": [
            {"title": "1) Register host", "steps": ["Go to Overview and verify host appears in Live host status", "Ensure libvirt URI is reachable and health is green"]},
            {"title": "2) VM lifecycle", "steps": ["Open Virtual Machines page", "Use Provision / Import section for creation", "Use action buttons for start/stop/reboot/pause/resume/delete"]},
            {"title": "3) Networks and storage", "steps": ["Use Networks page for create/delete/attach/detach", "Use Storage and Images pages to inspect pools, qcow2 volumes, and used-by tags"]},
            {"title": "4) Console", "steps": ["Open Console page or VM row console action", "noVNC URL is generated from libvirt display + configured NOVNC paths"]},
            {"title": "5) Events and tasks", "steps": ["Use Events page to audit operation timeline", "Use Tasks page for operation records and retries"]},
        ],
    }


@app.get("/api/v1/overview")
def overview(db: Session = Depends(get_db)) -> dict:
    hosts = db.query(Host).all()
    host_count = len(hosts)
    ready_hosts = len([host for host in hosts if host.status in {"ready", "registered"}])
    total_cpu = sum(host.cpu_cores for host in hosts)
    total_memory = sum(host.memory_mb for host in hosts)

    project_count = len(PROJECTS)
    quota_cpu, quota_memory, quota_vm_limit = _project_quota_summary()

    return {
        "hosts": {
            "total": host_count,
            "ready": ready_hosts,
            "total_cpu_cores": total_cpu,
            "total_memory_mb": total_memory,
        },
        "projects": {
            "total": project_count,
            "quota_cpu_cores": quota_cpu,
            "quota_memory_mb": quota_memory,
            "quota_vm_limit": quota_vm_limit,
        },
        "events": {"total": len(EVENTS)},
        "tasks": {"total": len(TASKS)},
        "policies": {"total": len(POLICIES)},
    }


@app.get("/api/v1/vms/{vm_id}/console", response_model=ConsoleTicketResponse)
def vm_console(vm_id: str, host_id: str, db: Session = Depends(get_db)) -> ConsoleTicketResponse:
    host = _get_host_or_404(db, host_id)

    now_ts = time.time()
    for item in CONSOLE_SESSIONS:
        if item.get("host_id") != host_id or item.get("vm_id") != vm_id:
            continue
        created = item.get("created_at", "")
        try:
            created_ts = datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
        except Exception:
            created_ts = 0.0
        if (now_ts - created_ts) <= CONSOLE_SESSION_TTL_S and item.get("novnc_url"):
            return ConsoleTicketResponse(
                host_id=host_id,
                vm_id=vm_id,
                ticket=item.get("ticket", ""),
                noVNC_url=item.get("novnc_url", ""),
            )

    console = _libvirt_call(host, "console_info", vm_id)
    ticket, novnc_url, console_meta = build_console_urls(
        novnc_base_url=NOVNC_BASE_URL,
        novnc_ws_base=NOVNC_WS_BASE,
        host_id=host_id,
        vm_id=vm_id,
        host_address=host.address,
        display_uri=str(console.get("display_uri") or ""),
    )

    session = {
        "session_id": str(uuid4()),
        "host_id": host_id,
        "vm_id": vm_id,
        "ticket": ticket,
        "novnc_url": novnc_url,
        "display_uri": console.get("display_uri"),
        "vnc_host": console_meta.get("vnc_host", ""),
        "vnc_port": console_meta.get("vnc_port", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    CONSOLE_SESSIONS.insert(0, session)
    del CONSOLE_SESSIONS[200:]
    _record_event("vm.console.ticket", f"console ticket requested for vm {vm_id} on host {host_id}")
    return ConsoleTicketResponse(
        host_id=host_id,
        vm_id=vm_id,
        ticket=ticket,
        noVNC_url=novnc_url,
    )


@app.get("/console/noVNC", response_class=HTMLResponse)
def novnc_console_redirect(host_id: str, vm_id: str, ticket: str) -> str:
    ws_url = f"{NOVNC_WS_BASE}?{urlencode({'host_id': host_id, 'vm_id': vm_id, 'ticket': ticket})}"
    target = f"{NOVNC_BASE_URL}?{urlencode({'host_id': host_id, 'vm_id': vm_id, 'ticket': ticket, 'path': ws_url, 'autoconnect': 1, 'resize': 'remote'})}"
    return f"""
    <!doctype html>
    <html>
      <head><meta charset='utf-8'/><title>noVNC Console</title></head>
      <body style='background:#0b1020;color:#e6ecff;font-family:Arial;padding:20px'>
        <h2>Opening noVNC console...</h2>
        <p>If redirection does not start automatically, use <a style='color:#71a7ff' href='{target}'>this noVNC link</a>.</p>
        <script>window.location.replace({target!r});</script>
      </body>
    </html>
    """


@app.post("/api/v1/projects/{project_id}/members", response_model=ProjectMemberRecord)
def add_project_member(project_id: str, payload: ProjectMemberRequest) -> ProjectMemberRecord:
    project = PROJECTS.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")

    members = PROJECT_MEMBERS.setdefault(project_id, [])
    if any(member.user_id == payload.user_id for member in members):
        raise HTTPException(status_code=409, detail="member already exists")

    member = ProjectMemberRecord(
        member_id=str(uuid4()),
        project_id=project_id,
        user_id=payload.user_id,
        role=payload.role,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    members.append(member)
    _record_event("project.member.added", f"member {payload.user_id} added to project {project.name} as {payload.role}")
    _create_completed_task("project.member.add", project_id, f"member {payload.user_id} added")
    return member


@app.get("/api/v1/projects/{project_id}/members", response_model=list[ProjectMemberRecord])
def list_project_members(project_id: str) -> list[ProjectMemberRecord]:
    project = PROJECTS.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    return PROJECT_MEMBERS.get(project_id, [])


@app.post("/api/v1/runbooks/{runbook_name}/execute", response_model=TaskRecord)
def execute_runbook(runbook_name: str, payload: RunbookExecuteRequest) -> TaskRecord:
    target = payload.vm_id or payload.host_id or "platform"
    detail = f"runbook={runbook_name}, params={payload.parameters}"
    task = _create_completed_task("runbook.execute", target, detail)
    _record_event("runbook.executed", f"runbook {runbook_name} executed for {target}")
    return task




@app.post("/api/v1/tasks/vm-operations", response_model=TaskRecord)
def create_vm_operation_task(payload: VMOperationTaskRequest) -> TaskRecord:
    task_type = normalize_task_type(payload.task_type)
    if task_type not in SUPPORTED_VM_TASK_TYPES:
        raise HTTPException(status_code=400, detail=f"unsupported task_type '{payload.task_type}'")
    target = payload.vm_id or payload.host_id or "cluster"
    detail = f"vm_id={payload.vm_id or '-'}, host_id={payload.host_id or '-'}"
    task = _create_completed_task(task_type, target, detail)
    _record_event("task.vm_operation.created", f"{task_type} requested for {target}")
    return task

@app.get("/api/v1/tasks", response_model=list[TaskRecord])
def list_tasks(limit: int = 50) -> list[TaskRecord]:
    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit must be > 0")
    tasks = sorted(TASKS.values(), key=lambda task: task.created_at, reverse=True)
    return tasks[: min(limit, 200)]


@app.get("/api/v1/tasks/{task_id}", response_model=TaskRecord)
def get_task(task_id: str) -> TaskRecord:
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task






@app.get("/api/v1/live/status")
def live_status(refresh: bool = False, db: Session = Depends(get_db)) -> dict:
    now_ts = datetime.now(timezone.utc).timestamp()
    cached = LIVE_STATUS_CACHE.get("payload")
    cached_at = float(LIVE_STATUS_CACHE.get("updated_at", 0.0) or 0.0)
    if not refresh and cached and (now_ts - cached_at) <= LIVE_STATUS_TTL_S:
        return cached

    hosts = db.query(Host).all()
    items: list[dict[str, Any]] = []
    for host in hosts:
        libvirt_ok = False
        detail = "unreachable"
        try:
            status = _libvirt_call(host, "health")
            libvirt_ok = bool(status.get("reachable"))
            detail = "libvirt-direct"
        except HTTPException:
            pass
        items.append(
            {
                "host_id": host.host_id,
                "address": host.address,
                "status": host.status,
                "libvirt_reachable": libvirt_ok,
                "execution": detail,
                "libvirt_uri": host.libvirt_uri,
            }
        )
    payload = {"count": len(items), "items": items, "timestamp": datetime.now(timezone.utc).isoformat(), "cache_ttl_s": LIVE_STATUS_TTL_S}
    LIVE_STATUS_CACHE["updated_at"] = now_ts
    LIVE_STATUS_CACHE["payload"] = payload
    return payload

@app.get("/api/v1/console/novnc/status")
def novnc_status() -> dict:
    return {
        "novnc_base_url": NOVNC_BASE_URL,
        "novnc_ws_base": NOVNC_WS_BASE,
        "active_sessions": len(CONSOLE_SESSIONS),
        "sessions": CONSOLE_SESSIONS[:20],
    }


@app.post("/api/v1/vms/{vm_id}/live-migrate")
def live_migrate_vm(vm_id: str, payload: VMMigrateRequest, db: Session = Depends(get_db)) -> dict:
    result = migrate_vm(vm_id, payload, db)
    result["mode"] = "live"
    _record_event("vm.migrate.live", f"live migration requested for vm {vm_id}")
    _create_completed_task("vm.migrate.live", vm_id, f"{payload.source_host_id}->{payload.target_host_id}")
    return result


@app.get("/api/v1/policies/vm-lifecycle")
def list_vm_lifecycle_policies() -> dict:
    return {"count": len(VM_LIFECYCLE_POLICIES), "items": list(VM_LIFECYCLE_POLICIES.values())}


@app.post("/api/v1/policies/vm-lifecycle")
def upsert_vm_lifecycle_policy(payload: dict[str, Any]) -> dict:
    name = str(payload.get("name", "default")).strip() or "default"
    spec = payload.get("spec", {})
    VM_LIFECYCLE_POLICIES[name] = {"name": name, "spec": spec, "updated_at": datetime.now(timezone.utc).isoformat()}
    _record_event("policy.vm_lifecycle.upsert", f"vm lifecycle policy {name} updated")
    return VM_LIFECYCLE_POLICIES[name]


@app.get("/api/v1/networks/advanced")
def list_advanced_networks() -> dict:
    return ADVANCED_NETWORK_CONFIG


@app.post("/api/v1/networks/advanced/{section}")
def add_advanced_network_item(section: str, payload: dict[str, Any]) -> dict:
    if section not in ADVANCED_NETWORK_CONFIG:
        raise HTTPException(status_code=404, detail="advanced section not found")
    item = {"id": str(uuid4()), **payload, "created_at": datetime.now(timezone.utc).isoformat()}
    ADVANCED_NETWORK_CONFIG[section].insert(0, item)
    _record_event("network.advanced.add", f"{section} updated")
    return item


@app.delete("/api/v1/networks/advanced/{section}/{item_id}")
def delete_advanced_network_item(section: str, item_id: str) -> dict:
    if section not in ADVANCED_NETWORK_CONFIG:
        raise HTTPException(status_code=404, detail="advanced section not found")
    before = len(ADVANCED_NETWORK_CONFIG[section])
    ADVANCED_NETWORK_CONFIG[section] = [item for item in ADVANCED_NETWORK_CONFIG[section] if item.get("id") != item_id]
    if len(ADVANCED_NETWORK_CONFIG[section]) == before:
        raise HTTPException(status_code=404, detail="item not found")
    _record_event("network.advanced.delete", f"{section}/{item_id} removed")
    return {"status": "deleted", "section": section, "id": item_id}


@app.post("/api/v1/images/{image_id}/deploy")
def deploy_image(image_id: str, host_id: str, vm_name: str) -> dict:
    deployment = {
        "deployment_id": str(uuid4()),
        "image_id": image_id,
        "host_id": host_id,
        "vm_name": vm_name,
        "status": "queued",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    IMAGE_DEPLOYMENTS.insert(0, deployment)
    _record_event("image.deploy", f"image {image_id} deployment queued for {vm_name}@{host_id}")
    _create_completed_task("image.deploy", vm_name, f"image={image_id}, host={host_id}")
    return deployment


@app.get("/api/v1/images/deployments")
def list_image_deployments(limit: int = 50) -> dict:
    return {"count": len(IMAGE_DEPLOYMENTS), "items": IMAGE_DEPLOYMENTS[: min(limit, 200)]}


@app.get("/{path:path}", include_in_schema=False, response_class=HTMLResponse)
def dashboard_fallback(path: str, request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    if _is_api_or_reserved_path(path):
        raise HTTPException(status_code=404, detail="page not found")
    try:
        require_ui_auth(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=303)
    return HTMLResponse(_render_ui_page("dashboard", db))


@app.exception_handler(404)
def not_found_handler(request: Request, exc: HTTPException):
    path = str(request.url.path)
    accept = request.headers.get("accept", "")
    if "text/html" in accept and not _is_api_or_reserved_path(path):
        db_gen = get_db()
        try:
            db = next(db_gen)
            try:
                require_ui_auth(request, db)
            except HTTPException:
                return RedirectResponse(url="/login", status_code=303)
            return HTMLResponse(_render_ui_page("dashboard", db), status_code=200)
        except Exception:
            pass
        finally:
            try:
                next(db_gen)
            except StopIteration:
                pass
    return JSONResponse(
        status_code=404,
        content={
            "detail": exc.detail if isinstance(exc.detail, str) else "page not found",
            "path": path,
            "suggestions": _dashboard_route_hints(),
            "routes_api": _with_base("/api/v1/routes"),
        },
    )
