# 单页促销文案排查

广告组 / 店铺组共用。  
上传单页链接 Excel 或粘贴链接，自动进结账页，识别价下方、规格名称、规格标签和顶栏里的促销文案并测算。规格名里的 Save N% 按单独买合计对比套餐现价；其它折扣仍对比划线价。only  each 按 SKU 写明的数量相乘（4件*2→8，60set*2→120）。支持套餐卡和 SKU 新布局。

同事使用说明见同目录 `使用说明.md`、`单页促销文案排查使用指南.docx`。

## 部署（独立第三个 Streamlit 站）

不要改现有 `sku_tools.py`、`rectification_clean_data.py` 两个站。

1. 打开 [share.streamlit.io](https://share.streamlit.io) → **New app**
2. Repository：`lfei2297/NCcompany_rpa_tools`
3. Branch：`main`
4. **Main file path**：`checkout_promo_checker/app.py`
5. Deploy 后把新网址发给两个组

Cloud **只读仓库根目录** `requirements.txt` 装包，不会读本目录 README。根文件里已包含：`streamlit`、`pandas`、`requests`、`openpyxl>=3.1.0`（Excel 富文本需要 3.1+）。

## 本地

在仓库根目录：

```bat
pip install -r requirements.txt
streamlit run checkout_promo_checker/app.py
```

## 同事怎么用

1. 上传 Excel（第一列链接），或直接粘贴链接（一行一条），两种都能跑
2. 开始排查 → 下载结果
3. 看 **系统检查结果**、**是否人工复核**
   - 测算一致：仍建议扫一眼页面
   - 测算不符：优先整改
   - 纯文案（包邮等）：必须进店核对，系统核不了运费条件

类型里不会出现「无需整改」。
