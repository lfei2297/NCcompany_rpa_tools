"""读写排查 Excel。"""

from __future__ import annotations

import io
import re
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
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
    "出现位置",
    "促销文案",
    "系统检查结果",
    "含包邮",
    "是否人工复核",
    "测算说明",
]

# Excel 单元格换行必须是 LF，并打开 wrap_text，否则看起来仍是一行
WRAP_ALIGN = Alignment(wrap_text=True, vertical="top")
WRAP_COLS = {"促销文案", "测算说明"}
HIGHLIGHT_RE = re.compile(r"(不符|包邮|Free\s+Shipping)", re.I)
_RED_FONT = InlineFont(color="FF0000", b=True)


def cell_plain_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, CellRichText):
        return "".join(str(p) for p in value)
    return str(value)


def excel_multiline(text) -> str:
    """把测算说明写成 Excel 能显示的多行：单元格内 LF 换行，并打开自动换行。

    顺带把旧结果里的「 | 」拆开，避免看起来仍是一整段。
    """
    t = cell_plain_text(text).replace("\r\n", "\n").replace("\r", "\n")
    t = t.replace(" | ", "\n")
    while "\n\n\n" in t:
        t = t.replace("\n\n\n", "\n\n")
    return t.strip()


def to_rich_text(text) -> str | CellRichText:
    """「不符」「包邮」标红，其余保持原样。"""
    t = excel_multiline(text)
    if not t or not HIGHLIGHT_RE.search(t):
        return t
    blocks: list = []
    pos = 0
    for m in HIGHLIGHT_RE.finditer(t):
        if m.start() > pos:
            blocks.append(t[pos : m.start()])
        blocks.append(TextBlock(_RED_FONT, m.group(0)))
        pos = m.end()
    if pos < len(t):
        blocks.append(t[pos:])
    return CellRichText(*blocks)


def highlight_html(text: str) -> str:
    """页面测算说明里把「不符」「包邮」标红。先转义再插入标签。"""
    body = excel_multiline(text or "")
    escaped = (
        body.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>")
    )
    return HIGHLIGHT_RE.sub(
        r"<span style='color:#d32f2f;font-weight:700'>\1</span>",
        escaped,
    )


def _row_height_for(text: str) -> float:
    lines = excel_multiline(text).count("\n") + 1
    return min(18 * max(lines, 2) + 8, 240)


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


def _cell_url_text(cell) -> str:
    if cell is None:
        return ""
    if getattr(cell, "hyperlink", None) is not None and cell.hyperlink.target:
        return str(cell.hyperlink.target).strip()
    if cell.value is None:
        return ""
    return str(cell.value).strip()


def _urls_in_cell(cell) -> list[str]:
    raw = _cell_url_text(cell)
    if not raw:
        return []
    found = re.findall(r"https?://[^\s<>\"']+", raw, flags=re.I)
    if found:
        return [u.rstrip(".,);，。") for u in found]
    if _looks_like_url(raw):
        return [raw]
    return []


def read_links(path: str | Path | bytes, url_column: int = 1) -> list[dict]:
    """读取第一列（默认）链接，保留同行其它列。同一格多个网址会拆开。"""
    if isinstance(path, (bytes, bytearray)):
        wb = load_workbook(io.BytesIO(path), data_only=True)
    else:
        wb = load_workbook(path, data_only=True)
    ws = wb.active
    rows: list[dict] = []
    header_row = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    first = header_row[url_column - 1] if header_row else None
    start = 2
    if first is not None and not _looks_like_url(str(first or "")):
        start = 2
    else:
        start = 1
        header_row = []

    for row in ws.iter_rows(min_row=start, values_only=False):
        cells = list(row)
        if not cells:
            continue
        urls: list[str] = []
        if len(cells) >= url_column:
            urls = _urls_in_cell(cells[url_column - 1])
        if not urls:
            for cell in cells:
                urls = _urls_in_cell(cell)
                if urls:
                    break
        if not urls:
            continue
        extra = {}
        if header_row:
            for i, cell in enumerate(cells, 1):
                if i == url_column:
                    continue
                if i > len(header_row) or not header_row[i - 1]:
                    continue
                extra[str(header_row[i - 1])] = cell.value
        for url in urls:
            rows.append({"url": url, "extra": extra})
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
    detail_col = headers.index("测算说明") + 1
    promo_col = headers.index("促销文案") + 1
    for item, extra in results:
        promo = excel_multiline(item.promo_text_joined)
        detail = excel_multiline(item.reason_detail or item.note)
        row = [
            item.source_url,
            item.checkout_url,
            "是" if item.jumped else "否",
            item.copy_type,
            item.locations_joined,
            promo,
            item.system_result,
            item.has_shipping,
            item.need_review,
            detail,
        ]
        for h in extra_headers:
            row.append(extra.get(h))
        ws.append(row)
        fill = FILL.get(item.system_result)
        ridx = ws.max_row
        ws.cell(ridx, promo_col).value = to_rich_text(promo)
        ws.cell(ridx, detail_col).value = to_rich_text(detail)
        for cell in ws[ridx]:
            cell.alignment = WRAP_ALIGN
            if fill:
                cell.fill = fill
        ws.row_dimensions[ridx].height = max(
            _row_height_for(promo),
            _row_height_for(detail),
        )
    widths = [48, 48, 14, 18, 22, 42, 16, 10, 14, 68] + [18] * len(extra_headers)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.auto_filter.ref = ws.dimensions
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 22
    ws.column_dimensions[get_column_letter(detail_col)].width = 68
    ws.column_dimensions[get_column_letter(promo_col)].width = 42
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


def rewrite_workbook_wrap(wb) -> None:
    ws = wb.active
    headers = [c.value for c in ws[1]]
    wrap_idx = [i for i, h in enumerate(headers, 1) if h in WRAP_COLS]
    for r in range(2, ws.max_row + 1):
        tallest = 36.0
        for c in wrap_idx:
            cell = ws.cell(r, c)
            plain = excel_multiline(cell.value)
            cell.value = to_rich_text(plain)
            cell.alignment = WRAP_ALIGN
            tallest = max(tallest, _row_height_for(plain))
        for cell in ws[r]:
            cell.alignment = WRAP_ALIGN
        ws.row_dimensions[r].height = tallest


def rewrite_result_bytes(data: bytes) -> bytes:
    wb = load_workbook(io.BytesIO(data), rich_text=True)
    rewrite_workbook_wrap(wb)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def rewrite_result_xlsx(path: str | Path) -> Path:
    """把已导出表的「促销文案 / 测算说明」改成单元格内换行。"""
    path = Path(path)
    wb = load_workbook(path, rich_text=True)
    rewrite_workbook_wrap(wb)
    wb.save(path)
    return path
