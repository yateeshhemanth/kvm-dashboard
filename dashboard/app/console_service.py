from __future__ import annotations

from urllib.parse import urlencode, urlparse
from uuid import uuid4


def _display_host_port(display_uri: str) -> tuple[str | None, int | None]:
    try:
        parsed = urlparse(display_uri)
    except Exception:
        return None, None
    if parsed.hostname and parsed.port:
        return parsed.hostname, parsed.port
    return None, None


def build_console_urls(
    *,
    novnc_base_url: str,
    novnc_ws_base: str,
    host_id: str,
    vm_id: str,
    host_address: str,
    display_uri: str,
) -> tuple[str, str, dict[str, str]]:
    ticket = str(uuid4())
    display_host, display_port = _display_host_port(display_uri)
    effective_host = host_address if display_host in {None, "127.0.0.1", "::1", "localhost"} else display_host

    ws_query = {"host_id": host_id, "vm_id": vm_id, "ticket": ticket}
    if effective_host and display_port:
        ws_query.update({"vnc_host": effective_host, "vnc_port": str(display_port)})

    ws_url = f"{novnc_ws_base}?{urlencode(ws_query)}"
    viewer_query = {
        "host_id": host_id,
        "vm_id": vm_id,
        "ticket": ticket,
        "path": ws_url,
        "autoconnect": 1,
        "resize": "remote",
    }
    if effective_host and display_port:
        viewer_query.update({"host": effective_host, "port": str(display_port)})

    novnc_url = f"{novnc_base_url}?{urlencode(viewer_query)}"
    metadata = {
        "ticket": ticket,
        "vnc_host": effective_host or "",
        "vnc_port": str(display_port or ""),
    }
    return ticket, novnc_url, metadata
