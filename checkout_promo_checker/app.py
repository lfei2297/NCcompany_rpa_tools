"""独立 Streamlit 站：广告组 / 店铺组共用，上传 Excel 排查结账页促销文案。"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import streamlit as st

from batch import run_batch
from excel_io import make_input_template, read_links, write_results_bytes

st.set_page_config(page_title="单页促销文案排查", page_icon="🧾", layout="wide")

st.markdown(
    """
    <style>
        .block-container { padding-top: 1.4rem; padding-bottom: 2rem; }
        [data-testid="stFileUploaderDropzone"] {
            min-height: 2.6rem !important;
            height: 2.6rem !important;
            padding: 0 0.6rem !important;
            align-items: center !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("单页促销文案排查")
st.caption("广告组 / 店铺组共用（独立站）。系统测算套餐价下促销文案后，仍建议人工扫一眼；包邮等纯文案必须进店核对。")

with st.expander("怎么用", expanded=False):
    st.markdown(
        """
1. 下载模板，或用现有表：**第一列放单页链接**（落地页或结账页均可）。
2. 上传后点「开始排查」。
3. 看两列：**系统检查结果**、**是否人工复核**。
4. `测算一致` 也请扫一眼页面；`纯文案`（如包邮）系统无法核店铺运费条件，必须人工复核。
        """
    )

st.download_button(
    "下载链接模板",
    data=make_input_template(),
    file_name="单页排查链接模板.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

uploaded = st.file_uploader("上传链接表（.xlsx）", type=["xlsx"])
workers = st.slider("并发数", 1, 6, 3, help="云上建议 3。链接很多时调低更稳。")

if "result_bytes" not in st.session_state:
    st.session_state.result_bytes = None
    st.session_state.result_name = ""
    st.session_state.result_table = []
    st.session_state.result_summary = ""

run_btn = st.button("开始排查", type="primary", disabled=uploaded is None)

if run_btn:
    if uploaded is None:
        st.error("请先上传 Excel。")
        st.stop()
    rows = read_links(uploaded.getvalue())
    if not rows:
        st.error("第一列没有读到链接。请确认表头下一行开始是网址。")
        st.stop()
    if len(rows) > 80:
        st.warning(f"本次 {len(rows)} 条，云上可能较慢。建议每批不超过 80 条。")

    bar = st.progress(0.0, text="准备中…")
    status = st.empty()

    def progress(done, total, item):
        bar.progress(done / total, text=f"{done}/{total}  {item.system_result}")
        status.write(f"{item.system_result} · 人工复核:{item.need_review} · {item.source_url}")

    results = run_batch([r["url"] for r in rows], workers=workers, progress=progress)
    extra_headers: list[str] = []
    for extra in [r["extra"] for r in rows]:
        for k in extra:
            if k not in extra_headers and k != "类型":
                extra_headers.append(k)
    paired = list(zip(results, [r["extra"] for r in rows]))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    st.session_state.result_bytes = write_results_bytes(paired, extra_headers)
    st.session_state.result_name = f"促销文案排查结果_{ts}.xlsx"
    st.session_state.result_table = [
        {
            "原链接": r.source_url,
            "结账页": r.checkout_url,
            "类型": r.copy_type,
            "促销文案": r.promo_text_joined,
            "系统检查结果": r.system_result,
            "是否人工复核": r.need_review,
            "测算说明": r.reason_detail or r.note,
        }
        for r in results
    ]
    review_n = sum(1 for r in results if r.need_review == "是")
    mismatch = sum(1 for r in results if r.system_result == "测算不符")
    st.session_state.result_summary = (
        f"完成 {len(results)} 条 · 需人工复核 {review_n} · 测算不符 {mismatch}"
    )
    bar.progress(1.0, text="完成")

if st.session_state.result_summary:
    st.success(st.session_state.result_summary)
    c1, c2, c3 = st.columns(3)
    table = st.session_state.result_table
    with c1:
        st.metric("需人工复核", sum(1 for r in table if r["是否人工复核"] == "是"))
    with c2:
        st.metric("测算不符", sum(1 for r in table if r["系统检查结果"] == "测算不符"))
    with c3:
        st.metric("无促销文案", sum(1 for r in table if r["系统检查结果"] == "无促销文案"))
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.download_button(
        "下载结果 Excel",
        data=st.session_state.result_bytes,
        file_name=st.session_state.result_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
