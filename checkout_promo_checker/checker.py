"""单条链接：落地页 → 结账页 → 促销文案检测。"""

from __future__ import annotations

from dataclasses import dataclass, field

from fetcher import FetchError, fetch_html, normalize_url
from parser import (
    LOC_LABELS,
    collect_checkout_candidates,
    extract_page_config,
    has_order_module,
    is_checkout_url,
    looks_like_checkout_config,
)
from reason import (
    NOT_PRICE,
    REASONABLE,
    TYPE_NONE,
    TYPE_PURE,
    UNREASONABLE,
    classify_page,
    evaluate_offer,
    extract_priced_offers,
    format_verdict_rows,
    parse_claim,
    summarize,
)

SYS_NONE = "无促销文案"
SYS_MATCH = "测算一致"
SYS_MISMATCH = "测算不符"
SYS_PURE = "纯文案，无法按价格测算"
SYS_CALC_FAIL = "无法完整测算"
SYS_FAIL = "无法检测"

REVIEW_YES = "是"
REVIEW_NO = "否"


@dataclass
class CheckResult:
    source_url: str
    checkout_url: str = ""
    jumped: bool = False
    copy_type: str = ""
    system_result: str = SYS_FAIL
    need_review: str = REVIEW_YES
    promo_texts: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    has_shipping: str = REVIEW_NO
    reason_detail: str = ""
    verdict_rows: list[dict] = field(default_factory=list)
    note: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def result(self) -> str:
        """兼容旧调用：用系统检查结果着色/统计。"""
        return self.system_result

    @property
    def promo_text_joined(self) -> str:
        return "\n".join(self.promo_texts)

    @property
    def locations_joined(self) -> str:
        return "、".join(self.locations)


def _try_fetch_checkout(candidates: list[str]) -> tuple[str, str, list | None, str]:
    """依次尝试候选结账 URL，返回 (final_url, html, cfg, note)。"""
    errors: list[str] = []
    for url in candidates:
        try:
            final, html = fetch_html(url)
        except FetchError as e:
            errors.append(f"{url} ({e.message})")
            continue
        cfg = extract_page_config(html)
        if is_checkout_url(final) and (looks_like_checkout_config(cfg) or cfg):
            return final, html, cfg, ""
        if is_checkout_url(final) and html and len(html) > 2000:
            return final, html, cfg, "结账页配置不完整，已回退页面文本"
        errors.append(f"{final} 不像结账页")
    return "", "", None, "未找到可访问的结账页: " + "; ".join(errors[:4])


def check_one(raw_url: str) -> CheckResult:
    source = normalize_url(raw_url)
    if not source:
        return CheckResult(
            source_url=str(raw_url or ""),
            note="链接为空",
            system_result=SYS_FAIL,
            need_review=REVIEW_YES,
        )

    out = CheckResult(source_url=source)
    try:
        final, html = fetch_html(source)
    except FetchError as e:
        out.note = f"打开原链接失败: {e.message}"
        out.system_result = SYS_FAIL
        out.need_review = REVIEW_YES
        return out

    cfg = extract_page_config(html)
    if is_checkout_url(final):
        checkout_url, checkout_html, checkout_cfg = final, html, cfg
        out.jumped = False
    else:
        candidates = collect_checkout_candidates(final, html, cfg)[:8]
        checkout_url, checkout_html, checkout_cfg, note = _try_fetch_checkout(candidates)
        out.jumped = bool(checkout_url) and (checkout_url.rstrip("/") != source.rstrip("/"))
        # 一页结账的路径常常不带 checkout，页内也没有另一条结账链接。
        if not checkout_url and has_order_module(cfg):
            checkout_url, checkout_html, checkout_cfg = final, html, cfg
            out.jumped = False
        if not checkout_url:
            out.note = note or "未能跳转到结账页"
            out.system_result = SYS_FAIL
            out.need_review = REVIEW_YES
            return out

    out.checkout_url = checkout_url
    offers = extract_priced_offers(checkout_cfg)
    if not offers:
        out.copy_type = TYPE_NONE
        out.system_result = SYS_NONE
        out.need_review = REVIEW_NO
        out.note = "结账页未发现促销文案（价下方、规格名称、规格标签、顶栏）。"
        return out

    out.promo_texts = list(
        dict.fromkeys(
            f"{LOC_LABELS.get(o.location, o.location)}：{o.price_tag}"
            if o.location
            else o.price_tag
            for o in offers
        )
    )
    locs: list[str] = []
    for o in offers:
        lab = LOC_LABELS.get(o.location, o.location)
        if lab and lab not in locs:
            locs.append(lab)
    out.locations = locs
    out.copy_type = classify_page([o.price_tag for o in offers])
    verdicts = [evaluate_offer(o) for o in offers]
    overall, detail = summarize(verdicts)
    out.reason_detail = detail
    out.verdict_rows = format_verdict_rows(verdicts)
    has_shipping = any(parse_claim(o.price_tag).free_shipping for o in offers)
    out.has_shipping = REVIEW_YES if has_shipping else REVIEW_NO
    # 只要有套餐价下文案，都建议人工扫一眼；包邮必须进店核对运费
    out.need_review = REVIEW_YES
    ship_note = " 含包邮文案，运费条件须进店核对。" if has_shipping else ""
    if overall == UNREASONABLE:
        out.system_result = SYS_MISMATCH
        out.note = "价格测算与文案不符。" + ship_note
    elif overall == REASONABLE:
        out.system_result = SYS_MATCH
        out.note = "价格测算一致，仍建议人工扫一眼页面展示。" + ship_note
    elif overall == NOT_PRICE or out.copy_type == TYPE_PURE:
        out.system_result = SYS_PURE
        out.note = "非折扣/非每件价格的纯文案（如包邮），系统无法核对店铺运费条件，需人工复核。"
    else:
        out.system_result = SYS_CALC_FAIL
        out.note = "无法按现价完整验算，需人工复核。" + ship_note
    return out
