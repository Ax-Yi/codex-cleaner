from __future__ import annotations

import html
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import quoteattr

from .models import ScanItem, format_size, scan_item_key


def export_scan_results(
    path: Path,
    items: list[ScanItem],
    scan_root: Path,
    report_text: str,
    checked_keys: set[str] | None = None,
) -> None:
    checked_keys = checked_keys or set()
    sheets = [
        ("清理报告", report_rows(items, scan_root, report_text)),
        ("清理建议", advice_rows(items, scan_root)),
        ("重复文件分组", duplicate_group_rows(items, checked_keys)),
        ("扫描结果", result_rows(items)),
    ]

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml(len(sheets)))
        archive.writestr("_rels/.rels", root_rels_xml())
        archive.writestr("xl/workbook.xml", workbook_xml([name for name, _rows in sheets]))
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml(len(sheets)))
        archive.writestr("xl/styles.xml", styles_xml())
        for index, (_name, rows) in enumerate(sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", sheet_xml(rows))


def report_rows(items: list[ScanItem], scan_root: Path, report_text: str) -> list[list[object]]:
    counts = Counter(item.category for item in items)
    total_size = sum(item.size_bytes for item in items)
    rows: list[list[object]] = [
        ["Windows 本地电脑清理助手报告", ""],
        ["生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ["扫描目录", str(scan_root)],
        ["扫描结果数量", len(items)],
        ["结果总大小（字节）", total_size],
        [],
        ["分类", "数量"],
    ]
    rows.extend([[category, count] for category, count in sorted(counts.items())])
    rows.extend([[], ["风险等级", "数量"]])
    rows.extend([[risk, count] for risk, count in sorted(Counter(item.risk_level for item in items).items())])
    rows.extend([[], ["报告摘要", ""]])
    rows.extend([[line, ""] for line in report_text.splitlines()])
    return rows


def advice_rows(items: list[ScanItem], scan_root: Path) -> list[list[object]]:
    risk_counts = Counter(item.risk_level for item in items)
    risk_sizes = risk_size_totals(items)
    rows: list[list[object]] = [
        ["清理建议", ""],
        ["扫描目录", str(scan_root)],
        ["扫描时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ["总结果数量", len(items)],
        ["总文件大小", format_size(sum(item.size_bytes for item in items))],
        ["推荐清理数量", risk_counts.get("推荐清理", 0)],
        ["推荐清理大小", format_size(risk_sizes.get("推荐清理", 0))],
        ["谨慎处理数量", risk_counts.get("谨慎处理", 0)],
        ["谨慎处理大小", format_size(risk_sizes.get("谨慎处理", 0))],
        ["不建议删除数量", risk_counts.get("不建议删除", 0)],
        ["不建议删除大小", format_size(risk_sizes.get("不建议删除", 0))],
        [],
        ["建议文字", ""],
    ]
    rows.extend([[message, ""] for message in build_cleaning_advice(items)])
    return rows


def risk_size_totals(items: list[ScanItem]) -> dict[str, int]:
    totals = {"推荐清理": 0, "谨慎处理": 0, "不建议删除": 0}
    for item in items:
        totals[item.risk_level] = totals.get(item.risk_level, 0) + item.size_bytes
    return totals


def build_cleaning_advice(items: list[ScanItem]) -> list[str]:
    paths = [str(item.path).lower().replace("/", "\\") for item in items]
    categories = {item.category for item in items}
    advice: list[str] = []

    if "Python 缓存" in categories or any("__pycache__" in path or path.endswith(".pyc") for path in paths):
        advice.append("存在 Python 缓存，建议优先清理 Python 缓存。")
    if any("temp" in path for path in paths):
        advice.append("存在 Temp 临时文件，建议优先清理临时文件。")
    if any("dxcache" in path for path in paths):
        advice.append("存在 NVIDIA DXCache，缓存可以清理，但下次启动游戏可能重新生成。")
    if any("graphicscache" in path for path in paths):
        advice.append("存在 GraphicsCache，游戏图形缓存可以清理，但游戏可能重新生成。")
    if any(keyword in path for path in paths for keyword in ("tencent", "wechat", "wxwork", "qq")):
        advice.append("存在 Tencent、WeChat、WXWork 或 QQ 目录，聊天软件数据需谨慎处理。")
    if any(keyword in path for path in paths for keyword in ("pagefile.sys", "windows", "program files")):
        advice.append("存在 pagefile.sys、Windows 或 Program Files 相关路径，系统关键文件不建议处理。")

    if not advice:
        advice.append("未发现明确路径建议，请结合风险等级人工判断。")
    advice.append("清理建议只做提示，不会自动勾选或自动处理文件。")
    return advice


def result_rows(items: list[ScanItem]) -> list[list[object]]:
    rows: list[list[object]] = [
        ["分类", "类型", "风险等级", "处理建议", "大小", "大小（字节）", "原因", "重复组", "SHA-256", "路径"]
    ]
    for item in items:
        rows.append(
            [
                item.category,
                item.item_type,
                item.risk_level,
                item.suggestion,
                item.display_size,
                item.size_bytes,
                item.reason,
                item.duplicate_group,
                item.checksum,
                str(item.path),
            ]
        )
    return rows


def duplicate_group_rows(items: list[ScanItem], checked_keys: set[str]) -> list[list[object]]:
    rows: list[list[object]] = [
        ["重复组编号", "文件路径", "文件大小", "修改时间", "是否推荐保留", "是否被勾选", "风险等级", "处理建议"]
    ]
    for group_id, group_items in sorted(duplicate_groups(items).items()):
        recommended = recommended_duplicate_keep(group_items)
        for item in sorted(group_items, key=lambda value: str(value.path).lower()):
            rows.append(
                [
                    group_id,
                    str(item.path),
                    item.display_size,
                    format_modified_time(item.path),
                    "谨慎处理，请手动确认"
                    if recommended is None
                    else "是"
                    if scan_item_key(item) == scan_item_key(recommended)
                    else "否",
                    "是" if scan_item_key(item) in checked_keys else "否",
                    item.risk_level,
                    item.suggestion,
                ]
            )
    return rows


def duplicate_groups(items: list[ScanItem]) -> dict[str, list[ScanItem]]:
    groups: dict[str, list[ScanItem]] = {}
    for item in items:
        if item.duplicate_group:
            groups.setdefault(item.duplicate_group, []).append(item)
    return {group_id: group_items for group_id, group_items in groups.items() if len(group_items) > 1}


def recommended_duplicate_keep(items: list[ScanItem]) -> ScanItem | None:
    if any(path_requires_manual_duplicate_review(item.path) for item in items):
        return None
    return sorted(items, key=lambda item: (-modified_timestamp(item.path), len(str(item.path)), str(item.path).lower()))[0]


def path_requires_manual_duplicate_review(path: Path) -> bool:
    normalized = str(path).lower().replace("/", "\\")
    keywords = (
        "windows",
        "program files",
        "programdata",
        "tencent",
        "wechat",
        "wxwork",
        "qq",
    )
    return any(keyword in normalized for keyword in keywords)


def modified_timestamp(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except (OSError, PermissionError):
        return 0.0


def format_modified_time(path: Path) -> str:
    timestamp = modified_timestamp(path)
    if not timestamp:
        return "无法读取"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def content_types_xml(sheet_count: int) -> str:
    sheet_overrides = "\n".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, sheet_count + 1)
    )
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  {sheet_overrides}
</Types>'''


def root_rels_xml() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''


def workbook_xml(sheet_names: list[str]) -> str:
    sheets_xml = "\n".join(
        f'    <sheet name={quoteattr(name)} sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(sheet_names, start=1)
    )
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
{sheets_xml}
  </sheets>
</workbook>'''


def workbook_rels_xml(sheet_count: int) -> str:
    relationships = "\n".join(
        f'  <Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, sheet_count + 1)
    )
    relationships += (
        f'\n  <Relationship Id="rId{sheet_count + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    )
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
{relationships}
</Relationships>'''


def styles_xml() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>
  <fills count="1"><fill><patternFill patternType="none"/></fill></fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''


def sheet_xml(rows: list[list[object]]) -> str:
    row_xml = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row, start=1):
            cells.append(cell_xml(row_index, column_index, value))
        row_xml.append(f'    <row r="{row_index}">{"".join(cells)}</row>')

    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetViews><sheetView workbookViewId="0"/></sheetViews>
  <sheetData>
{chr(10).join(row_xml)}
  </sheetData>
</worksheet>'''


def cell_xml(row_index: int, column_index: int, value: object) -> str:
    ref = f"{column_name(column_index)}{row_index}"
    if isinstance(value, int | float):
        return f'<c r="{ref}"><v>{value}</v></c>'
    escaped = html.escape(str(value), quote=False)
    return f'<c r="{ref}" t="inlineStr"><is><t>{escaped}</t></is></c>'


def column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name
