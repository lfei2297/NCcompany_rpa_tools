# 单页促销文案排查

广告组 / 店铺组共用。上传链接表，排查结账页套餐价下促销文案。

## 部署（独立第三个 Streamlit 站）

不要改现有 `sku_tools.py`、`rectification_clean_data.py` 两个站。

1. 打开 [share.streamlit.io](https://share.streamlit.io) → **New app**
2. Repository：`lfei2297/NCcompany_rpa_tools`
3. Branch：`main`
4. **Main file path**：`checkout_promo_checker/app.py`
5. Deploy 后把新网址发给两个组

根目录 `requirements.txt` 已包含本工具依赖（`requests`）。Cloud 从仓库根安装依赖。

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
   - 测算一致：仍建议扫一眼
   - 测算不符：优先整改
   - 纯文案（包邮等）：必须进店核对，系统核不了运费条件
