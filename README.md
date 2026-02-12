# KVM Dashboard + KVM Host Agent (Starter Platform)

This repository now contains a **working starter implementation** of:
- a centralized **KVM Dashboard API** (control plane server)
- a lightweight **KVM Host Agent** (runs on each KVM host)

The goal is to give you a clean base to build a full OpenShift-inspired operations platform (VM lifecycle, network operations, noVNC, qcow2 image lifecycle, policy, and day-2 automation).

---

## What is included now

### 1) Central Dashboard API (`/dashboard`)
- FastAPI server
- SQLite-backed host inventory
- Web dashboard page at `/`
- Host registration endpoint
- Heartbeat endpoint
- Host listing endpoint
- Host day-2 status actions (ready/maintenance/draining/disable)
- Host remove endpoint

### 2) KVM Host Agent API Server (`/agent`)
- Python **server-based agent** (FastAPI) for each KVM host that:
  - runs as an API service on the host (recommended with systemd)
  - auto-detects host CPU and memory
  - posts registration and heartbeat data to the central dashboard server
  - exposes local host-agent API endpoints (`/healthz`, `/agent/status`, `/agent/push-now`)

### 3) Containerized local setup
- `docker-compose.yml` to run both services quickly

---

## Repository structure

```text
.
├── agent/
│   ├── agent.py                  # compatibility entrypoint for uvicorn
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py             # environment + host configuration loading
│   │   ├── main.py               # FastAPI app wiring + lifecycle hooks
│   │   ├── routes.py             # API endpoints for VM/network operations
│   │   ├── schemas.py            # pydantic request/response models
│   │   ├── services.py           # heartbeat + dashboard sync logic
│   │   └── state.py              # shared in-memory state container
│   ├── Dockerfile
│   └── requirements.txt
├── dashboard/
│   ├── app/
│   │   ├── db.py
│   │   ├── main.py
│   │   ├── models.py
│   │   └── schemas.py
│   ├── Dockerfile
│   └── requirements.txt
├── docker-compose.yml
└── README.md
```

## Dashboard ↔ Agent linking model

- `dashboard` keeps source-of-truth host inventory in SQLite and exposes central APIs.
- `agent` auto-registers and sends heartbeat updates to dashboard using `DASHBOARD_URL`.
- Dashboard calls host-agent APIs (`/agent/vms`, `/agent/networks`, snapshots) using host address + port `9090`.
- This split lets you troubleshoot either side independently:
  - Agent-side logic and state issues: inspect `agent/app/routes.py`, `agent/app/services.py`, and `/agent/status`.
  - Control-plane orchestration issues: inspect `dashboard/app/main.py` and `/api/v1/events`.

---

## Quick start (Docker Compose)

### Prerequisites
- Docker
- Docker Compose

### 1) Start services

```bash
docker compose up --build
```

### 2) Check host-agent API server

```bash
curl http://localhost:9090/healthz
curl http://localhost:9090/agent/status
```

### 3) Open dashboard in browser

Visit: `http://localhost:8000/`

### 4) Validate dashboard health

```bash
curl http://localhost:8000/healthz
```

Expected output:

```json
{"status":"ok"}
```

### 5) See registered hosts

```bash
curl http://localhost:8000/api/v1/hosts
```

After ~15 seconds, the `host-agent` container should appear in the list.

---

## Run without Docker (local dev)

### Dashboard API

```bash
cd dashboard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Agent API server

Open another terminal:

```bash
cd agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
DASHBOARD_URL=http://127.0.0.1:8000 uvicorn agent:app --host 0.0.0.0 --port 9090
```

Trigger an immediate push to dashboard (optional):

```bash
curl -X POST http://127.0.0.1:9090/agent/push-now
```

---


## Day-to-day operations status (important)

### ✅ Available now in dashboard + agent
- Register hosts from agents
- Live heartbeat-based host status updates
- View all hosts from centralized page
- Perform host actions from UI/API:
  - mark ready
  - mark maintenance
  - mark draining
  - disable host
- Remove host from inventory
- Agent runs as API server on KVM host and posts host data to dashboard server
- **Next phase now added:** VM lifecycle API orchestration through centralized dashboard:
  - provision VM on selected host
  - list VMs per host
  - start/stop/reboot VM
  - delete VM
  - create/list/delete host networks
  - attach network to VM
  - create/list/delete qcow2 image records per host

### 🚧 Not implemented yet (next phases)
- Live migration and advanced VM lifecycle policies
- Advanced network operations (VLAN trunking, bridge automation, IPAM integration, security policies)
- noVNC VM console
- qcow2 image catalog and deployment workflows
- replace mock agent VM backend with direct libvirt execution on host



### ✅ Added in this phase (expanded day-2 operations)
- VM power actions now include `pause` and `resume`
- VM resize operation (`cpu_cores`, `memory_mb`)
- VM migration workflow across hosts via dashboard orchestration
- VM snapshots lifecycle (`create`, `list`, `revert`, `delete`)
- VM clone operation
- VM metadata operations (labels + annotations)
- Network detach operation (`detach network from VM`)


### ✅ Added in this phase (platform operations + console path)
- Projects API (create/list) for multi-tenant control-plane modeling
- Project quota API (CPU, memory, VM limit)
- Operations events API for timeline/audit-style feed
- Overview API for dashboard summary (hosts/projects/events totals)
- VM console ticket API and a noVNC integration placeholder page (`/console/noVNC`)

### New control-plane APIs in this phase
- `POST /api/v1/projects`
- `GET /api/v1/projects`
- `POST /api/v1/projects/{project_id}/quota`
- `GET /api/v1/events`
- `GET /api/v1/overview`
- `GET /api/v1/vms/{vm_id}/console?host_id=<host-id>`
- `GET /console/noVNC?host_id=<host-id>&vm_id=<vm-id>&ticket=<ticket>`


### ✅ Added in this phase (operations backbone APIs)
- Project membership APIs for RBAC-style team assignment
- Runbook execution API for OpenShift-like day-2 automation trigger flows
- Task tracking APIs (`list/get`) so operation results can be queried and audited
- Dashboard render hardening for recent events section (pre-rendered event html)


### ✅ Added in this phase (OpenShift-style policy controls)
- Policies API (create/list)
- Policy binding to hosts and projects
- Effective policy resolution endpoint for troubleshooting
- Capabilities discovery endpoint for UI/API clients

### New APIs in this phase
- `GET /api/v1/capabilities`
- `GET /api/v1/routes`
- `GET /api/v1/dashboard/diagnostics`
- `GET /api/v1/roadmap`
- `GET /api/v1/pending-tasks`
- `POST /api/v1/policies`
- `GET /api/v1/policies`
- `POST /api/v1/policies/{policy_id}/bind-host`
- `POST /api/v1/policies/{policy_id}/bind-project`
- `GET /api/v1/policies/effective?host_id=<host-id>&project_id=<project-id>`
- `GET /dashboard` (dashboard alias)
- `GET /ui` (dashboard alias)

### New APIs in this phase
- `POST /api/v1/projects/{project_id}/members`
- `GET /api/v1/projects/{project_id}/members`
- `POST /api/v1/runbooks/{runbook_name}/execute`
- `GET /api/v1/tasks`
- `GET /api/v1/tasks/{task_id}`
- `GET /api/v1/hosts/{host_id}/agent-health`
- `GET /api/v1/backbone/check`

## Next phase delivered in this commit

This phase adds centralized VM + network orchestration APIs in dashboard and host-side execution APIs in agent.

### Important scope note
Current VM and network lifecycle in agent is a **mock in-memory backend** for fast iteration and API workflow validation.
The next step is wiring these endpoints to real `libvirt` + host network backend operations on each KVM host.

## API endpoints (current)

### `GET /healthz`
Basic service liveness check.

### `POST /api/v1/hosts/register`
Registers/updates a host in inventory.

Example payload:

```json
{
  "host_id": "kvm-host-01",
  "name": "kvm-host-01",
  "address": "192.168.1.101",
  "cpu_cores": 16,
  "memory_mb": 65536,
  "libvirt_uri": "qemu:///system"
}
```

### `POST /api/v1/hosts/{host_id}/heartbeat`
Updates host status and capacity.

Example payload:

```json
{
  "status": "ready",
  "cpu_cores": 16,
  "memory_mb": 65536
}
```

### `POST /api/v1/hosts/{host_id}/action`
Apply a day-2 host operation.

Example payload:

```json
{
  "action": "mark_maintenance"
}
```

Available values: `mark_ready`, `mark_maintenance`, `mark_draining`, `disable`.

### `DELETE /api/v1/hosts/{host_id}`
Remove host from inventory.

### `GET /api/v1/hosts`
Returns all known hosts (latest first).

### `POST /api/v1/vms/provision`
Provision a VM on a specific host by forwarding request to host agent API.

Example payload:

```json
{
  "host_id": "kvm-host-01",
  "name": "web-01",
  "cpu_cores": 2,
  "memory_mb": 4096,
  "image": "ubuntu-24.04.qcow2"
}
```

### `GET /api/v1/hosts/{host_id}/vms`
List VMs for a given host.

### `POST /api/v1/vms/{vm_id}/action`
Apply VM action on selected host.

Example payload:

```json
{
  "host_id": "kvm-host-01",
  "action": "start"
}
```

### `DELETE /api/v1/vms/{vm_id}?host_id=<host-id>`
Delete VM from selected host.


### `POST /api/v1/networks`
Create network on selected host.

Example payload:

```json
{
  "host_id": "kvm-host-01",
  "name": "tenant-blue",
  "cidr": "10.20.0.0/24",
  "vlan_id": 120
}
```

### `GET /api/v1/hosts/{host_id}/networks`
List networks on selected host.

### `POST /api/v1/networks/{network_id}/attach`
Attach selected network to VM on selected host.

Example payload:

```json
{
  "host_id": "kvm-host-01",
  "vm_id": "<vm-id>"
}
```

### `DELETE /api/v1/networks/{network_id}?host_id=<host-id>`
Delete network from selected host.

## Agent API endpoints (on each KVM host)

### `GET /healthz`
Agent liveness and host identity.

### `GET /agent/status`
Current agent runtime status (last push time/result, errors, interval).

### `POST /agent/push-now`
Force immediate data push from host to dashboard.

### `GET /agent/vms`
List VMs currently managed by the host agent.

### `POST /agent/vms`
Create/provision VM in agent backend (mock in-memory for this phase).

### `POST /agent/vms/{vm_id}/action`
Apply VM action: `start`, `stop`, `reboot`.

### `DELETE /agent/vms/{vm_id}`
Delete VM from host agent backend.

### `GET /agent/networks`
List networks managed by host agent.

### `POST /agent/networks`
Create network in host agent backend.

### `POST /agent/networks/{network_id}/attach`
Attach network to VM.

### `DELETE /agent/networks/{network_id}`
Delete network from host agent backend.

---

## Running the agent on real KVM hosts

Install Python 3, then run with env vars:

```bash
export DASHBOARD_URL=http://<dashboard-server-ip>:8000
export HOST_ID=$(hostname)
export HOST_NAME=$(hostname)
export HOST_ADDRESS=<host-mgmt-ip>
export LIBVIRT_URI=qemu:///system
export HEARTBEAT_INTERVAL=15
uvicorn agent:app --host 0.0.0.0 --port 9090
```

Recommended production model:
- run agent as a `systemd` service on each KVM host
- use mTLS or signed tokens between agent and dashboard
- restrict API ingress to management subnet

Example `systemd` service unit:

```ini
[Unit]
Description=KVM Host Agent API
After=network.target

[Service]
WorkingDirectory=/opt/kvm-agent
Environment="DASHBOARD_URL=http://<dashboard-server-ip>:8000"
Environment="HOST_ID=%H"
Environment="HOST_NAME=%H"
Environment="HOST_ADDRESS=<host-mgmt-ip>"
Environment="LIBVIRT_URI=qemu:///system"
Environment="HEARTBEAT_INTERVAL=15"
ExecStart=/opt/kvm-agent/.venv/bin/uvicorn agent:app --host 0.0.0.0 --port 9090
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

---

## Next build steps (to reach your full vision)

### Phase 1 (immediately next)
- Add PostgreSQL for persistence
- Add auth (OIDC + RBAC)
- Add host tags and project mapping

### Phase 2
- VM lifecycle endpoints (create/start/stop/reboot/delete)
- libvirt integration on host side
- task queue for async operations

### Phase 3
- Network operations module:
  - virtual network definitions
  - VLAN/bridge mapping
  - security policy groups
  - IPAM integration

### Phase 4
- noVNC console broker flow
- qcow2 image catalog + checksum + versioning
- snapshot/backup/restore workflows

### Phase 5 (OpenShift-like operations maturity)
- project quotas
- policy/approval workflows
- audit timelines
- automation hooks and runbooks

---

## Notes

This is a **starter control-plane + agent scaffold**, intentionally simple and easy to run.
It is designed so you can now incrementally add full KVM orchestration, network operations, noVNC, qcow2 lifecycle, and enterprise governance features.


### New VM day-2 endpoints
- `POST /api/v1/vms/{vm_id}/resize`
- `POST /api/v1/vms/{vm_id}/migrate`
- `POST /api/v1/vms/{vm_id}/snapshots`
- `GET /api/v1/vms/{vm_id}/snapshots?host_id=<host-id>`
- `POST /api/v1/vms/{vm_id}/snapshots/{snapshot_id}/revert`
- `DELETE /api/v1/vms/{vm_id}/snapshots/{snapshot_id}?host_id=<host-id>`

### New network day-2 endpoint
- `POST /api/v1/networks/{network_id}/detach`



## API smoke-check (run every phase)
Use these commands after starting dashboard + agent:

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:9090/healthz
curl http://127.0.0.1:8000/api/v1/overview
curl -X POST http://127.0.0.1:8000/api/v1/projects -H 'content-type: application/json' -d '{"name":"team-a","description":"platform team"}'
curl http://127.0.0.1:8000/api/v1/projects
curl http://127.0.0.1:8000/api/v1/events
curl -X POST http://127.0.0.1:8000/api/v1/runbooks/node-drain/execute -H 'content-type: application/json' -d '{"host_id":"kvm-host-01","parameters":{"mode":"safe"}}'
curl http://127.0.0.1:8000/api/v1/tasks
```


## Blank page / Not Found troubleshooting
If dashboard page looks blank or shows `Not Found`, verify service routing first:

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/api/v1/backbone/check
```

If `/healthz` fails, dashboard service is not running.
If `/healthz` works but `/` still fails, ensure requests are sent to the dashboard port (not another local service) and that reverse proxy path forwarding includes `/`.

- `POST /api/v1/vms/{vm_id}/clone`
- `POST /api/v1/vms/{vm_id}/metadata`


## Quick non-Docker validation (avoids Docker page-not-found confusion)

Start dashboard directly:

```bash
uvicorn dashboard.app.main:app --host 0.0.0.0 --port 8000
```

Then verify routes:

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/
curl http://127.0.0.1:8000/dashboard
curl http://127.0.0.1:8000/ui
curl http://127.0.0.1:8000/index.html
curl http://127.0.0.1:8000/home
curl http://127.0.0.1:8000/api/v1/capabilities
curl http://127.0.0.1:8000/api/v1/routes
curl http://127.0.0.1:8000/api/v1/dashboard/diagnostics
```


## Base-path mode (for reverse proxies)

If your ingress/proxy serves dashboard under a prefix (for example `/kvm`), set:

```bash
export DASHBOARD_BASE_PATH=/kvm
uvicorn dashboard.app.main:app --host 0.0.0.0 --port 8000
```

Then both UI and API can be accessed with the prefix:

```bash
curl http://127.0.0.1:8000/kvm/dashboard
curl http://127.0.0.1:8000/kvm/api/v1/routes
curl http://127.0.0.1:8000/kvm/api/v1/dashboard/diagnostics
```


## Next phase plan (explicit)

### Phase 6 - Execution Backend (next)
- Integrate libvirt-backed VM lifecycle execution in host-agent
- Implement real host network backend operations (bridge/VLAN)
- Build qcow2 image import pipeline with checksum verification

### Phase 7 - Console + UX
- Replace noVNC placeholder with real tokenized console proxy path
- Add task retry and event filtering in dashboard
- Add project-scoped health views

### Phase 8 - Policy Enforcement
- Enforce policy checks before VM/network operations
- Add audit export and event retention controls
- Add scheduled runbooks and reusable templates

## Pending tasks (tracked in API)
Use:

```bash
curl http://127.0.0.1:8000/api/v1/roadmap
curl http://127.0.0.1:8000/api/v1/pending-tasks
```

## Multi-page dashboard navigation (new)

The dashboard UI is now split into navigable pages similar to OpenShift console sections:

- `/dashboard` - overview
- `/vms` - VM inventory view
- `/storage` - storage/image import jobs
- `/console` - console session view
- `/networks` - network inventory view
- `/images` - image catalog view
- `/projects` - project list view
- `/policies` - policy list view
- `/events` - event timeline view
- `/tasks` - task history view

Each page includes a shared left navigation and loads live data from API endpoints.

## Phase 6, 7, 8 implementation foundations (new)

### Phase 6 - Execution Backend foundations
- `GET /api/v1/phase6/execution`
- `POST /api/v1/images/import`
- `GET /api/v1/images/import-jobs`

### Phase 7 - Console + UX foundations
- `GET /api/v1/console/sessions`
- `POST /api/v1/tasks/{task_id}/retry`
- Enhanced `GET /api/v1/events` filters: `event_type`, `since`

### Phase 8 - Policy + audit foundations
- Policy enforcement hook for selected mutating actions (VM provision/action, network create, image create)
- `GET /api/v1/audit/export`
- `GET /api/v1/events/retention`
- `POST /api/v1/events/retention?days=<n>`
- `GET /api/v1/runbooks/templates`
- `POST /api/v1/runbooks/templates`
- `GET /api/v1/runbooks/schedules`
- `POST /api/v1/runbooks/schedules`

## Refined VM/Storage/Console UX updates

Latest UI update adds OpenShift-style interaction for operators:

- VM page includes direct actions: **Run**, **Shutdown**, **Reboot**, **Pause**, **Resume**, and **Console**.
- VM page supports **Create VM** and **Import VM** flows from the UI.
- Storage page shows **storage pools** with qcow2 volumes and VM-disk associations for quick visibility.
- Network page includes quick **Create network** action.
- Images page includes quick **Create image** and **Import image pipeline** actions.

New control-plane APIs used by this UX:

- `POST /api/v1/vms/import`
- `GET /api/v1/hosts/{host_id}/storage-pools`

## Live API mode (default) - no local DB file

Dashboard now runs in **live API mode by default** with in-memory inventory storage (no `kvm_dashboard.db` file persisted).

- Default behavior: ephemeral in-memory SQLite (`sqlite+pysqlite:///:memory:`)
- To enable file persistence again:

```bash
export PERSIST_LOCAL_DB=true
# optional override:
export DATABASE_URL=sqlite:///./kvm_dashboard.db
```

This keeps the app focused on live API fetch workflows from host agents while avoiding stale local DB artifacts in default runs.

## Live inventory + VM attachments APIs

To support fully live API-driven UI data (no mocked page state), the dashboard exposes:

- `GET /api/v1/hosts/{host_id}/inventory-live`
  - returns live host state, VM list, network list, image list, and VM attachment summary
- `GET /api/v1/vms/{vm_id}/attachments?host_id=<host-id>`
  - returns VM-level attachments: image, attached networks, snapshots, qcow2 volume metadata

## noVNC live console URL integration

Console ticket API now returns a live noVNC viewer URL composed from env-configurable values:

- `NOVNC_BASE_URL` (default: `/console/noVNC/viewer`)
- `NOVNC_WS_BASE` (default: `/console/noVNC/websockify`)

Example:

```bash
export NOVNC_BASE_URL=https://novnc.example.com/vnc.html
export NOVNC_WS_BASE=wss://novnc.example.com/websockify
```
