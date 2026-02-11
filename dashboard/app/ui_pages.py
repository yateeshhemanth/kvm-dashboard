from __future__ import annotations

from typing import Any


NAV_ITEMS = [
    ("dashboard", "Overview", "/dashboard"),
    ("vms", "VMs", "/vms"),
    ("storage", "Storage", "/storage"),
    ("console", "Console", "/console"),
    ("networks", "Networks", "/networks"),
    ("images", "Images", "/images"),
    ("projects", "Projects", "/projects"),
    ("policies", "Policies", "/policies"),
    ("events", "Events", "/events"),
    ("tasks", "Tasks", "/tasks"),
]

PAGE_CONFIG: dict[str, dict[str, str]] = {
    "dashboard": {"title": "Platform Overview", "description": "Cluster summary and routing diagnostics."},
    "vms": {"title": "Virtual Machines", "description": "Host-scoped VM inventory and lifecycle visibility.", "api": "/api/v1/hosts/{host_id}/vms"},
    "storage": {"title": "Storage", "description": "Image catalog + import pipeline status.", "api": "/api/v1/images/import-jobs"},
    "console": {"title": "Console", "description": "noVNC tickets and console workflow visibility.", "api": "/api/v1/console/sessions"},
    "networks": {"title": "Networks", "description": "Host-scoped network inventory.", "api": "/api/v1/hosts/{host_id}/networks"},
    "images": {"title": "Images", "description": "qcow2 image catalog by host.", "api": "/api/v1/hosts/{host_id}/images"},
    "projects": {"title": "Projects", "description": "Tenancy, quotas, and memberships.", "api": "/api/v1/projects"},
    "policies": {"title": "Policies", "description": "Policy catalog and bindings.", "api": "/api/v1/policies"},
    "events": {"title": "Events", "description": "Operational timeline with filters.", "api": "/api/v1/events"},
    "tasks": {"title": "Tasks", "description": "Execution and automation task history.", "api": "/api/v1/tasks"},
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
    nav_html = "".join(
        f"<a class='nav-link {'active' if key == page_key else ''}' href='{_with_base(base_path, path)}'>{label}</a>"
        for key, label, path in NAV_ITEMS
    )
    diagnostics_html = "".join(f"<li><strong>{label}:</strong> {value}</li>" for label, value in diagnostics)

    return f"""
    <!doctype html>
    <html>
      <head>
        <meta charset='utf-8' />
        <meta name='viewport' content='width=device-width, initial-scale=1' />
        <title>KVM Dashboard - {config['title']}</title>
        <style>
          :root {{ color-scheme: dark; --bg: #0b1020; --panel: #121a33; --muted: #8ea0c9; --text: #e6ecff; --border: #23325f; }}
          body {{ margin: 0; font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif; background: radial-gradient(circle at 10% 10%, #172345, var(--bg)); color: var(--text); }}
          .layout {{ display: grid; grid-template-columns: 250px 1fr; min-height: 100vh; }}
          .sidebar {{ border-right: 1px solid var(--border); padding: 16px; background: #0c1430; }}
          .brand {{ font-size: 20px; font-weight: 700; margin-bottom: 8px; }}
          .pill {{ display:inline-block; background:#1f2f5f; border:1px solid #385aa8; border-radius:999px; padding:4px 10px; font-size:12px; color:#cfe0ff; margin-bottom: 14px; }}
          .nav {{ display:flex; flex-direction:column; gap:8px; }}
          .nav-link {{ color:#c9d5f7; text-decoration:none; padding:8px 10px; border-radius:8px; border:1px solid transparent; }}
          .nav-link:hover, .nav-link.active {{ background:#15244c; border-color:#3552a3; }}
          .content {{ padding: 22px; }}
          .cards {{ display:grid; grid-template-columns: repeat(auto-fit,minmax(200px,1fr)); gap:12px; margin-bottom:16px; }}
          .card {{ background: var(--panel); border:1px solid var(--border); border-radius:12px; padding:12px; }}
          .muted {{ color: var(--muted); }}
          ul {{ margin: 0; padding-left: 18px; }}
          #data pre {{ white-space: pre-wrap; word-wrap: break-word; font-size: 12px; color:#d9e3ff; }}
        </style>
      </head>
      <body>
        <div class='layout'>
          <aside class='sidebar'>
            <div class='brand'>KVM Dashboard</div>
            <div class='pill'>base: {base_path or '/'}</div>
            <nav class='nav'>{nav_html}</nav>
          </aside>
          <main class='content'>
            <h1>{config['title']}</h1>
            <p class='muted'>{config['description']}</p>
            <div class='cards'>
              <div class='card'><strong>Hosts</strong><div>{stats['hosts']}</div></div>
              <div class='card'><strong>Ready</strong><div>{stats['ready_hosts']}</div></div>
              <div class='card'><strong>Projects</strong><div>{stats['projects']}</div></div>
              <div class='card'><strong>Policies</strong><div>{stats['policies']}</div></div>
            </div>
            <div class='card' id='data'><strong>Live data</strong><pre>Loading...</pre></div>
            <div class='card' style='margin-top:12px'><strong>Diagnostics</strong><ul>{diagnostics_html}</ul></div>
          </main>
        </div>
        <script>
          async function loadData() {{
            const key = {page_key!r};
            const base = {base_path!r};
            const cfg = {PAGE_CONFIG!r};
            if (!cfg[key].api) {{
              document.querySelector('#data pre').textContent = JSON.stringify({stats!r}, null, 2);
              return;
            }}
            let api = cfg[key].api;
            if (api.includes('{{host_id}}')) {{
              const hostsRes = await fetch((base || '') + '/api/v1/hosts');
              const hosts = await hostsRes.json();
              const hostId = hosts[0]?.host_id;
              if (!hostId) {{
                document.querySelector('#data pre').textContent = 'No hosts registered yet.';
                return;
              }}
              api = api.replace('{{host_id}}', hostId);
            }}
            const res = await fetch((base || '') + api);
            const body = await res.json();
            document.querySelector('#data pre').textContent = JSON.stringify(body, null, 2);
          }}
          loadData().catch((err) => {{
            document.querySelector('#data pre').textContent = 'Failed to load: ' + err;
          }});
        </script>
      </body>
    </html>
    """
