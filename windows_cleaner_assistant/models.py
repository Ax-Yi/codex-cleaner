from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScanItem:
    category: str
    path: Path
    item_type: str
    size_bytes: int
    reason: str
    duplicate_group: str = ""
    checksum: str = ""

    @property
    def display_size(self) -> str:
        return format_size(self.size_bytes)


def format_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024
