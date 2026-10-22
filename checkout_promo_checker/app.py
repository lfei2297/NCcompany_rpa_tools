"""独立 Streamlit 站：广告组 / 店铺组共用，上传 Excel 排查结账页促销文案。"""

from __future__ import annotations

import importlib
import re
import sys
from datetime import datetime
from pathlib import Path

import streamlit.components.v1 as components

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import streamlit as st

import batch
import checker
import reason

# Streamlit 重跑脚本时不会重新加载已导入模块。原价写在 reason.py，
# 不刷新的话页面会一直用进程启动时的旧逻辑。
importlib.reload(reason)
importlib.reload(checker)
importlib.reload(batch)

from batch import run_batch
from checker import SYS_CALC_FAIL, SYS_FAIL, SYS_MATCH, SYS_MISMATCH, SYS_NONE, SYS_PURE
from excel_io import excel_multiline, highlight_html, make_input_template, read_links, rewrite_result_bytes, write_results_bytes


_URL_RE = re.compile(r"https?://[^\s<>\"'\]]+", re.I)


def urls_from_text(text: str) -> list[str]:
    """一行一条、逗号分隔、同一格里多个网址，都能拆出来。"""
    raw = str(text or "").strip()
    if not raw or raw.lower() in {"url", "链接", "一页商店链接", "nan", "none"}:
        return []
    found = [_clean_url(u) for u in _URL_RE.findall(raw)]
    found = [u for u in found if u]
    if found:
        return found
    t = raw.strip().strip("'\"")
    if t.startswith("//"):
        t = "https:" + t
    if "." in t and "/" in t:
        return [t]
    return []


def _clean_url(url: str) -> str:
    return url.rstrip(".,);，。")


def _split_pasted_urls(text: str) -> list[str]:
    if not (text or "").strip():
        return []
    raw = (
        text.replace(",", "\n")
        .replace(";", "\n")
        .replace("，", "\n")
        .replace("；", "\n")
    )
    urls: list[str] = []
    for line in raw.splitlines():
        urls.extend(urls_from_text(line))
    if not urls:
        urls = urls_from_text(text)
    return urls


def parse_pasted_urls(text: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for u in _split_pasted_urls(text):
        key = u.lower()
        if key in seen:
            continue
        seen.add(key)
        urls.append(u)
    return urls


def collect_rows(uploaded, pasted: str) -> tuple[list[dict], int]:
    rows: list[dict] = []
    seen: set[str] = set()
    raw_n = 0
    if uploaded is not None:
        for item in read_links(uploaded.getvalue()):
            raw_n += 1
            key = item["url"].strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append(item)
    for url in _split_pasted_urls(pasted):
        raw_n += 1
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append({"url": url, "extra": {}})
    return rows, raw_n

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
        table.promo-calc { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
        table.promo-calc th {
            text-align: left; background: #f4f6f8; padding: 7px 8px;
            border-bottom: 1px solid #e0e0e0; white-space: nowrap;
        }
        table.promo-calc td {
            padding: 7px 8px; border-bottom: 1px solid #f0f0f0; vertical-align: top;
        }
        table.promo-calc .mark-ok { color: #2e7d32; font-weight: 700; }
        table.promo-calc .mark-bad { color: #d32f2f; font-weight: 700; }
        table.promo-calc .mark-ship { color: #d32f2f; font-weight: 700; }
        table.promo-calc .mark-other { color: #666; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("单页促销文案排查")
st.caption("广告组 / 店铺组共用。系统测算价下方、规格名称、规格标签、顶栏里的促销文案后，仍建议人工扫一眼；包邮等纯文案必须进店核对。测算版本 20261022（Each $X；N-piece×N；德文 pro Stück）。")

with st.expander("怎么用", expanded=False):
    st.markdown(
        """
1. **上传 Excel**（第一列链接）或 **粘贴链接**（一行一条），两种都能跑，也可以一起用。
2. 点「开始排查」。看 **系统检查结果**、**是否人工复核**。
3. `测算一致` 也请扫一眼页面；`纯文案`（如包邮）必须进店核对运费条件。
4. 新 SKU 布局会查：价下文案、规格名里的 Save X% OFF、带价格的规格标签、顶栏折扣。
        """
    )

st.download_button(
    "下载链接模板",
    data=make_input_template(),
    file_name="单页排查链接模板.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

uploaded = st.file_uploader("上传链接表（.xlsx，第一列是链接）", type=["xlsx"])
pasted = st.text_area(
    "或粘贴链接（一行一条，也可逗号分隔）",
    height=120,
    placeholder="https://example.com/pages/news-xxx-m\nhttps://example.com/funnel/checkout-xxx-m",
)
workers = st.slider("并发数", 1, 6, 3, help="云上建议 3。链接很多时调低更稳。")

if "result_bytes" not in st.session_state:
    st.session_state.result_bytes = None
    st.session_state.result_name = ""
    st.session_state.result_table = []
    st.session_state.result_summary = ""

has_input = uploaded is not None or bool((pasted or "").strip())
act1, act2, _ = st.columns([1.1, 1.4, 2.8])
with act1:
    run_btn = st.button("开始排查", type="primary", disabled=not has_input)

if run_btn:
    rows, raw_n = collect_rows(uploaded, pasted or "")
    if not rows:
        st.error("没有读到链接。请上传 Excel（第一列是网址），或在粘贴框里填链接。")
        st.stop()
    dup_n = raw_n - len(rows)
    if dup_n > 0:
        st.info(f"共读到 {raw_n} 条链接，其中 {dup_n} 条重复，实际排查 {len(rows)} 条。")
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
    st.session_state.result_bytes = rewrite_result_bytes(st.session_state.result_bytes)
    st.session_state.result_table = [
        {
            "原链接": r.source_url,
            "结账页": r.checkout_url,
            "类型": r.copy_type,
            "出现位置": r.locations_joined,
            "促销文案": excel_multiline(r.promo_text_joined),
            "系统检查结果": r.system_result,
            "含包邮": r.has_shipping,
            "是否人工复核": r.need_review,
            "测算说明": excel_multiline(r.reason_detail or r.note),
            "测算明细": r.verdict_rows,
        }
        for r in results
    ]
    review_n = sum(1 for r in results if r.need_review == "是")
    mismatch = sum(1 for r in results if r.system_result == "测算不符")
    st.session_state.result_summary = (
        f"完成 {len(results)} 条（下载文件同样是 {len(results)} 条）"
        f" · 需人工复核 {review_n} · 测算不符 {mismatch}"
    )
    bar.progress(1.0, text="完成")

n_done = len(st.session_state.result_table or [])
with act2:
    st.download_button(
        f"下载结果 Excel（{n_done} 条）" if n_done else "下载结果 Excel",
        data=st.session_state.result_bytes or b"",
        file_name=st.session_state.result_name or "促销文案排查结果.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        disabled=not st.session_state.result_bytes,
        key="download_results",
    )

if st.session_state.result_summary:
    table = st.session_state.result_table
    for r in table:
        r["促销文案"] = excel_multiline(r.get("促销文案") or "")
        r["测算说明"] = excel_multiline(r.get("测算说明") or "")
    if st.session_state.result_bytes:
        st.session_state.result_bytes = rewrite_result_bytes(st.session_state.result_bytes)
    st.success(st.session_state.result_summary)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("需人工复核", sum(1 for r in table if r.get("是否人工复核") == "是"))
    with c2:
        st.metric("测算不符", sum(1 for r in table if r.get("系统检查结果") == "测算不符"))
    with c3:
        st.metric("含包邮", sum(1 for r in table if r.get("含包邮") == "是"))
    with c4:
        st.metric("无促销文案", sum(1 for r in table if r.get("系统检查结果") == "无促销文案"))
    overview = [
        {
            k: r[k]
            for k in (
                "原链接",
                "结账页",
                "出现位置",
                "系统检查结果",
                "含包邮",
                "是否人工复核",
            )
            if k in r
        }
        for r in table
    ]
    st.dataframe(overview, use_container_width=True, hide_index=True)

    def _esc(text: str) -> str:
        return (
            (text or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def render_pre(text: str):
        body = excel_multiline(text or "")
        if not body:
            st.caption("无")
            return
        st.markdown(
            "<div style='white-space:pre-wrap;line-height:1.6;font-size:0.95rem'>"
            f"{highlight_html(body)}</div>",
            unsafe_allow_html=True,
        )

    def render_calc_table(rows: list[dict], key_prefix: str = "calc"):
        if not rows:
            return False
        uid = re.sub(r"[^a-zA-Z0-9]", "", key_prefix) or "calc"
        statuses = list(dict.fromkeys(r.get("status") or "" for r in rows if r.get("status")))
        locs = list(dict.fromkeys(r.get("location") or "" for r in rows if r.get("location")))
        has_bad = "不符" in statuses

        def checks(values: list[str], prefix: str, default_only: str | None = None) -> str:
            bits = []
            for v in values:
                on = " checked" if not default_only or v == default_only else ""
                bits.append(
                    f'<label><input type="checkbox" class="{prefix}" value="{_esc(v)}"{on}> {_esc(v)}</label>'
                )
            return "".join(bits)

        st_checks = checks(statuses, f"{uid}-st", "不符" if has_bad else None)
        loc_checks = checks(locs, f"{uid}-loc")
        visible = (
            sum(1 for r in rows if r.get("status") == "不符") if has_bad else len(rows)
        )
        # 数据区单独限高。列表头放在滚动区外面，滚数据行时表头不动。
        n = max(visible, 1)
        body_h = min(420, 96 * n)
        cls = {"符合": "mark-ok", "不符": "mark-bad", "包邮": "mark-ship"}
        trs = []
        for row in rows:
            mark = row.get("status") or ""
            label = row.get("label") or ""
            price = row.get("price") or ""
            regular = row.get("regular") or ""
            loc = row.get("location") or ""
            copy = row.get("copy") or ""
            calc = row.get("calc") or ""
            trs.append(
                "<tr "
                f'data-st="{_esc(mark)}" data-loc="{_esc(loc)}">'
                f"<td class='{cls.get(mark, 'mark-other')}'>{_esc(mark)}</td>"
                f"<td>{_esc(label)}</td>"
                f"<td class='price'>{_esc(price)}</td>"
                f"<td class='price'>{_esc(regular)}</td>"
                f"<td>{_esc(loc)}</td>"
                f"<td>{_esc(copy)}</td>"
                f"<td>{_esc(calc)}</td>"
                "</tr>"
            )

        def th(title: str, panel_id: str, body: str) -> str:
            return (
                f'<th><div class="th-in"><span>{_esc(title)}</span>'
                f'<button type="button" class="arr" data-p="{panel_id}">▾</button></div>'
                f'<div class="panel" id="{panel_id}">{body}</div></th>'
            )

        html = f"""
<style>
  html, body {{ margin: 0; padding: 0; background: #fff; overflow: hidden; }}
  * {{ box-sizing: border-box; }}
  .pw {{
    font-family: Calibri, "Microsoft YaHei", sans-serif; font-size: 13px; color: #222;
    width: 100%;
  }}
  .pw .sheet {{ max-height: {body_h}px; overflow: auto; }}
  .pw table {{
    width: 100%; min-width: 920px; border-collapse: separate; border-spacing: 0;
    table-layout: fixed;
  }}
  .pw thead th {{
    background: #305496; color: #fff; font-weight: 700; text-align: left;
    padding: 0; position: relative; z-index: 5;
    white-space: nowrap; border-right: 1px solid #4a6eab;
  }}
  .pw .th-in {{ display: flex; align-items: center; justify-content: space-between; padding: 8px 6px 8px 10px; gap: 4px; }}
  .pw .arr {{
    background: transparent; border: 0; color: #fff; cursor: pointer;
    font-size: 11px; line-height: 1; padding: 2px 5px; border-radius: 2px;
  }}
  .pw .arr:hover, .pw .arr.on {{ background: #1f3d73; }}
  .pw .arr.filtered {{ color: #ffd54f; }}
  .pw .panel {{
    display: none; position: absolute; top: 100%; left: 0; z-index: 20;
    background: #fff; color: #222; border: 1px solid #b0b0b0;
    box-shadow: 0 2px 8px rgba(0,0,0,.18); min-width: 160px; max-width: 260px;
    padding: 8px; text-align: left; font-weight: 400; white-space: normal;
  }}
  .pw .panel label {{ display: block; font-size: 12px; margin: 3px 0; cursor: pointer; }}
  .pw .panel input[type="text"] {{
    width: 100%; box-sizing: border-box; margin-bottom: 6px; padding: 4px 6px;
    border: 1px solid #ccc; font-size: 12px;
  }}
  .pw td {{
    padding: 8px 10px; border: 1px solid #d0d7e2; vertical-align: top; background: #fff;
    word-break: break-word; line-height: 1.45;
  }}
  .pw td.price {{ white-space: nowrap; }}
  .pw tbody tr:nth-child(even) td {{ background: #f7f9fc; }}
  .mark-ok {{ color: #2e7d32; font-weight: 700; }}
  .mark-bad {{ color: #d32f2f; font-weight: 700; }}
  .mark-ship {{ color: #d32f2f; font-weight: 700; }}
  .pw .cnt {{ color: #666; font-size: 12px; margin: 0 0 6px; }}
</style>
<div class="pw" id="{uid}-wrap">
<div class="cnt" id="{uid}-cnt"></div>
<table class="head">
<colgroup>
  <col style="width:72px">
  <col style="width:16%">
  <col style="width:92px">
  <col style="width:92px">
  <col style="width:88px">
  <col style="width:22%">
  <col>
</colgroup>
<thead><tr>
{th("结论", uid + "-p0", st_checks)}
{th("规格", uid + "-p1", '<input type="text" id="' + uid + '-q1" placeholder="搜索规格">')}
{th("现价", uid + "-p5", '<input type="text" id="' + uid + '-q4" placeholder="搜索现价">')}
{th("原价", uid + "-p6", '<input type="text" id="' + uid + '-q5" placeholder="搜索原价">')}
{th("位置", uid + "-p2", loc_checks)}
{th("促销文案", uid + "-p3", '<input type="text" id="' + uid + '-q2" placeholder="搜索文案">')}
{th("测算", uid + "-p4", '<input type="text" id="' + uid + '-q3" placeholder="搜索测算">')}
</tr></thead>
</table>
<div class="sheet" id="{uid}-sheet">
<table>
<colgroup>
  <col style="width:72px">
  <col style="width:16%">
  <col style="width:92px">
  <col style="width:92px">
  <col style="width:88px">
  <col style="width:22%">
  <col>
</colgroup>
<tbody id="{uid}-body">
{''.join(trs)}
</tbody>
</table>
</div>
</div>
<script>
(function() {{
  var root = document.getElementById('{uid}-wrap');
  function checked(cls) {{
    var boxes = root.querySelectorAll('input.' + cls);
    var on = [];
    boxes.forEach(function(b) {{ if (b.checked) on.push(b.value); }});
    return on;
  }}
  function apply() {{
    var st = checked('{uid}-st');
    var loc = checked('{uid}-loc');
    var q1 = ((document.getElementById('{uid}-q1') || {{}}).value || '').toLowerCase();
    var q2 = ((document.getElementById('{uid}-q2') || {{}}).value || '').toLowerCase();
    var q3 = ((document.getElementById('{uid}-q3') || {{}}).value || '').toLowerCase();
    var q4 = ((document.getElementById('{uid}-q4') || {{}}).value || '').toLowerCase();
    var q5 = ((document.getElementById('{uid}-q5') || {{}}).value || '').toLowerCase();
    var trs = document.getElementById('{uid}-body').rows;
    var show = 0;
    for (var i = 0; i < trs.length; i++) {{
      var tr = trs[i], tds = tr.cells, ok = true;
      if (st.length && st.indexOf(tr.getAttribute('data-st')) < 0) ok = false;
      if (loc.length && loc.indexOf(tr.getAttribute('data-loc')) < 0) ok = false;
      if (q1 && (tds[1].innerText || '').toLowerCase().indexOf(q1) < 0) ok = false;
      if (q4 && (tds[2].innerText || '').toLowerCase().indexOf(q4) < 0) ok = false;
      if (q5 && (tds[3].innerText || '').toLowerCase().indexOf(q5) < 0) ok = false;
      if (q2 && (tds[5].innerText || '').toLowerCase().indexOf(q2) < 0) ok = false;
      if (q3 && (tds[6].innerText || '').toLowerCase().indexOf(q3) < 0) ok = false;
      tr.style.display = ok ? '' : 'none';
      if (ok) show++;
    }}
    document.getElementById('{uid}-cnt').textContent = '显示 ' + show + ' / ' + trs.length + ' 条';
    root.querySelectorAll('.arr').forEach(function(btn) {{
      var p = document.getElementById(btn.getAttribute('data-p'));
      var filtered = false;
      if (!p) return;
      var boxes = p.querySelectorAll('input[type=checkbox]');
      if (boxes.length) {{
        var n = 0; boxes.forEach(function(b) {{ if (b.checked) n++; }});
        filtered = n > 0 && n < boxes.length;
      }}
      p.querySelectorAll('input[type=text]').forEach(function(inp) {{
        if (inp.value) filtered = true;
      }});
      btn.classList.toggle('filtered', filtered);
    }});
  }}
  root.querySelectorAll('.arr').forEach(function(btn) {{
    btn.addEventListener('click', function(e) {{
      e.stopPropagation();
      var id = btn.getAttribute('data-p');
      root.querySelectorAll('.panel').forEach(function(p) {{
        p.style.display = (p.id === id && p.style.display !== 'block') ? 'block' : 'none';
      }});
    }});
  }});
  root.querySelectorAll('.panel input').forEach(function(inp) {{
    inp.addEventListener('input', apply);
    inp.addEventListener('change', apply);
  }});
  document.addEventListener('click', function() {{
    root.querySelectorAll('.panel').forEach(function(p) {{ p.style.display = 'none'; }});
  }});
  root.querySelectorAll('.panel').forEach(function(p) {{
    p.addEventListener('click', function(e) {{ e.stopPropagation(); }});
  }});
  setTimeout(apply, 0);
}})();
</script>
"""
        # 外框一次定死。列表头在滚动区外，只滚数据行。
        components.html(html, height=body_h + 78, scrolling=False)
        return True

    def render_group(items: list[dict], expand_first: bool):
        if not items:
            st.caption("这一类没有记录。")
            return
        many = len(items) > 5
        if many:
            st.caption(f"共 {len(items)} 条，默认收起，点开查看。完整内容也可下载 Excel。")
        for i, r in enumerate(items):
            ship = " · 含包邮" if r.get("含包邮") == "是" else ""
            title = f"{r['系统检查结果']}{ship} · {r['原链接']}"
            with st.expander(title, expanded=expand_first and not many and i == 0):
                st.markdown(f"[打开结账页]({r.get('结账页') or r['原链接']})")
                bits = []
                if r.get("出现位置"):
                    bits.append(f"出现位置：{r['出现位置']}")
                if r.get("含包邮") == "是":
                    bits.append("含包邮，运费须进店核对")
                if bits:
                    st.caption("  ·  ".join(bits))
                if r.get("促销文案"):
                    st.markdown("**促销文案**")
                    render_pre(r["促销文案"])
                st.markdown("**测算**")
                if not render_calc_table(
                    r.get("测算明细") or [],
                    key_prefix=f"calc-{i}-{abs(hash(r.get('原链接') or str(i))) % 10**8}",
                ):
                    render_pre(r["测算说明"] or "")

    def render_ship_tabs(items: list[dict], expand_first: bool):
        ship = [r for r in items if r.get("含包邮") == "是"]
        plain = [r for r in items if r.get("含包邮") != "是"]
        tab_plain, tab_ship = st.tabs(
            [f"不含包邮（{len(plain)}）", f"含包邮（{len(ship)}）"]
        )
        with tab_plain:
            render_group(plain, expand_first=expand_first)
        with tab_ship:
            render_group(ship, expand_first=expand_first)

    mismatch = [r for r in table if r["系统检查结果"] == SYS_MISMATCH]
    match = [r for r in table if r["系统检查结果"] == SYS_MATCH]
    pure = [r for r in table if r["系统检查结果"] == SYS_PURE]
    none = [r for r in table if r["系统检查结果"] == SYS_NONE]
    other = [
        r
        for r in table
        if r["系统检查结果"] in {SYS_FAIL, SYS_CALC_FAIL}
        or r["系统检查结果"] not in {SYS_MISMATCH, SYS_MATCH, SYS_PURE, SYS_NONE}
    ]

    st.markdown("#### 测算说明")
    t_bad, t_ok, t_pure, t_none, t_other = st.tabs(
        [
            f"测算不符（{len(mismatch)}）" + (
                f" · 含包邮{sum(1 for r in mismatch if r.get('含包邮') == '是')}"
                if any(r.get("含包邮") == "是" for r in mismatch)
                else ""
            ),
            f"测算一致（{len(match)}）" + (
                f" · 含包邮{sum(1 for r in match if r.get('含包邮') == '是')}"
                if any(r.get("含包邮") == "是" for r in match)
                else ""
            ),
            f"纯文案 / 包邮（{len(pure)}）",
            f"无促销文案（{len(none)}）",
            f"无法检测（{len(other)}）",
        ]
    )
    with t_bad:
        st.caption("文案和价格对不上，优先整改。含包邮的折扣先改，运费仍须进店核对。")
        render_ship_tabs(mismatch, expand_first=True)
    with t_ok:
        st.caption("价格测算对得上。含包邮的折扣已核过，运费仍须进店核对。")
        render_ship_tabs(match, expand_first=True)
    with t_pure:
        st.caption("只有包邮等无法按价格测算的文案。折扣已测算的页面在「测算一致/不符」，表里会标「含包邮」。")
        render_group(pure, expand_first=True)
    with t_none:
        render_group(none, expand_first=False)
    with t_other:
        render_group(other, expand_first=True)
