import os
import socket
from dataclasses import dataclass


@dataclass
class AgentConfig:
    dashboard_url: str
    host_id: str
    host_name: str
    host_address: str
    libvirt_uri: str
    interval_seconds: int = 15


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
