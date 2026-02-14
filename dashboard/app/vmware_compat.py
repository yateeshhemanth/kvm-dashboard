from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .db import get_db
from .models import Host


def build_vmware_router(
    get_host_or_404: Callable[[Session, str], Host],
    libvirt_call: Callable[..., object],
    refresh_cache: Callable[[Session, Host], dict],
):
    router = APIRouter(prefix="/api/v1/vmware", tags=["vmware-compat"])

    @router.post("/hosts/{host_id}/vms/{vm_id}/power-on")
    def power_on_vm(host_id: str, vm_id: str, db: Session = Depends(get_db)) -> dict:
        host = get_host_or_404(db, host_id)
        libvirt_call(host, "vm_action", vm_id, "start")
        refresh_cache(db, host)
        return {"host_id": host_id, "vm_id": vm_id, "status": "powered_on", "backend": "kvm/libvirt"}

    @router.post("/hosts/{host_id}/vms/{vm_id}/power-off")
    def power_off_vm(host_id: str, vm_id: str, db: Session = Depends(get_db)) -> dict:
        host = get_host_or_404(db, host_id)
        libvirt_call(host, "vm_action", vm_id, "stop")
        refresh_cache(db, host)
        return {"host_id": host_id, "vm_id": vm_id, "status": "powered_off", "backend": "kvm/libvirt"}

    @router.post("/hosts/{host_id}/vms/{vm_id}/reset")
    def reset_vm(host_id: str, vm_id: str, db: Session = Depends(get_db)) -> dict:
        host = get_host_or_404(db, host_id)
        libvirt_call(host, "vm_action", vm_id, "reboot")
        refresh_cache(db, host)
        return {"host_id": host_id, "vm_id": vm_id, "status": "reset", "backend": "kvm/libvirt"}

    @router.get("/feasibility")
    def vmware_feasibility() -> dict:
        return {
            "backend": "kvm/libvirt",
            "feasible_mappings": [
                {"vmware": "Power On/Off/Reset", "kvm": "vm_action start/stop/reboot", "status": "supported"},
                {"vmware": "Snapshots", "kvm": "snapshot-create/list/revert/delete", "status": "supported"},
                {"vmware": "Hot resize", "kvm": "setvcpus/setmem", "status": "partial"},
                {"vmware": "vMotion", "kvm": "virsh migrate --live", "status": "supported"},
                {"vmware": "Tools guest operations", "kvm": "qemu-guest-agent required", "status": "not_enabled"},
                {"vmware": "DRS/HA cluster automation", "kvm": "needs scheduler layer", "status": "not_enabled"},
            ],
        }

    return router
