import streamlit as st
import pandas as pd
import os

st.set_page_config(page_title="广告与产品数据智能化匹配工具", layout="wide")
st.title("📊 广告与产品数据智能化匹配工具")

st.markdown("""
### 💡 使用指南：
1. **同时上传文件**：点击下方的上传框，按住 `Ctrl` 或 `Command` 键**同时选中**你的广告表和产品信息表上传。
2. **多重条件筛选**：系统会自动按**创建时间最新排序**，并筛选 **`版本名称 == '优化组版本-GPTJ'`** 且 **`状态 == '正常'`** 的数据。
3. **输入并生成**：在输入框粘贴待查的 `虚拟SKU` 和 `国家`（支持从 Excel 直接复制粘贴），点击按钮即可一键匹配下载。
""")

# 1. 文件同时上传
uploaded_files = st.file_uploader(
    "📁 请同时选择并上传【广告信息表】和【产品信息表】（按住Ctrl/Cmd可多选）", 
    type=["xlsx", "xls", "csv"], 
    accept_multiple_files=True
)

# 2. 输入框
st.subheader("✏️ 输入待匹配的 虚拟SKU 和 国家")
input_data = st.text_area(
    "格式：虚拟SKU [空格/制表符] 国家（每行一条，可以直接从 Excel 复制粘贴）",
    height=180,
    placeholder="LO3224268\t美国\nDG3249754\t美国\nGW3335705\t美国"
)

# 自动识别并处理表格的函数
def process_dataframe(df, file_name):
    df.columns = df.columns.str.strip()
    
    # 1. 排序：如果存在创建时间，按最新时间在最上面排序
    if '创建时间' in df.columns:
        df['创建时间'] = pd.to_datetime(df['创建时间'], errors='coerce')
        df = df.sort_values(by='创建时间', ascending=False)
    else:
        st.warning(f"⚠️ 提示：文件【{file_name}】未找到‘创建时间’列，将跳过时间排序。")
        
    # 2. 筛选版本名称
    if '版本名称' in df.columns:
        df = df[df['版本名称'].astype(str).str.strip() == '优化组版本-GPTJ']
    else:
        st.error(f"❌ 错误：文件【{file_name}】未找到‘版本名称’列，无法筛选‘优化组版本-GPTJ’。")
        return None
        
    # 3. 新增筛选：状态为“正常”
    if '状态' in df.columns:
        df = df[df['状态'].astype(str).str.strip() == '正常']
    else:
        st.error(f"❌ 错误：文件【{file_name}】未找到‘状态’列，无法筛选‘正常’状态。")
        return None
        
    return df

# 3. 核心匹配逻辑
if st.button("🚀 开始匹配并生成表格", type="primary"):
    if not uploaded_files or len(uploaded_files) < 2:
        st.error("❌ 请同时上传至少两个表格文件（广告信息表 + 产品信息表）！")
    elif not input_data.strip():
        st.error("❌ 请输入需要匹配的虚拟SKU和国家！")
    else:
        with st.spinner("正在自动识别表格并处理中..."):
            df_adv = None
            df_lp = None
            
            # 分流并识别上传的文件
            for file in uploaded_files:
                if file.name.endswith('.csv'):
                    df_temp = pd.read_csv(file)
                else:
                    df_temp = pd.read_excel(file)
                
                df_temp.columns = df_temp.columns.str.strip()
                
                # 根据特征列自动识别表类型
                if '产品链接' in df_temp.columns or '着陆页链接' in df_temp.columns:
                    if '着陆页链接' in df_temp.columns and '产品链接' not in df_temp.columns:
                        df_temp = df_temp.rename(columns={'着陆页链接': '产品链接'})
                    df_lp = process_dataframe(df_temp, file.name)
                elif '封面链接' in df_temp.columns or '素材链接' in df_temp.columns:
                    df_adv = process_dataframe(df_temp, file.name)
            
            # 检查文件识别结果
            if df_adv is None:
                st.error("❌ 未能识别到【广告信息表】，请检查是否包含 封面链接 或 素材链接 等列。")
            if df_lp is None:
                st.error("❌ 未能识别到【产品信息表】，请检查是否包含 产品链接（或着陆页链接）列。")
                
            if df_adv is not None and df_lp is not None:
                # 解析用户输入的查询数据
                input_lines = [line.strip().split() for line in input_data.strip().split('\n') if line.strip()]
                df_input = pd.DataFrame(input_lines, columns=['虚拟SKU', '国家'])
                df_input['虚拟SKU'] = df_input['虚拟SKU'].astype(str).str.strip()
                df_input['国家'] = df_input['国家'].astype(str).str.strip()
                
                # 关联键清洗
                df_adv['虚拟SKU'] = df_adv['虚拟SKU'].astype(str).str.strip()
                df_adv['国家'] = df_adv['国家'].astype(str).str.strip()
                df_lp['虚拟SKU'] = df_lp['虚拟SKU'].astype(str).str.strip()
                df_lp['国家'] = df_lp['国家'].astype(str).str.strip()
                
                # 已经降序排序，去重时 keep='first' 保留最新的一条
                df_adv_unique = df_adv.drop_duplicates(subset=['虚拟SKU', '国家'], keep='first')
                df_lp_unique = df_lp.drop_duplicates(subset=['虚拟SKU', '国家'], keep='first')
                
                # 数据合并 (Left Join)
                result = pd.merge(df_input, df_lp_unique, on=['虚拟SKU', '国家'], how='left')
                result = pd.merge(result, df_adv_unique, on=['虚拟SKU', '国家'], how='left')
                
                # 拼接正文与标题
                if '正文标题' not in result.columns:
                    if '正文' in result.columns and '标题' in result.columns:
                        result['正文标题'] = result['正文'].fillna('') + result['标题'].fillna('')
                    elif '正文' in result.columns:
                        result['正文标题'] = result['正文']
                    elif '标题' in result.columns:
                        result['正文标题'] = result['标题']
                    else:
                        result['正文标题'] = ""
                
                # 定义最终输出的目标列和顺序
                target_columns = ['真实SKU', '虚拟SKU', '国家', '产品链接', '封面链接', '素材链接', '正文标题', '描述']
                
                # 补齐可能缺失的列
                for col in target_columns:
                    if col not in result.columns:
                        result[col] = ""
                        
                final_df = result[target_columns]
                
                # ✨ 这里去掉了网页表格展示(st.dataframe)，让界面更清爽
                st.success("✨ 筛选与匹配全部完成！请点击下方按钮下载表格。")
                
                # 保存并提供下载
                output_path = "matched_result_v2.xlsx"
                final_df.to_excel(output_path, index=False, engine='openpyxl')
                
                with open(output_path, "rb") as file:
                    st.download_button(
                        label="📥 下载更新后的 Excel 表格",
                        data=file,
                        file_name="匹配结果表_已筛选正常.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                
                if os.path.exists(output_path):
                    os.remove(output_path)