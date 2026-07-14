"""
SKU 工具箱 - 主入口
集成你们部门多个工具：素材版本验证、产品库素材匹配等
"""

import streamlit as st
from sku_modules import data_validator, sku_product_matcher

st.set_page_config(page_title="SKU 工具箱", layout="wide")

# 缩小侧边栏宽度
st.markdown("""
<style>
[data-testid="stSidebar"] { width: 260px !important; min-width: 260px !important; }
</style>
""", unsafe_allow_html=True)

st.sidebar.title("📊 SKU 工具箱")
app_mode = st.sidebar.radio(
    "选择功能",
    ["🧪 素材版本验证", "🔗 产品库素材匹配"],
    index=0,
)

if app_mode == "🧪 素材版本验证":
    st.header("🧪 域名版本数据验证工具")
    data_validator.run()
elif app_mode == "🔗 产品库素材匹配":
    st.header("🔗 虚拟SKU着陆页链接素材匹配工具")
    sku_product_matcher.run()
