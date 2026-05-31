from __future__ import annotations

from pathlib import Path

from .safety import is_protected_path

SEND2TRASH_INSTALL_MESSAGE = "请先运行：python -m pip install send2trash"


def send2trash_available() -> bool:
    try:
        import send2trash  # noqa: F401
    except ImportError:
        return False
    return True


def delete_path(path: Path) -> tuple[bool, str]:
    if is_protected_path(path):
        return False, "已阻止移动系统目录或系统目录内文件"

    try:
        from send2trash import send2trash
    except ImportError:
        return False, SEND2TRASH_INSTALL_MESSAGE

    try:
        if not path.exists():
            return False, "路径不存在"
        send2trash(str(path))
    except Exception as exc:
        return False, str(exc)

    return True, "已移动到回收站"
