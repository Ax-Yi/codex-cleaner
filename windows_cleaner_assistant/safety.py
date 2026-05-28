from __future__ import annotations

import os
from pathlib import Path


SYSTEM_DIR_NAMES = {
    "$Recycle.Bin",
    "Config.Msi",
    "Documents and Settings",
    "PerfLogs",
    "Program Files",
    "Program Files (x86)",
    "ProgramData",
    "Recovery",
    "System Volume Information",
    "Windows",
}


def _candidate_system_paths() -> set[Path]:
    paths: set[Path] = set()
    for env_name in ("SystemRoot", "WINDIR", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        value = os.environ.get(env_name)
        if value:
            paths.add(Path(value))

    system_drive = os.environ.get("SystemDrive", "C:")
    for name in SYSTEM_DIR_NAMES:
        paths.add(Path(system_drive) / name)
    return paths


SYSTEM_PATHS = _candidate_system_paths()


def normalize_path(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def is_same_or_child(path: Path, parent: Path) -> bool:
    child_norm = normalize_path(path)
    parent_norm = normalize_path(parent)
    return child_norm == parent_norm or child_norm.startswith(parent_norm.rstrip("\\/") + os.sep)


def is_protected_path(path: Path) -> bool:
    try:
        if path.name in SYSTEM_DIR_NAMES:
            return True
    except OSError:
        return True

    return any(is_same_or_child(path, protected) for protected in SYSTEM_PATHS)


def validate_scan_root(root: Path) -> Path:
    resolved = root.expanduser().resolve(strict=False)
    if is_protected_path(resolved):
        raise ValueError(f"出于安全考虑，不允许扫描系统目录：{resolved}")
    return resolved
