from __future__ import annotations

import shutil
from pathlib import Path

from .safety import is_protected_path


def delete_path(path: Path) -> tuple[bool, str]:
    if is_protected_path(path):
        return False, "已阻止删除系统目录或系统目录内文件"

    try:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
        else:
            return False, "路径不存在"
    except (OSError, PermissionError) as exc:
        return False, str(exc)

    return True, "已删除"
