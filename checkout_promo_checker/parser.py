"""解析一页商店（Shopage 类）页面配置，并抽取结账页文案。"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

from keywords import PromoHit, match_promo, should_skip_path


def parse_json_value(text: str, start: int) -> Any:
    depth_obj = 0
    depth_arr = 0
    in_str = False
    esc = False
    for i, ch in enumerate(text[start:]):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth_obj += 1
        elif ch == "}":
            depth_obj -= 1
        elif ch == "[":
            depth_arr += 1
        elif ch == "]":
            depth_arr -= 1
            if depth_arr == 0 and depth_obj == 0:
                raw = text[start : start + i + 1]
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return None
    return None


def extract_page_config(html: str) -> list[dict] | None:
    """抽出 window[...] = [页面配置] 中体积最大的组件配置。"""
    best = None
    best_len = 0
    for m in re.finditer(r"window\[[^\n]{0,800}?\]\s*=\s*\[", html):
        data = parse_json_value(html, m.end() - 1)
        if not isinstance(data, list) or not data:
            continue
        blob = json.dumps(data, ensure_ascii=False)
        if ("_props" not in blob and '"tag"' not in blob) or len(blob) <= best_len:
            continue
        best = data
        best_len = len(blob)
    return best


def walk(obj: Any, path: str = ""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else str(k)
            yield from walk(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if "shipping" in path.lower() and i > 2:
                break
            yield from walk(v, f"{path}[{i}]")
    else:
        yield path, obj


def find_prop(item: dict, key: str) -> Any:
    for p in item.get("_props") or []:
        if isinstance(p, dict) and p.get("key") == key:
            return p.get("value")
    return None


def is_checkout_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return bool(re.search(r"(?:^|/)(?:pages|funnel)/checkout|/checkout(?:-|/|$)", path))


def get_next_url(cfg: list | None) -> str:
    if not cfg:
        return ""
    for item in cfg:
        if isinstance(item, dict) and (item.get("tag") == "next" or item.get("key") == "next"):
            v = find_prop(item, "next-url")
            if isinstance(v, str):
                return v.strip()
    return ""


class _HrefParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs: list[str] = []
        self.texts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip = True
        ad = dict(attrs)
        href = ad.get("href") or ad.get("data-href")
        if href:
            self.hrefs.append(href)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._skip = False

    def handle_data(self, data):
        if self._skip:
            return
        t = " ".join(data.split())
        if t:
            self.texts.append(t)


def _checkout_hrefs_from_html(html: str) -> list[str]:
    hrefs: list[str] = []
    for m in re.finditer(
        r"""(?:href|data-href)\s*=\s*["']([^"']*(?:/pages/|/funnel/)?(?:checkout|landingpage)-[^"']*)["']""",
        html,
        re.I,
    ):
        hrefs.append(m.group(1))
    for m in re.finditer(
        r"""/(?:pages|funnel)/(?:checkout|landingpage)-[^"'\\\s<>]*""",
        html,
        re.I,
    ):
        hrefs.append(m.group(0))
    return hrefs


def _path_tokens(url: str) -> set[str]:
    path = urlparse(url).path.lower()
    tokens = set(re.findall(r"[a-z0-9]+", path))
    tokens -= {"pages", "funnel", "news", "checkout", "landingpage", "www", "m", "http", "https"}
    return tokens


def rank_checkout_candidates(source_url: str, candidates: list[str]) -> list[str]:
    """同一商品 slug 优先，避免跳到页脚推荐的其它产品结账页。"""
    src = _path_tokens(source_url)
    if not src:
        return candidates

    def score(u: str) -> tuple:
        other = _path_tokens(u)
        overlap = len(src & other) / max(len(src), 1)
        return (-overlap, candidates.index(u))

    return sorted(candidates, key=score)


def _slug_suffix(path: str) -> str:
    m = re.search(r"((?:-\d+)*-m)/?$", path, re.I)
    return m.group(1) if m else ""


def _product_slug(path_or_href: str) -> str:
    m = re.search(
        r"/(?:pages|funnel)/(?:checkout|landingpage|news)-([^/?#]+)",
        path_or_href,
        re.I,
    )
    if not m:
        return ""
    slug = m.group(1)
    slug = re.sub(r"((?:-\d+)*-m)$", "", slug, flags=re.I)
    return slug.strip("-")


def _checkout_paths_from_slug(parsed, slug: str, suffix: str) -> list[str]:
    if not slug:
        return []
    out = []
    for prefix in ("/pages/checkout-", "/funnel/checkout-"):
        for tail in (suffix, ""):
            path = prefix + slug + tail
            out.append(urlunparse(parsed._replace(path=path, query="", fragment="")))
    return out


def collect_checkout_candidates(page_url: str, html: str, cfg: list | None) -> list[str]:
    """从落地页推导结账页候选 URL，已是结账页则只返回自身。"""
    ordered: list[str] = []

    def add(u: str):
        if not u or u in ("#", "/", "javascript:void(0)"):
            return
        full = urljoin(page_url, u)
        if full not in ordered:
            ordered.append(full)

    if is_checkout_url(page_url):
        add(page_url)
        return ordered

    next_url = get_next_url(cfg)
    if next_url and next_url not in ("#", "") and "checkout" in next_url.lower():
        add(next_url)

    parsed = urlparse(page_url)
    path = parsed.path or ""
    suffix = _slug_suffix(path)
    if "/news-" in path:
        rewritten = path.replace("/news-", "/checkout-", 1)
        add(urlunparse(parsed._replace(path=rewritten)))

    hrefs: list[str] = list(_checkout_hrefs_from_html(html))
    if cfg:
        blob = json.dumps(cfg, ensure_ascii=False)
        for m in re.finditer(
            r"/(?:pages|funnel)/(?:checkout|landingpage)-[^\"'\\\s<>]*",
            blob,
            re.I,
        ):
            hrefs.append(m.group(0))
        for item in cfg:
            if not isinstance(item, dict):
                continue
            if item.get("tag") == "customize-html":
                val = find_prop(item, "customize-html")
                if isinstance(val, str):
                    hrefs.extend(_checkout_hrefs_from_html(val))

    for href in hrefs:
        if re.search(r"/(?:pages|funnel)/checkout-", href, re.I):
            add(href)
        slug = _product_slug(href)
        if slug:
            for u in _checkout_paths_from_slug(parsed, slug, suffix):
                add(u)

    orig_slug = _product_slug(path)
    if orig_slug:
        for u in _checkout_paths_from_slug(parsed, orig_slug, suffix):
            add(u)

    # pages <-> funnel 互换，处理模板前缀不一致
    extras: list[str] = []
    for u in ordered:
        if "/pages/" in u:
            extras.append(u.replace("/pages/", "/funnel/", 1))
        if "/funnel/" in u:
            extras.append(u.replace("/funnel/", "/pages/", 1))
    for u in extras:
        add(u)

    return rank_checkout_candidates(page_url, ordered)


def _header_top_text(cfg: list) -> str:
    for item in cfg:
        if not isinstance(item, dict) or item.get("tag") != "header":
            continue
        val = find_prop(item, "topText")
        if isinstance(val, list):
            for x in val:
                if isinstance(x, dict) and x.get("key") in ("text", "value"):
                    t = x.get("value")
                    if isinstance(t, str) and t.strip():
                        return t.strip()
                if isinstance(x, dict) and isinstance(x.get("value"), str) and x.get("key") == "text":
                    return x["value"].strip()
        elif isinstance(val, str) and val.strip():
            return val.strip()
        # 有的结构是 topText.value[0].value
        for path, v in walk(item):
            if path.endswith(".value") and isinstance(v, str) and v.strip() and len(v) < 300:
                if "toptext" in path.lower() or path.endswith("value[0].value"):
                    # 取第一段可见文案
                    if not v.startswith("/") and "http" not in v[:12]:
                        return v.strip()
    return ""


PROMO_LOCATION = "套餐价格下方"
LOC_PRICE = PROMO_LOCATION
LOC_SPEC = "规格名称"
LOC_BADGE = "规格标签"
LOC_HEADER = "顶栏"
LOC_LABELS = {
    LOC_PRICE: "价下方",
    LOC_SPEC: "规格名",
    LOC_BADGE: "规格标签",
    LOC_HEADER: "顶栏",
}


def _price_tag_texts(value) -> list[str]:
    out: list[str] = []
    if value is None:
        return out
    if isinstance(value, str):
        t = re.sub(r"<[^>]+>", " ", value)
        t = re.sub(r"\s+", " ", t).strip()
        if t:
            out.append(t)
        return out
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                for key in ("text", "value", "content"):
                    out.extend(_price_tag_texts(item.get(key)))
            else:
                out.extend(_price_tag_texts(item))
        return out
    if isinstance(value, dict):
        for key in ("text", "value", "content"):
            out.extend(_price_tag_texts(value.get(key)))
    return out


def extract_copy_snippets(cfg: list | None, html: str = "") -> list[tuple[str, str]]:
    """抽取结账页促销文案：价下 priceTags、规格名、规格标签、顶栏。

    对应 SKU 新布局卡片上的价下文案、规格里的 Save X% OFF、
    以及标签/顶栏里带价格或折扣的文案。Best Seller 等非价格标签不收录。
    """
    snippets: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(location: str, text: str):
        t = re.sub(r"\s+", " ", (text or "").strip())
        if not t or t in seen or len(t) > 400:
            return
        seen.add(t)
        snippets.append((location, t))

    if cfg:
        header = _header_top_text(cfg)
        if header and match_promo(header):
            add(LOC_HEADER, header)
        for path, v in walk(cfg):
            if should_skip_path(path):
                continue
            leaf = path.split(".")[-1].lower()
            if leaf in ("pricetags", "pricetag"):
                for text in _price_tag_texts(v):
                    add(LOC_PRICE, text)
            elif leaf in ("titletags", "titletag"):
                for text in _price_tag_texts(v):
                    if match_promo(text):
                        add(LOC_BADGE, text)

    return snippets


def detect_from_checkout(cfg: list | None, html: str = "") -> list[PromoHit]:
    """套餐价下方只要填了文案即提示人工复核；关键词仅用于归类。"""
    hits: list[PromoHit] = []
    for location, text in extract_copy_snippets(cfg, html):
        kws = match_promo(text) or ["套餐价下文案"]
        hits.append(PromoHit(text=text, location=location, keywords=kws))
    return hits


def looks_like_checkout_config(cfg: list | None) -> bool:
    if not cfg:
        return False
    tags = {(x.get("tag") or "").lower() for x in cfg if isinstance(x, dict)}
    keys = {(x.get("key") or "").lower() for x in cfg if isinstance(x, dict)}
    return bool({"header", "order", "quickorder", "banner"} & (tags | keys))


def has_order_module(cfg: list | None) -> bool:
    """页面自带下单模块。路径里没有 checkout 的一页结账靠这个识别。"""
    if not cfg:
        return False
    for item in cfg:
        if isinstance(item, dict) and str(item.get("tag") or "").lower() == "order":
            return True
    return False
