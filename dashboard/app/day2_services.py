SUPPORTED_VM_TASK_TYPES = {
    "vm.start",
    "vm.stop",
    "vm.reboot",
    "vm.pause",
    "vm.resume",
    "vm.delete",
    "vm.resize",
    "vm.clone",
    "vm.migrate",
    "vm.snapshot",
    "vm.snapshot.revert",
    "vm.snapshot.delete",
    "vm.power_cycle",
    "vm.backup",
    "vm.network.attach",
    "vm.network.detach",
    "vm.recovery.iso.attach",
    "vm.recovery.iso.detach",
}


def normalize_task_type(task_type: str) -> str:
    return task_type.strip().lower()
