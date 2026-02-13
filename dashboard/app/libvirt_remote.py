from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from typing import Any


class LibvirtRemoteError(RuntimeError):
    pass


class LibvirtRemote:
    def __init__(self, uri: str) -> None:
        self.uri = uri

    def _run(self, args: list[str]) -> str:
        cmd = ["virsh", "-c", self.uri, *args]
        try:
            return subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True).strip()
        except FileNotFoundError as exc:
            raise LibvirtRemoteError("virsh not installed on dashboard host") from exc
        except subprocess.CalledProcessError as exc:
            raise LibvirtRemoteError(exc.output.strip() or "virsh command failed") from exc

    def health(self) -> dict[str, Any]:
        out = self._run(["list", "--all", "--name"])
        return {"reachable": True, "vm_count": len([x for x in out.splitlines() if x.strip()])}

    def list_vms(self) -> list[dict[str, Any]]:
        names = [n.strip() for n in self._run(["list", "--all", "--name"]).splitlines() if n.strip()]
        rows: list[dict[str, Any]] = []
        for name in names:
            info = self._run(["dominfo", name])
            cpu = int(re.search(r"CPU\(s\):\s+(\d+)", info).group(1)) if re.search(r"CPU\(s\):\s+(\d+)", info) else 0
            mem_kib = int(re.search(r"Max memory:\s+(\d+)\s+KiB", info).group(1)) if re.search(r"Max memory:\s+(\d+)\s+KiB", info) else 0
            state_raw = re.search(r"State:\s+(.+)", info).group(1).lower() if re.search(r"State:\s+(.+)", info) else "unknown"
            power = "running" if "running" in state_raw else ("paused" if "paused" in state_raw else "stopped")
            nets: list[str] = []
            try:
                nout = self._run(["domiflist", name])
                for line in nout.splitlines()[2:]:
                    parts = line.split()
                    if len(parts) >= 3:
                        nets.append(parts[2])
            except LibvirtRemoteError:
                pass
            rows.append({
                "vm_id": name,
                "name": name,
                "cpu_cores": cpu,
                "memory_mb": mem_kib // 1024,
                "image": f"libvirt:{name}",
                "power_state": power,
                "networks": nets,
                "labels": {"executor": "libvirt-direct"},
                "annotations": {"libvirt_uri": self.uri},
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        return rows

    def vm_action(self, vm_id: str, action: str) -> None:
        mapping = {
            "start": ["start", vm_id],
            "stop": ["shutdown", vm_id],
            "reboot": ["reboot", vm_id],
            "pause": ["suspend", vm_id],
            "resume": ["resume", vm_id],
        }
        self._run(mapping[action])

    def resize(self, vm_id: str, cpu: int, mem_mb: int) -> None:
        self._run(["setvcpus", vm_id, str(cpu), "--live", "--config"])
        self._run(["setmaxmem", vm_id, str(mem_mb * 1024), "--config"])
        self._run(["setmem", vm_id, str(mem_mb * 1024), "--live"])

    def delete_vm(self, vm_id: str) -> None:
        try:
            self._run(["destroy", vm_id])
        except LibvirtRemoteError:
            pass
        self._run(["undefine", vm_id, "--nvram"])

    def snapshot_create(self, vm_id: str, name: str) -> dict[str, Any]:
        self._run(["snapshot-create-as", vm_id, name, "--atomic"])
        return {"snapshot_id": name, "vm_id": vm_id, "name": name, "created_at": datetime.now(timezone.utc).isoformat()}

    def snapshot_list(self, vm_id: str) -> list[dict[str, Any]]:
        out = self._run(["snapshot-list", vm_id, "--name"])
        return [{"snapshot_id": s.strip(), "vm_id": vm_id, "name": s.strip(), "created_at": datetime.now(timezone.utc).isoformat()} for s in out.splitlines() if s.strip()]

    def snapshot_revert(self, vm_id: str, snapshot_id: str) -> None:
        self._run(["snapshot-revert", vm_id, snapshot_id, "--running"])

    def snapshot_delete(self, vm_id: str, snapshot_id: str) -> None:
        self._run(["snapshot-delete", vm_id, snapshot_id])

    def list_networks(self) -> list[dict[str, Any]]:
        nets = [n.strip() for n in self._run(["net-list", "--all", "--name"]).splitlines() if n.strip()]
        return [{"network_id": n, "name": n, "cidr": "n/a", "vlan_id": None, "attached_vm_ids": []} for n in nets]

    def list_storage_pools(self) -> list[dict[str, Any]]:
        pools = [n.strip() for n in self._run(["pool-list", "--all", "--name"]).splitlines() if n.strip()]
        out: list[dict[str, Any]] = []
        for p in pools:
            vols: list[dict[str, Any]] = []
            try:
                vout = self._run(["vol-list", p])
                for line in vout.splitlines()[2:]:
                    parts = line.split()
                    if parts:
                        vols.append({"name": parts[0], "kind": "qcow2", "used_by": "-", "size_gb": 0})
            except LibvirtRemoteError:
                pass
            out.append({"pool_id": p, "name": p, "type": "dir", "state": "active", "capacity_gb": 0, "allocated_gb": 0, "available_gb": 0, "volumes": vols})
        return out

    def list_images(self) -> list[dict[str, Any]]:
        images: list[dict[str, Any]] = []
        for pool in self.list_storage_pools():
            for vol in pool.get("volumes", []):
                if vol["name"].endswith((".qcow2", ".iso", ".img")):
                    images.append({"image_id": f"{pool['name']}::{vol['name']}", "name": vol["name"], "source_url": pool["name"], "status": "available", "created_at": datetime.now(timezone.utc).isoformat()})
        return images

    def migrate(self, vm_id: str, target_uri: str, live: bool = True) -> None:
        args = ["migrate"]
        if live:
            args.extend(["--live", "--persistent", "--undefinesource"])
        args.extend([vm_id, target_uri])
        self._run(args)
