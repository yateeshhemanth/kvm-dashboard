from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone

from .schemas import SnapshotRecord, VMAction, VMRecord


class VirshLibvirtExecutor:
    def __init__(self, uri: str) -> None:
        self.uri = uri

    def _run(self, args: list[str]) -> str:
        cmd = ["virsh", "-c", self.uri, *args]
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
            return out.strip()
        except FileNotFoundError as exc:
            raise RuntimeError("virsh is not installed on this host") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(exc.output.strip() or f"virsh command failed: {' '.join(cmd)}") from exc

    def list_vms(self) -> list[VMRecord]:
        names = [line.strip() for line in self._run(["list", "--all", "--name"]).splitlines() if line.strip()]
        items: list[VMRecord] = []
        for name in names:
            info = self._run(["dominfo", name])
            state_match = re.search(r"State:\s+(.+)", info)
            cpu_match = re.search(r"CPU\(s\):\s+(\d+)", info)
            mem_match = re.search(r"Max memory:\s+(\d+)\s+KiB", info)
            state = (state_match.group(1).lower() if state_match else "unknown")
            if "running" in state:
                power_state = "running"
            elif "paused" in state:
                power_state = "paused"
            else:
                power_state = "stopped"
            cpu_cores = int(cpu_match.group(1)) if cpu_match else 0
            memory_mb = int(mem_match.group(1)) // 1024 if mem_match else 0
            items.append(
                VMRecord(
                    vm_id=name,
                    name=name,
                    cpu_cores=cpu_cores,
                    memory_mb=memory_mb,
                    image=f"libvirt:{name}",
                    power_state=power_state,
                    networks=[],
                    labels={"execution": "libvirt"},
                    annotations={"libvirt_uri": self.uri},
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
            )
        return items

    def vm_action(self, vm_id: str, action: VMAction) -> None:
        mapping = {
            VMAction.start: ["start", vm_id],
            VMAction.stop: ["shutdown", vm_id],
            VMAction.reboot: ["reboot", vm_id],
            VMAction.pause: ["suspend", vm_id],
            VMAction.resume: ["resume", vm_id],
        }
        self._run(mapping[action])

    def delete_vm(self, vm_id: str) -> None:
        try:
            self._run(["destroy", vm_id])
        except RuntimeError:
            pass
        self._run(["undefine", vm_id, "--nvram"])

    def resize_vm(self, vm_id: str, cpu_cores: int, memory_mb: int) -> None:
        self._run(["setvcpus", vm_id, str(cpu_cores), "--live", "--config"])
        self._run(["setmem", vm_id, str(memory_mb * 1024), "--live", "--config"])

    def create_snapshot(self, vm_id: str, name: str) -> SnapshotRecord:
        self._run(["snapshot-create-as", vm_id, name, "--atomic"])
        return SnapshotRecord(
            snapshot_id=name,
            vm_id=vm_id,
            name=name,
            captured_power_state="running",
            captured_cpu_cores=0,
            captured_memory_mb=0,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def list_snapshots(self, vm_id: str) -> list[SnapshotRecord]:
        out = self._run(["snapshot-list", vm_id, "--name"])
        return [
            SnapshotRecord(
                snapshot_id=n.strip(),
                vm_id=vm_id,
                name=n.strip(),
                captured_power_state="unknown",
                captured_cpu_cores=0,
                captured_memory_mb=0,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            for n in out.splitlines()
            if n.strip()
        ]

    def revert_snapshot(self, vm_id: str, snapshot_id: str) -> None:
        self._run(["snapshot-revert", vm_id, snapshot_id, "--running"])

    def delete_snapshot(self, vm_id: str, snapshot_id: str) -> None:
        self._run(["snapshot-delete", vm_id, snapshot_id])
