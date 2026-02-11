import os
import threading
from datetime import datetime, timezone

import requests

from .config import AgentConfig
from .state import AgentState


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


def push_to_dashboard(config: AgentConfig, state: AgentState) -> None:
    cpu_cores, memory_mb = detect_cpu_memory()
    register(config, cpu_cores, memory_mb)
    send_heartbeat(config, cpu_cores, memory_mb)

    with state.lock:
        state.last_push_ok = True
        state.last_error = None
        state.push_count += 1
        state.last_push_at = datetime.now(timezone.utc).isoformat()


def heartbeat_loop(config: AgentConfig, state: AgentState, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            push_to_dashboard(config, state)
            print(f"heartbeat sent for {config.host_id}")
        except requests.RequestException as exc:
            with state.lock:
                state.last_push_ok = False
                state.last_error = str(exc)
                state.last_push_at = datetime.now(timezone.utc).isoformat()
            print(f"agent warning: {exc}")

        stop_event.wait(config.interval_seconds)
