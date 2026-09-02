"""
素材版本数量多维统计与排查模块
分组聚合维度：虚拟SKU + 国家 + 素材版本前缀
"""

import io
import re
import time
from collections import Counter
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
import pandas as pd
import streamlit as st

FILL_FAIL = PatternFill("solid", fgColor="FFC7CE")  # 浅红高亮异常项
FILL_HEADER = PatternFill("solid", fgColor="4472C4")  # 蓝底表头
FONT_HEADER = Font(color="FFFFFF", bold=True)
FONT_FAIL = Font(color="9C0006", bold=True)


# ── 生成带国家字段的纯净空白模板 ──────────────────────────────────────────────
def make_template_bytes() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "素材版本填报模板"

    # 仅保留标准表头，不写入任何案例数据行
    headers = ["虚拟SKU", "国家", "素材版本名称", "素材版本数量(总行数)"]
    ws.append(headers)

    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    # 设置表头样式
    for col_idx in range(1, 5):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    # 设置常用列宽与行高
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 38
    ws.column_dimensions["D"].width = 24
    ws.row_dimensions[1].height = 24

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


# ── 前缀与序列号解析 ────────────────────────────────────────────────────────
def extract_prefix_and_num(name: str):
    name = name.strip()
    m = re.match(r"^(.*?)-(\d+)$", name)
    if m:
        return m.group(1), int(m.group(2))
    return name, None


# ── 核心数据处理 ─────────────────────────────────────────────────────────────
def process_version_matrix(file_bytes: bytes):
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes))
    ws = wb.active

    headers = [
        str(cell.value).strip() if cell.value is not None else ""
        for cell in ws[1]
    ]

    sku_col = None
    country_col = None
    ver_name_col = None
    count_col = None

    for idx, h in enumerate(headers, start=1):
        if "SKU" in h.upper():
            sku_col = idx
        elif any(k in h for k in ["国家", "市场", "国家名称", "目的国"]):
            country_col = idx
        elif any(k in h for k in ["素材版本名称", "入库版本", "版本名称"]):
            ver_name_col = idx
        elif any(k in h for k in ["素材版本数量", "版本数量"]):
            count_col = idx

    # 智能列定位回退
    if not sku_col:
        sku_col = 1
    if not country_col:
        country_col = 2
    if not ver_name_col:
        ver_name_col = 3
    if not count_col:
        count_col = 4

    dedup_count_col = count_col + 1
    warning_col = count_col + 2

    # 规范化表头文字
    ws.cell(row=1, column=count_col, value="素材版本数量(总行数)")
    ws.cell(row=1, column=dedup_count_col, value="实际有效版本(去重数)")
    ws.cell(row=1, column=warning_col, value="异常标注(重复/断号遗漏)")

    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for c_idx in [count_col, dedup_count_col, warning_col]:
        cell = ws.cell(row=1, column=c_idx)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    # 1. 逐行向下继承 SKU 与 国家，并提取前缀
    max_row = ws.max_row
    row_records = []
    curr_sku = ""
    curr_country = ""

    for r in range(2, max_row + 1):
        sku_val = ws.cell(row=r, column=sku_col).value
        country_val = ws.cell(row=r, column=country_col).value
        ver_val = ws.cell(row=r, column=ver_name_col).value

        # 空行跳过
        if sku_val is None and country_val is None and ver_val is None:
            continue

        if sku_val is not None and str(sku_val).strip() != "":
            curr_sku = str(sku_val).strip()
        if country_val is not None and str(country_val).strip() != "":
            curr_country = str(country_val).strip()

        ver_str = str(ver_val).strip() if ver_val is not None else ""
        prefix, seq_num = extract_prefix_and_num(ver_str) if ver_str else ("", None)

        row_records.append({
            "row_idx": r,
            "sku": curr_sku,
            "country": curr_country,
            "ver_name": ver_str,
            "prefix": prefix,
            "seq_num": seq_num,
        })

    # 2. 按 (SKU + 国家 + 前缀) 划分连续分组
    groups = []
    current_group = None

    for item in row_records:
        group_key = (item["sku"], item["country"], item["prefix"])
        if current_group is None:
            current_group = {"key": group_key, "items": [item]}
        elif current_group["key"] == group_key:
            current_group["items"].append(item)
        else:
            groups.append(current_group)
            current_group = {"key": group_key, "items": [item]}

    if current_group is not None:
        groups.append(current_group)

    summary_list = []

    # 3. 统计每个分组并回填 Excel
    for grp in groups:
        items = grp["items"]
        sku, country, prefix = grp["key"]

        names = [it["ver_name"] for it in items if it["ver_name"]]
        raw_count = len(names)
        counter = Counter(names)
        unique_count = len(counter)
        dup_names = {name for name, cnt in counter.items() if cnt > 1}

        # 检测连号与断号
        nums = [it["seq_num"] for it in items if it["seq_num"] is not None]
        missing_nums = []
        if len(nums) > 1:
            expected = set(range(min(nums), max(nums) + 1))
            actual = set(nums)
            missing_nums = sorted(expected - actual)

        # 汇总异常
        issues = []
        if dup_names:
            dup_details = [f"'{k}'(x{counter[k]})" for k in dup_names]
            issues.append(f"🔴 重复: {', '.join(dup_details)}")
            # 高亮重复单元格
            for it in items:
                if it["ver_name"] in dup_names:
                    ws.cell(row=it["row_idx"], column=ver_name_col).fill = FILL_FAIL

        if missing_nums:
            issues.append(f"⚠️ 缺少序号: {', '.join('-' + str(n) for n in missing_nums)}")

        status_text = "存在异常" if issues else "正常"
        note_str = " ｜ ".join(issues) if issues else "正常"

        # 回填首行，清空后续行旧统计
        for idx, it in enumerate(items):
            r = it["row_idx"]
            if idx == 0:
                c1 = ws.cell(row=r, column=count_col, value=raw_count)
                c2 = ws.cell(row=r, column=dedup_count_col, value=unique_count)
                c3 = ws.cell(row=r, column=warning_col, value=note_str)

                for cell in (c1, c2):
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                c3.alignment = Alignment(vertical="center")

                if status_text != "正常":
                    c3.font = FONT_FAIL
                    c3.fill = FILL_FAIL
            else:
                ws.cell(row=r, column=count_col, value=None)
                ws.cell(row=r, column=dedup_count_col, value=None)
                ws.cell(row=r, column=warning_col, value=None)

        summary_list.append({
            "虚拟SKU": sku,
            "国家": country,
            "素材前缀": prefix,
            "总行数(普通计数)": raw_count,
            "去重版本数": unique_count,
            "校验状态": status_text,
            "异常明细": note_str,
        })

    # 设置列宽
    for col_i in range(1, warning_col + 1):
        col_letter = get_column_letter(col_i)
        ws.column_dimensions[col_letter].width = (
            28 if col_i in (ver_name_col, warning_col) else 18
        )

    out_buf = io.BytesIO()
    wb.save(out_buf)
    out_buf.seek(0)
    return out_buf.getvalue(), summary_list


# ── Streamlit UI ────────────────────────────────────────────────────────────
def run():
    st.caption(
        "聚合规则：**【虚拟SKU ＋ 国家 ＋ 素材版本前缀】** 为一组。自动统计总数、去重数，并独立排查组内连号与重复名称。"
    )

    col_t1, col_t2 = st.columns([1, 3])
    with col_t1:
        st.download_button(
            "📥 下载空白填写模板",
            make_template_bytes(),
            file_name="素材版本聚合统计_空白模板.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with col_t2:
        st.caption(
            "💡 **填报说明**：每组仅需在首行填写 SKU 和 国家，系统会自动按 SKU+国家+版本前缀聚合统计。"
        )

    uploaded_file = st.file_uploader(
        "📂 上传 Excel 文件（.xlsx）",
        type=["xlsx"],
        key="ver_country_uploader",
    )

    if uploaded_file is not None:
        try:
            with st.spinner("正在按 SKU + 国家 + 前缀 聚合统计与排查..."):
                processed_bytes, summary_list = process_version_matrix(
                    uploaded_file.getvalue()
                )

            summary_df = pd.DataFrame(summary_list)
            issue_records = summary_df[summary_df["校验状态"] == "存在异常"]

            m1, m2, m3 = st.columns(3)
            m1.metric("聚合分组总数", len(summary_df))
            m2.metric("✅ 正常分组", len(summary_df) - len(issue_records))
            m3.metric(
                "🚨 存在异常(重复/断号)",
                len(issue_records),
                delta_color="inverse",
            )

            out_filename = f"素材版本聚合统计报告_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
            st.download_button(
                label="📥 点击下载聚合统计结果 Excel",
                data=processed_bytes,
                file_name=out_filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
            )

            filter_opt = st.radio(
                "筛选视图：",
                ["查看全部", "🚨 仅看异常", "✅ 仅看正常"],
                horizontal=True,
            )
            if filter_opt == "🚨 仅看异常":
                display_df = issue_records
            elif filter_opt == "✅ 仅看正常":
                display_df = summary_df[summary_df["校验状态"] == "正常"]
            else:
                display_df = summary_df

            def highlight_status(val):
                if val == "存在异常":
                    return "background-color:#FFC7CE; color:#9C0006; font-weight:bold"
                return ""

            st.dataframe(
                display_df.style.map(highlight_status, subset=["校验状态"]),
                width="stretch",
                hide_index=True,
            )

        except Exception as e:
            st.error(f"❌ 处理文件失败: {e}")