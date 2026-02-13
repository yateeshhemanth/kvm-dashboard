from datetime import datetime, timezone
from uuid import uuid4

import requests
from fastapi import APIRouter, HTTPException

from .config import AgentConfig
from .schemas import (
    ImageCreateRequest,
    ImageRecord,
    NetworkAttachRequest,
    NetworkCreateRequest,
    NetworkRecord,
    SnapshotCreateRequest,
    SnapshotRecord,
    VMAction,
    VMActionRequest,
    VMCloneRequest,
    VMCreateRequest,
    VMImportRequest,
    VMMetadataRequest,
    VMRecord,
    VMResizeRequest,
)
from .services import push_to_dashboard
from .state import AgentState
from .libvirt_executor import VirshLibvirtExecutor


def create_router(config: AgentConfig, state: AgentState) -> APIRouter:
    router = APIRouter()
    libvirt = VirshLibvirtExecutor(config.libvirt_uri)

    def using_libvirt() -> bool:
        return config.execution_mode == "libvirt"

    @router.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "host_id": config.host_id}

    @router.get("/agent/status")
    def agent_status() -> dict[str, str | bool | int | None]:
        with state.lock:
            return {
                "host_id": config.host_id,
                "host_name": config.host_name,
                "host_address": config.host_address,
                "dashboard_url": config.dashboard_url,
                "last_push_at": state.last_push_at,
                "last_push_ok": state.last_push_ok,
                "last_error": state.last_error,
                "push_count": state.push_count,
                "interval_seconds": config.interval_seconds,
                "vm_count": len(state.vms),
                "network_count": len(state.networks),
                "execution_mode": config.execution_mode,
                "libvirt_uri": config.libvirt_uri,
            }

    @router.post("/agent/push-now")
    def push_now() -> dict[str, str]:
        try:
            push_to_dashboard(config, state)
        except requests.RequestException as exc:
            with state.lock:
                state.last_push_ok = False
                state.last_error = str(exc)
                state.last_push_at = datetime.now(timezone.utc).isoformat()
            return {"status": "error", "detail": str(exc)}

        return {"status": "ok"}

    @router.get("/agent/vms", response_model=list[VMRecord])
    def list_vms() -> list[VMRecord]:
        if using_libvirt():
            try:
                return libvirt.list_vms()
            except RuntimeError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        with state.lock:
            return list(state.vms.values())

    @router.post("/agent/vms", response_model=VMRecord)
    def create_vm(payload: VMCreateRequest) -> VMRecord:
        vm = VMRecord(
            vm_id=str(uuid4()),
            name=payload.name,
            cpu_cores=payload.cpu_cores,
            memory_mb=payload.memory_mb,
            image=payload.image,
            power_state="stopped",
            networks=[],
            labels={},
            annotations={},
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with state.lock:
            state.vms[vm.vm_id] = vm
            state.snapshots[vm.vm_id] = {}
        return vm

    @router.get("/agent/vms/{vm_id}/export", response_model=VMRecord)
    def export_vm(vm_id: str) -> VMRecord:
        with state.lock:
            vm = state.vms.get(vm_id)
            if not vm:
                raise HTTPException(status_code=404, detail="vm not found")
            return vm

    @router.post("/agent/vms/import", response_model=VMRecord)
    def import_vm(payload: VMImportRequest) -> VMRecord:
        vm = VMRecord(**payload.model_dump())
        with state.lock:
            if vm.vm_id in state.vms:
                raise HTTPException(status_code=409, detail="vm already exists")
            state.vms[vm.vm_id] = vm
            state.snapshots[vm.vm_id] = {}
        return vm



    @router.post("/agent/vms/{vm_id}/clone", response_model=VMRecord)
    def clone_vm(vm_id: str, payload: VMCloneRequest) -> VMRecord:
        with state.lock:
            source = state.vms.get(vm_id)
            if not source:
                raise HTTPException(status_code=404, detail="vm not found")

            cloned = VMRecord(
                vm_id=str(uuid4()),
                name=payload.name,
                cpu_cores=source.cpu_cores,
                memory_mb=source.memory_mb,
                image=source.image,
                power_state="stopped",
                networks=list(source.networks),
                labels=dict(source.labels),
                annotations=dict(source.annotations),
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            state.vms[cloned.vm_id] = cloned
            state.snapshots[cloned.vm_id] = {}
            return cloned


    @router.post("/agent/vms/{vm_id}/metadata", response_model=VMRecord)
    def set_vm_metadata(vm_id: str, payload: VMMetadataRequest) -> VMRecord:
        with state.lock:
            vm = state.vms.get(vm_id)
            if not vm:
                raise HTTPException(status_code=404, detail="vm not found")

            vm.labels = payload.labels
            vm.annotations = payload.annotations
            state.vms[vm.vm_id] = vm
            return vm

    @router.post("/agent/vms/{vm_id}/action", response_model=VMRecord)
    def vm_action(vm_id: str, payload: VMActionRequest) -> VMRecord:
        if using_libvirt():
            try:
                libvirt.vm_action(vm_id, payload.action)
                for vm in libvirt.list_vms():
                    if vm.vm_id == vm_id:
                        return vm
                raise HTTPException(status_code=404, detail="vm not found")
            except RuntimeError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        with state.lock:
            vm = state.vms.get(vm_id)
            if not vm:
                raise HTTPException(status_code=404, detail="vm not found")

            if payload.action == VMAction.start:
                vm.power_state = "running"
            elif payload.action == VMAction.stop:
                vm.power_state = "stopped"
            elif payload.action == VMAction.reboot:
                vm.power_state = "running"
            elif payload.action == VMAction.pause:
                vm.power_state = "paused"
            elif payload.action == VMAction.resume:
                vm.power_state = "running"

            state.vms[vm_id] = vm
            return vm

    @router.post("/agent/vms/{vm_id}/resize", response_model=VMRecord)
    def resize_vm(vm_id: str, payload: VMResizeRequest) -> VMRecord:
        if using_libvirt():
            try:
                libvirt.resize_vm(vm_id, payload.cpu_cores, payload.memory_mb)
                for vm in libvirt.list_vms():
                    if vm.vm_id == vm_id:
                        return vm
                raise HTTPException(status_code=404, detail="vm not found")
            except RuntimeError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        with state.lock:
            vm = state.vms.get(vm_id)
            if not vm:
                raise HTTPException(status_code=404, detail="vm not found")
            vm.cpu_cores = payload.cpu_cores
            vm.memory_mb = payload.memory_mb
            state.vms[vm_id] = vm
            return vm

    @router.delete("/agent/vms/{vm_id}")
    def delete_vm(vm_id: str) -> dict[str, str]:
        if using_libvirt():
            try:
                libvirt.delete_vm(vm_id)
                return {"status": "deleted", "vm_id": vm_id, "executor": "libvirt"}
            except RuntimeError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        with state.lock:
            vm = state.vms.get(vm_id)
            if not vm:
                raise HTTPException(status_code=404, detail="vm not found")
            del state.vms[vm_id]
            state.snapshots.pop(vm_id, None)

        return {"status": "deleted", "vm_id": vm_id}

    @router.post("/agent/vms/{vm_id}/snapshots", response_model=SnapshotRecord)
    def create_snapshot(vm_id: str, payload: SnapshotCreateRequest) -> SnapshotRecord:
        if using_libvirt():
            try:
                return libvirt.create_snapshot(vm_id, payload.name)
            except RuntimeError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        with state.lock:
            vm = state.vms.get(vm_id)
            if not vm:
                raise HTTPException(status_code=404, detail="vm not found")

            snapshot = SnapshotRecord(
                snapshot_id=str(uuid4()),
                vm_id=vm_id,
                name=payload.name,
                captured_power_state=vm.power_state,
                captured_cpu_cores=vm.cpu_cores,
                captured_memory_mb=vm.memory_mb,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            vm_snapshots = state.snapshots.setdefault(vm_id, {})
            vm_snapshots[snapshot.snapshot_id] = snapshot
            return snapshot

    @router.get("/agent/vms/{vm_id}/snapshots", response_model=list[SnapshotRecord])
    def list_snapshots(vm_id: str) -> list[SnapshotRecord]:
        if using_libvirt():
            try:
                return libvirt.list_snapshots(vm_id)
            except RuntimeError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        with state.lock:
            if vm_id not in state.vms:
                raise HTTPException(status_code=404, detail="vm not found")
            return list(state.snapshots.get(vm_id, {}).values())

    @router.post("/agent/vms/{vm_id}/snapshots/{snapshot_id}/revert", response_model=VMRecord)
    def revert_snapshot(vm_id: str, snapshot_id: str) -> VMRecord:
        if using_libvirt():
            try:
                libvirt.revert_snapshot(vm_id, snapshot_id)
                for vm in libvirt.list_vms():
                    if vm.vm_id == vm_id:
                        return vm
                raise HTTPException(status_code=404, detail="vm not found")
            except RuntimeError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        with state.lock:
            vm = state.vms.get(vm_id)
            if not vm:
                raise HTTPException(status_code=404, detail="vm not found")

            snapshot = state.snapshots.get(vm_id, {}).get(snapshot_id)
            if not snapshot:
                raise HTTPException(status_code=404, detail="snapshot not found")

            vm.power_state = snapshot.captured_power_state
            vm.cpu_cores = snapshot.captured_cpu_cores
            vm.memory_mb = snapshot.captured_memory_mb
            state.vms[vm_id] = vm
            return vm

    @router.delete("/agent/vms/{vm_id}/snapshots/{snapshot_id}")
    def delete_snapshot(vm_id: str, snapshot_id: str) -> dict[str, str]:
        if using_libvirt():
            try:
                libvirt.delete_snapshot(vm_id, snapshot_id)
                return {"status": "deleted", "snapshot_id": snapshot_id, "vm_id": vm_id, "executor": "libvirt"}
            except RuntimeError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        with state.lock:
            if vm_id not in state.vms:
                raise HTTPException(status_code=404, detail="vm not found")

            vm_snapshots = state.snapshots.get(vm_id, {})
            if snapshot_id not in vm_snapshots:
                raise HTTPException(status_code=404, detail="snapshot not found")

            del vm_snapshots[snapshot_id]

        return {"status": "deleted", "snapshot_id": snapshot_id, "vm_id": vm_id}


    @router.get("/agent/images", response_model=list[ImageRecord])
    def list_images() -> list[ImageRecord]:
        with state.lock:
            return list(state.images.values())

    @router.post("/agent/images", response_model=ImageRecord)
    def create_image(payload: ImageCreateRequest) -> ImageRecord:
        image = ImageRecord(
            image_id=str(uuid4()),
            name=payload.name,
            source_url=payload.source_url,
            status="available",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with state.lock:
            state.images[image.image_id] = image
        return image

    @router.delete("/agent/images/{image_id}")
    def delete_image(image_id: str) -> dict[str, str]:
        with state.lock:
            image = state.images.get(image_id)
            if not image:
                raise HTTPException(status_code=404, detail="image not found")
            del state.images[image_id]

        return {"status": "deleted", "image_id": image_id}

    @router.get("/agent/networks", response_model=list[NetworkRecord])
    def list_networks() -> list[NetworkRecord]:
        with state.lock:
            return list(state.networks.values())

    @router.post("/agent/networks", response_model=NetworkRecord)
    def create_network(payload: NetworkCreateRequest) -> NetworkRecord:
        network = NetworkRecord(
            network_id=str(uuid4()),
            name=payload.name,
            cidr=payload.cidr,
            vlan_id=payload.vlan_id,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with state.lock:
            state.networks[network.network_id] = network
        return network

    @router.post("/agent/networks/{network_id}/attach")
    def attach_network(network_id: str, payload: NetworkAttachRequest) -> dict[str, str]:
        with state.lock:
            network = state.networks.get(network_id)
            if not network:
                raise HTTPException(status_code=404, detail="network not found")

            vm = state.vms.get(payload.vm_id)
            if not vm:
                raise HTTPException(status_code=404, detail="vm not found")

            if network_id not in vm.networks:
                vm.networks.append(network_id)
                state.vms[vm.vm_id] = vm

        return {"status": "attached", "vm_id": payload.vm_id, "network_id": network_id}

    @router.post("/agent/networks/{network_id}/detach")
    def detach_network(network_id: str, payload: NetworkAttachRequest) -> dict[str, str]:
        with state.lock:
            network = state.networks.get(network_id)
            if not network:
                raise HTTPException(status_code=404, detail="network not found")

            vm = state.vms.get(payload.vm_id)
            if not vm:
                raise HTTPException(status_code=404, detail="vm not found")

            vm.networks = [attached_id for attached_id in vm.networks if attached_id != network_id]
            state.vms[vm.vm_id] = vm

        return {"status": "detached", "vm_id": payload.vm_id, "network_id": network_id}

    @router.delete("/agent/networks/{network_id}")
    def delete_network(network_id: str) -> dict[str, str]:
        with state.lock:
            network = state.networks.get(network_id)
            if not network:
                raise HTTPException(status_code=404, detail="network not found")

            for vm_id, vm in state.vms.items():
                if network_id in vm.networks:
                    vm.networks = [attached_id for attached_id in vm.networks if attached_id != network_id]
                    state.vms[vm_id] = vm

            del state.networks[network_id]

        return {"status": "deleted", "network_id": network_id}

    return router
