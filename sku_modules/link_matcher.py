import datetime
import io
import re
import pandas as pd
import streamlit as st


# ---------------- 辅助函数 ----------------
def clean_url_or_key(text):
    """文本/链接归一化：去除首尾空格、降低大小写，如果是网址则去除协议头和结尾斜杠"""
    if not isinstance(text, str) or pd.isna(text):
        return ""
    text = text.strip().lower()
    if "http://" in text or "https://" in text or "www." in text:
        text = re.sub(r"^https?://", "", text)
        text = re.sub(r"^www\.", "", text)
        text = text.split("?")[0].split("#")[0].rstrip("/")
    return text


def parse_pasted_input(text):
    """解析用户从 Excel 复制粘贴的两列数据"""
    rows = []
    lines = text.strip().split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"[\t,]+|\s{2,}", line)
        if len(parts) == 1:
            parts = line.split()

        if len(parts) >= 2:
            input_val = parts[0].strip()
            input_key = " ".join(parts[1:]).strip()
            rows.append({"输入校验值": input_val, "关联查找键": input_key})
        elif len(parts) == 1:
            rows.append({"输入校验值": parts[0].strip(), "关联查找键": ""})
    return pd.DataFrame(rows)


def run():
    st.markdown(
        """
        <style>
        .block-container {padding-top: 1.5rem; padding-bottom: 2rem;}
        .section-title {font-size: 18px; font-weight: 600; color: #1f2d3d; margin-top: 1.2rem; margin-bottom: 0.5rem;}
        .card-box {background-color: #f8f9fa; border-left: 4px solid #409eff; padding: 10px 14px; border-radius: 4px; margin-bottom: 1rem;}
        .card-box p {margin: 0; font-size: 13px; color: #606266;}
        </style>
    """,
        unsafe_allow_html=True,
    )

    # st.title("🔗 通用双字段交叉匹配与校验工具")
    st.caption(
        "上传基础参考表，选择需要交叉对比的两个字段，一键校验输入数据是否与参考表完全匹配。"
    )

    # --- 步骤 1：上传基础数据表 ---
    st.markdown(
        '<p class="section-title">📂 第一步：上传基础参考表（例如：着陆页出单查询表）</p>',
        unsafe_allow_html=True,
    )
    ref_file = st.file_uploader(
        "选择 Excel / CSV 文件",
        type=["xlsx", "xls", "csv"],
        key="ref_uploader",
    )

    if ref_file is not None:
        try:
            if ref_file.name.endswith(".csv"):
                ref_df = pd.read_csv(ref_file)
            else:
                ref_df = pd.read_excel(ref_file)

            st.success(f"✅ 基础表读取成功，共 {len(ref_df)} 行记录。")

            all_cols = ref_df.columns.tolist()

            default_target_col = next(
                (c for c in all_cols if "SKU" in c.upper()),
                all_cols[0],
            )
            default_lookup_cols = [
                c
                for c in all_cols
                if "链接" in c or "URL" in c.upper()
            ]

            col1, col2 = st.columns(2)
            with col1:
                target_col = st.selectbox(
                    "🎯 选择【目标核验列】(你期望核对的正确值，如SKU/负责人)：",
                    all_cols,
                    index=all_cols.index(default_target_col),
                )
            with col2:
                lookup_cols = st.multiselect(
                    "🔑 选择【关联查找列】(用于检索的Key，如链接/ID，可多选)：",
                    all_cols,
                    default=default_lookup_cols
                    if default_lookup_cols
                    else [all_cols[-1]],
                )

            # 构建匹配字典
            lookup_map = {}
            for _, row in ref_df.iterrows():
                target_val = (
                    str(row[target_col]).strip()
                    if pd.notna(row[target_col])
                    else ""
                )

                for l_col in lookup_cols:
                    if l_col in ref_df.columns and pd.notna(row[l_col]):
                        c_key = clean_url_or_key(str(row[l_col]))
                        if c_key and c_key not in lookup_map:
                            lookup_map[c_key] = {"标准值": target_val}

            st.markdown(
                f'<div class="card-box"><p>💡 已成功根据 <b>【{", ".join(lookup_cols)}】</b> 建立 <b>{len(lookup_map)}</b> 条唯一匹配映射。</p></div>',
                unsafe_allow_html=True,
            )

            # --- 步骤 2：输入待校验的数据 ---
            st.markdown(
                '<p class="section-title">✏️ 第二步：粘贴待核验数据（两列：待校验值 ＋ 关联查找键）</p>',
                unsafe_allow_html=True,
            )
            default_demo_text = (
                "FU3507268\thttps://www.specimien.com/pages/news-instant-firming-cream-m-2\n"
                "FU3507268\thttps://www.specimien.com/pages/news-inst-ant-fir-ming-cream-m-1"
            )

            input_text = st.text_area(
                "请直接从 Excel 复制两列数据粘贴到下方文本框中 (第1列: 待校验值 ｜ 第2列: 查找键/链接/ID)：",
                value="",
                placeholder=f"示例格式（直接从 Excel 选中两列复制粘贴即可）：\n{default_demo_text}",
                height=180,
            )

            # 放置按钮区域：【开始匹配】与【下载按钮】紧跟在输入框正下方
            btn_col1, btn_col2 = st.columns([1, 2])
            with btn_col1:
                start_btn = st.button(
                    "🚀 开始匹配校验", type="primary", use_container_width=True
                )

            # SessionState 记录校验状态，保证下载文件时数据不丢
            if start_btn or "res_df" in st.session_state:
                if start_btn:
                    if not input_text.strip():
                        st.warning("⚠️ 请先在上方文本框中粘贴待校验的数据！")
                    else:
                        input_df = parse_pasted_input(input_text)
                        if not input_df.empty:
                            match_results = []
                            for _, row in input_df.iterrows():
                                in_val = row["输入校验值"]
                                in_key = row["关联查找键"]
                                c_in_key = clean_url_or_key(in_key)

                                if c_in_key in lookup_map:
                                    ref_info = lookup_map[c_in_key]
                                    std_val = ref_info["标准值"]
                                    if in_val.lower() == std_val.lower():
                                        status = "✅ 匹配正常"
                                    else:
                                        status = "🔴 异常 (值不一致)"
                                else:
                                    std_val = "-"
                                    status = "⚠️ 未在参考表中找到对应Key"

                                match_results.append(
                                    {
                                        "输入待校验值": in_val,
                                        "输入关联查找键": in_key,
                                        "参考表标准值": std_val,
                                        "校验状态": status,
                                    }
                                )

                            st.session_state.res_df = pd.DataFrame(
                                match_results
                            )

                # 如果有核验结果，就在【开始匹配】按钮旁边直接露出【下载按钮】
                if "res_df" in st.session_state and not st.session_state.res_df.empty:
                    res_df = st.session_state.res_df

                    timestamp = datetime.datetime.now().strftime(
                        "%Y%m%d_%H%M%S"
                    )
                    out_filename = f"双字段核验结果报告_{timestamp}.xlsx"

                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                        res_df.to_excel(writer, index=False)
                    buffer.seek(0)

                    with btn_col2:
                        st.download_button(
                            label="📥 点击下载校验结果 Excel",
                            data=buffer,
                            file_name=out_filename,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                        )

                    # --- 步骤 3：下方展示统计面板和明细预览 ---
                    st.markdown(
                        '<p class="section-title">📊 校验结果统计与明细</p>',
                        unsafe_allow_html=True,
                    )

                    total_count = len(res_df)
                    normal_count = len(res_df[res_df["校验状态"] == "✅ 匹配正常"])
                    anomaly_count = len(
                        res_df[res_df["校验状态"] == "🔴 异常 (值不一致)"]
                    )
                    not_found_count = len(
                        res_df[res_df["校验状态"] == "⚠️ 未在参考表中找到对应Key"]
                    )

                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("待核验总数", f"{total_count} 条")
                    m2.metric("✅ 匹配正常", f"{normal_count} 条")
                    m3.metric(
                        "🔴 数据不一致",
                        f"{anomaly_count} 条",
                        delta_color="inverse",
                    )
                    m4.metric("⚠️ 未找到对应Key", f"{not_found_count} 条")

                    filter_opt = st.radio(
                        "筛选视图：",
                        [
                            "查看全部",
                            "🔴 仅看异常",
                            "⚠️ 仅看未找到KEY",
                            "✅ 仅看正常",
                        ],
                        horizontal=True,
                    )

                    if filter_opt == "🔴 仅看异常":
                        display_df = res_df[
                            res_df["校验状态"] == "🔴 异常 (值不一致)"
                        ]
                    elif filter_opt == "⚠️ 仅看未找到KEY":
                        display_df = res_df[
                            res_df["校验状态"] == "⚠️ 未在参考表中找到对应Key"
                        ]
                    elif filter_opt == "✅ 仅看正常":
                        display_df = res_df[res_df["校验状态"] == "✅ 匹配正常"]
                    else:
                        display_df = res_df

                    st.dataframe(
                        display_df,
                        use_container_width=True,
                        hide_index=True,
                    )

        except Exception as e:
            st.error(f"💥 读取基础表格时发生错误: {e}")


if __name__ == "__main__":
    run()