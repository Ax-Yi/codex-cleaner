from __future__ import annotations

import html
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import quoteattr

from .models import ScanItem


def export_scan_results(path: Path, items: list[ScanItem], scan_root: Path, report_text: str) -> None:
    sheets = [
        ("清理报告", report_rows(items, scan_root, report_text)),
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
