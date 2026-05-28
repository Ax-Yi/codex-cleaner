from __future__ import annotations

import fnmatch
import hashlib
import os
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable

from .models import ScanItem
from .safety import is_protected_path, validate_scan_root

ProgressCallback = Callable[[str], None]

PYTHON_CACHE_DIRS = {
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    "htmlcov",
}

PYTHON_CACHE_PATTERNS = (
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".coverage",
    "coverage.xml",
)

PRIVACY_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.ovpn",
    "*.kdbx",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "credentials.json",
    "token.json",
    "*password*",
    "*passwd*",
    "*secret*",
    "*credential*",
    "*private*key*",
    "wallet.dat",
)


class CleanerScanner:
    def __init__(self, progress: ProgressCallback | None = None) -> None:
        self.progress = progress or (lambda _message: None)

    def iter_files(self, root: Path) -> Iterable[Path]:
        root = validate_scan_root(root)
        stack = [root]
        while stack:
            current = stack.pop()
            self.progress(f"正在扫描：{current}")
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        path = Path(entry.path)
                        try:
                            if entry.is_symlink() or is_protected_path(path):
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(path)
                            elif entry.is_file(follow_symlinks=False):
                                yield path
                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError):
                continue

    def iter_dirs(self, root: Path) -> Iterable[Path]:
        root = validate_scan_root(root)
        stack = [root]
        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        path = Path(entry.path)
                        try:
                            if entry.is_symlink() or is_protected_path(path):
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                yield path
                                stack.append(path)
                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError):
                continue

    def scan_large_files(self, root: Path, min_size_mb: int = 100) -> list[ScanItem]:
        min_size = max(1, min_size_mb) * 1024 * 1024
        results: list[ScanItem] = []
        for path in self.iter_files(root):
            try:
                size = path.stat().st_size
            except (OSError, PermissionError):
                continue
            if size >= min_size:
                results.append(
                    ScanItem(
                        category="大文件",
                        path=path,
                        item_type="文件",
                        size_bytes=size,
                        reason=f"文件大小不小于 {min_size_mb} MB",
                    )
                )
        return sorted(results, key=lambda item: item.size_bytes, reverse=True)

    def scan_python_caches(self, root: Path) -> list[ScanItem]:
        results: list[ScanItem] = []
        root = validate_scan_root(root)
        stack = [root]

        while stack:
            current = stack.pop()
            self.progress(f"正在扫描 Python 缓存：{current}")
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        path = Path(entry.path)
                        try:
                            if entry.is_symlink() or is_protected_path(path):
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                if path.name in PYTHON_CACHE_DIRS or path.name.endswith(".egg-info"):
                                    results.append(
                                        ScanItem(
                                            category="Python 缓存",
                                            path=path,
                                            item_type="文件夹",
                                            size_bytes=directory_size(path),
                                            reason="Python 项目缓存目录",
                                        )
                                    )
                                else:
                                    stack.append(path)
                            elif entry.is_file(follow_symlinks=False):
                                name = path.name
                                if any(fnmatch.fnmatchcase(name, pattern) for pattern in PYTHON_CACHE_PATTERNS):
                                    results.append(
                                        ScanItem(
                                            category="Python 缓存",
                                            path=path,
                                            item_type="文件",
                                            size_bytes=entry.stat(follow_symlinks=False).st_size,
                                            reason="Python 项目缓存文件",
                                        )
                                    )
                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError):
                continue
        return sorted(results, key=lambda item: os.fspath(item.path).lower())

    def scan_privacy_files(self, root: Path) -> list[ScanItem]:
        results: list[ScanItem] = []
        for path in self.iter_files(root):
            lower_name = path.name.lower()
            if any(fnmatch.fnmatchcase(lower_name, pattern.lower()) for pattern in PRIVACY_PATTERNS):
                try:
                    size = path.stat().st_size
                except (OSError, PermissionError):
                    size = 0
                results.append(
                    ScanItem(
                        category="隐私文件",
                        path=path,
                        item_type="文件",
                        size_bytes=size,
                        reason="文件名疑似包含密钥、凭据、密码或钱包信息；未读取文件内容",
                    )
                )
        return sorted(results, key=lambda item: os.fspath(item.path).lower())

    def scan_duplicate_files(self, root: Path) -> list[ScanItem]:
        size_groups: dict[int, list[Path]] = defaultdict(list)
        for path in self.iter_files(root):
            try:
                size = path.stat().st_size
            except (OSError, PermissionError):
                continue
            if size > 0:
                size_groups[size].append(path)

        hash_groups: dict[tuple[int, str], list[Path]] = defaultdict(list)
        for size, paths in size_groups.items():
            if len(paths) < 2:
                continue
            for path in paths:
                checksum = file_sha256(path)
                if checksum:
                    hash_groups[(size, checksum)].append(path)

        results: list[ScanItem] = []
        group_number = 1
        for (size, checksum), paths in hash_groups.items():
            if len(paths) < 2:
                continue
            group_id = f"DUP-{group_number:04d}"
            for path in sorted(paths, key=lambda item: os.fspath(item).lower()):
                results.append(
                    ScanItem(
                        category="重复文件",
                        path=path,
                        item_type="文件",
                        size_bytes=size,
                        reason="文件大小和 SHA-256 哈希完全相同",
                        duplicate_group=group_id,
                        checksum=checksum,
                    )
                )
            group_number += 1
        return results


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
    except (OSError, PermissionError):
        return ""
    return digest.hexdigest()


def directory_size(path: Path) -> int:
    total = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError):
            continue
    return total
