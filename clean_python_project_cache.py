from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


CACHE_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".streamlit",
    "dist",
    "build",
}

ASK_BEFORE_DELETE_DIR_NAMES = {
    ".venv",
}

CACHE_FILE_PATTERNS = {
    "*.pyc",
}

TEMP_LOG_PATTERNS = {
    "*.log",
    "*.log.*",
    "*.tmp",
    "*.temp",
}

PROTECTED_FILE_PATTERNS = {
    ".env",
    ".env.*",
    ".gitignore",
    "README",
    "README.*",
    "requirements.txt",
    "*config*",
    "*cookie*",
    "*cookies*",
    "*credential*",
    "*token*",
    "*secret*",
    "*api_key*",
    "*apikey*",
    "*.key",
    "*.pem",
}

PROTECTED_DIR_NAMES = {
    ".git",
}


@dataclass(frozen=True)
class Candidate:
    path: str
    kind: str
    category: str
    size_bytes: int
    reason: str
    requires_confirmation: bool = False


@dataclass(frozen=True)
class SkippedItem:
    path: str
    reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run first cleaner for common Python project cache files.",
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Python project directory to scan. Defaults to the current directory.",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Actually delete matched files and directories. Without this flag, only dry-run.",
    )
    parser.add_argument(
        "--json-report",
        metavar="PATH",
        help="Write a JSON report to this path.",
    )
    parser.add_argument(
        "--yes-venv",
        action="store_true",
        help="Allow deleting .venv without an interactive prompt. Use with care.",
    )
    return parser.parse_args()


def is_match(name: str, patterns: set[str]) -> bool:
    lowered = name.lower()
    return any(fnmatch.fnmatchcase(lowered, pattern.lower()) for pattern in patterns)


def is_protected_file(path: Path) -> bool:
    return is_match(path.name, PROTECTED_FILE_PATTERNS)


def is_protected_dir(path: Path) -> bool:
    return path.name in PROTECTED_DIR_NAMES


def is_under_path(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def safe_resolve(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def format_size(size: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{size} B"


def path_size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0

    total = 0
    for current, dirs, files in os.walk(path, topdown=True, followlinks=False):
        dirs[:] = [name for name in dirs if not is_protected_dir(Path(current) / name)]
        for filename in files:
            file_path = Path(current) / filename
            try:
                total += file_path.stat().st_size
            except OSError:
                continue
    return total


def contains_protected_file(path: Path) -> bool:
    if path.is_file():
        return is_protected_file(path)

    for current, dirs, files in os.walk(path, topdown=True, followlinks=False):
        current_path = Path(current)
        dirs[:] = [name for name in dirs if not is_protected_dir(current_path / name)]
        for filename in files:
            if is_protected_file(current_path / filename):
                return True
    return False


def collect_candidates(root: Path) -> tuple[list[Candidate], list[SkippedItem]]:
    root = safe_resolve(root)
    candidates: dict[Path, Candidate] = {}
    skipped: list[SkippedItem] = []

    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        next_dirs: list[str] = []

        for dirname in dirs:
            path = current_path / dirname
            if is_protected_dir(path):
                continue
            if path.is_symlink():
                skipped.append(SkippedItem(str(path), "skip symlink"))
                continue

            if dirname in CACHE_DIR_NAMES:
                if contains_protected_file(path):
                    skipped.append(
                        SkippedItem(
                            str(path),
                            "contains protected file name such as .env/config/token/api_key/README/requirements.txt",
                        )
                    )
                    continue
                candidates[path] = Candidate(
                    path=str(path),
                    kind="directory",
                    category="cache/build directory",
                    size_bytes=path_size(path),
                    reason=f"matched directory name: {path.name}",
                    )
                continue

            if dirname in ASK_BEFORE_DELETE_DIR_NAMES:
                if contains_protected_file(path):
                    skipped.append(
                        SkippedItem(
                            str(path),
                            "virtual environment contains protected file name; manual review required",
                        )
                    )
                    continue
                candidates[path] = Candidate(
                    path=str(path),
                    kind="directory",
                    category="virtual environment",
                    size_bytes=path_size(path),
                    reason=".venv requires separate confirmation before deletion",
                    requires_confirmation=True,
                )
                continue

            next_dirs.append(dirname)

        dirs[:] = next_dirs

        for filename in files:
            path = current_path / filename
            if path.is_symlink():
                skipped.append(SkippedItem(str(path), "skip symlink"))
                continue
            if is_protected_file(path):
                continue

            if is_match(path.name, CACHE_FILE_PATTERNS):
                candidates[path] = Candidate(
                    path=str(path),
                    kind="file",
                    category="python bytecode",
                    size_bytes=path_size(path),
                    reason="matched file pattern: *.pyc",
                )
            elif is_match(path.name, TEMP_LOG_PATTERNS):
                candidates[path] = Candidate(
                    path=str(path),
                    kind="file",
                    category="temporary log",
                    size_bytes=path_size(path),
                    reason="matched temporary log pattern",
                )

    # Empty directories are handled after direct candidates so nested cache dirs win.
    for current, dirs, files in os.walk(root, topdown=False, followlinks=False):
        current_path = Path(current)
        if current_path == root or is_protected_dir(current_path):
            continue
        if any(is_under_path(current_path, selected) for selected in candidates):
            continue
        try:
            if not any(current_path.iterdir()):
                candidates[current_path] = Candidate(
                    path=str(current_path),
                    kind="directory",
                    category="empty directory",
                    size_bytes=0,
                    reason="directory is empty",
                )
        except OSError:
            skipped.append(SkippedItem(str(current_path), "cannot inspect directory"))

    ordered = sorted(
        candidates.values(),
        key=lambda item: (item.requires_confirmation, item.kind, item.path.lower()),
    )
    return ordered, skipped


def confirm_venv_deletion(candidates: list[Candidate], yes_venv: bool) -> set[str]:
    venv_paths = {item.path for item in candidates if item.requires_confirmation}
    if not venv_paths or yes_venv:
        return venv_paths

    print("\nFound .venv directories. They are not deleted unless you confirm separately:")
    for path in sorted(venv_paths):
        print(f"  - {path}")
    answer = input("Delete these .venv directories too? Type 'delete .venv' to confirm: ")
    if answer.strip() == "delete .venv":
        return venv_paths
    return set()


def delete_candidates(candidates: list[Candidate], allowed_venv: set[str]) -> tuple[list[str], list[SkippedItem]]:
    deleted: list[str] = []
    skipped: list[SkippedItem] = []

    for item in sorted(candidates, key=lambda candidate: len(candidate.path), reverse=True):
        if item.requires_confirmation and item.path not in allowed_venv:
            skipped.append(SkippedItem(item.path, ".venv deletion was not confirmed"))
            continue

        path = Path(item.path)
        try:
            if item.kind == "directory":
                shutil.rmtree(path)
            else:
                path.unlink()
            deleted.append(item.path)
        except FileNotFoundError:
            skipped.append(SkippedItem(item.path, "already removed"))
        except OSError as exc:
            skipped.append(SkippedItem(item.path, f"delete failed: {exc}"))

    return deleted, skipped


def print_report(
    root: Path,
    dry_run: bool,
    candidates: list[Candidate],
    skipped: list[SkippedItem],
    deleted: list[str] | None = None,
) -> None:
    total_size = sum(item.size_bytes for item in candidates)
    print("\nPython project cleanup report")
    print("=" * 31)
    print(f"Root: {root}")
    print(f"Mode: {'dry-run' if dry_run else 'delete'}")
    print(f"Candidates: {len(candidates)}")
    print(f"Potential reclaim: {format_size(total_size)}")

    if candidates:
        print("\nCandidates:")
        for item in candidates:
            suffix = " [requires .venv confirmation]" if item.requires_confirmation else ""
            print(f"- {item.category}: {item.path} ({format_size(item.size_bytes)}){suffix}")
            print(f"  reason: {item.reason}")

    if skipped:
        print("\nSkipped:")
        for item in skipped:
            print(f"- {item.path}")
            print(f"  reason: {item.reason}")

    if deleted is not None:
        print("\nDeleted:")
        if deleted:
            for path in deleted:
                print(f"- {path}")
        else:
            print("- nothing")

    if dry_run:
        print("\nNo files were deleted. Re-run with --delete to delete non-.venv candidates.")


def write_json_report(
    report_path: Path,
    root: Path,
    dry_run: bool,
    candidates: list[Candidate],
    skipped: list[SkippedItem],
    deleted: list[str],
) -> None:
    payload = {
        "root": str(root),
        "mode": "dry-run" if dry_run else "delete",
        "candidate_count": len(candidates),
        "potential_reclaim_bytes": sum(item.size_bytes for item in candidates),
        "candidates": [asdict(item) for item in candidates],
        "skipped": [asdict(item) for item in skipped],
        "deleted": deleted,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    root = safe_resolve(Path(args.root))
    if not root.exists() or not root.is_dir():
        print(f"error: scan root is not a directory: {root}", file=sys.stderr)
        return 2

    candidates, skipped = collect_candidates(root)
    deleted: list[str] = []

    if args.delete:
        allowed_venv = confirm_venv_deletion(candidates, args.yes_venv)
        deleted, delete_skipped = delete_candidates(candidates, allowed_venv)
        skipped.extend(delete_skipped)

    print_report(root, not args.delete, candidates, skipped, deleted if args.delete else None)

    if args.json_report:
        write_json_report(
            safe_resolve(Path(args.json_report)),
            root,
            not args.delete,
            candidates,
            skipped,
            deleted,
        )
        print(f"\nJSON report written: {safe_resolve(Path(args.json_report))}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
