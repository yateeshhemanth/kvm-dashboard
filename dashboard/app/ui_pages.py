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
    diagnostics: list[tuple[str, str]],
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

    diagnostics_html = "".join(f"<li><strong>{label}:</strong> {value}</li>" for label, value in diagnostics)

    return f"""
    <!doctype html>
    <html>
      <head>
        <meta charset='utf-8' />
        <meta name='viewport' content='width=device-width, initial-scale=1' />
        <title>KVM Dashboard - {config['title']}</title>
        <style>
          :root {{ color-scheme: dark; --bg: #0b1020; --panel: #121a33; --muted: #8ea0c9; --text: #e6ecff; --border: #23325f; --primary:#2484ff; --ok:#23c552; --warn:#f5a524; --danger:#f31260; }}
          body {{ margin: 0; font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif; background: radial-gradient(circle at 10% 10%, #172345, var(--bg)); color: var(--text); }}
          .layout {{ display:grid; grid-template-columns:270px 1fr; min-height:100vh; }}
          .sidebar {{ border-right:1px solid var(--border); padding:16px; background:#0c1430; }}
          .brand {{ font-size:20px; font-weight:700; }}
          .sub {{ color:var(--muted); font-size:12px; margin:6px 0 12px; }}
          .nav-group {{ margin-bottom:14px; }}
          .nav-title {{ color:var(--muted); font-size:11px; text-transform:uppercase; margin-bottom:6px; }}
          .nav-link {{ display:block; color:#c9d5f7; text-decoration:none; padding:8px 10px; border-radius:8px; border:1px solid transparent; margin-bottom:6px; }}
          .nav-link.active,.nav-link:hover {{ background:#15244c; border-color:#3552a3; }}
          .content {{ padding:20px; }}
          .toolbar {{ display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:14px; }}
          .search {{ background:#0f1a3b; border:1px solid #32498d; color:#dce7ff; border-radius:8px; padding:8px 10px; min-width:260px; }}
          .cards {{ display:grid; grid-template-columns: repeat(auto-fit,minmax(170px,1fr)); gap:12px; margin-bottom:14px; }}
          .card {{ background:var(--panel); border:1px solid var(--border); border-radius:12px; padding:12px; }}
          .muted {{ color:var(--muted); }}
          .btn {{ border:1px solid #2f5dad; background:#123777; color:#e8f2ff; padding:6px 10px; border-radius:8px; cursor:pointer; }}
          .btn.danger {{ border-color:#7e294f; background:#57243d; }}
          .btn.warn {{ border-color:#8c5e1c; background:#6b4a1d; }}
          .row {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:8px; }}
          input, select {{ background:#0f1a3b; border:1px solid #2a447f; color:#dce7ff; border-radius:8px; padding:7px 9px; }}
          table {{ width:100%; border-collapse:collapse; margin-top:8px; }}
          th, td {{ border-bottom:1px solid #22325c; padding:8px; text-align:left; font-size:13px; }}
          .pill {{ border-radius:999px; padding:2px 8px; font-size:11px; }}
          .pill.running {{ background: rgba(35,197,82,.2); color:#7ef5a7; }}
          .pill.stopped {{ background: rgba(122,130,148,.2); color:#b6c0d4; }}
          .pill.paused {{ background: rgba(245,165,36,.2); color:#ffd277; }}
          .error {{ color:#ff9cbc; }}
        </style>
      </head>
      <body>
        <div class='layout'>
          <aside class='sidebar'>
            <div class='brand'>KVM Dashboard</div>
            <div class='sub'>OpenShift-inspired operations view</div>
            {nav_html}
          </aside>
          <main class='content'>
            <div class='toolbar'>
              <div><h1 style='margin:0'>{config['title']}</h1><div class='muted'>{config['description']}</div></div>
              <input id='search' class='search' placeholder='Filter table rows...' />
            </div>
            <div class='cards'>
              <div class='card'><strong>Hosts</strong><div>{stats['hosts']}</div></div>
              <div class='card'><strong>Ready</strong><div>{stats['ready_hosts']}</div></div>
              <div class='card'><strong>Projects</strong><div>{stats['projects']}</div></div>
              <div class='card'><strong>Policies</strong><div>{stats['policies']}</div></div>
            </div>
            <div class='card' id='actions'></div>
            <div class='card' style='margin-top:12px' id='content'></div>
            <div class='card' style='margin-top:12px'><strong>Platform Status</strong><ul>{diagnostics_html}</ul></div>
          </main>
        </div>
        <script>
          const key = {page_key!r};
          const base = {base_path!r};
          const content = document.getElementById('content');
          const actions = document.getElementById('actions');
          const searchInput = document.getElementById('search');
          let currentRows = [];

          async function api(path, method='GET', body=null) {{
            const resp = await fetch((base || '') + path, {{
              method,
              headers: {{ 'Content-Type': 'application/json' }},
              body: body ? JSON.stringify(body) : null,
            }});
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.detail || 'Request failed');
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
            const rows = [
              ['Hosts total', ov.hosts.total, 'Ready', ov.hosts.ready],
              ['CPU cores', ov.hosts.total_cpu_cores, 'Memory MB', ov.hosts.total_memory_mb],
              ['Projects', ov.projects.total, 'Policies', ov.policies.total],
              ['Events', ov.events.total, 'Tasks', ov.tasks.total],
            ];
            content.innerHTML = `<strong>Cluster summary</strong>${{table(['Metric','Value','Metric','Value'], rows)}}`;
            bindSearch();
          }}

          async function loadVMs() {{
            const {{ hosts, hostId }} = await pickSelectedHostId();
            actions.innerHTML = `<strong>VM operations</strong>
              <div class='row'>${{renderHostSelector(hosts, hostId, 'vmHostSelect')}}</div>
              <div class='row'>
                <input id='vmName' placeholder='VM name' />
                <input id='vmCpu' type='number' value='2' min='1' style='width:80px' />
                <input id='vmMem' type='number' value='2048' min='512' style='width:100px' />
                <input id='vmImage' placeholder='qcow2 image' value='base.qcow2' />
                <button class='btn' id='createVmBtn'>Create VM</button>
              </div>
              <div class='row'>
                <input id='impVmId' placeholder='Import VM ID' />
                <input id='impVmName' placeholder='Import VM name' />
                <button class='btn' id='importVmBtn'>Import VM</button>
              </div>
              <div class='muted'>All VM state, attachments, qcow2 mapping, and snapshots are loaded from live APIs.</div>`;
            if (!hostId) {{
              content.innerHTML = "<div class='muted'>No hosts registered yet.</div>";
              return;
            }}
            const live = await api(`/api/v1/hosts/${{hostId}}/inventory-live`);
            const rows = (live.vms || []).map(vm => {{
              const att = (live.attachments || {{}})[vm.vm_id] || {{}};
              const snaps = (att.snapshots || []).length;
              return [
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
                 <button class='btn' onclick="viewAttach('${{vm.vm_id}}','${{hostId}}')">Attachments</button>`
              ];
            }});
            content.innerHTML = `<strong>VM inventory (live)</strong>${{table(['Name','Image','CPU','Memory MB','State','Networks','Snapshots','Actions'], rows)}}`;
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
            bindSearch();
            bindHostSelector('vmHostSelect', loadVMs);
          }}

          window.vmPower = async (vmId, action, hostId) => {{
            try {{
              await api(`/api/v1/vms/${{vmId}}/action`, 'POST', {{ host_id: hostId, action }});
              loadVMs();
            }} catch (e) {{ setError(e); }}
          }};

          window.viewAttach = async (vmId, hostId) => {{
            try {{
              const details = await api(`/api/v1/vms/${{vmId}}/attachments?host_id=${{encodeURIComponent(hostId)}}`);
              const att = details.attachments || {{}};
              alert(`VM: ${{vmId}}
Image: ${{att.image?.name || 'n/a'}}
Networks: ${{(att.networks || []).map(n => n.name || n.network_id || '-').join(', ') || '-'}}
Snapshots: ${{(att.snapshots || []).length}}
Volumes: ${{(att.volumes || []).map(v => v.name).join(', ') || '-'}}`);
            }} catch (e) {{ setError(e); }}
          }};

          window.openConsole = async (vmId, hostId) => {{
            try {{
              const c = await api(`/api/v1/vms/${{vmId}}/console?host_id=${{encodeURIComponent(hostId)}}`);
              window.open(c.noVNC_url, '_blank');
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
            actions.innerHTML = `<strong>Network actions</strong><div class='row'>${{renderHostSelector(hosts, hostId, 'networkHostSelect')}}</div><div class='row'><input id='netName' placeholder='network name' /><input id='netCidr' placeholder='10.10.0.0/24' /><input id='netVlan' type='number' placeholder='vlan' style='width:90px' /><button class='btn' id='createNetBtn'>Create network</button></div>`;
            if (!hostId) {{ content.innerHTML = "<div class='muted'>No hosts registered yet.</div>"; return; }}
            const data = await api(`/api/v1/hosts/${{hostId}}/networks`);
            const rows = (data.networks || []).map(n => [n.name, n.cidr, n.vlan_id ?? '-', (n.attached_vm_ids || []).join(', ') || '-']);
            content.innerHTML = `<strong>Virtual networks</strong>${{table(['Name','CIDR','VLAN','Attached VMs'], rows)}}`;
            document.getElementById('createNetBtn').onclick = async () => {{
              await api('/api/v1/networks', 'POST', {{ host_id: hostId, name: document.getElementById('netName').value, cidr: document.getElementById('netCidr').value, vlan_id: Number(document.getElementById('netVlan').value) || null }});
              loadNetworks();
            }};
            bindSearch();
            bindHostSelector('networkHostSelect', loadNetworks);
          }}

          async function loadImages() {{
            const {{ hosts, hostId }} = await pickSelectedHostId();
            actions.innerHTML = `<strong>Image actions</strong><div class='row'>${{renderHostSelector(hosts, hostId, 'imageHostSelect')}}</div><div class='row'><input id='imgName' placeholder='image name' /><input id='imgSrc' placeholder='https://.../image.qcow2' style='min-width:280px'/><button class='btn' id='createImgBtn'>Create image</button><button class='btn' id='importImgBtn'>Import image pipeline</button></div>`;
            if (!hostId) {{ content.innerHTML = "<div class='muted'>No hosts registered yet.</div>"; return; }}
            const data = await api(`/api/v1/hosts/${{hostId}}/images`);
            const rows = (data.images || []).map(i => [i.name, i.status, i.source_url, i.created_at]);
            content.innerHTML = `<strong>qcow2 image catalog</strong>${{table(['Name','Status','Source','Created at'], rows)}}`;
            document.getElementById('createImgBtn').onclick = async () => {{
              await api('/api/v1/images', 'POST', {{ host_id: hostId, name: document.getElementById('imgName').value, source_url: document.getElementById('imgSrc').value }});
              loadImages();
            }};
            document.getElementById('importImgBtn').onclick = async () => {{
              await api('/api/v1/images/import', 'POST', {{ host_id: hostId, name: document.getElementById('imgName').value, source_url: document.getElementById('imgSrc').value }});
              loadImages();
            }};
            bindSearch();
            bindHostSelector('imageHostSelect', loadImages);
          }}

          async function loadConsole() {{
            const {{ hosts, hostId }} = await pickSelectedHostId();
            actions.innerHTML = `<strong>Console options</strong><div class='row'>${{renderHostSelector(hosts, hostId, 'consoleHostSelect')}}</div><div class='muted'>Use the VMs page “Console” action or request here manually.</div><div class='row'><input id='conVm' placeholder='vm id'/><button class='btn' id='conBtn'>Create console ticket</button></div>`;
            const sess = await api('/api/v1/console/sessions');
            const rows = (sess.items || []).map(s => [s.session_id, s.host_id, s.vm_id, s.created_at]);
            content.innerHTML = `<strong>Console sessions</strong>${{table(['Session','Host','VM','Created'], rows)}}`;
            document.getElementById('conBtn').onclick = async () => {{
              if (!hostId) return;
              const vmId = document.getElementById('conVm').value;
              const t = await api(`/api/v1/vms/${{vmId}}/console?host_id=${{encodeURIComponent(hostId)}}`);
              window.open(t.noVNC_url, '_blank');
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
            actions.innerHTML = `<strong>Task operations</strong><div class='muted'>Retry any task from the list.</div>`;
            const tasks = await api('/api/v1/tasks');
            const rows = tasks.map(t => [t.task_id, t.task_type, t.status, t.target, `<button class='btn' onclick="retryTask('${{t.task_id}}')">Retry</button>`]);
            content.innerHTML = `<strong>Tasks</strong>${{table(['Task ID','Type','Status','Target','Action'], rows)}}`;
            bindSearch();
          }}

          window.retryTask = async (taskId) => {{
            await api(`/api/v1/tasks/${{taskId}}/retry`, 'POST');
            loadTasks();
          }};

          async function loadSimple(path, title, cols, mapper) {{
            actions.innerHTML = `<strong>${{title}}</strong>`;
            const data = await api(path);
            const rows = mapper(data);
            content.innerHTML = `<strong>${{title}}</strong>${{table(cols, rows)}}`;
            bindSearch();
          }}

          async function boot() {{
            try {{
              if (key === 'dashboard') return loadOverview();
              if (key === 'vms') return loadVMs();
              if (key === 'storage') return loadStorage();
              if (key === 'networks') return loadNetworks();
              if (key === 'images') return loadImages();
              if (key === 'console') return loadConsole();
              if (key === 'events') return loadEvents();
              if (key === 'tasks') return loadTasks();
              if (key === 'projects') return loadSimple('/api/v1/projects', 'Projects', ['Project','Description','CPU quota','Memory quota','VM limit'], d => d.map(p => [p.name,p.description,p.cpu_cores_quota,p.memory_mb_quota,p.vm_limit]));
              if (key === 'policies') return loadSimple('/api/v1/policies', 'Policies', ['Name','Category','Created'], d => d.map(p => [p.name,p.category,p.created_at]));
            }} catch (err) {{ setError(err); }}
          }}

          boot();
        </script>
      </body>
    </html>
    """
