from datetime import datetime, timezone
import os
from typing import Any
from uuid import uuid4

import requests
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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

app = FastAPI(title="KVM Dashboard API", version="0.7.1")

AGENT_PORT = 9090
AGENT_TIMEOUT_S = 10
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


def _with_base(path: str) -> str:
    return f"{BASE_PATH}{path}" if BASE_PATH else path


def _dashboard_route_hints() -> list[str]:
    return [
        _with_base("/"),
        _with_base("/dashboard"),
        _with_base("/dashboard/"),
        _with_base("/ui"),
        _with_base("/ui/"),
        _with_base("/index.html"),
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

def _project_quota_summary() -> tuple[int, int, int]:
    total_cpu = sum(project.cpu_cores_quota for project in PROJECTS.values())
    total_memory = sum(project.memory_mb_quota for project in PROJECTS.values())
    total_vm_limit = sum(project.vm_limit for project in PROJECTS.values())
    return total_cpu, total_memory, total_vm_limit


@app.on_event("startup")
def startup() -> None:
    init_db()


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


def _apply_host_action(host: Host, action: HostAction) -> None:
    if action == HostAction.mark_ready:
        host.status = "ready"
    elif action == HostAction.mark_maintenance:
        host.status = "maintenance"
    elif action == HostAction.mark_draining:
        host.status = "draining"
    elif action == HostAction.disable:
        host.status = "disabled"


def _agent_base_url(host: Host) -> str:
    return f"http://{host.address}:{AGENT_PORT}"


def _get_host_or_404(db: Session, host_id: str) -> Host:
    host = db.query(Host).filter(Host.host_id == host_id).first()
    if not host:
        raise HTTPException(status_code=404, detail="host not found")
    return host


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/dashboard/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
@app.get("/ui/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
@app.get("/home", response_class=HTMLResponse)
def dashboard_home(db: Session = Depends(get_db)) -> str:
    dashboard_error: str | None = None
    hosts: list[Any] = []
    try:
        hosts = db.query(Host).order_by(Host.id.desc()).all()
    except Exception as exc:
        dashboard_error = f"Host inventory load failed: {exc}"

    ready_hosts = len([host for host in hosts if host.status in {"ready", "registered"}])
    quota_cpu, quota_memory, quota_vm_limit = _project_quota_summary()
    latest_events = EVENTS[:5]
    recent_events_html = "".join(
        f"<p><strong>{event.type}</strong> - {event.message}</p>" for event in latest_events
    )
    vm_features_html = "".join(
        f"<li>{feature}</li>"
        for feature in [
            "Provision, power control (start/stop/reboot/pause/resume), and delete",
            "Resize (CPU + memory), migrate between hosts, snapshot lifecycle",
            "Network attach/detach and host network operations",
            "Console ticket API and noVNC placeholder flow",
            "Metadata (labels/annotations), clone, runbooks, tasks, projects/quotas",
            "Image lifecycle APIs for qcow2 catalog records",
        ]
    )
    diagnostics_rows_html = "".join(
        f"<li><strong>{label}:</strong> {value}</li>"
        for label, value in [
            ("Base Path", BASE_PATH or "/"),
            ("UI Route", _with_base("/dashboard")),
            ("Routes API", _with_base("/api/v1/routes")),
            ("Diagnostics API", _with_base("/api/v1/dashboard/diagnostics")),
            ("Capabilities API", _with_base("/api/v1/capabilities")),
        ]
    )

    host_cards = "".join(
        f"""
        <div class='card'>
          <h3>{host.name}</h3>
          <p><strong>Host ID:</strong> {host.host_id}</p>
          <p><strong>Address:</strong> {host.address}</p>
          <p><strong>Status:</strong> <span class='status {host.status}'>{host.status}</span></p>
          <p><strong>CPU:</strong> {host.cpu_cores} cores</p>
          <p><strong>Memory:</strong> {host.memory_mb} MB</p>
          <p><strong>Libvirt:</strong> {host.libvirt_uri}</p>
          <p><strong>Last heartbeat:</strong> {host.last_heartbeat}</p>
          <div class='actions'>
            <form method='post' action='/hosts/{host.host_id}/action-web'>
              <input type='hidden' name='action' value='mark_ready'/>
              <button type='submit'>Mark ready</button>
            </form>
            <form method='post' action='/hosts/{host.host_id}/action-web'>
              <input type='hidden' name='action' value='mark_maintenance'/>
              <button type='submit'>Maintenance</button>
            </form>
            <form method='post' action='/hosts/{host.host_id}/action-web'>
              <input type='hidden' name='action' value='mark_draining'/>
              <button type='submit'>Draining</button>
            </form>
            <form method='post' action='/hosts/{host.host_id}/action-web'>
              <input type='hidden' name='action' value='disable'/>
              <button type='submit' class='danger'>Disable</button>
            </form>
          </div>
        </div>
        """
        for host in hosts
    )

    if not hosts:
        host_cards = "<div class='empty'>No hosts registered yet. Start the KVM host agent to populate this dashboard.</div>"

    return f"""
    <!doctype html>
    <html>
      <head>
        <meta charset='utf-8' />
        <meta name='viewport' content='width=device-width, initial-scale=1' />
        <title>KVM Dashboard</title>
        <style>
          :root {{ color-scheme: dark; --bg: #0b1020; --panel: #121a33; --muted: #8ea0c9; --text: #e6ecff; --ok: #23c552; --warn: #f5a524; --unknown: #7a8294; --critical: #f31260; }}
          body {{ margin: 0; font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif; background: radial-gradient(circle at 10% 10%, #172345, var(--bg)); color: var(--text); }}
          .container {{ max-width: 1100px; margin: 0 auto; padding: 24px; }}
          .header {{ display: flex; justify-content: space-between; align-items: center; gap: 16px; }}
          h1 {{ margin: 0; font-size: 28px; }}
          .subtitle {{ color: var(--muted); margin-top: 8px; }}
          .pill {{ background: #1e2a52; padding: 8px 12px; border-radius: 999px; font-weight: 600; }}
          .pill-accent {{ background: #203f6f; border: 1px solid #406ea8; }}
          .grid {{ margin-top: 20px; display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; }}
          .card {{ background: var(--panel); border: 1px solid #23325f; border-radius: 12px; padding: 14px; }}
          .card h3 {{ margin: 0 0 10px 0; }}
          .card p {{ margin: 6px 0; color: #c9d5f7; font-size: 14px; }}
          .status {{ padding: 2px 8px; border-radius: 999px; text-transform: uppercase; font-size: 12px; letter-spacing: .3px; }}
          .status.ready, .status.registered {{ background: rgba(35,197,82,.18); color: var(--ok); }}
          .status.warning, .status.draining, .status.maintenance {{ background: rgba(245,165,36,.18); color: var(--warn); }}
          .status.unknown {{ background: rgba(122,130,148,.2); color: #aab2c7; }}
          .status.disabled {{ background: rgba(243,18,96,.2); color: #ff5d9e; }}
          .actions {{ margin-top: 10px; display: flex; flex-wrap: wrap; gap: 8px; }}
          button {{ cursor: pointer; background: #253a74; color: #eaf0ff; border: 1px solid #3552a3; border-radius: 8px; padding: 6px 10px; font-size: 12px; }}
          button:hover {{ filter: brightness(1.1); }}
          button.danger {{ border-color: #8d2b57; background: #55243b; color: #ffc1d6; }}
          .empty {{ margin-top: 20px; padding: 16px; border-radius: 10px; background: #121a33; border: 1px dashed #31447d; color: var(--muted); }}
          ul {{ margin: 0; padding-left: 18px; }}
          li {{ margin: 6px 0; color: #c9d5f7; font-size: 14px; }}
          footer {{ margin-top: 28px; color: var(--muted); font-size: 13px; }}
        </style>
      </head>
      <body>
        <div class='container'>
          <div class='header'>
            <div>
              <h1>KVM Dashboard</h1>
              <div class='subtitle'>Centralized control plane for KVM hosts with OpenShift-inspired VM, network, image, and day-2 operations</div>
            </div>
            <div style='display:flex;gap:8px;flex-wrap:wrap'><div class='pill'>{len(hosts)} host(s)</div><div class='pill pill-accent'>base: {BASE_PATH or '/'} </div></div>
          </div>
          {f"<div class='card' style='border-color:#8d2b57'><h3>Dashboard warning</h3><p>{dashboard_error}</p></div>" if dashboard_error else ''}
          <div class='grid'>
            <div class='card'>
              <h3>Platform Overview</h3>
              <p><strong>Total Hosts:</strong> {len(hosts)}</p>
              <p><strong>Ready Hosts:</strong> {ready_hosts}</p>
              <p><strong>Projects:</strong> {len(PROJECTS)}</p>
              <p><strong>Events:</strong> {len(EVENTS)}</p>
              <p><strong>Policies:</strong> {len(POLICIES)}</p>
            </div>
            <div class='card'>
              <h3>Quota Summary</h3>
              <p><strong>CPU Quota:</strong> {quota_cpu} cores</p>
              <p><strong>Memory Quota:</strong> {quota_memory} MB</p>
              <p><strong>VM Limit:</strong> {quota_vm_limit}</p>
              <p style='color:#8ea0c9'>OpenShift-like controls start with projects, quotas, and events.</p>
            </div>
          </div>
          <div class='card' style='margin-top:14px'>
            <h3>VM Feature Visibility (OpenShift-inspired)</h3>
            <ul>{vm_features_html}</ul>
            <p style='color:#8ea0c9'>Use `/api/v1/overview`, `/api/v1/tasks`, `/api/v1/events`, and `/api/v1/capabilities` for troubleshooting control-plane workflows.</p>
          </div>
          <div class='card' style='margin-top:14px'>
            <h3>Routing & Diagnostics</h3>
            <ul>{diagnostics_rows_html}</ul>
            <p style='color:#8ea0c9'>If you still get 404, open diagnostics API and verify proxy base path mapping.</p>
          </div>
          <div class='card' style='margin-top:14px'>
            <h3>Recent Events</h3>
            {'<p style="color:#8ea0c9">No events yet.</p>' if not latest_events else recent_events_html}
          </div>
          <div class='grid'>{host_cards}</div>
          <footer>Current scope: host + VM + network API orchestration. VM/network operations are simulated on host-agent in this phase; libvirt/network backend integration is next.</footer>
        </div>
      </body>
    </html>
    """


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
            last_heartbeat=datetime.now(timezone.utc),
        )
        db.add(host)

    db.commit()
    db.refresh(host)
    return host


@app.post("/api/v1/hosts/{host_id}/heartbeat", response_model=HostResponse)
def heartbeat(host_id: str, payload: HeartbeatRequest, db: Session = Depends(get_db)) -> Host:
    host = _get_host_or_404(db, host_id)
    host.status = payload.status
    host.cpu_cores = payload.cpu_cores
    host.memory_mb = payload.memory_mb
    host.last_heartbeat = datetime.now(timezone.utc)
    db.commit()
    db.refresh(host)
    return host


@app.post("/api/v1/hosts/{host_id}/action", response_model=HostResponse)
def host_action(host_id: str, payload: HostActionRequest, db: Session = Depends(get_db)) -> Host:
    host = _get_host_or_404(db, host_id)
    _apply_host_action(host, payload.action)
    host.last_heartbeat = datetime.now(timezone.utc)
    db.commit()
    db.refresh(host)
    return host


@app.delete("/api/v1/hosts/{host_id}")
def remove_host(host_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    host = _get_host_or_404(db, host_id)
    db.delete(host)
    db.commit()
    return {"status": "deleted", "host_id": host_id}


@app.get("/api/v1/hosts", response_model=list[HostResponse])
def list_hosts(db: Session = Depends(get_db)) -> list[Host]:
    return db.query(Host).order_by(Host.id.desc()).all()


@app.post("/api/v1/vms/provision")
def provision_vm(payload: VMProvisionRequest, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, payload.host_id)
    url = f"{_agent_base_url(host)}/agent/vms"
    try:
        response = requests.post(
            url,
            json={
                "name": payload.name,
                "cpu_cores": payload.cpu_cores,
                "memory_mb": payload.memory_mb,
                "image": payload.image,
            },
            timeout=AGENT_TIMEOUT_S,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"agent request failed: {exc}") from exc

    return {"host_id": payload.host_id, "vm": response.json()}


@app.get("/api/v1/hosts/{host_id}/vms")
def list_host_vms(host_id: str, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, host_id)
    url = f"{_agent_base_url(host)}/agent/vms"
    try:
        response = requests.get(url, timeout=AGENT_TIMEOUT_S)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"agent request failed: {exc}") from exc

    return {"host_id": host_id, "vms": response.json()}


@app.post("/api/v1/vms/{vm_id}/action")
def vm_action(vm_id: str, payload: VMHostActionRequest, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, payload.host_id)
    url = f"{_agent_base_url(host)}/agent/vms/{vm_id}/action"
    try:
        response = requests.post(url, json={"action": payload.action.value}, timeout=AGENT_TIMEOUT_S)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"agent request failed: {exc}") from exc

    _record_event("vm.provision", f"vm {payload.name} provisioned on host {payload.host_id}")
    return {"host_id": payload.host_id, "vm": response.json()}


@app.delete("/api/v1/vms/{vm_id}")
def delete_vm(vm_id: str, host_id: str, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, host_id)
    url = f"{_agent_base_url(host)}/agent/vms/{vm_id}"
    try:
        response = requests.delete(url, timeout=AGENT_TIMEOUT_S)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"agent request failed: {exc}") from exc

    return {"host_id": host_id, "result": response.json()}


@app.post("/api/v1/networks")
def create_network(payload: NetworkCreateRequest, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, payload.host_id)
    url = f"{_agent_base_url(host)}/agent/networks"
    try:
        response = requests.post(
            url,
            json={"name": payload.name, "cidr": payload.cidr, "vlan_id": payload.vlan_id},
            timeout=AGENT_TIMEOUT_S,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"agent request failed: {exc}") from exc

    return {"host_id": payload.host_id, "network": response.json()}


@app.get("/api/v1/hosts/{host_id}/networks")
def list_host_networks(host_id: str, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, host_id)
    url = f"{_agent_base_url(host)}/agent/networks"
    try:
        response = requests.get(url, timeout=AGENT_TIMEOUT_S)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"agent request failed: {exc}") from exc

    return {"host_id": host_id, "networks": response.json()}


@app.post("/api/v1/networks/{network_id}/attach")
def attach_network(network_id: str, payload: NetworkAttachRequest, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, payload.host_id)
    url = f"{_agent_base_url(host)}/agent/networks/{network_id}/attach"
    try:
        response = requests.post(url, json={"vm_id": payload.vm_id}, timeout=AGENT_TIMEOUT_S)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"agent request failed: {exc}") from exc

    return {"host_id": payload.host_id, "result": response.json()}


@app.delete("/api/v1/networks/{network_id}")
def delete_network(network_id: str, host_id: str, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, host_id)
    url = f"{_agent_base_url(host)}/agent/networks/{network_id}"
    try:
        response = requests.delete(url, timeout=AGENT_TIMEOUT_S)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"agent request failed: {exc}") from exc

    return {"host_id": host_id, "result": response.json()}


@app.post("/api/v1/vms/{vm_id}/resize")
def resize_vm(vm_id: str, payload: VMResizeRequest, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, payload.host_id)
    url = f"{_agent_base_url(host)}/agent/vms/{vm_id}/resize"
    try:
        response = requests.post(
            url,
            json={"cpu_cores": payload.cpu_cores, "memory_mb": payload.memory_mb},
            timeout=AGENT_TIMEOUT_S,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"agent request failed: {exc}") from exc

    _record_event("vm.resize", f"vm {vm_id} resized on host {payload.host_id}")
    return {"host_id": payload.host_id, "vm": response.json()}


@app.post("/api/v1/vms/{vm_id}/clone")
def clone_vm(vm_id: str, payload: VMCloneRequest, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, payload.host_id)
    url = f"{_agent_base_url(host)}/agent/vms/{vm_id}/clone"
    try:
        response = requests.post(url, json={"name": payload.name}, timeout=AGENT_TIMEOUT_S)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"agent request failed: {exc}") from exc

    _record_event("vm.clone", f"vm {vm_id} cloned as {payload.name} on host {payload.host_id}")
    return {"host_id": payload.host_id, "vm": response.json()}


@app.post("/api/v1/vms/{vm_id}/metadata")
def set_vm_metadata(vm_id: str, payload: VMMetadataRequest, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, payload.host_id)
    url = f"{_agent_base_url(host)}/agent/vms/{vm_id}/metadata"
    try:
        response = requests.post(
            url,
            json={"labels": payload.labels, "annotations": payload.annotations},
            timeout=AGENT_TIMEOUT_S,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"agent request failed: {exc}") from exc

    _record_event("vm.metadata", f"vm {vm_id} metadata updated on host {payload.host_id}")
    return {"host_id": payload.host_id, "vm": response.json()}


@app.post("/api/v1/vms/{vm_id}/migrate")
def migrate_vm(vm_id: str, payload: VMMigrateRequest, db: Session = Depends(get_db)) -> dict:
    source_host = _get_host_or_404(db, payload.source_host_id)
    target_host = _get_host_or_404(db, payload.target_host_id)

    export_url = f"{_agent_base_url(source_host)}/agent/vms/{vm_id}/export"
    import_url = f"{_agent_base_url(target_host)}/agent/vms/import"
    delete_url = f"{_agent_base_url(source_host)}/agent/vms/{vm_id}"

    try:
        export_response = requests.get(export_url, timeout=AGENT_TIMEOUT_S)
        export_response.raise_for_status()
        vm_data = export_response.json()

        import_response = requests.post(import_url, json=vm_data, timeout=AGENT_TIMEOUT_S)
        import_response.raise_for_status()

        delete_response = requests.delete(delete_url, timeout=AGENT_TIMEOUT_S)
        delete_response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"agent request failed: {exc}") from exc

    _record_event("vm.migrate", f"vm {vm_id} migrated from {payload.source_host_id} to {payload.target_host_id}")
    return {
        "vm_id": vm_id,
        "source_host_id": payload.source_host_id,
        "target_host_id": payload.target_host_id,
        "vm": import_response.json(),
    }


@app.post("/api/v1/vms/{vm_id}/snapshots")
def create_snapshot(vm_id: str, payload: VMSnapshotCreateRequest, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, payload.host_id)
    url = f"{_agent_base_url(host)}/agent/vms/{vm_id}/snapshots"
    try:
        response = requests.post(url, json={"name": payload.name}, timeout=AGENT_TIMEOUT_S)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"agent request failed: {exc}") from exc

    return {"host_id": payload.host_id, "snapshot": response.json()}


@app.get("/api/v1/vms/{vm_id}/snapshots")
def list_snapshots(vm_id: str, host_id: str, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, host_id)
    url = f"{_agent_base_url(host)}/agent/vms/{vm_id}/snapshots"
    try:
        response = requests.get(url, timeout=AGENT_TIMEOUT_S)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"agent request failed: {exc}") from exc

    return {"host_id": host_id, "vm_id": vm_id, "snapshots": response.json()}


@app.post("/api/v1/vms/{vm_id}/snapshots/{snapshot_id}/revert")
def revert_snapshot(vm_id: str, snapshot_id: str, payload: VMSnapshotHostRequest, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, payload.host_id)
    url = f"{_agent_base_url(host)}/agent/vms/{vm_id}/snapshots/{snapshot_id}/revert"
    try:
        response = requests.post(url, timeout=AGENT_TIMEOUT_S)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"agent request failed: {exc}") from exc

    return {"host_id": payload.host_id, "vm": response.json()}


@app.delete("/api/v1/vms/{vm_id}/snapshots/{snapshot_id}")
def delete_snapshot(vm_id: str, snapshot_id: str, host_id: str, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, host_id)
    url = f"{_agent_base_url(host)}/agent/vms/{vm_id}/snapshots/{snapshot_id}"
    try:
        response = requests.delete(url, timeout=AGENT_TIMEOUT_S)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"agent request failed: {exc}") from exc

    return {"host_id": host_id, "result": response.json()}


@app.post("/api/v1/networks/{network_id}/detach")
def detach_network(network_id: str, payload: NetworkDetachRequest, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, payload.host_id)
    url = f"{_agent_base_url(host)}/agent/networks/{network_id}/detach"
    try:
        response = requests.post(url, json={"vm_id": payload.vm_id}, timeout=AGENT_TIMEOUT_S)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"agent request failed: {exc}") from exc

    return {"host_id": payload.host_id, "result": response.json()}


@app.get("/api/v1/hosts/{host_id}/agent-health")
def host_agent_health(host_id: str, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, host_id)
    url = f"{_agent_base_url(host)}/healthz"
    try:
        response = requests.get(url, timeout=AGENT_TIMEOUT_S)
        response.raise_for_status()
    except requests.RequestException as exc:
        _record_event("agent.health.failed", f"health check failed for host {host_id}: {exc}")
        raise HTTPException(status_code=502, detail=f"agent request failed: {exc}") from exc

    _record_event("agent.health.ok", f"health check ok for host {host_id}")
    return {"host_id": host_id, "agent": response.json()}


@app.get("/api/v1/backbone/check")
def api_backbone_check(db: Session = Depends(get_db)) -> dict:
    hosts = db.query(Host).all()
    return {
        "status": "ok",
        "api_version": "0.7.1",
        "features": {
            "hosts": len(hosts),
            "projects": len(PROJECTS),
            "events": len(EVENTS),
            "tasks": len(TASKS),
            "runbooks": "enabled",
            "console": "enabled",
        },
    }


@app.get("/api/v1/hosts/{host_id}/images")
def list_host_images(host_id: str, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, host_id)
    url = f"{_agent_base_url(host)}/agent/images"
    try:
        response = requests.get(url, timeout=AGENT_TIMEOUT_S)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"agent request failed: {exc}") from exc

    return {"host_id": host_id, "images": response.json()}


@app.post("/api/v1/images")
def create_image(payload: ImageCreateRequest, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, payload.host_id)
    url = f"{_agent_base_url(host)}/agent/images"
    try:
        response = requests.post(
            url,
            json={"name": payload.name, "source_url": payload.source_url},
            timeout=AGENT_TIMEOUT_S,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"agent request failed: {exc}") from exc

    _record_event("image.created", f"image {payload.name} created on host {payload.host_id}")
    return {"host_id": payload.host_id, "image": response.json()}


@app.delete("/api/v1/images/{image_id}")
def delete_image(image_id: str, host_id: str, db: Session = Depends(get_db)) -> dict:
    host = _get_host_or_404(db, host_id)
    url = f"{_agent_base_url(host)}/agent/images/{image_id}"
    try:
        response = requests.delete(url, timeout=AGENT_TIMEOUT_S)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"agent request failed: {exc}") from exc

    _record_event("image.deleted", f"image {image_id} deleted from host {host_id}")
    return {"host_id": host_id, "result": response.json()}


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


@app.get("/api/v1/dashboard/diagnostics")
def dashboard_diagnostics(db: Session = Depends(get_db)) -> dict:
    hosts = db.query(Host).all()
    return {
        "base_path": BASE_PATH or "/",
        "ui_routes": _dashboard_route_hints(),
        "host_count": len(hosts),
        "ready_hosts": len([host for host in hosts if host.status in {"ready", "registered"}]),
        "project_count": len(PROJECTS),
        "policy_count": len(POLICIES),
        "event_count": len(EVENTS),
        "task_count": len(TASKS),
    }


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


@app.get("/api/v1/capabilities")
def capabilities() -> dict:
    return {
        "platform": "kvm-dashboard",
        "mode": "openshift-inspired",
        "features": {
            "host_lifecycle": True,
            "vm_lifecycle": True,
            "network_operations": True,
            "image_lifecycle": True,
            "projects_quotas": True,
            "runbooks_tasks_events": True,
            "policies": True,
            "console_ticket_placeholder": True,
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
def list_events(limit: int = 50) -> list[EventRecord]:
    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit must be > 0")
    return EVENTS[: min(limit, 200)]


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
    ticket = str(uuid4())
    _record_event("vm.console.ticket", f"console ticket requested for vm {vm_id} on host {host_id}")
    return ConsoleTicketResponse(
        host_id=host_id,
        vm_id=vm_id,
        ticket=ticket,
        noVNC_url=f"/console/noVNC?host_id={host_id}&vm_id={vm_id}&ticket={ticket}",
    )


@app.get("/console/noVNC", response_class=HTMLResponse)
def novnc_console_placeholder(host_id: str, vm_id: str, ticket: str) -> str:
    return f"""
    <!doctype html>
    <html>
      <head><meta charset='utf-8'/><title>noVNC Console</title></head>
      <body style='background:#0b1020;color:#e6ecff;font-family:Arial;padding:20px'>
        <h2>Console placeholder</h2>
        <p>This screen reserves the noVNC integration path for VM console sessions.</p>
        <ul>
          <li>Host: {host_id}</li>
          <li>VM: {vm_id}</li>
          <li>Ticket: {ticket}</li>
        </ul>
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


@app.get("/{path:path}", include_in_schema=False, response_class=HTMLResponse)
def dashboard_fallback(path: str, db: Session = Depends(get_db)) -> HTMLResponse:
    if _is_api_or_reserved_path(path):
        raise HTTPException(status_code=404, detail="page not found")
    return HTMLResponse(dashboard_home(db))


@app.exception_handler(404)
def not_found_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "detail": exc.detail if isinstance(exc.detail, str) else "page not found",
            "path": str(request.url.path),
            "suggestions": _dashboard_route_hints(),
            "routes_api": _with_base("/api/v1/routes"),
        },
    )
