from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import ScanItem, format_size

HISTORY_PATH = Path("history.json")


def build_history_record(items: list[ScanItem], scan_root: Path) -> dict[str, Any]:
    risk_counts = Counter(item.risk_level for item in items)
    risk_sizes = risk_size_totals(items)
    duplicate_group_count = len({item.duplicate_group for item in items if item.duplicate_group})
    total_size = sum(item.size_bytes for item in items)

    return {
        "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scan_root": str(scan_root),
        "result_count": len(items),
        "total_size_bytes": total_size,
        "total_size": format_size(total_size),
        "recommended_count": risk_counts.get("推荐清理", 0),
        "recommended_size_bytes": risk_sizes.get("推荐清理", 0),
        "recommended_size": format_size(risk_sizes.get("推荐清理", 0)),
        "caution_count": risk_counts.get("谨慎处理", 0),
        "caution_size_bytes": risk_sizes.get("谨慎处理", 0),
        "caution_size": format_size(risk_sizes.get("谨慎处理", 0)),
        "not_recommended_count": risk_counts.get("不建议删除", 0),
        "not_recommended_size_bytes": risk_sizes.get("不建议删除", 0),
        "not_recommended_size": format_size(risk_sizes.get("不建议删除", 0)),
        "duplicate_group_count": duplicate_group_count,
    }


def load_scan_history() -> list[dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []
    try:
        with HISTORY_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [record for record in data if isinstance(record, dict)]


def save_scan_history(items: list[ScanItem], scan_root: Path) -> None:
    records = load_scan_history()
    records.append(build_history_record(items, scan_root))
    with HISTORY_PATH.open("w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2)


def clear_scan_history() -> None:
    with HISTORY_PATH.open("w", encoding="utf-8") as handle:
        json.dump([], handle, ensure_ascii=False, indent=2)


def risk_size_totals(items: list[ScanItem]) -> dict[str, int]:
    totals = {"推荐清理": 0, "谨慎处理": 0, "不建议删除": 0}
    for item in items:
        totals[item.risk_level] = totals.get(item.risk_level, 0) + item.size_bytes
    return totals
