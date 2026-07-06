import datetime
import io
import re
import pandas as pd
import streamlit as st

# 设置页面标题
st.set_page_config(page_title="Excel整改内容自动拆分工具", layout="wide")

# 【优化】注入CSS以缩小Streamlit组件之间的默认大间隔，并美化布局
st.markdown(
    """
    <style>
    /* 缩小整体组件间距 */
    .block-container {padding-top: 2rem; padding-bottom: 2rem;}
    element-container, div.stMarkdown, div.stButton { margin-bottom: 0.5rem !important; }
    /* 针对标题和二级标题的特殊紧凑处理 */
    h1 { margin-bottom: 0.2rem !important; padding-bottom: 0px !important; }
    h3 { margin-top: 1rem !important; margin-bottom: 0.3rem !important; }
    </style>
""",
    unsafe_allow_html=True,
)

st.title("📊 Excel 整改内容清洗与拆分工具")
st.write("上传你的整改表格，自动识别日期、一变多拆分、去除重复整改类型，并输出标准表格。")

st.subheader("📋 第一步：获取标准模板")
st.write("为了确保系统能准确识别，请使用下方提供的标准模板进行数据填写：")

# 创建内存中的空白模板
template_buffer = io.BytesIO()
template_df = pd.DataFrame(
    {
        "真实SKU": ["ZM3019882", "示例SKU002"],
        "虚拟SKU": ["sku07", "sku04"],
        "整改内容": [
            "4.3 sku07 ZM3019882\n商标侵权：帖子体现商标WONDERSKIN...",
            "7.3 sku04\n1.材质与实物不符：据核实...2.功效与实物不符：...",
        ],
    }
)
with pd.ExcelWriter(template_buffer, engine="openpyxl") as writer:
    template_df.to_excel(writer, index=False)
template_buffer.seek(0)

# 模板下载按钮
st.download_button(
    label="📥 点击下载标准 Excel 模板 (包含示例数据)",
    data=template_buffer,
    file_name="整改内容导入模板.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

# 【优化】移除了原本导致大空白的 st.write("---") 分割线，直接紧凑衔接下一步
st.subheader("🚀 第二步：上传并处理表格")


# ================== 核心解析逻辑 ==================
def parse_rectification_content(content):
    if pd.isna(content):
        return []

    pattern = r"(\d{1,2}\.\d{1,2})\s+sku\d*"
    matches = list(re.finditer(pattern, content, re.IGNORECASE))

    if not matches:
        return [("", "", content)]

    results = []
    for i in range(len(matches)):
        start_idx = matches[i].start()
        end_idx = matches[i + 1].start() if i + 1 < len(matches) else len(content)

        date_str = matches[i].group(1)
        sub_text = content[start_idx:end_idx].strip()

        type_pattern = r"(?:(?:\d+\.)|(?:\n))?([\u4e00-\u9fa5]{2,15})[:：]"
        types_found = re.findall(type_pattern, sub_text)

        exclude_words = {"封面", "视频", "整改内容"}
        seen = set()
        clean_types = []

        for t in types_found:
            if t not in exclude_words and t not in seen:
                seen.add(t)
                clean_types.append(t)

        rectify_type = "\n".join(clean_types) if clean_types else "其他整改"
        results.append((date_str, rectify_type, sub_text))

    return results


# 2. 文件上传组件
uploaded_file = st.file_uploader(
    "请选择填写好数据的 Excel 文件 (.xlsx)", type=["xlsx"]
)

if uploaded_file is not None:
    try:
        df = pd.read_excel(uploaded_file)

        # 检查列名
        required_cols = ["真实SKU", "虚拟SKU", "整改内容"]
        missing_cols = [col for col in required_cols if col not in df.columns]

        if missing_cols:
            st.error(
                f"❌ 上传失败！检测到列名不匹配。请确认是否修改了模板表头。缺少的列: {', '.join(missing_cols)}"
            )
        else:
            # 3. 数据处理
            new_rows = []
            for index, row in df.iterrows():
                parsed_data = parse_rectification_content(row["整改内容"])
                for date, r_type, clean_content in parsed_data:
                    new_rows.append(
                        {
                            "日期": date,
                            "真实SKU": row["真实SKU"],
                            "虚拟SKU": row["虚拟SKU"],
                            "整改内容": clean_content,
                            "整改类型": r_type,
                        }
                    )

            # 【优化】重新调整 DataFrame 的列顺序为：日期、真实SKU、虚拟SKU、整改内容、整改类型
            result_df = pd.DataFrame(new_rows)
            result_df = result_df[
                ["日期", "真实SKU", "虚拟SKU", "整改内容", "整改类型"]
            ]

            # 【优化】去除了原先展示前5行 dataframe 预览的区域，直接显示成功状态
            st.success(
                f"🎉 数据处理成功！原表格共 {len(df)} 行，经拆分去重后，新表格共生成了 {len(result_df)} 行数据。"
            )

            # 4. 生成带时间戳的文件名与二进制流
            current_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            download_filename = f"处理后的表格_{current_time}.xlsx"

            output_buffer = io.BytesIO()
            with pd.ExcelWriter(output_buffer, engine="openpyxl") as writer:
                result_df.to_excel(writer, index=False)
            output_buffer.seek(0)

            # 5. 下载按钮
            st.download_button(
                label="📥 点击下载处理后的标准结果表格",
                data=output_buffer,
                file_name=download_filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    except Exception as e:
        st.error(f"💥 处理文件时发生未知错误: {e}")