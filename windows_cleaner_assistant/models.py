from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

RISK_RECOMMENDED = "推荐清理"
RISK_CAUTION = "谨慎处理"
RISK_NOT_RECOMMENDED = "不建议删除"
RISK_LEVELS = {RISK_RECOMMENDED, RISK_CAUTION, RISK_NOT_RECOMMENDED}

RECOMMENDED_KEYWORDS = (
    "Temp",
    "DXCache",
    "GraphicsCache",
    "__pycache__",
    ".pyc",
    ".log",
    ".dmp",
)

CAUTION_KEYWORDS = (
    "Tencent",
    "WeChat",
    "WXWork",
    "QQ",
    "JetBrains",
    "Microsoft\\Edge",
    "CapCut",
)

NOT_RECOMMENDED_KEYWORDS = (
    "Windows",
    "Program Files",
    "ProgramData",
    "pagefile.sys",
)

NOT_RECOMMENDED_SUFFIXES = {".dll", ".exe", ".sys"}


@dataclass(frozen=True)
class ScanItem:
    category: str
    path: Path
    item_type: str
    size_bytes: int
    reason: str
    duplicate_group: str = ""
    checksum: str = ""
    risk_level: str = ""
    suggestion: str = ""

    def __post_init__(self) -> None:
        risk_level, suggestion = classify_risk(self.path)
        if self.risk_level:
            if self.risk_level not in RISK_LEVELS:
                raise ValueError(f"不支持的风险等级：{self.risk_level}")
            risk_level = self.risk_level
        if self.suggestion:
            suggestion = self.suggestion

        object.__setattr__(self, "risk_level", risk_level)
        object.__setattr__(self, "suggestion", suggestion)

    @property
    def display_size(self) -> str:
        return format_size(self.size_bytes)


def scan_item_key(item: ScanItem) -> str:
    return "\0".join(
        [
            str(item.path),
            item.category,
            item.reason,
            item.duplicate_group,
            item.checksum,
        ]
    )


def classify_risk(path: Path) -> tuple[str, str]:
    path_text = str(path)
    path_lower = path_text.lower()
    normalized_path_lower = path_lower.replace("/", "\\")
    suffix = path.suffix.lower()

    if suffix in NOT_RECOMMENDED_SUFFIXES or contains_any(normalized_path_lower, NOT_RECOMMENDED_KEYWORDS):
        return RISK_NOT_RECOMMENDED, "疑似系统、程序或关键运行文件，默认禁止删除。"

    if contains_any(normalized_path_lower, CAUTION_KEYWORDS):
        return RISK_CAUTION, "可能属于常用软件数据，请确认用途并备份后再处理。"

    if contains_any(normalized_path_lower, RECOMMENDED_KEYWORDS):
        return RISK_RECOMMENDED, "通常属于缓存、日志或转储文件，可优先考虑清理。"

    return RISK_CAUTION, "无法明确判断是否可清理，请人工确认后再处理。"


def contains_any(path_lower: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword.lower() in path_lower for keyword in keywords)


def format_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024
