import datetime
import io
import re
import pandas as pd
import streamlit as st

# 设置页面标题
st.set_page_config(page_title="Excel整改内容自动拆分工具", layout="wide")

# 注入CSS：精准控制字体大小，突出上传区域，维持整体紧凑性
st.markdown(
    """
    <style>
    .block-container {padding-top: 1.5rem; padding-bottom: 1.5rem;}
    element-container, div.stMarkdown, div.stButton { margin-bottom: 0.4rem !important; }
    h1 { margin-bottom: 0.1rem !important; padding-bottom: 0px !important; }
    
    /* 弱化模板文本字体（使用正常大小/稍弱颜色） */
    .template-text {
        font-size: 14px;
        color: #666666;
        margin-bottom: 4px;
    }
    
    /* 强化强化上传文本字体（大一号 + 加粗） */
    .upload-title {
        font-size: 20px;
        font-weight: 600;
        color: #222222;
        margin-top: 1.2rem;
        margin-bottom: 4px;
    }
    
    /* 让文件上传框有淡淡的红边轮廓，视觉更加聚焦 */
    [data-testid="stFileUploader"] {
        border: 1px solid #ff4b4b33;
        border-radius: 8px;
        padding: 4px;
    }
    </style>
""",
    unsafe_allow_html=True,
)

# 页面头部
st.title("📊 Excel 整改内容清洗与拆分工具")
st.write("自动识别文本中的日期、实现一变多拆分、去除重复整改类型，并按标准字段输出。")

# --- 标准模板下载（平铺展现，但使用正常/弱化字体） ---
st.markdown('<p class="template-text">💡 规范提示：请使用标准模板的表头字段（真实SKU、虚拟SKU、整改内容）录入数据：</p>', unsafe_allow_html=True)

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

st.download_button(
    label="📥 下载标准 Excel 模板 (含示例数据)",
    data=template_buffer,
    file_name="整改内容导入模板.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)


# --- 核心功能区：大字体加粗标题，成为视觉绝对核心 ---
st.markdown('<p class="upload-title">🚀 导入整改表格</p>', unsafe_allow_html=True)


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


# 文件上传组件（直接作为主视觉）
uploaded_file = st.file_uploader(
    "请上传需要处理的整改 Excel 文件 (.xlsx)", type=["xlsx"], label_visibility="collapsed"
)

if uploaded_file is not None:
    try:
        df = pd.read_excel(uploaded_file)

        # 检查列名
        required_cols = ["真实SKU", "虚拟SKU", "整改内容"]
        missing_cols = [col for col in required_cols if col not in df.columns]

        if missing_cols:
            st.error(
                f"❌ 导入失败：表格字段不匹配。请检查是否包含【真实SKU】、【虚拟SKU】、【整改内容】这三列。"
            )
        else:
            # 数据处理
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

            # 调整最终列顺序
            result_df = pd.DataFrame(new_rows)
            result_df = result_df[
                ["日期", "真实SKU", "虚拟SKU", "整改内容", "整改类型"]
            ]

            # 成功提示与下载
            st.success(
                f"🎉 处理完成！原数据 {len(df)} 行 --> 拆分去重后 {len(result_df)} 行。"
            )

            # 生成带时间戳的文件
            current_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            download_filename = f"处理后的表格_已拆分_{current_time}.xlsx"

            output_buffer = io.BytesIO()
            with pd.ExcelWriter(output_buffer, engine="openpyxl") as writer:
                result_df.to_excel(writer, index=False)
            output_buffer.seek(0)

            st.download_button(
                label="📥 点击下载处理后的标准结果表格",
                data=output_buffer,
                file_name=download_filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    except Exception as e:
        st.error(f"💥 运行错误: {e}")