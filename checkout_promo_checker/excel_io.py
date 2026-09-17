"""读写排查 Excel。"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from checker import (
    SYS_CALC_FAIL,
    SYS_FAIL,
    SYS_MATCH,
    SYS_MISMATCH,
    SYS_NONE,
    SYS_PURE,
    CheckResult,
)

FILL = {
    SYS_NONE: PatternFill("solid", fgColor="E2EFDA"),
    SYS_MATCH: PatternFill("solid", fgColor="FFF2CC"),
    SYS_MISMATCH: PatternFill("solid", fgColor="FFC7CE"),
    SYS_PURE: PatternFill("solid", fgColor="FCE4D6"),
    SYS_CALC_FAIL: PatternFill("solid", fgColor="FCE4D6"),
    SYS_FAIL: PatternFill("solid", fgColor="D9D9D9"),
}

# 输入表里的「类型」常带「无需整改」，输出改用本工具自己的类型列
SKIP_EXTRA_HEADERS = {"类型"}

HEADERS = [
    "原链接",
    "结账页链接",
    "是否跳转结账页",
    "类型",
    "促销文案",
    "系统检查结果",
    "是否人工复核",
    "测算说明",
]


def make_input_template() -> bytes:
    """给同事用的空表：第一列放单页链接。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "链接"
    ws["A1"] = "一页商店链接"
    ws["A1"].font = Font(bold=True, color="FFFFFF")
    ws["A1"].fill = PatternFill("solid", fgColor="305496")
    ws.column_dimensions["A"].width = 72
    ws["A2"] = "https://example.com/pages/news-demo-m"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def read_links(path: str | Path | bytes, url_column: int = 1) -> list[dict]:
    """读取第一列（默认）链接，保留同行其它列。"""
    if isinstance(path, (bytes, bytearray)):
        wb = load_workbook(io.BytesIO(path), data_only=True)
    else:
        wb = load_workbook(path, data_only=True)
    ws = wb.active
    rows: list[dict] = []
    header_row = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    first = header_row[url_column - 1] if header_row else None
    start = 2
    if first is not None and not _looks_like_url(str(first)):
        start = 2
    else:
        start = 1
        header_row = []

    for row in ws.iter_rows(min_row=start, values_only=False):
        cells = list(row)
        if not cells:
            continue
        url_cell = cells[url_column - 1].value if len(cells) >= url_column else None
        if url_cell is None or str(url_cell).strip() == "":
            continue
        extra = {}
        if header_row:
            for i, cell in enumerate(cells, 1):
                if i == url_column:
                    continue
                if i > len(header_row) or not header_row[i - 1]:
                    continue
                extra[str(header_row[i - 1])] = cell.value
        rows.append({"url": str(url_cell).strip(), "extra": extra})
    return rows


def _looks_like_url(text: str) -> bool:
    t = text.strip().lower()
    return t.startswith("http") or "." in t and "/" in t


def write_results_bytes(
    results: list[tuple[CheckResult, dict]],
    extra_headers: list[str] | None = None,
) -> bytes:
    extra_headers = [h for h in (extra_headers or []) if h not in SKIP_EXTRA_HEADERS]
    wb = Workbook()
    ws = wb.active
    ws.title = "排查结果"
    headers = HEADERS + extra_headers
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="305496")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    wrap = Alignment(wrap_text=True, vertical="center")
    for item, extra in results:
        row = [
            item.source_url,
            item.checkout_url,
            "是" if item.jumped else "否",
            item.copy_type,
            item.promo_text_joined,
            item.system_result,
            item.need_review,
            item.reason_detail or item.note,
        ]
        for h in extra_headers:
            row.append(extra.get(h))
        ws.append(row)
        fill = FILL.get(item.system_result)
        for cell in ws[ws.max_row]:
            cell.alignment = wrap
            if fill:
                cell.fill = fill
    widths = [48, 48, 14, 18, 56, 28, 14, 72] + [18] * len(extra_headers)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.auto_filter.ref = ws.dimensions
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 22
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def write_results(
    results: list[tuple[CheckResult, dict]],
    output_path: str | Path,
    extra_headers: list[str] | None = None,
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(write_results_bytes(results, extra_headers))
    return output_path


def default_output_path(folder: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return folder / f"促销文案排查结果_{ts}.xlsx"
