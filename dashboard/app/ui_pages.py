from __future__ import annotations

from typing import Any

NAV_GROUPS = [
    ("Observe", [("dashboard", "Overview", "/dashboard"), ("events", "Events", "/events"), ("tasks", "Tasks", "/tasks")]),
    ("Workloads", [("vms", "Virtual Machines", "/vms"), ("console", "Console", "/console")]),
    ("Infrastructure", [("networks", "Networks", "/networks"), ("storage", "Storage pools", "/storage"), ("images", "Images", "/images")]),
    ("Administration", [("projects", "Projects", "/projects"), ("policies", "Policies", "/policies")]),
]

PAGE_CONFIG: dict[str, dict[str, str]] = {
    "dashboard": {"title": "Overview", "description": "Cluster status and quick actions."},
    "vms": {"title": "Virtual Machines", "description": "Create/import VMs and run power operations."},
    "storage": {"title": "Storage pools", "description": "Pool usage, qcow2 volumes, and mapping to VMs."},
    "console": {"title": "Console", "description": "Request and track VM console sessions."},
    "networks": {"title": "Networks", "description": "Create virtual networks and inspect host networks."},
    "images": {"title": "Images", "description": "qcow2 image catalog and import pipeline."},
    "projects": {"title": "Projects", "description": "Tenancy and quota controls."},
    "policies": {"title": "Policies", "description": "Governance and action control policies."},
    "events": {"title": "Events", "description": "Operational timeline for troubleshooting."},
    "tasks": {"title": "Tasks", "description": "Automation task history and retries."},
}


def _with_base(base_path: str, path: str) -> str:
    return f"{base_path}{path}" if base_path else path


def render_dashboard_page(
    page: str,
    *,
    base_path: str,
    stats: dict[str, Any],
) -> str:
    page_key = page if page in PAGE_CONFIG else "dashboard"
    config = PAGE_CONFIG[page_key]

    nav_html = ""
    for group, items in NAV_GROUPS:
        links = "".join(
            f"<a class='nav-link {'active' if key == page_key else ''}' href='{_with_base(base_path, path)}'>{label}</a>"
            for key, label, path in items
        )
        nav_html += f"<div class='nav-group'><div class='nav-title'>{group}</div>{links}</div>"


    return f"""
    <!doctype html>
    <html>
      <head>
        <meta charset='utf-8' />
        <meta name='viewport' content='width=device-width, initial-scale=1' />
        <title>KVM Dashboard - {config['title']}</title>
        <style>
          :root {{ color-scheme: dark; --bg:#1f2633; --panel:#263145; --panel-2:#2d3a4f; --muted:#a9b6cc; --text:#ecf1fa; --border:#3a4a62; --primary:#3f8cff; --ok:#39b26b; --warn:#d39b34; --danger:#d85b67; }}
          body {{ margin:0; font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif; background: var(--bg); color: var(--text); }}
          .layout {{ display:grid; grid-template-columns:240px 1fr; min-height:100vh; }}
          .sidebar {{ border-right:1px solid var(--border); padding:12px; background:#1b2330; }}
          .brand {{ font-size:19px; font-weight:700; }}
          .sub {{ color:var(--muted); font-size:12px; margin:6px 0 12px; }}
          .nav-group {{ margin-bottom:14px; }}
          .nav-title {{ color:var(--muted); font-size:11px; text-transform:uppercase; margin-bottom:6px; }}
          .nav-link {{ display:block; color:#c9d5f7; text-decoration:none; padding:8px 10px; border-radius:8px; border:1px solid transparent; margin-bottom:6px; }}
          .nav-link.active,.nav-link:hover {{ background:#2a3a52; border-color:#4f6b8a; }}
          .content {{ padding:0; }}
          .headerbar {{ height:44px; display:flex; align-items:center; padding:0 14px; border-bottom:1px solid var(--border); background:#1a2330; color:#cbd6ea; font-size:13px; }}
          .page {{ padding:16px; }}
          .toolbar {{ display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:14px; }}
          .search {{ background:#0f1a3b; border:1px solid #32498d; color:#dce7ff; border-radius:8px; padding:8px 10px; min-width:260px; }}
          .cards {{ display:grid; grid-template-columns: repeat(auto-fit,minmax(170px,1fr)); gap:12px; margin-bottom:14px; }}
          .card {{ background:var(--panel); border:1px solid var(--border); border-radius:6px; padding:10px; }}
          .muted {{ color:var(--muted); }}
          .btn {{ border:1px solid #2f5dad; background:#123777; color:#e8f2ff; padding:6px 10px; border-radius:8px; cursor:pointer; }}
          .btn.danger {{ border-color:#7e294f; background:#57243d; }}
          .btn.warn {{ border-color:#8c5e1c; background:#6b4a1d; }}
          .row {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:8px; }}
          .op-grid {{ display:grid; gap:10px; grid-template-columns: repeat(auto-fit,minmax(330px,1fr)); margin-top:8px; }}
          .op-card {{ border:1px solid #334a72; background:#1a2740; border-radius:8px; padding:10px; }}
          .op-card h4 {{ margin:0 0 8px; font-size:13px; color:#dbe7ff; }}
          input, select {{ background:#0f1a3b; border:1px solid #2a447f; color:#dce7ff; border-radius:8px; padding:7px 9px; }}
          table {{ width:100%; border-collapse:collapse; margin-top:8px; }}
          th, td {{ border-bottom:1px solid #22325c; padding:8px; text-align:left; font-size:13px; }}
          .pill {{ border-radius:999px; padding:2px 8px; font-size:11px; }}
          .pill.running {{ background: rgba(35,197,82,.2); color:#7ef5a7; }}
          .pill.stopped {{ background: rgba(122,130,148,.2); color:#b6c0d4; }}
          .pill.paused {{ background: rgba(245,165,36,.2); color:#ffd277; }}
          .error {{ color:#ff9cbc; }}
          .console-modal {{ position:fixed; inset:0; background:rgba(4,9,20,.75); display:none; align-items:center; justify-content:center; z-index:9999; }}
          .console-modal.open {{ display:flex; }}
          .console-shell {{ width:min(1200px,96vw); height:min(780px,92vh); background:#0d1526; border:1px solid #38507a; border-radius:10px; overflow:hidden; display:flex; flex-direction:column; }}
          .console-head {{ display:flex; justify-content:space-between; align-items:center; padding:8px 10px; border-bottom:1px solid #263b61; background:#111c33; }}
          .console-frame {{ width:100%; height:100%; border:0; background:#000; }}
        </style>
      </head>
      <body>
        <div class='layout'>
          <aside class='sidebar'>
            <div class='brand'>KVM Dashboard</div>
            <div class='sub'>Proxmox-style operations view</div>
            {nav_html}
          </aside>
          <main class='content'>
            <div class='headerbar'>Datacenter / Virtualization / {config['title']}</div>
            <div class='page'>
            <div class='toolbar'>
              <div><h1 style='margin:0'>{config['title']}</h1><div class='muted'>{config['description']}</div></div>
              <div class='row'><span id='realtimeStatus' class='muted'>Realtime refresh: initializing…</span><input id='search' class='search' placeholder='Filter table rows...' /></div>
            </div>
            <div class='cards'>
              <div class='card'><strong>Hosts</strong><div>{stats['hosts']}</div></div>
              <div class='card'><strong>Ready</strong><div>{stats['ready_hosts']}</div></div>
              <div class='card'><strong>Projects</strong><div>{stats['projects']}</div></div>
              <div class='card'><strong>Policies</strong><div>{stats['policies']}</div></div>
            </div>
            <div class='card' id='actions'></div>
            <div class='card' style='margin-top:12px' id='content'></div>
            </div>
          </main>
        </div>

        <div id='consoleModal' class='console-modal'>
          <div class='console-shell'>
            <div class='console-head'>
              <strong id='consoleTitle'>VM Console</strong>
              <div class='row' style='margin:0'>
                <button class='btn' id='consolePopoutBtn'>Pop out</button>
                <button class='btn danger' id='consoleCloseBtn'>Close</button>
              </div>
            </div>
            <iframe id='consoleFrame' class='console-frame' loading='eager' referrerpolicy='no-referrer'></iframe>
          </div>
        </div>

        <script>
          const key = {page_key!r};
          const base = {base_path!r};
          const content = document.getElementById('content');
          const actions = document.getElementById('actions');
          const searchInput = document.getElementById('search');
          let currentRows = [];
          let consoleLastUrl = '';

          window.showConsole = function showConsole(url, title='VM Console') {{
            const modal = document.getElementById('consoleModal');
            const frame = document.getElementById('consoleFrame');
            const titleEl = document.getElementById('consoleTitle');
            if (!modal || !frame || !titleEl) return;
            titleEl.textContent = title;
            if (consoleLastUrl !== url) {{
              frame.src = url;
              consoleLastUrl = url;
            }}
            modal.classList.add('open');
          }}

          function closeConsole() {{
            const modal = document.getElementById('consoleModal');
            const frame = document.getElementById('consoleFrame');
            if (!modal || !frame) return;
            modal.classList.remove('open');
            frame.src = 'about:blank';
            consoleLastUrl = '';
          }}

          async function api(path, method='GET', body=null) {{
            const resp = await fetch((base || '') + path, {{
              method,
              credentials: 'same-origin',
              headers: {{ 'Content-Type': 'application/json' }},
              body: body ? JSON.stringify(body) : null,
            }});
            const ctype = resp.headers.get('content-type') || '';
            const isJson = ctype.includes('application/json');
            const data = isJson ? await resp.json() : await resp.text();
            if (!resp.ok) {{
              if (!isJson && typeof data === 'string' && data.toLowerCase().includes('<!doctype html')) {{
                throw new Error('Session expired. Please login again.');
              }}
              throw new Error((isJson && data?.detail) || 'Request failed');
            }}
            return data;
          }}

          function table(headers, rows) {{
            currentRows = rows.map(r => r.join(' ').toLowerCase());
            const thead = `<tr>${{headers.map(h => `<th>${{h}}</th>`).join('')}}</tr>`;
            const tbody = rows.length ? rows.map(r => `<tr>${{r.map(c => `<td>${{c}}</td>`).join('')}}</tr>`).join('') : `<tr><td colspan='${{headers.length}}' class='muted'>No data</td></tr>`;
            return `<table>${{thead}}${{tbody}}</table>`;
          }}

          let selectedHostId = null;

          async function getHosts() {{
            const hosts = await api('/api/v1/hosts');
            return Array.isArray(hosts) ? hosts : [];
          }}

          function renderHostSelector(hosts, selectedId, selectId) {{
            if (!hosts.length) return "<span class='muted'>No hosts registered</span>";
            const options = hosts.map(h => `<option value='${{h.host_id}}' ${{h.host_id === selectedId ? 'selected' : ''}}>${{h.name}} (${{h.host_id}})</option>`).join('');
            return `<label class='muted'>Host:</label><select id='${{selectId}}'>${{options}}</select>`;
          }}

          async function pickSelectedHostId() {{
            const hosts = await getHosts();
            if (!hosts.length) return {{ hosts, hostId: null }};
            const saved = localStorage.getItem('kvm.selectedHostId');
            const chosen = selectedHostId || saved;
            const valid = hosts.some(h => h.host_id === chosen) ? chosen : hosts[0].host_id;
            selectedHostId = valid;
            localStorage.setItem('kvm.selectedHostId', valid);
            return {{ hosts, hostId: valid }};
          }}

          function bindSearch() {{
            const rows = Array.from(content.querySelectorAll('tbody tr'));
            searchInput.oninput = () => {{
              const q = searchInput.value.toLowerCase().trim();
              rows.forEach((row, idx) => {{
                row.style.display = !q || currentRows[idx]?.includes(q) ? '' : 'none';
              }});
            }};
          }}


          function bindHostSelector(selectId, reloadFn) {{
            const el = document.getElementById(selectId);
            if (!el) return;
            el.onchange = () => {{
              selectedHostId = el.value;
              localStorage.setItem('kvm.selectedHostId', selectedHostId);
              reloadFn();
            }};
          }}

          function setError(err) {{
            content.innerHTML = `<div class='error'>${{err.message || err}}</div>`;
          }}

          async function loadOverview() {{
            actions.innerHTML = `<strong>Quick links</strong><div class='row'><a class='btn' href='${{base||''}}/vms'>Go to VMs</a><a class='btn' href='${{base||''}}/storage'>Go to Storage</a><a class='btn' href='${{base||''}}/networks'>Go to Networks</a><a class='btn' href='${{base||''}}/console'>Go to Console</a></div>`;
            const ov = await api('/api/v1/overview');
            const live = await api('/api/v1/live/status');
            const rows = [
              ['Hosts total', ov.hosts.total, 'Ready', ov.hosts.ready],
              ['CPU cores', ov.hosts.total_cpu_cores, 'Memory MB', ov.hosts.total_memory_mb],
              ['Projects', ov.projects.total, 'Policies', ov.policies.total],
              ['Events', ov.events.total, 'Tasks', ov.tasks.total],
            ];
            const hostRows = (live.items || []).map(h => [h.host_id, h.status, h.agent_reachable ? 'reachable' : 'down', h.execution, h.libvirt_uri]);
            content.innerHTML = `<strong>Cluster summary</strong>${{table(['Metric','Value','Metric','Value'], rows)}}<div style='margin-top:10px'><strong>Live host API status</strong>${{table(['Host','Status','Libvirt Reachability','Execution','Libvirt URI'], hostRows)}}</div>`;
            bindSearch();
          }}

          async function loadVMs() {{
            const {{ hosts, hostId }} = await pickSelectedHostId();
            actions.innerHTML = `<strong>VM operations</strong>
              <div class='row'>${{renderHostSelector(hosts, hostId, 'vmHostSelect')}}</div>
              <div class='op-grid'>
                <div class='op-card'>
                  <h4>Provision / Import</h4>
                  <div class='row'>
                    <input id='vmName' placeholder='VM name' />
                    <input id='vmCpu' type='number' value='2' min='1' style='width:80px' />
                    <input id='vmMem' type='number' value='2048' min='512' style='width:100px' />
                    <input id='vmImage' placeholder='base.qcow2 or pool::volume' value='base.qcow2' />
                    <button class='btn' id='createVmBtn'>Create VM</button>
                  </div>
                  <div class='row'>
                    <input id='impVmId' placeholder='Import VM ID' />
                    <input id='impVmName' placeholder='Import VM name' />
                    <button class='btn' id='importVmBtn'>Import VM</button>
                  </div>
                </div>
                <div class='op-card'>
                  <h4>Day-2 Compute</h4>
                  <div class='row'>
                    <input id='opVmId' placeholder='Target VM ID for day-2 ops' style='min-width:220px' />
                    <input id='opCpu' type='number' value='4' min='1' style='width:80px' />
                    <input id='opMem' type='number' value='4096' min='512' style='width:100px' />
                    <button class='btn' id='resizeVmBtn'>Resize CPU/Memory</button>
                    <input id='cloneName' placeholder='clone name' />
                    <button class='btn' id='cloneVmBtn'>Clone VM</button>
                  </div>
                  <div class='row'>
                    <input id='snapName' placeholder='snapshot name' value='pre-maintenance' />
                    <button class='btn' id='snapshotBtn'>Create Snapshot</button>
                    <input id='migHost' placeholder='target host id' />
                    <button class='btn' id='migrateBtn'>Migrate</button>
                    <button class='btn danger' id='deleteVmBtn'>Delete VM</button>
                  </div>
                </div>
                <div class='op-card'>
                  <h4>Network / Snapshot / Recovery ISO</h4>
                  <div class='row'>
                    <input id='netId' placeholder='network id for attach/detach' style='min-width:220px' />
                    <button class='btn' id='attachNetBtn'>Attach Network</button>
                    <button class='btn warn' id='detachNetBtn'>Detach Network</button>
                    <input id='snapId' placeholder='snapshot id' style='min-width:180px' />
                    <button class='btn' id='revertSnapBtn'>Revert Snapshot</button>
                    <button class='btn danger' id='deleteSnapBtn'>Delete Snapshot</button>
                  </div>
                  <div class='row'>
                    <input id='isoPath' placeholder='/var/lib/libvirt/images/recovery.iso' style='min-width:320px' />
                    <button class='btn warn' id='attachIsoBtn'>Attach Recovery ISO</button>
                    <button class='btn' id='detachIsoBtn'>Detach Recovery ISO</button>
                  </div>
                </div>
              </div>
              <div class='muted'>Live day-2 operations: power, resize, clone, migrate, snapshots (create/revert/delete), network attach/detach, delete, console, and recovery ISO workflows.</div>`;
            if (!hostId) {{
              content.innerHTML = "<div class='muted'>No hosts registered yet.</div>";
              return;
            }}
            const live = await api(`/api/v1/hosts/${{hostId}}/inventory-live`);
            const rows = (live.vms || []).map(vm => {{
              const att = (live.attachments || {{}})[vm.vm_id] || {{}};
              const snaps = (att.snapshots || []).length;
              return [
                vm.vm_id,
                vm.name,
                vm.image,
                vm.cpu_cores,
                vm.memory_mb,
                `<span class='pill ${{vm.power_state}}'>${{vm.power_state}}</span>`,
                (att.networks || vm.networks || []).join(', ') || '-',
                `${{snaps}} snapshot(s)`,
                `<button class='btn' onclick="vmPower('${{vm.vm_id}}','start','${{hostId}}')">Run</button>
                 <button class='btn warn' onclick="vmPower('${{vm.vm_id}}','stop','${{hostId}}')">Shutdown</button>
                 <button class='btn' onclick="vmPower('${{vm.vm_id}}','reboot','${{hostId}}')">Reboot</button>
                 <button class='btn warn' onclick="vmPower('${{vm.vm_id}}','pause','${{hostId}}')">Pause</button>
                 <button class='btn' onclick="vmPower('${{vm.vm_id}}','resume','${{hostId}}')">Resume</button>
                 <button class='btn' onclick="openConsole('${{vm.vm_id}}','${{hostId}}')">Console</button>
                 <button class='btn' onclick="viewAttach('${{vm.vm_id}}','${{hostId}}')">Attachments</button>
                 <button class='btn danger' onclick="deleteVm('${{vm.vm_id}}','${{hostId}}')">Delete</button>`
              ];
            }});
            content.innerHTML = `<strong>VM inventory (live)</strong>${{table(['VM ID','Name','Image','CPU','Memory MB','State','Networks','Snapshots','Actions'], rows)}}`;

            document.getElementById('createVmBtn').onclick = async () => {{
              await api('/api/v1/vms/provision', 'POST', {{
                host_id: hostId,
                name: document.getElementById('vmName').value,
                cpu_cores: Number(document.getElementById('vmCpu').value),
                memory_mb: Number(document.getElementById('vmMem').value),
                image: document.getElementById('vmImage').value,
              }});
              loadVMs();
            }};
            document.getElementById('importVmBtn').onclick = async () => {{
              const now = new Date().toISOString();
              await api('/api/v1/vms/import', 'POST', {{
                host_id: hostId,
                vm_id: document.getElementById('impVmId').value,
                name: document.getElementById('impVmName').value,
                cpu_cores: 2,
                memory_mb: 2048,
                image: 'imported.qcow2',
                power_state: 'stopped',
                networks: [],
                labels: {{}},
                annotations: {{}},
                created_at: now,
              }});
              loadVMs();
            }};

            const opVmId = () => document.getElementById('opVmId').value.trim();
            document.getElementById('resizeVmBtn').onclick = async () => {{
              const vmId = opVmId();
              if (!vmId) return alert('Provide VM ID');
              await api(`/api/v1/vms/${{vmId}}/resize`, 'POST', {{ host_id: hostId, cpu_cores: Number(document.getElementById('opCpu').value), memory_mb: Number(document.getElementById('opMem').value) }});
              await api('/api/v1/tasks/vm-operations', 'POST', {{ task_type: 'vm.resize', vm_id: vmId, host_id: hostId }});
              loadVMs();
            }};
            document.getElementById('cloneVmBtn').onclick = async () => {{
              const vmId = opVmId();
              if (!vmId) return alert('Provide VM ID');
              await api(`/api/v1/vms/${{vmId}}/clone`, 'POST', {{ host_id: hostId, name: document.getElementById('cloneName').value || `${{vmId}}-clone` }});
              await api('/api/v1/tasks/vm-operations', 'POST', {{ task_type: 'vm.clone', vm_id: vmId, host_id: hostId }});
              loadVMs();
            }};
            document.getElementById('snapshotBtn').onclick = async () => {{
              const vmId = opVmId();
              if (!vmId) return alert('Provide VM ID');
              await api(`/api/v1/vms/${{vmId}}/snapshots`, 'POST', {{ host_id: hostId, name: document.getElementById('snapName').value || 'manual-snapshot' }});
              await api('/api/v1/tasks/vm-operations', 'POST', {{ task_type: 'vm.snapshot', vm_id: vmId, host_id: hostId }});
              loadVMs();
            }};
            document.getElementById('migrateBtn').onclick = async () => {{
              const vmId = opVmId();
              if (!vmId) return alert('Provide VM ID');
              const targetHost = document.getElementById('migHost').value.trim();
              if (!targetHost) return alert('Provide target host id');
              await api(`/api/v1/vms/${{vmId}}/migrate`, 'POST', {{ source_host_id: hostId, target_host_id: targetHost }});
              await api('/api/v1/tasks/vm-operations', 'POST', {{ task_type: 'vm.migrate', vm_id: vmId, host_id: hostId }});
              loadVMs();
            }};

            document.getElementById('attachNetBtn').onclick = async () => {{
              const vmId = opVmId();
              const networkId = document.getElementById('netId').value.trim();
              if (!vmId || !networkId) return alert('Provide VM ID and network ID');
              await api(`/api/v1/networks/${{networkId}}/attach`, 'POST', {{ host_id: hostId, vm_id: vmId }});
              await api('/api/v1/tasks/vm-operations', 'POST', {{ task_type: 'vm.network.attach', vm_id: vmId, host_id: hostId }});
              loadVMs();
            }};
            document.getElementById('detachNetBtn').onclick = async () => {{
              const vmId = opVmId();
              const networkId = document.getElementById('netId').value.trim();
              if (!vmId || !networkId) return alert('Provide VM ID and network ID');
              await api(`/api/v1/networks/${{networkId}}/detach`, 'POST', {{ host_id: hostId, vm_id: vmId }});
              await api('/api/v1/tasks/vm-operations', 'POST', {{ task_type: 'vm.network.detach', vm_id: vmId, host_id: hostId }});
              loadVMs();
            }};
            document.getElementById('revertSnapBtn').onclick = async () => {{
              const vmId = opVmId();
              const snapshotId = document.getElementById('snapId').value.trim();
              if (!vmId || !snapshotId) return alert('Provide VM ID and snapshot ID');
              await api(`/api/v1/vms/${{vmId}}/snapshots/${{snapshotId}}/revert`, 'POST', {{ host_id: hostId }});
              await api('/api/v1/tasks/vm-operations', 'POST', {{ task_type: 'vm.snapshot.revert', vm_id: vmId, host_id: hostId }});
              loadVMs();
            }};
            document.getElementById('deleteSnapBtn').onclick = async () => {{
              const vmId = opVmId();
              const snapshotId = document.getElementById('snapId').value.trim();
              if (!vmId || !snapshotId) return alert('Provide VM ID and snapshot ID');
              await api(`/api/v1/vms/${{vmId}}/snapshots/${{snapshotId}}?host_id=${{encodeURIComponent(hostId)}}`, 'DELETE');
              await api('/api/v1/tasks/vm-operations', 'POST', {{ task_type: 'vm.snapshot.delete', vm_id: vmId, host_id: hostId }});
              loadVMs();
            }};
            document.getElementById('deleteVmBtn').onclick = async () => {{
              const vmId = opVmId();
              if (!vmId) return alert('Provide VM ID');
              await deleteVm(vmId, hostId);
            }};
            document.getElementById('attachIsoBtn').onclick = async () => {{
              const vmId = opVmId();
              if (!vmId) return alert('Provide VM ID');
              await api(`/api/v1/vms/${{vmId}}/recovery/attach-iso`, 'POST', {{ host_id: hostId, iso_path: document.getElementById('isoPath').value, boot_once: true }});
              await api('/api/v1/tasks/vm-operations', 'POST', {{ task_type: 'vm.recovery.iso.attach', vm_id: vmId, host_id: hostId }});
              loadVMs();
            }};
            document.getElementById('detachIsoBtn').onclick = async () => {{
              const vmId = opVmId();
              if (!vmId) return alert('Provide VM ID');
              await api(`/api/v1/vms/${{vmId}}/recovery/detach-iso`, 'POST', {{ host_id: hostId }});
              await api('/api/v1/tasks/vm-operations', 'POST', {{ task_type: 'vm.recovery.iso.detach', vm_id: vmId, host_id: hostId }});
              loadVMs();
            }};

            bindSearch();
            bindHostSelector('vmHostSelect', loadVMs);
          }}

          window.vmPower = async (vmId, action, hostId) => {{
            try {{
              await api(`/api/v1/vms/${{vmId}}/action`, 'POST', {{ host_id: hostId, action }});
              await api('/api/v1/tasks/vm-operations', 'POST', {{ task_type: `vm.${{action}}`, vm_id: vmId, host_id: hostId }});
              loadVMs();
            }} catch (e) {{ setError(e); }}
          }};

          window.deleteVm = async (vmId, hostId) => {{
            try {{
              await api(`/api/v1/vms/${{vmId}}?host_id=${{encodeURIComponent(hostId)}}`, 'DELETE');
              await api('/api/v1/tasks/vm-operations', 'POST', {{ task_type: 'vm.delete', vm_id: vmId, host_id: hostId }});
              loadVMs();
            }} catch (e) {{ setError(e); }}
          }};

          window.viewAttach = async (vmId, hostId) => {{
            try {{
              const details = await api(`/api/v1/vms/${{vmId}}/attachments?host_id=${{encodeURIComponent(hostId)}}`);
              const att = details.attachments || {{}};
              const vm = details.vm || {{}};
              alert(`VM: ${{vmId}}
Image: ${{att.image?.name || 'n/a'}}
Networks: ${{(att.networks || []).map(n => n.name || n.network_id || '-').join(', ') || '-'}}
Snapshots: ${{(att.snapshots || []).length}}
Volumes: ${{(att.volumes || []).map(v => v.name).join(', ') || '-'}}
Recovery ISO: ${{vm.annotations?.['recovery.iso'] || 'not attached'}}`);
            }} catch (e) {{ setError(e); }}
          }};

          window.openConsole = async (vmId, hostId) => {{
            try {{
              const c = await api(`/api/v1/vms/${{vmId}}/console?host_id=${{encodeURIComponent(hostId)}}`);
              showConsole(c.noVNC_url, `Console · ${{vmId}}@${{hostId}}`);
            }} catch (e) {{ setError(e); }}
          }};

          async function loadStorage() {{
            const {{ hosts, hostId }} = await pickSelectedHostId();
            actions.innerHTML = `<strong>Storage actions</strong><div class='row'>${{renderHostSelector(hosts, hostId, 'storageHostSelect')}}</div><div class='muted'>Storage pools include qcow2 images and VM disks.</div>`;
            if (!hostId) {{ content.innerHTML = "<div class='muted'>No hosts registered yet.</div>"; return; }}
            const data = await api(`/api/v1/hosts/${{hostId}}/storage-pools`);
            const rows = [];
            (data.storage_pools || []).forEach(pool => {{
              rows.push([pool.name, pool.type, pool.state, pool.capacity_gb, pool.allocated_gb, pool.available_gb]);
              (pool.volumes || []).forEach(v => rows.push([`↳ ${{v.name}}`, v.kind, v.used_by, v.size_gb, '-', '-']));
            }});
            content.innerHTML = `<strong>Storage pools and volumes</strong>${{table(['Name','Type/Kind','State/Used by','Capacity GB','Allocated GB','Available GB'], rows)}}`;
            bindSearch();
            bindHostSelector('storageHostSelect', loadStorage);
          }}

          async function loadNetworks() {{
            const {{ hosts, hostId }} = await pickSelectedHostId();
            actions.innerHTML = `<strong>Network actions</strong><div class='row'>${{renderHostSelector(hosts, hostId, 'networkHostSelect')}}</div><div class='row'><input id='netName' placeholder='network name' /><input id='netCidr' placeholder='10.10.0.0/24' /><input id='netVlan' type='number' placeholder='vlan' style='width:90px' /><button class='btn' id='createNetBtn'>Create network</button></div><div class='row'><select id='advSection'><option value='vlan_trunks'>VLAN trunking</option><option value='bridge_automation'>Bridge automation</option><option value='ipam'>IPAM</option><option value='security_policies'>Security policy</option></select><input id='advName' placeholder='name/description' /><button class='btn' id='addAdvNetBtn'>Add advanced policy</button></div>`;
            if (!hostId) {{ content.innerHTML = "<div class='muted'>No hosts registered yet.</div>"; return; }}
            const data = await api(`/api/v1/hosts/${{hostId}}/networks`);
            const adv = await api('/api/v1/networks/advanced');
            const rows = (data.networks || []).map(n => [n.name, n.cidr, n.vlan_id ?? '-', (n.attached_vm_ids || []).join(', ') || '-']);
            (adv.vlan_trunks || []).forEach(item => rows.push([`ADV::${{item.name || item.id}}`, 'trunk', item.id, '-']));
            (adv.bridge_automation || []).forEach(item => rows.push([`ADV::${{item.name || item.id}}`, 'bridge', item.id, '-']));
            (adv.ipam || []).forEach(item => rows.push([`ADV::${{item.name || item.id}}`, 'ipam', item.id, '-']));
            (adv.security_policies || []).forEach(item => rows.push([`ADV::${{item.name || item.id}}`, 'security', item.id, '-']));
            content.innerHTML = `<strong>Virtual and advanced networks</strong>${{table(['Name','CIDR/Type','VLAN/ID','Attached VMs'], rows)}}`;
            document.getElementById('createNetBtn').onclick = async () => {{
              await api('/api/v1/networks', 'POST', {{ host_id: hostId, name: document.getElementById('netName').value, cidr: document.getElementById('netCidr').value, vlan_id: Number(document.getElementById('netVlan').value) || null }});
              loadNetworks();
            }};
            document.getElementById('addAdvNetBtn').onclick = async () => {{
              const section = document.getElementById('advSection').value;
              const name = document.getElementById('advName').value;
              await api(`/api/v1/networks/advanced/${{section}}`, 'POST', {{ name }});
              loadNetworks();
            }};
            bindSearch();
            bindHostSelector('networkHostSelect', loadNetworks);
          }}

          async function loadImages() {{
            const {{ hosts, hostId }} = await pickSelectedHostId();
            actions.innerHTML = `<strong>Image actions</strong><div class='row'>${{renderHostSelector(hosts, hostId, 'imageHostSelect')}}</div><div class='row'><input id='imgName' placeholder='image name' /><input id='imgSrc' placeholder='https://.../image.qcow2' style='min-width:280px'/><button class='btn' id='createImgBtn'>Create image</button><button class='btn' id='importImgBtn'>Import image pipeline</button></div><div class='row'><input id='depImgId' placeholder='image id' /><input id='depVmName' placeholder='target vm name' /><button class='btn' id='deployImgBtn'>Deploy image</button></div>`;
            if (!hostId) {{ content.innerHTML = "<div class='muted'>No hosts registered yet.</div>"; return; }}
            const data = await api(`/api/v1/hosts/${{hostId}}/images`);
            const deployments = await api('/api/v1/images/deployments');
            const rows = (data.images || []).map(i => [i.image_id || '-', i.name, i.status, i.source_url, i.created_at]);
            (deployments.items || []).forEach(d => rows.push([d.image_id, `DEPLOY::${{d.vm_name}}`, d.status, d.host_id, d.created_at]));
            content.innerHTML = `<strong>qcow2 image catalog + deployments</strong>${{table(['Image ID','Name','Status','Source/Host','Created at'], rows)}}`;
            document.getElementById('createImgBtn').onclick = async () => {{
              await api('/api/v1/images', 'POST', {{ host_id: hostId, name: document.getElementById('imgName').value, source_url: document.getElementById('imgSrc').value }});
              loadImages();
            }};
            document.getElementById('importImgBtn').onclick = async () => {{
              await api('/api/v1/images/import', 'POST', {{ host_id: hostId, name: document.getElementById('imgName').value, source_url: document.getElementById('imgSrc').value }});
              loadImages();
            }};
            document.getElementById('deployImgBtn').onclick = async () => {{
              await api(`/api/v1/images/${{document.getElementById('depImgId').value}}/deploy?host_id=${{encodeURIComponent(hostId)}}&vm_name=${{encodeURIComponent(document.getElementById('depVmName').value)}}`, 'POST');
              loadImages();
            }};
            bindSearch();
            bindHostSelector('imageHostSelect', loadImages);
          }}

          async function loadConsole() {{
            const {{ hosts, hostId }} = await pickSelectedHostId();
            actions.innerHTML = `<strong>Console options</strong><div class='row'>${{renderHostSelector(hosts, hostId, 'consoleHostSelect')}}</div><div class='muted'>Use the VMs page “Console” action or request here manually.</div><div class='row'><input id='conVm' placeholder='vm id'/><button class='btn' id='conBtn'>Create console ticket</button></div>`;
            const sess = await api('/api/v1/console/sessions');
            const novnc = await api('/api/v1/console/novnc/status');
            const rows = (sess.items || []).map(s => [
              s.session_id,
              s.host_id,
              s.vm_id,
              s.created_at,
              `<button class='btn' onclick="showConsole('${{(s.novnc_url || '').replace(/'/g, "\\'")}}','Console · ${{s.vm_id}}@${{s.host_id}}')">Open</button>`
            ]);
            rows.unshift(['noVNC base', '-', novnc.novnc_base_url, `ws:${{novnc.novnc_ws_base}}`, '-']);
            content.innerHTML = `<strong>Console sessions + noVNC status</strong>${{table(['Session','Host','VM','Created/Path','Action'], rows)}}`;
            document.getElementById('conBtn').onclick = async () => {{
              if (!hostId) return;
              const vmId = document.getElementById('conVm').value;
              const t = await api(`/api/v1/vms/${{vmId}}/console?host_id=${{encodeURIComponent(hostId)}}`);
              showConsole(t.noVNC_url, `Console · ${{vmId}}@${{hostId}}`);
            }};
            bindSearch();
            bindHostSelector('consoleHostSelect', loadConsole);
          }}

          async function loadEvents() {{
            actions.innerHTML = `<strong>Event filters</strong><div class='row'><input id='etype' placeholder='event type'/><button class='btn' id='fEvt'>Apply filter</button></div>`;
            const events = await api('/api/v1/events');
            const render = (items) => {{
              const rows = items.map(e => [e.type, e.message, e.created_at]);
              content.innerHTML = `<strong>Events</strong>${{table(['Type','Message','Created'], rows)}}`;
              bindSearch();
            }};
            render(events);
            document.getElementById('fEvt').onclick = async () => {{
              const t = document.getElementById('etype').value.trim();
              const data = await api('/api/v1/events' + (t ? `?event_type=${{encodeURIComponent(t)}}` : ''));
              render(data);
            }};
          }}

          async function loadTasks() {{
            actions.innerHTML = `<strong>Task operations</strong>
              <div class='row'>
                <input id='taskVm' placeholder='vm id (optional)' />
                <input id='taskHost' placeholder='host id (optional)' />
                <select id='taskType'>
                  <option value='vm.power_cycle'>VM power cycle</option>
                  <option value='vm.snapshot'>VM snapshot</option>
                  <option value='vm.clone'>VM clone</option>
                  <option value='vm.migrate'>VM migrate</option>
                  <option value='vm.resize'>VM resize</option>
                  <option value='vm.backup'>VM backup</option>
                </select>
                <button class='btn' id='createTaskBtn'>Create Task</button>
              </div>
              <div class='muted'>Realtime operations queue for day-2 virtualization tasks.</div>`;
            const tasks = await api('/api/v1/tasks');
            const rows = tasks.map(t => [t.task_id, t.task_type, t.status, t.target, t.detail, `<button class='btn' onclick="retryTask('${{t.task_id}}')">Retry</button>`]);
            content.innerHTML = `<strong>Tasks</strong>${{table(['Task ID','Type','Status','Target','Detail','Action'], rows)}}`;
            document.getElementById('createTaskBtn').onclick = async () => {{
              const payload = {{
                task_type: document.getElementById('taskType').value,
                vm_id: document.getElementById('taskVm').value || null,
                host_id: document.getElementById('taskHost').value || null,
              }};
              await api('/api/v1/tasks/vm-operations', 'POST', payload);
              loadTasks();
            }};
            bindSearch();
          }}

          window.retryTask = async (taskId) => {{
            await api(`/api/v1/tasks/${{taskId}}/retry`, 'POST');
            loadTasks();
          }};


          async function loadPolicies() {{
            actions.innerHTML = `<strong>Policy operations</strong><div class='row'><input id='polName' placeholder='policy name'/><input id='polActions' placeholder='deny actions comma-separated'/><button class='btn' id='savePolBtn'>Save VM lifecycle policy</button></div>`;
            const data = await api('/api/v1/policies/vm-lifecycle');
            const rows = (data.items || []).map(p => [p.name, JSON.stringify(p.spec || {{}}), p.updated_at]);
            content.innerHTML = `<strong>VM lifecycle policies</strong>${{table(['Name','Spec','Updated'], rows)}}`;
            document.getElementById('savePolBtn').onclick = async () => {{
              const name = document.getElementById('polName').value || 'default';
              const deny = document.getElementById('polActions').value;
              await api('/api/v1/policies/vm-lifecycle', 'POST', {{ name, spec: {{ deny_actions: deny }} }});
              loadPolicies();
            }};
            bindSearch();
          }}

          async function loadSimple(path, title, cols, mapper) {{
            actions.innerHTML = `<strong>${{title}}</strong>`;
            const data = await api(path);
            const rows = mapper(data);
            content.innerHTML = `<strong>${{title}}</strong>${{table(cols, rows)}}`;
            bindSearch();
          }}

          const loaders = {{
            dashboard: loadOverview,
            vms: loadVMs,
            storage: loadStorage,
            networks: loadNetworks,
            images: loadImages,
            console: loadConsole,
            events: loadEvents,
            tasks: loadTasks,
            projects: () => loadSimple('/api/v1/projects', 'Projects', ['Project','Description','CPU quota','Memory quota','VM limit'], d => d.map(p => [p.name,p.description,p.cpu_cores_quota,p.memory_mb_quota,p.vm_limit])),
            policies: loadPolicies,
          }};

          let refreshTimer = null;
          const realtimePages = new Set(['dashboard','vms','storage','networks','images','console','events','tasks']);

          function updateRealtimeStatus(msg) {{
            const el = document.getElementById('realtimeStatus');
            if (el) el.textContent = msg;
          }}

          function userEditing() {{
            const active = document.activeElement;
            if (!active) return false;
            return ['INPUT', 'TEXTAREA', 'SELECT'].includes(active.tagName);
          }}

          async function refreshPage() {{
            const loader = loaders[key];
            if (!loader) return;
            if (userEditing()) {{
              updateRealtimeStatus(`Realtime refresh: paused while editing · ${{new Date().toLocaleTimeString()}}`);
              return;
            }}
            await loader();
            updateRealtimeStatus(`Realtime refresh: active · ${{new Date().toLocaleTimeString()}}`);
          }}

          function startAutoRefresh() {{
            if (!realtimePages.has(key)) {{
              updateRealtimeStatus('Realtime refresh: not required on this page');
              return;
            }}
            if (refreshTimer) clearInterval(refreshTimer);
            const intervalMs = key === 'tasks' ? 5000 : (key === 'console' ? 20000 : 10000);
            refreshTimer = setInterval(async () => {{
              try {{
                if (document.hidden) return;
                await refreshPage();
              }} catch (err) {{
                setError(err);
              }}
            }}, intervalMs);
          }}

          async function boot() {{
            const closeBtn = document.getElementById('consoleCloseBtn');
            const popBtn = document.getElementById('consolePopoutBtn');
            const modal = document.getElementById('consoleModal');
            if (closeBtn) closeBtn.onclick = closeConsole;
            if (modal) modal.onclick = (e) => {{ if (e.target === modal) closeConsole(); }};
            if (popBtn) popBtn.onclick = () => {{ if (consoleLastUrl) window.open(consoleLastUrl, '_blank'); }};
            try {{
              await refreshPage();
              startAutoRefresh();
            }} catch (err) {{ setError(err); }}
          }}

          boot();
        </script>
      </body>
    </html>
    """
