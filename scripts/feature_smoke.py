from __future__ import annotations

import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("ALLOW_SQLITE_FOR_TESTS", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:///./feature_smoke.db")

from fastapi.testclient import TestClient

from dashboard.app.main import app
from dashboard.app.db import init_db


@dataclass
class FakeResp:
    payload: object
    status_code: int = 200

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http error {self.status_code}")

    def json(self):
        return self.payload




def fake_libvirt_call(host, fn_name, *args):
    if fn_name == 'health':
        return {'reachable': True, 'vm_count': len(STATE['vms'])}
    if fn_name == 'list_vms':
        return list(STATE['vms'].values())
    if fn_name == 'vm_action':
        vm_id, action = args
        vm = STATE['vms'][vm_id]
        vm['power_state'] = 'running' if action in {'start','resume','reboot'} else ('paused' if action == 'pause' else 'stopped')
        return None
    if fn_name == 'resize':
        vm_id, cpu, mem = args
        vm = STATE['vms'][vm_id]
        vm['cpu_cores'] = cpu
        vm['memory_mb'] = mem
        return None
    if fn_name == 'delete_vm':
        vm_id = args[0]
        STATE['vms'].pop(vm_id, None)
        return None
    if fn_name == 'snapshot_create':
        vm_id, name = args
        snap = {'snapshot_id': name, 'vm_id': vm_id, 'name': name, 'created_at': 'now'}
        STATE['snapshots'].setdefault(vm_id, []).append(snap)
        return snap
    if fn_name == 'snapshot_list':
        vm_id = args[0]
        return STATE['snapshots'].get(vm_id, [])
    if fn_name == 'snapshot_revert':
        return None
    if fn_name == 'snapshot_delete':
        vm_id, snap_id = args
        STATE['snapshots'][vm_id] = [s for s in STATE['snapshots'].get(vm_id, []) if s['snapshot_id'] != snap_id]
        return None
    if fn_name == 'list_networks':
        return STATE['networks']
    if fn_name == 'list_storage_pools':
        return [{'pool_id':'default','name':'default','type':'dir','state':'active','capacity_gb':0,'allocated_gb':0,'available_gb':0,'volumes':[{'name':'ubuntu24.qcow2','kind':'qcow2','used_by':'-','size_gb':0}]}]
    if fn_name == 'list_images':
        return STATE['images']
    if fn_name == 'migrate':
        return None
    raise RuntimeError(f'unknown fn {fn_name}')

STATE = {
    "vms": {},
    "snapshots": {},
    "networks": [{"network_id": "net-1", "name": "br-mgmt", "cidr": "10.0.0.0/24", "vlan_id": 100, "attached_vm_ids": []}],
    "images": [{"image_id": "img-1", "name": "ubuntu24", "status": "available", "source_url": "https://img", "created_at": "now"}],
}


def fake_get(url: str, timeout: int = 10):
    if url.endswith("/agent/status"):
        return FakeResp({"execution_mode": "libvirt"})
    if url.endswith("/agent/vms"):
        return FakeResp(list(STATE["vms"].values()))
    if "/agent/vms/" in url and url.endswith("/snapshots"):
        vm_id = url.split("/agent/vms/")[1].split("/")[0]
        return FakeResp(STATE["snapshots"].get(vm_id, []))
    if "/agent/vms/" in url and url.endswith("/export"):
        vm_id = url.split("/agent/vms/")[1].split("/")[0]
        return FakeResp(STATE["vms"][vm_id])
    if url.endswith("/agent/networks"):
        return FakeResp(STATE["networks"])
    if url.endswith("/agent/images"):
        return FakeResp(STATE["images"])
    return FakeResp({}, 404)


def fake_post(url: str, json=None, timeout: int = 10):
    if url.endswith("/agent/vms"):
        vm_id = f"vm-{len(STATE['vms'])+1}"
        vm = {"vm_id": vm_id, "name": json["name"], "cpu_cores": json["cpu_cores"], "memory_mb": json["memory_mb"], "image": json["image"], "power_state": "stopped", "networks": [], "labels": {}, "annotations": {}, "created_at": "now"}
        STATE["vms"][vm_id] = vm
        return FakeResp(vm)
    if url.endswith("/agent/vms/import"):
        vm = dict(json)
        STATE["vms"][vm["vm_id"]] = vm
        return FakeResp(vm)
    if "/agent/vms/" in url and url.endswith("/action"):
        vm_id = url.split("/agent/vms/")[1].split("/")[0]
        vm = STATE["vms"][vm_id]
        act = json["action"]
        vm["power_state"] = "running" if act in {"start", "resume", "reboot"} else ("paused" if act == "pause" else "stopped")
        return FakeResp(vm)
    if "/agent/vms/" in url and url.endswith("/resize"):
        vm_id = url.split("/agent/vms/")[1].split("/")[0]
        vm = STATE["vms"][vm_id]
        vm["cpu_cores"] = json["cpu_cores"]
        vm["memory_mb"] = json["memory_mb"]
        return FakeResp(vm)
    if "/agent/vms/" in url and url.endswith("/clone"):
        vm_id = url.split("/agent/vms/")[1].split("/")[0]
        src = STATE["vms"][vm_id]
        clone_id = f"vm-{len(STATE['vms'])+1}"
        vm = {**src, "vm_id": clone_id, "name": json["name"], "power_state": "stopped"}
        STATE["vms"][clone_id] = vm
        return FakeResp(vm)
    if "/agent/vms/" in url and url.endswith("/metadata"):
        vm_id = url.split("/agent/vms/")[1].split("/")[0]
        vm = STATE["vms"][vm_id]
        vm["labels"] = json.get("labels", {})
        vm["annotations"] = json.get("annotations", {})
        return FakeResp(vm)
    if "/agent/vms/" in url and "/snapshots/" in url and url.endswith("/revert"):
        vm_id = url.split("/agent/vms/")[1].split("/")[0]
        return FakeResp(STATE["vms"][vm_id])
    if "/agent/vms/" in url and url.endswith("/snapshots"):
        vm_id = url.split("/agent/vms/")[1].split("/")[0]
        snap = {"snapshot_id": f"s-{len(STATE['snapshots'].get(vm_id, []))+1}", "vm_id": vm_id, "name": json["name"], "captured_power_state": "running", "captured_cpu_cores": 2, "captured_memory_mb": 2048, "created_at": "now"}
        STATE["snapshots"].setdefault(vm_id, []).append(snap)
        return FakeResp(snap)
    if "/agent/networks/" in url and url.endswith("/attach"):
        return FakeResp({"status": "attached"})
    if "/agent/networks/" in url and url.endswith("/detach"):
        return FakeResp({"status": "detached"})
    if url.endswith("/api/v1/hosts/register") or "/heartbeat" in url:
        return FakeResp({})
    return FakeResp({}, 404)


def fake_delete(url: str, timeout: int = 10):
    if "/agent/vms/" in url:
        vm_id = url.split("/agent/vms/")[1].split("/")[0]
        STATE["vms"].pop(vm_id, None)
        return FakeResp({"status": "deleted"})
    if "/agent/vms/" in url and "/snapshots/" in url:
        return FakeResp({"status": "deleted"})
    if "/agent/networks/" in url:
        return FakeResp({"status": "deleted"})
    return FakeResp({}, 404)


def run() -> None:
    init_db()
    client = TestClient(app)
    with patch("dashboard.app.main._libvirt_call", side_effect=fake_libvirt_call), patch("dashboard.app.main.requests.get", side_effect=fake_get), patch("dashboard.app.main.requests.post", side_effect=fake_post), patch("dashboard.app.main.requests.delete", side_effect=fake_delete):
        r = client.post("/api/v1/hosts/register", json={"host_id": "h1", "name": "h1", "address": "10.0.0.1", "cpu_cores": 16, "memory_mb": 32768, "libvirt_uri": "qemu+ssh://root@10.110.17.153/system"})
        assert r.status_code == 200
        assert client.get("/api/v1/live/status").status_code == 200
        assert client.post("/api/v1/vms/provision", json={"host_id": "h1", "name": "vm-a", "cpu_cores": 2, "memory_mb": 2048, "image": "img"}).status_code == 200
        if "vm-a" not in STATE["vms"]:
            STATE["vms"]["vm-a"] = {"vm_id":"vm-a","name":"vm-a","cpu_cores":2,"memory_mb":2048,"image":"img","power_state":"stopped","networks":[],"labels":{},"annotations":{},"created_at":"now"}
        vm_id = next(iter(STATE["vms"].keys()))
        assert client.post(f"/api/v1/vms/{vm_id}/action", json={"host_id": "h1", "action": "start"}).status_code == 200
        assert client.post(f"/api/v1/vms/{vm_id}/resize", json={"host_id": "h1", "cpu_cores": 4, "memory_mb": 4096}).status_code == 200
        assert client.post(f"/api/v1/vms/{vm_id}/clone", json={"host_id": "h1", "name": "vm-a-clone"}).status_code == 200
        assert client.post(f"/api/v1/vms/{vm_id}/snapshots", json={"host_id": "h1", "name": "snap1"}).status_code == 200
        snapshot_id = STATE["snapshots"][vm_id][0]["snapshot_id"]
        assert client.post(f"/api/v1/vms/{vm_id}/snapshots/{snapshot_id}/revert", json={"host_id": "h1"}).status_code == 200
        assert client.post(f"/api/v1/networks/net-1/attach", json={"host_id": "h1", "vm_id": vm_id}).status_code == 200
        assert client.post(f"/api/v1/networks/net-1/detach", json={"host_id": "h1", "vm_id": vm_id}).status_code == 200
        assert client.post(f"/api/v1/vms/{vm_id}/recovery/attach-iso", json={"host_id": "h1", "iso_path": "/iso/rescue.iso", "boot_once": True}).status_code == 200
        assert client.post(f"/api/v1/vms/{vm_id}/recovery/detach-iso", json={"host_id": "h1"}).status_code == 200
        assert client.get(f"/api/v1/vms/{vm_id}/console?host_id=h1").status_code == 200
        assert client.get("/api/v1/console/novnc/status").status_code == 200
        assert client.post("/api/v1/policies/vm-lifecycle", json={"name": "default", "spec": {"deny_actions": "vm.delete"}}).status_code == 200
        assert client.get("/api/v1/policies/vm-lifecycle").status_code == 200
        assert client.post("/api/v1/networks/advanced/vlan_trunks", json={"name": "trunk-100"}).status_code == 200
        assert client.get("/api/v1/networks/advanced").status_code == 200
        assert client.post("/api/v1/images/img-1/deploy?host_id=h1&vm_name=vm-from-image").status_code == 200
        assert client.get("/api/v1/images/deployments").status_code == 200
        assert client.post(f"/api/v1/vms/{vm_id}/live-migrate", json={"source_host_id": "h1", "target_host_id": "h1"}).status_code == 200
    print("SMOKE_OK")


if __name__ == "__main__":
    run()
