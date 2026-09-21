# NCcompany_rpa_tools

NC 提效工具。同一个仓库里挂多个独立 Streamlit 站（Main file 不同即可）。

| 应用 | 使用方 | 仓库内入口 | Streamlit Main file |
| --- | --- | --- | --- |
| SKU 工具箱 | 现有站 | `sku_tools.py` | `sku_tools.py` |
| Excel 整改清洗拆分 | 现有站 | `rectification_clean_data.py` | `rectification_clean_data.py` |
| 单页促销文案排查 | 广告组 + 店铺组 | `checkout_promo_checker/app.py` | `checkout_promo_checker/app.py` |

## 新增：单页促销文案排查

上传单页链接 Excel 或粘贴链接，自动进结账页，识别价下方、规格名称、规格标签和顶栏里的促销文案并测算。  
部署：Streamlit Cloud → New app → 仍选本仓库 → **Main file path** 填 `checkout_promo_checker/app.py`（不要覆盖现有两个站）。

同事打开新地址即可，无需装 Python。详见 `checkout_promo_checker/README.md`。

## 依赖

Streamlit Cloud **只安装仓库根目录**的 `requirements.txt`，不会读子目录 README，也不会读 `checkout_promo_checker/` 里的文件来装包。

当前根目录依赖：

```
streamlit
pandas
openpyxl>=3.1.0
requests
```

`openpyxl>=3.1.0` 是促销文案排查这次升级需要的（Excel 单元格富文本）。改依赖必须改这个根文件，否则 Cloud 会继续用旧包。
