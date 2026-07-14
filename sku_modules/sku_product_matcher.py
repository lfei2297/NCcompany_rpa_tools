"""
广告与产品数据智能化匹配模块
功能：
  1. 双表关联匹配（广告信息表 + 产品信息表）
  2. 按创建时间最新排序 + 筛选优化组版本 + 状态正常
  3. 输入 SKU + 国家，输出合并匹配结果
"""

import streamlit as st
import pandas as pd
import os


# ── 核心数据处理函数 ────────────────────────────────────────────────────────
def process_dataframe(df, file_name):
    df.columns = df.columns.str.strip()

    # 1. 按创建时间降序排序
    if "创建时间" in df.columns:
        df["创建时间"] = pd.to_datetime(df["创建时间"], errors="coerce")
        df = df.sort_values(by="创建时间", ascending=False)
    else:
        st.warning(f"⚠️ 提示：文件【{file_name}】未找到'创建时间'列，将跳过时间排序。")

    # 2. 筛选版本名称：优化组版本-XJP 或 优化组版本-GPTJ
    if "版本名称" in df.columns:
        df["版本名称"] = df["版本名称"].astype(str).str.strip()
        df = df[df["版本名称"].isin(["优化组版本-XJP", "优化组版本-GPTJ"])]
    else:
        st.error(f"❌ 错误：文件【{file_name}】未找到'版本名称'列，无法筛选版本。")
        return None

    # 3. 筛选状态为"正常"
    if "状态" in df.columns:
        df = df[df["状态"].astype(str).str.strip() == "正常"]
    else:
        st.error(f"❌ 错误：文件【{file_name}】未找到'状态'列，无法筛选'正常'状态。")
        return None

    return df


# ── Streamlit UI ────────────────────────────────────────────────────────────
def run():
    st.markdown("""
    ### 💡 使用指南：
    1. **同时上传文件**：点击下方上传框，按住 `Ctrl` 键**同时选中**广告表和产品信息表上传。
    2. **多重条件筛选**：自动按**创建时间最新排序**，筛选**版本名称为'优化组版本-XJP'或'优化组版本-GPTJ'**且**状态==正常**的数据。
    3. **输入并生成**：粘贴待查的 `虚拟SKU` 和 `国家`（每行一条，可从 Excel 直接复制粘贴），点击按钮即可匹配下载。
    """)

    # 文件上传
    uploaded_files = st.file_uploader(
        "📁 请同时选择并上传【广告信息表】和【产品信息表】（按住Ctrl可多选）",
        type=["xlsx", "xls", "csv"],
        accept_multiple_files=True,
    )

    # 输入框
    st.subheader("✏️ 输入待匹配的 虚拟SKU 和 国家")
    input_data = st.text_area(
        "格式：虚拟SKU [空格/制表符] 国家（每行一条，可直接从 Excel 复制粘贴）",
        height=180,
        placeholder="LO3224268\t美国\nDG3249754\t美国\nGW3335705\t美国",
    )

    if not st.button("🚀 开始匹配并生成表格", type="primary"):
        return

    if not uploaded_files or len(uploaded_files) < 2:
        st.error("❌ 请同时上传至少两个表格文件（广告信息表 + 产品信息表）！")
        return

    if not input_data.strip():
        st.error("❌ 请输入需要匹配的虚拟SKU和国家！")
        return

    with st.spinner("正在自动识别表格并处理中..."):
        df_adv, df_lp = None, None

        for file in uploaded_files:
            df_temp = pd.read_csv(file) if file.name.endswith(".csv") else pd.read_excel(file)
            df_temp.columns = df_temp.columns.str.strip()

            if "产品链接" in df_temp.columns or "着陆页链接" in df_temp.columns:
                if "着陆页链接" in df_temp.columns and "产品链接" not in df_temp.columns:
                    df_temp = df_temp.rename(columns={"着陆页链接": "产品链接"})
                df_lp = process_dataframe(df_temp, file.name)
            elif "封面链接" in df_temp.columns or "素材链接" in df_temp.columns:
                df_adv = process_dataframe(df_temp, file.name)

        if df_adv is None:
            st.error("❌ 未能识别到【广告信息表】，请检查是否包含 封面链接 或 素材链接 等列。")
            return
        if df_lp is None:
            st.error("❌ 未能识别到【产品信息表】，请检查是否包含 产品链接 列。")
            return

        # 解析输入
        input_lines = [line.strip().split() for line in input_data.strip().split("\n") if line.strip()]
        df_input = pd.DataFrame(input_lines, columns=["虚拟SKU", "国家"])
        df_input["虚拟SKU"] = df_input["虚拟SKU"].astype(str).str.strip()
        df_input["国家"] = df_input["国家"].astype(str).str.strip()

        # 关联键清洗
        df_adv["虚拟SKU"] = df_adv["虚拟SKU"].astype(str).str.strip()
        df_adv["国家"] = df_adv["国家"].astype(str).str.strip()
        df_lp["虚拟SKU"] = df_lp["虚拟SKU"].astype(str).str.strip()
        df_lp["国家"] = df_lp["国家"].astype(str).str.strip()

        # 去重保留最新一条
        df_adv_unique = df_adv.drop_duplicates(subset=["虚拟SKU", "国家"], keep="first")
        df_lp_unique = df_lp.drop_duplicates(subset=["虚拟SKU", "国家"], keep="first")

        # 合并
        result = pd.merge(df_input, df_lp_unique, on=["虚拟SKU", "国家"], how="left")
        result = pd.merge(result, df_adv_unique, on=["虚拟SKU", "国家"], how="left")

        # 输出列
        target_columns = ["真实SKU", "虚拟SKU", "国家", "产品链接", "封面链接",
                         "素材链接", "正文", "标题", "描述"]
        for col in target_columns:
            if col not in result.columns:
                result[col] = ""

        final_df = result[target_columns]
        st.success("✨ 筛选与匹配全部完成！请点击下方按钮下载表格。")

        output_path = os.path.join(os.path.dirname(__file__), "matched_result.xlsx")
        final_df.to_excel(output_path, index=False, engine="openpyxl")
        with open(output_path, "rb") as f:
            st.download_button(
                label="📥 下载更新后的 Excel 表格",
                data=f.read(),
                file_name="匹配结果表_最新.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        if os.path.exists(output_path):
            os.remove(output_path)
