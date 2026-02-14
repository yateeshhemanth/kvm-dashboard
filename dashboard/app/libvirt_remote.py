from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


class LibvirtRemoteError(RuntimeError):
    pass


class LibvirtRemote:
    _semaphore: threading.BoundedSemaphore | None = None
    _semaphore_size: int | None = None
    _semaphore_lock = threading.Lock()

    def __init__(self, uri: str) -> None:
        self.uri = uri
        self.timeout_s = int(os.getenv("LIBVIRT_CMD_TIMEOUT_S", "8"))
        self.max_concurrency = max(1, int(os.getenv("LIBVIRT_MAX_CONCURRENCY", "2")))
        self.retry_count = max(0, int(os.getenv("LIBVIRT_FORK_RETRY_COUNT", "2")))
        self.retry_sleep_s = max(0.0, float(os.getenv("LIBVIRT_FORK_RETRY_SLEEP_S", "0.25")))
        self.default_pool = os.getenv("LIBVIRT_DEFAULT_POOL", "default").strip() or "default"

    @classmethod
    def _get_semaphore(cls, size: int) -> threading.BoundedSemaphore:
        with cls._semaphore_lock:
            if cls._semaphore is None or cls._semaphore_size != size:
                cls._semaphore = threading.BoundedSemaphore(size)
                cls._semaphore_size = size
            return cls._semaphore

    def _run(self, args: list[str]) -> str:
        cmd = ["virsh", "-c", self.uri, *args]
        semaphore = self._get_semaphore(self.max_concurrency)
        acquire_timeout = max(self.timeout_s + 1, 5)
        if not semaphore.acquire(timeout=acquire_timeout):
            raise LibvirtRemoteError("libvirt command queue saturated; try again")
        try:
            attempts = self.retry_count + 1
            for attempt in range(attempts):
                try:
                    return subprocess.check_output(
                        cmd,
                        stderr=subprocess.STDOUT,
                        text=True,
                        timeout=self.timeout_s,
                    ).strip()
                except FileNotFoundError as exc:
                    raise LibvirtRemoteError("virsh not installed on dashboard host") from exc
                except subprocess.TimeoutExpired as exc:
                    raise LibvirtRemoteError(
                        f"virsh command timed out after {self.timeout_s}s: {' '.join(cmd)}"
                    ) from exc
                except subprocess.CalledProcessError as exc:
                    output = exc.output.strip() or "virsh command failed"
                    if "cannot fork child process" in output and attempt < attempts - 1:
                        time.sleep(self.retry_sleep_s)
                        continue
                    raise LibvirtRemoteError(output) from exc
        finally:
            semaphore.release()

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

    def _disk_source_from_image(self, image: str) -> str:
        image = (image or "").strip()
        if not image:
            return ""
        if "::" in image:
            pool, _, vol = image.partition("::")
            if pool and vol:
                try:
                    return self._run(["vol-path", vol, "--pool", pool])
                except LibvirtRemoteError:
                    return ""
        if image.startswith("/"):
            return image
        # Fallback: treat plain image names as volumes in default pool.
        try:
            return self._run(["vol-path", image, "--pool", self.default_pool])
        except LibvirtRemoteError:
            return ""

    def create_vm(self, name: str, cpu_cores: int, memory_mb: int, image: str, network: str = "default") -> dict[str, Any]:
        disk_path = self._disk_source_from_image(image)
        disk_xml = f"""<disk type='file' device='disk'>
      <driver name='qemu' type='qcow2'/>
      <source file='{disk_path}'/>
      <target dev='vda' bus='virtio'/>
    </disk>""" if disk_path else ""

        domain_xml = f"""
<domain type='kvm'>
  <name>{name}</name>
  <uuid>{uuid4()}</uuid>
  <memory unit='MiB'>{memory_mb}</memory>
  <currentMemory unit='MiB'>{memory_mb}</currentMemory>
  <vcpu>{cpu_cores}</vcpu>
  <os>
    <type arch='x86_64' machine='pc'>hvm</type>
    <boot dev='hd'/>
    <boot dev='network'/>
  </os>
  <features>
    <acpi/>
    <apic/>
  </features>
  <clock offset='utc'/>
  <on_poweroff>destroy</on_poweroff>
  <on_reboot>restart</on_reboot>
  <on_crash>destroy</on_crash>
  <devices>
    <emulator>/usr/bin/qemu-system-x86_64</emulator>
    <interface type='network'>
      <source network='{network}'/>
      <model type='virtio'/>
    </interface>
    {disk_xml}
    <graphics type='vnc' autoport='yes' listen='0.0.0.0'/>
    <console type='pty'/>
    <serial type='pty'/>
    <video>
      <model type='vga' vram='16384' heads='1'/>
    </video>
  </devices>
</domain>
""".strip()

        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=True) as tmp:
            tmp.write(domain_xml)
            tmp.flush()
            self._run(["define", tmp.name])

        return {
            "vm_id": name,
            "name": name,
            "cpu_cores": cpu_cores,
            "memory_mb": memory_mb,
            "image": image,
            "power_state": "stopped",
            "networks": [network],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "disk_source": disk_path or None,
        }

    def console_info(self, vm_id: str) -> dict[str, Any]:
        display_uri = self._run(["domdisplay", vm_id])
        m = re.search(r":(\d+)$", display_uri)
        vnc_port = int(m.group(1)) if m else None
        return {"display_uri": display_uri, "vnc_port": vnc_port}

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

    def _volume_usage_map(self) -> dict[str, set[str]]:
        usage: dict[str, set[str]] = {}
        vm_names = [n.strip() for n in self._run(["list", "--all", "--name"]).splitlines() if n.strip()]
        for vm_name in vm_names:
            try:
                bout = self._run(["domblklist", vm_name, "--details"])
            except LibvirtRemoteError:
                continue
            for line in bout.splitlines()[2:]:
                parts = line.split()
                if len(parts) < 4:
                    continue
                source = parts[-1]
                base = os.path.basename(source)
                if not base or source == "-":
                    continue
                usage.setdefault(base, set()).add(vm_name)
        return usage

    def current_iso(self, vm_id: str) -> str:
        try:
            bout = self._run(["domblklist", vm_id, "--details"])
        except LibvirtRemoteError:
            return ""
        for line in bout.splitlines()[2:]:
            parts = line.split()
            if len(parts) >= 4 and parts[0] == "cdrom" and parts[-1] != "-":
                return parts[-1]
        return ""

    def attach_iso(self, vm_id: str, iso_path: str, boot_once: bool = True) -> dict[str, Any]:
        attempts = [
            ["change-media", vm_id, "hdb", "--insert", iso_path, "--live", "--config"],
            ["attach-disk", vm_id, iso_path, "hdb", "--type", "cdrom", "--mode", "readonly", "--live", "--config"],
        ]
        last_error = None
        for cmd in attempts:
            try:
                self._run(cmd)
                break
            except LibvirtRemoteError as exc:
                last_error = exc
        else:
            raise LibvirtRemoteError(f"failed to attach iso: {last_error}")
        return {"vm_id": vm_id, "iso_path": iso_path, "boot_once": boot_once, "attached": True}

    def detach_iso(self, vm_id: str) -> dict[str, Any]:
        attempts = [
            ["change-media", vm_id, "hdb", "--eject", "--live", "--config"],
            ["detach-disk", vm_id, "hdb", "--live", "--config"],
        ]
        for cmd in attempts:
            try:
                self._run(cmd)
                return {"vm_id": vm_id, "detached": True}
            except LibvirtRemoteError:
                continue
        return {"vm_id": vm_id, "detached": False}

    def list_storage_pools(self) -> list[dict[str, Any]]:
        pools = [n.strip() for n in self._run(["pool-list", "--all", "--name"]).splitlines() if n.strip()]
        usage = self._volume_usage_map()
        out: list[dict[str, Any]] = []
        for p in pools:
            vols: list[dict[str, Any]] = []
            try:
                vout = self._run(["vol-list", p])
                for line in vout.splitlines()[2:]:
                    parts = line.split()
                    if not parts:
                        continue
                    vol_name = parts[0]
                    used_by = sorted(usage.get(vol_name, set()))
                    size_gb = 0.0
                    try:
                        info = self._run(["vol-info", vol_name, "--pool", p])
                        m = re.search(r"Capacity:\s+([\d.]+)\s+([A-Za-z]+)", info)
                        if m:
                            size = float(m.group(1))
                            unit = m.group(2).lower()
                            if unit.startswith("g"):
                                size_gb = size
                            elif unit.startswith("m"):
                                size_gb = size / 1024.0
                            elif unit.startswith("k"):
                                size_gb = size / (1024.0 * 1024.0)
                    except LibvirtRemoteError:
                        pass
                    kind = "iso" if vol_name.lower().endswith('.iso') else ("qcow2" if vol_name.lower().endswith('.qcow2') else "disk")
                    vols.append({"name": vol_name, "kind": kind, "used_by": ",".join(used_by) if used_by else "-", "size_gb": round(size_gb, 2)})
            except LibvirtRemoteError:
                pass
            out.append({"pool_id": p, "name": p, "type": "dir", "state": "active", "capacity_gb": 0, "allocated_gb": 0, "available_gb": 0, "volumes": vols})
        return out

    def list_images(self) -> list[dict[str, Any]]:
        images: list[dict[str, Any]] = []
        for pool in self.list_storage_pools():
            for vol in pool.get("volumes", []):
                if vol["name"].endswith((".qcow2", ".iso", ".img")):
                    images.append({"image_id": f"{pool['name']}::{vol['name']}", "name": vol["name"], "source_url": pool["name"], "status": "available", "used_by": vol.get("used_by", "-"), "created_at": datetime.now(timezone.utc).isoformat()})
        return images


    def create_network(self, name: str, cidr: str, vlan_id: int | None = None) -> dict[str, Any]:
        ip_part, prefix = cidr.split("/")
        octets = ip_part.split(".")
        if len(octets) != 4:
            raise LibvirtRemoteError("invalid CIDR")
        gateway = f"{octets[0]}.{octets[1]}.{octets[2]}.1"
        network_xml = f"""
<network>
  <name>{name}</name>
  <forward mode='nat'/>
  <bridge name='virbr-{name[:8]}' stp='on' delay='0'/>
  <ip address='{gateway}' prefix='{prefix}'/>
</network>
""".strip()
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=True) as tmp:
            tmp.write(network_xml)
            tmp.flush()
            self._run(["net-define", tmp.name])
        self._run(["net-autostart", name])
        self._run(["net-start", name])
        return {"network_id": name, "name": name, "cidr": cidr, "vlan_id": vlan_id, "attached_vm_ids": []}

    def delete_network(self, network_id: str) -> None:
        try:
            self._run(["net-destroy", network_id])
        except LibvirtRemoteError:
            pass
        self._run(["net-undefine", network_id])

    def create_image(self, name: str, pool: str = "default", size_gb: int = 20) -> dict[str, Any]:
        self._run(["vol-create-as", pool, name, f"{size_gb}G", "--format", "qcow2"])
        return {"image_id": f"{pool}::{name}", "name": name, "source_url": pool, "status": "available", "created_at": datetime.now(timezone.utc).isoformat()}

    def delete_image(self, image_id: str) -> dict[str, Any]:
        pool, _, volume = image_id.partition("::")
        if not pool or not volume:
            raise LibvirtRemoteError("image_id must be '<pool>::<volume>'")
        self._run(["vol-delete", volume, "--pool", pool])
        return {"status": "deleted", "image_id": image_id}

    def migrate(self, vm_id: str, target_uri: str, live: bool = True) -> None:
        args = ["migrate"]
        if live:
            args.extend(["--live", "--persistent", "--undefinesource"])
        args.extend([vm_id, target_uri])
        self._run(args)
