"""
多关键字条件匹配模块

上传任意表，设置筛选和排序，再用 1～3 列关键字同时精确匹配，取出指定列。
同一组关键字默认只保留排序后的第一条。被筛掉的行不占用这个名额，
因此「最新一条已删除、下一条正常」时会自动取到下一条。
"""

import copy
import datetime
import io
import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

PRESET_PATH = Path(__file__).with_name("lookup_presets.json")
BROWSER_STORAGE_KEY = "ncsku_lookup_presets_v1"
_BROWSER_STORE = components.declare_component(
    "ncsku_browser_store",
    path=str(Path(__file__).with_name("browser_store")),
)
BUILTIN_PRESET_NAME = "广告素材最新ID"
BUILTIN_PRESET = {
    "key_cols": ["虚拟SKU", "国家", "版本名称"],
    "return_cols": ["广告素材ID"],
    "sort_col": "创建时间",
    "sort_desc": True,
    "keep_first": True,
    "filters": [{"col": "状态", "mode": "只保留", "values": ["正常", "重复"]}],
}


def normalize_cell(value) -> str:
    """把单元格收成可比较的字符串。数字去掉无意义的 .0。"""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value).strip()
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    text = str(value).strip().replace("\u3000", "")
    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    return text


def _init_kwargs(key, field, value):
    """控件已有会话值时不再传默认值，避免和预设按钮冲突。"""
    if key in st.session_state:
        return {"key": key}
    return {"key": key, field: value}


def load_store(path: Path | None = None) -> dict:
    """读取已保存的预设。文件不存在时写入内置的广告素材预设。"""
    target = Path(path) if path else PRESET_PATH
    if not target.exists():
        store = {"last": BUILTIN_PRESET_NAME, "presets": {BUILTIN_PRESET_NAME: BUILTIN_PRESET}}
        write_store(store, target)
        return store
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"last": None, "presets": {}, "error": f"预设文件无法读取：{target}"}
    presets = data.get("presets")
    if not isinstance(presets, dict):
        presets = {}
    return {"last": data.get("last"), "presets": presets}


def write_store(store: dict, path: Path | None = None) -> None:
    target = Path(path) if path else PRESET_PATH
    payload = {"last": store.get("last"), "presets": store.get("presets", {})}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def store_payload(store: dict) -> str:
    return json.dumps(
        {"last": store.get("last"), "presets": store.get("presets", {})},
        ensure_ascii=False,
    )


def normalize_saved_preset(item) -> dict | None:
    if not isinstance(item, dict):
        return None
    filters = []
    for raw in (item.get("filters") or [])[:5]:
        if not isinstance(raw, dict) or not raw.get("col"):
            continue
        mode = raw.get("mode") if raw.get("mode") in ("只保留", "排除") else "只保留"
        filters.append(
            {
                "col": str(raw.get("col")),
                "mode": mode,
                "values": [str(value) for value in raw.get("values") or [] if str(value).strip()],
            }
        )
    return {
        "key_cols": [str(col) for col in (item.get("key_cols") or [])][:3],
        "return_cols": [str(col) for col in (item.get("return_cols") or [])],
        "sort_col": item.get("sort_col") or None,
        "sort_desc": bool(item.get("sort_desc", True)),
        "keep_first": bool(item.get("keep_first", True)),
        "filters": filters,
    }


def parse_store_text(raw: str) -> dict:
    data = json.loads(raw)
    presets_in = data.get("presets") if isinstance(data, dict) else None
    if not isinstance(presets_in, dict):
        raise ValueError("预设文件里没有 presets")
    presets = {}
    for name, item in presets_in.items():
        normalized = normalize_saved_preset(item)
        title = str(name).strip()
        if title and normalized:
            presets[title] = normalized
    if not presets:
        raise ValueError("预设文件里没有可用预设")
    last = data.get("last")
    if last not in presets:
        last = next(iter(presets))
    return {"last": last, "presets": presets}


def seed_store() -> dict:
    """浏览器还没有预设时，沿用本机旧文件；没有旧文件就用内置预设。"""
    if PRESET_PATH.exists():
        loaded = load_store()
        if loaded.get("presets") and not loaded.get("error"):
            last = loaded.get("last")
            presets = copy.deepcopy(loaded["presets"])
            if last not in presets:
                last = next(iter(presets))
            return {"last": last, "presets": presets}
    return {
        "last": BUILTIN_PRESET_NAME,
        "presets": {BUILTIN_PRESET_NAME: copy.deepcopy(BUILTIN_PRESET)},
    }


def load_browser_store() -> dict:
    """从当前浏览器读取预设。读不到时先等组件返回，避免用空数据盖掉已保存的内容。"""
    if "cl_store" in st.session_state:
        return st.session_state["cl_store"]

    raw = _BROWSER_STORE(
        action="read",
        storage_key=BROWSER_STORAGE_KEY,
        payload="",
        key="cl_browser_read",
        default=None,
    )
    if raw is None:
        waits = st.session_state.get("cl_store_wait", 0) + 1
        st.session_state["cl_store_wait"] = waits
        if waits <= 3:
            st.caption("正在读取这个浏览器里保存的预设…")
            st.stop()
        st.session_state["cl_store"] = seed_store()
        st.session_state["cl_store_warning"] = "浏览器没有允许保存预设，这次设置只在当前页面有效。"
        return st.session_state["cl_store"]

    if raw:
        try:
            st.session_state["cl_store"] = parse_store_text(raw)
        except (json.JSONDecodeError, ValueError):
            st.session_state["cl_store"] = seed_store()
    else:
        st.session_state["cl_store"] = seed_store()
    return st.session_state["cl_store"]


def push_browser_store() -> None:
    store = st.session_state.get("cl_store")
    if not isinstance(store, dict):
        return
    payload = store_payload(store)
    echoed = _BROWSER_STORE(
        action="write",
        storage_key=BROWSER_STORAGE_KEY,
        payload=payload,
        key="cl_browser_write",
        default=None,
    )
    if st.session_state.get("cl_refresh_presets") and echoed == payload:
        st.session_state["cl_refresh_presets"] = False
        st.rerun()


def describe_preset(preset: dict) -> str:
    keys = " + ".join(preset.get("key_cols") or []) or "未设置"
    returns = "、".join(preset.get("return_cols") or []) or "未设置"
    sort_col = preset.get("sort_col") or "不排序"
    direction = "从新到旧" if preset.get("sort_desc", True) else "从旧到新"
    keep = "每组只留第一条" if preset.get("keep_first", True) else "保留全部命中"
    parts = []
    for item in preset.get("filters") or []:
        values = [str(value) for value in item.get("values") or [] if str(value).strip()]
        if item.get("col") and values:
            parts.append(f"{item['col']} {item.get('mode', '只保留')} {' / '.join(values)}")
    filters = "；".join(parts) if parts else "不筛选"
    sort_text = sort_col if sort_col == "不排序" else f"{sort_col}，{direction}"
    return f"关键字 {keys} → {returns}。排序：{sort_text}，{keep}。筛选：{filters}"


def preset_fits(preset: dict, columns: list[str]) -> bool:
    keys = [col for col in preset.get("key_cols") or [] if col in columns]
    returns = [col for col in preset.get("return_cols") or [] if col in columns]
    return bool(keys) and bool(returns)


def _clear_filter_state(file_id: str) -> None:
    prefix = f"_{file_id}_"
    for key in list(st.session_state.keys()):
        if (
            key.startswith(f"cl_fcol{prefix}")
            or key.startswith(f"cl_fmode{prefix}")
            or key.startswith(f"cl_fvals{prefix}")
            or key.startswith(f"cl_ftext{prefix}")
        ):
            del st.session_state[key]


def apply_preset(preset: dict, file_id: str, ref_df: pd.DataFrame) -> str:
    """把预设写进控件状态。必须在这些控件创建之前调用。"""
    columns = list(ref_df.columns)
    skipped = []
    keys = []
    for col in preset.get("key_cols") or []:
        if col in columns and col not in keys:
            keys.append(col)
        elif col not in columns:
            skipped.append(col)
    keys = keys[:3]
    returns = []
    for col in preset.get("return_cols") or []:
        if col in columns and col not in returns:
            returns.append(col)
        elif col not in columns:
            skipped.append(col)
    sort_col = preset.get("sort_col") or ""
    if sort_col and sort_col not in columns:
        skipped.append(sort_col)
        sort_choice = "（不排序）"
    elif not sort_col:
        sort_choice = "（不排序）"
    else:
        sort_choice = sort_col

    _clear_filter_state(file_id)
    st.session_state[f"cl_keys_{file_id}"] = keys
    st.session_state[f"cl_rets_{file_id}"] = returns
    st.session_state[f"cl_sort_{file_id}"] = sort_choice
    st.session_state[f"cl_order_{file_id}"] = "从新到旧" if preset.get("sort_desc", True) else "从旧到新"
    st.session_state[f"cl_keep_{file_id}"] = bool(preset.get("keep_first", True))

    kept = 0
    for item in (preset.get("filters") or [])[:5]:
        col = item.get("col")
        if col not in columns:
            if col:
                skipped.append(col)
            continue
        mode = item.get("mode") if item.get("mode") in ("只保留", "排除") else "只保留"
        values = [normalize_cell(value) for value in item.get("values") or [] if normalize_cell(value)]
        options = unique_text_values(ref_df[col])
        if len(options) <= 40:
            available = set(options)
            st.session_state[f"cl_fvals_{file_id}_{kept}_{col}"] = [value for value in values if value in available]
        else:
            st.session_state[f"cl_ftext_{file_id}_{kept}_{col}"] = ", ".join(values)
        st.session_state[f"cl_fcol_{file_id}_{kept}"] = col
        st.session_state[f"cl_fmode_{file_id}_{kept}"] = mode
        kept += 1
    st.session_state[f"cl_n_{file_id}"] = kept
    if not skipped:
        return ""
    return "这些列在当前表里没有，已跳过：" + "、".join(dict.fromkeys(skipped))


def current_preset(key_cols, return_cols, sort_col, sort_desc, keep_first, filters) -> dict:
    return {
        "key_cols": list(key_cols),
        "return_cols": list(return_cols),
        "sort_col": None if sort_col in (None, "", "（不排序）") else sort_col,
        "sort_desc": bool(sort_desc),
        "keep_first": bool(keep_first),
        "filters": [
            {
                "col": item["col"],
                "mode": item["mode"],
                "values": [normalize_cell(value) for value in item["values"] if normalize_cell(value)],
            }
            for item in filters
        ],
    }


KEY_ALIASES = {
    "虚拟SKU": ["虚拟sku", "sku"],
    "国家": ["国家名称", "市场", "目的国"],
    "版本名称": ["素材版本名称", "素材入库版本", "入库版本", "版本名"],
}


def read_table(uploaded, header=0) -> pd.DataFrame:
    if hasattr(uploaded, "seek"):
        uploaded.seek(0)
    if uploaded.name.lower().endswith(".csv"):
        df = pd.read_csv(uploaded, header=header)
    else:
        df = pd.read_excel(uploaded, header=header)
    if header is not None:
        df.columns = [str(c).strip() for c in df.columns]
    return df


def _alias_names(key: str) -> set[str]:
    names = {key.lower()}
    names.update(alias.lower() for alias in KEY_ALIASES.get(key, []))
    return names


def resolve_key_columns(columns: list[str], key_cols: list[str]) -> tuple[dict, list[str]]:
    mapping = {}
    used = set()
    missing = []
    for key in key_cols:
        aliases = _alias_names(key)
        found = next((col for col in columns if col not in used and str(col).lower() in aliases), None)
        if found is None:
            missing.append(key)
            continue
        used.add(found)
        mapping[key] = found
    return mapping, missing


def _looks_like_header(cells: list[str], key_cols: list[str]) -> bool:
    hints = set()
    for key in key_cols:
        hints.update(_alias_names(key))
    return any(cell.lower() in hints for cell in cells if cell)


def unique_text_values(series: pd.Series) -> list[str]:
    values = []
    seen = set()
    for raw in series:
        text = normalize_cell(raw)
        if text and text not in seen:
            seen.add(text)
            values.append(text)
    return sorted(values)


def apply_filters(df: pd.DataFrame, filters: list[dict]) -> pd.DataFrame:
    work = df
    for item in filters:
        values = [normalize_cell(v) for v in item["values"] if normalize_cell(v)]
        if not values:
            continue
        current = work[item["col"]].map(normalize_cell)
        allowed = set(values)
        if item["mode"] == "排除":
            work = work[~current.isin(allowed)]
        else:
            work = work[current.isin(allowed)]
    return work


def sort_series(series: pd.Series) -> pd.Series:
    as_time = pd.to_datetime(series, errors="coerce")
    if as_time.notna().mean() > 0.5:
        return as_time
    as_number = pd.to_numeric(series, errors="coerce")
    if as_number.notna().mean() > 0.5:
        return as_number
    return series.map(normalize_cell)


def fill_down_rows(rows: list[list[str]]) -> list[list[str]]:
    """空单元格沿用同一列上一行的值。整行都空则跳过，避免复制出重复查询。"""
    filled = []
    previous = None
    for parts in rows:
        current = [normalize_cell(part) for part in parts]
        if not any(current):
            continue
        if previous is not None:
            for index, value in enumerate(current):
                if not value:
                    current[index] = previous[index]
        previous = current
        filled.append(current)
    return filled


def fill_down_frame(df: pd.DataFrame, key_cols: list[str]) -> pd.DataFrame:
    work = df[key_cols].copy()
    for col in key_cols:
        work[col] = work[col].map(normalize_cell)
    work = work.loc[work.ne("").any(axis=1)].copy()
    for col in key_cols:
        work[col] = work[col].replace("", pd.NA).ffill().fillna("")
    return work.reset_index(drop=True)


def parse_query_text(text: str, width: int) -> tuple[list[list[str]], list[int], list[int]]:
    rows = []
    bad_lines = []
    wide_lines = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        if width == 1:
            parts = [line.strip()]
        elif "\t" in line:
            parts = [part.strip() for part in line.rstrip("\r\n").split("\t")]
            if len(parts) > width:
                wide_lines.append(line_no)
            if len(parts) < width:
                parts.extend([""] * (width - len(parts)))
            parts = parts[:width]
        else:
            parts = [part.strip() for part in re.split(r"\s{2,}", line.strip())]
            if len(parts) < width:
                parts = line.split()
            if len(parts) < width:
                bad_lines.append(line_no)
                continue
            if len(parts) > width:
                wide_lines.append(line_no)
            parts = parts[:width]
        rows.append(parts)
    return fill_down_rows(rows), bad_lines, wide_lines


def match_by_keys(
    ref: pd.DataFrame,
    queries: pd.DataFrame,
    key_cols: list[str],
    return_cols: list[str],
    filters: list[dict],
    sort_col: str | None,
    sort_desc: bool,
    keep_first: bool,
) -> pd.DataFrame:
    """按关键字同时精确匹配。queries 的列名必须就是 key_cols。"""
    filtered = apply_filters(ref, filters).copy()
    for col in key_cols:
        filtered[col] = filtered[col].map(normalize_cell)
    filtered = filtered[filtered[key_cols].ne("").all(axis=1)]

    if sort_col:
        filtered = filtered.assign(_sort=sort_series(filtered[sort_col]))
        filtered = filtered.sort_values("_sort", ascending=not sort_desc, kind="mergesort")
        filtered = filtered.drop(columns="_sort")

    counts = (
        filtered.groupby(key_cols, dropna=False).size().rename("候选条数").reset_index()
        if not filtered.empty
        else pd.DataFrame(columns=key_cols + ["候选条数"])
    )
    if keep_first and not filtered.empty:
        filtered = filtered.drop_duplicates(subset=key_cols, keep="first")

    query = queries.copy()
    query["_query_order"] = range(len(query))
    normalized = query[key_cols].apply(lambda series: series.map(normalize_cell))
    incomplete_orders = set(query.loc[normalized.eq("").any(axis=1), "_query_order"])
    for col in key_cols:
        query[col] = normalized[col]

    extra_cols = [col for col in return_cols if col not in key_cols]
    if filtered.empty:
        right = pd.DataFrame(columns=key_cols + extra_cols)
    else:
        right = filtered[key_cols + extra_cols].copy()
    right["_hit"] = 1

    merged = query.merge(right, on=key_cols, how="left")
    merged = merged.merge(counts, on=key_cols, how="left")

    def row_status(row):
        if row["_query_order"] in incomplete_orders:
            return "关键字不完整"
        if row["_hit"] == 1:
            return "已匹配"
        return "未匹配"

    merged["匹配状态"] = merged.apply(row_status, axis=1)
    merged.loc[merged["匹配状态"] != "已匹配", "候选条数"] = 0
    merged["候选条数"] = merged["候选条数"].fillna(0).astype(int)
    for col in extra_cols:
        merged.loc[merged["匹配状态"] != "已匹配", col] = ""

    ordered = key_cols + extra_cols + ["候选条数", "匹配状态"]
    merged = merged.sort_values(["_query_order"], kind="mergesort")
    return merged[ordered].reset_index(drop=True)


def _queries_from_upload(uploaded, key_cols: list[str]) -> pd.DataFrame:
    table = read_table(uploaded, header=0)
    mapping, missing = resolve_key_columns(list(table.columns), key_cols)
    if not missing:
        renamed = table.rename(columns={src: dst for dst, src in mapping.items()})
        return fill_down_frame(renamed, key_cols)
    if mapping:
        raise ValueError(f"查询表缺少列 {missing}。当前列：{list(table.columns)}")

    raw = read_table(uploaded, header=None)
    width = len(key_cols)
    if raw.shape[1] < width:
        raise ValueError(f"查询表只有 {raw.shape[1]} 列，当前关键字需要 {width} 列。")
    first = [normalize_cell(value) for value in raw.iloc[0, :width].tolist()]
    if _looks_like_header(first, key_cols):
        raw = raw.iloc[1:]
    raw = raw.iloc[:, :width].copy()
    raw.columns = key_cols
    return fill_down_frame(raw, key_cols)


def run():
    st.caption(
        "上传一张表，先设筛选和排序，再按 1～3 列关键字同时精确匹配，取出你要的列。"
        "同一组关键字只保留排序后的第一条；被筛掉的行会跳过，自动落到下一条符合条件的记录。"
    )

    ref_file = st.file_uploader(
        "上传被查询的表格（Excel / CSV）",
        type=["xlsx", "xls", "csv"],
        key="cl_ref_uploader",
    )
    if ref_file is None:
        st.info(
            "上传表格后可以套用已保存的预设。第一次会自带「广告素材最新ID」："
            "关键字是虚拟SKU、国家、版本名称，取出广告素材ID，按创建时间从新到旧只留一条，"
            "状态只保留正常和重复。预设保存在当前浏览器，部署到网站上之后，同一浏览器下次打开还能用。"
        )
        return

    try:
        ref_df = read_table(ref_file)
    except Exception as exc:
        st.error(f"读取表格失败：{exc}")
        return

    if ref_df.empty:
        st.error("表格没有数据。")
        return

    file_id = f"{ref_file.name}_{getattr(ref_file, 'size', 0)}"
    if st.session_state.get("cl_file_id") != file_id:
        st.session_state["cl_file_id"] = file_id
        st.session_state.pop("cl_result", None)
        st.session_state.pop("cl_download_cols", None)

    cols = list(ref_df.columns)
    st.success(f"已读取 {ref_file.name}，共 {len(ref_df)} 行，{len(cols)} 列。")

    store = load_browser_store()
    presets = store["presets"]
    if st.session_state.get("cl_store_warning"):
        st.warning(st.session_state["cl_store_warning"])
    new_file = st.session_state.get("cl_seen_file") != file_id
    if new_file:
        st.session_state["cl_seen_file"] = file_id
        last_name = store.get("last")
        last_preset = presets.get(last_name) if last_name else None
        if last_preset and preset_fits(last_preset, cols):
            skipped = apply_preset(last_preset, file_id, ref_df)
            note = f"已套用上次使用的预设「{last_name}」。"
            if skipped:
                note += skipped
            st.session_state["cl_preset_note"] = note
            st.session_state["cl_preset_pick"] = last_name

    pending_name = st.session_state.pop("cl_pending_preset", None)
    if pending_name and pending_name in presets:
        skipped = apply_preset(presets[pending_name], file_id, ref_df)
        note = f"已套用预设「{pending_name}」。"
        if skipped:
            note += skipped
        st.session_state["cl_preset_note"] = note
        st.session_state["cl_preset_pick"] = pending_name
        store["last"] = pending_name

    with st.expander("预设", expanded=True, key="cl_preset_expander"):
        st.caption("调好匹配条件后，在这里填名称并保存。点标题可折叠。")
        preset_note = st.session_state.pop("cl_preset_note", None)
        if preset_note:
            st.info(preset_note)
        preset_names = list(presets)
        if "cl_pending_pick" in st.session_state:
            pending_pick = st.session_state.pop("cl_pending_pick")
            if pending_pick in preset_names:
                st.session_state["cl_preset_pick"] = pending_pick
            else:
                st.session_state.pop("cl_preset_pick", None)
        if preset_names:
            pick_key = "cl_preset_pick"
            if st.session_state.get(pick_key) not in preset_names:
                st.session_state.pop(pick_key, None)
            last_index = preset_names.index(store["last"]) if store.get("last") in preset_names else 0
            pick_col, apply_col, delete_col = st.columns([4, 1, 1], vertical_alignment="bottom")
            with pick_col:
                picked = st.selectbox(
                    "已保存的预设",
                    preset_names,
                    **_init_kwargs(pick_key, "index", last_index),
                )
            with apply_col:
                apply_clicked = st.button("套用", type="primary", key="cl_apply_preset")
            with delete_col:
                delete_clicked = st.button("删除", key="cl_delete_preset")
            st.caption(describe_preset(presets[picked]))
            if apply_clicked:
                st.session_state.pop("cl_confirm_delete", None)
                st.session_state["cl_pending_preset"] = picked
                st.rerun()
            if delete_clicked:
                st.session_state["cl_confirm_delete"] = picked
            if st.session_state.get("cl_confirm_delete") == picked:
                st.warning(f"确认删除预设「{picked}」？删除后不能恢复。")
                confirm_col, cancel_col, _spacer = st.columns([1, 1, 3])
                with confirm_col:
                    confirm_delete = st.button("确认删除", key="cl_confirm_delete_btn")
                with cancel_col:
                    cancel_delete = st.button("取消", key="cl_cancel_delete_btn")
                if cancel_delete:
                    st.session_state.pop("cl_confirm_delete", None)
                    st.rerun()
                if confirm_delete:
                    presets.pop(picked, None)
                    if store.get("last") == picked:
                        store["last"] = next(iter(presets), None)
                    st.session_state["cl_pending_pick"] = store.get("last")
                    st.session_state.pop("cl_confirm_delete", None)
                    st.session_state["cl_preset_note"] = f"已删除预设「{picked}」。"
                    st.session_state["cl_refresh_presets"] = True
        else:
            st.caption("还没有保存的预设。先设置下面的条件，再保存。")

        name_col, save_col = st.columns([4, 1], vertical_alignment="bottom")
        with name_col:
            preset_name = st.text_input(
                "预设名称",
                key="cl_preset_name",
                placeholder="例如：广告素材最新ID",
            )
        with save_col:
            save_clicked = st.button("保存当前设置", type="primary", key="cl_save_preset")

        st.caption("换电脑或换到网站时，下载这份文件再导入。同名预设会被覆盖。")
        backup_col, import_col = st.columns(2)
        with backup_col:
            st.download_button(
                "下载预设备份",
                data=store_payload(store).encode("utf-8"),
                file_name="lookup_presets.json",
                mime="application/json",
                key="cl_download_presets",
            )
        with import_col:
            preset_upload = st.file_uploader("导入预设备份", type=["json"], key="cl_import_presets")
        if preset_upload is not None:
            try:
                imported = parse_store_text(preset_upload.getvalue().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                st.error(f"这份备份无法读取：{exc}")
            else:
                token = f"{preset_upload.name}_{preset_upload.size}"
                if st.session_state.get("cl_imported_token") != token:
                    presets.update(imported["presets"])
                    store["last"] = imported["last"]
                    st.session_state["cl_imported_token"] = token
                    st.session_state["cl_pending_pick"] = imported["last"]
                    st.session_state["cl_preset_note"] = f"已导入 {len(imported['presets'])} 个预设。"
                    st.session_state["cl_refresh_presets"] = True

    with st.expander("匹配条件", expanded=True, key="cl_condition_expander"):
        default_keys = [name for name in ["虚拟SKU", "国家", "版本名称"] if name in cols][:3]
        default_returns = ["广告素材ID"] if "广告素材ID" in cols else []
        sort_options = ["（不排序）"] + cols
        default_sort = "创建时间" if "创建时间" in cols else "（不排序）"

        key_col, return_col = st.columns(2)
        with key_col:
            key_cols = st.multiselect(
                "匹配关键字（1～3列，须同时相同）",
                cols,
                max_selections=3,
                **_init_kwargs(f"cl_keys_{file_id}", "default", default_keys),
            )
        with return_col:
            return_cols = st.multiselect(
                "取出的列",
                cols,
                **_init_kwargs(f"cl_rets_{file_id}", "default", default_returns),
            )

        sort_pick, order_pick, keep_pick = st.columns([2, 1, 1], vertical_alignment="bottom")
        with sort_pick:
            sort_col = st.selectbox(
                "排序列",
                sort_options,
                **_init_kwargs(f"cl_sort_{file_id}", "index", sort_options.index(default_sort)),
            )
        with order_pick:
            sort_order = st.selectbox(
                "顺序",
                ["从新到旧", "从旧到新"],
                **_init_kwargs(f"cl_order_{file_id}", "index", 0),
            )
        with keep_pick:
            keep_first = st.checkbox(
                "每组只留第一条",
                **_init_kwargs(f"cl_keep_{file_id}", "value", True),
            )
        sort_desc = sort_order == "从新到旧"
        if "创建时间" in cols:
            st.caption("要取最新一条时，排序列选「创建时间」，顺序选「从新到旧」。")

        count_col, hint_col = st.columns([1, 3], vertical_alignment="bottom")
        with count_col:
            n_filters = st.selectbox(
                "筛选条数",
                [0, 1, 2, 3, 4, 5],
                **_init_kwargs(f"cl_n_{file_id}", "index", 1 if "状态" in cols else 0),
            )
        with hint_col:
            st.caption("0 表示不筛选。多条同时满足；被筛掉的记录会跳过，自动用下一条。")

        filters = []
        for index in range(int(n_filters)):
            visibility = "visible" if index == 0 else "collapsed"
            left, mid, right = st.columns([2, 1, 3])
            with left:
                default_index = cols.index("状态") if index == 0 and "状态" in cols else 0
                filter_col = st.selectbox(
                    "筛选列" if index == 0 else f"筛选列{index + 1}",
                    cols,
                    label_visibility=visibility,
                    **_init_kwargs(f"cl_fcol_{file_id}_{index}", "index", default_index),
                )
            with mid:
                filter_mode = st.selectbox(
                    "方式" if index == 0 else f"方式{index + 1}",
                    ["只保留", "排除"],
                    label_visibility=visibility,
                    **_init_kwargs(f"cl_fmode_{file_id}_{index}", "index", 0),
                )
            with right:
                options = unique_text_values(ref_df[filter_col])
                value_label = "值（满足任一）" if index == 0 else f"值{index + 1}"
                if len(options) <= 40:
                    preset_values = [v for v in ["正常", "重复"] if v in options] if filter_col == "状态" else []
                    picked = st.multiselect(
                        value_label,
                        options,
                        label_visibility=visibility,
                        **_init_kwargs(f"cl_fvals_{file_id}_{index}_{filter_col}", "default", preset_values),
                    )
                else:
                    typed = st.text_input(
                        value_label,
                        label_visibility=visibility,
                        placeholder="多个值用逗号分隔",
                        **_init_kwargs(
                            f"cl_ftext_{file_id}_{index}_{filter_col}",
                            "value",
                            "正常, 重复" if filter_col == "状态" else "",
                        ),
                    )
                    picked = [part.strip() for part in re.split(r"[\n,，;；]+", typed) if part.strip()]
            filters.append({"col": filter_col, "mode": filter_mode, "values": picked})

        active_filters = [item for item in filters if any(normalize_cell(v) for v in item["values"])]
        ignored = len(filters) - len(active_filters)
        if ignored:
            st.caption(f"{ignored} 条筛选没有填值，匹配时会忽略。")

    if save_clicked:
        name = preset_name.strip()
        if not name:
            st.error("先写一个预设名称。")
        elif not key_cols or not return_cols:
            st.error("先选好匹配关键字和要取出的列，再保存。")
        else:
            replaced = name in presets
            presets[name] = current_preset(key_cols, return_cols, sort_col, sort_desc, keep_first, filters)
            store["last"] = name
            st.session_state["cl_pending_pick"] = name
            verb = "已更新" if replaced else "已保存"
            st.session_state["cl_preset_note"] = f"{verb}预设「{name}」。下次打开可直接套用。"
            st.session_state["cl_refresh_presets"] = True

    st.markdown("**输入待查关键字**")
    width = len(key_cols)
    if width == 0:
        st.warning("先选择至少一列匹配关键字。")
    else:
        sample = "\t".join(key_cols)
        st.caption(
            f"从 Excel 复制 {width} 列贴到下面，列顺序对应：{'、'.join(key_cols)}。"
            "分组表里只在每组第一行写 SKU、国家，下面单元格留空会自动沿用上一行。"
        )
        query_text = st.text_area(
            "关键字",
            height=160,
            placeholder=sample + "\n",
            key=f"cl_query_text_{file_id}",
        )
        query_file = st.file_uploader(
            "或上传查询表。每行都填全、或只在每组第一行填写，两种都支持。"
            "有表头时按列名对应（SKU 等同于虚拟SKU）；没有表头时按从左到右的列顺序。",
            type=["xlsx", "xls", "csv"],
            key=f"cl_query_file_{file_id}",
        )

        if st.button("开始匹配", type="primary"):
            if not return_cols:
                st.error("请至少选择一列要取出的值。")
            else:
                try:
                    bad_lines = []
                    wide_lines = []
                    if query_file is not None:
                        queries = _queries_from_upload(query_file, key_cols)
                    else:
                        parsed, bad_lines, wide_lines = parse_query_text(query_text, width)
                        queries = pd.DataFrame(parsed, columns=key_cols)
                    if bad_lines:
                        st.warning(f"这些行的列数不足，已跳过：{bad_lines[:20]}")
                    if wide_lines:
                        st.warning(
                            "有的行比关键字列多，多出的列已忽略。"
                            "请按当前关键字的选择顺序粘贴。"
                        )
                    if queries.empty:
                        st.error("没有可匹配的关键字。")
                    else:
                        result = match_by_keys(
                            ref_df,
                            queries,
                            key_cols,
                            return_cols,
                            active_filters,
                            None if sort_col == "（不排序）" else sort_col,
                            sort_desc,
                            keep_first,
                        )
                        st.session_state["cl_result"] = result
                        st.session_state["cl_download_cols"] = (
                            key_cols
                            + [col for col in return_cols if col not in key_cols]
                            + ["匹配状态"]
                        )
                except Exception as exc:
                    st.error(f"匹配失败：{exc}")

    result = st.session_state.get("cl_result")
    if not isinstance(result, pd.DataFrame) or result.empty:
        push_browser_store()
        return

    matched = int((result["匹配状态"] == "已匹配").sum())
    missing = int((result["匹配状态"] == "未匹配").sum())
    incomplete = int((result["匹配状态"] == "关键字不完整").sum())
    m1, m2, m3 = st.columns(3)
    m1.metric("查询行数", len(result))
    m2.metric("已匹配", matched)
    m3.metric("未匹配", missing + incomplete)

    download_cols = st.session_state.get("cl_download_cols") or list(result.columns)
    export_df = result[download_cols]
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        export_df.to_excel(writer, index=False)
    buffer.seek(0)
    st.download_button(
        "下载匹配结果",
        data=buffer.getvalue(),
        file_name=f"条件匹配结果_{stamp}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )
    st.caption("下载表含关键字列、取值列和匹配状态。下方预览另有候选条数，表示筛选后这一组还剩几条。")

    def paint_status(value):
        if value == "已匹配":
            return "background-color:#C6EFCE; color:#276221; font-weight:bold"
        if value == "未匹配":
            return "background-color:#FFC7CE; color:#9C0006; font-weight:bold"
        if value == "关键字不完整":
            return "background-color:#FFEB9C; color:#9C5700; font-weight:bold"
        return ""

    st.dataframe(
        result.style.map(paint_status, subset=["匹配状态"]),
        width="stretch",
        hide_index=True,
        height=480,
    )
    push_browser_store()
