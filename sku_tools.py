"""
SKU 工具箱 - 主入口
"""

import streamlit as st
from sku_modules import conditional_lookup, data_validator, link_matcher, version_counter

st.set_page_config(page_title="SKU 工具箱", layout="wide")

# 统一样式：控制侧边栏宽度，并压缩顶部空白边距
st.markdown(
    """
<style>
/* 压缩页面顶部与大标题的空白边距 */
.block-container {
    padding-top: 1.5rem !important;
    padding-bottom: 2rem !important;
}
/* 控制侧边栏宽度 */
[data-testid="stSidebar"] {
    width: 260px !important;
    min-width: 260px !important;
}
</style>
""",
    unsafe_allow_html=True,
)

st.sidebar.title("📊 SKU 工具箱")
app_mode = st.sidebar.radio(
    "选择功能",
    ["🧪 素材版本验证", "🔍 数据交叉核验", "🔢 素材版本统计", "🎯 条件匹配取值"],
    index=0,
)

if app_mode == "🧪 素材版本验证":
    st.title("🧪 域名版本数据验证工具")
    data_validator.run()
elif app_mode == "🔍 数据交叉核验":
    st.title("🔍 通用数据交叉核验工具")
    link_matcher.run()
elif app_mode == "🔢 素材版本统计":
    st.title("🔢 素材版本数量自动统计")
    version_counter.run()
elif app_mode == "🎯 条件匹配取值":
    st.title("🎯 多关键字条件匹配")
    conditional_lookup.run()