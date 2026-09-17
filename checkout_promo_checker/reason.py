"""按结账价测算套餐价下方促销文案是否成立。

规则：
- only $X each / $X/each：现价 ÷ 件数 ≈ 文案单价
- $X/set：现价 ÷ 套数 ≈ 文案套价
- N% OFF：相对划线价的折扣 ≈ N%
金额按文案小数位四舍五入，允许 0.02 元误差；折扣允许 2 个百分点（49.5% 可写 50% OFF）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from parser import _price_tag_texts

PRICE_ABS_TOL = Decimal("0.02")
PERCENT_TOL = Decimal("2.5")  # 48% 写成 50% OFF 视为合理

REASONABLE = "文案合理"
UNREASONABLE = "文案不合理"
UNCHECKABLE = "无法测算"
NOT_PRICE = "不涉及价格"

TYPE_NONE = "无促销文案"
TYPE_PRICE = "促销文案含价格"
TYPE_DISCOUNT = "促销文案为纯折扣"
TYPE_BOTH = "促销文案含价格与折扣"
TYPE_PURE = "纯文案"


def classify_tag(text: str) -> str:
    """文案类型。纯文案（包邮等）不加「无需整改」。"""
    claim = parse_claim(text)
    has_price = bool(claim.each_prices or claim.set_prices)
    has_pct = bool(claim.percents)
    if has_price and has_pct:
        return TYPE_BOTH
    if has_price:
        return TYPE_PRICE
    if has_pct:
        return TYPE_DISCOUNT
    return TYPE_PURE


def classify_page(texts: list[str]) -> str:
    types = {classify_tag(t) for t in texts if t and t.strip()}
    if not types:
        return TYPE_NONE
    if TYPE_BOTH in types or (TYPE_PRICE in types and TYPE_DISCOUNT in types):
        return TYPE_BOTH
    if TYPE_PRICE in types:
        return TYPE_PRICE
    if TYPE_DISCOUNT in types:
        return TYPE_DISCOUNT
    return TYPE_PURE


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except Exception:
        return None


def _money(value: Decimal, places: int = 2) -> str:
    if places <= 0:
        step = Decimal("1")
    else:
        step = Decimal("1").scaleb(-places)
    q = value.quantize(step, rounding=ROUND_HALF_UP)
    return f"${q}"


def _round_to(value: Decimal, places: int) -> Decimal:
    if places <= 0:
        step = Decimal("1")
    else:
        step = Decimal("1").scaleb(-places)
    return value.quantize(step, rounding=ROUND_HALF_UP)


def money_matches(actual: Decimal, claimed: Decimal) -> bool:
    if abs(actual - claimed) <= PRICE_ABS_TOL:
        return True
    text = format(claimed, "f")
    if "." in text:
        places = len(text.split(".", 1)[1].rstrip("0")) or 1
        # 保留文案里写出的小数位，46.5 → 1 位；8.62 → 2 位
        raw_places = len(text.split(".", 1)[1])
        places = raw_places
    else:
        places = 0
    return _round_to(actual, places) == _round_to(claimed, places)


def percent_matches(actual: Decimal, claimed: Decimal) -> bool:
    return abs(actual - claimed) <= PERCENT_TOL


@dataclass
class Claim:
    percents: list[Decimal] = field(default_factory=list)
    each_prices: list[Decimal] = field(default_factory=list)
    set_prices: list[Decimal] = field(default_factory=list)
    free_shipping: bool = False
    has_numeric: bool = False


def parse_claim(text: str) -> Claim:
    t = re.sub(r"\s+", " ", (text or "")).strip()
    claim = Claim()
    if not t:
        return claim
    if re.search(r"free\s+shipping", t, re.I) or "包邮" in t:
        claim.free_shipping = True
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*%\s*-?\s*off", t, re.I):
        claim.percents.append(Decimal(m.group(1)))
        claim.has_numeric = True
    for m in re.finditer(r"off\s+(\d+(?:\.\d+)?)\s*%", t, re.I):
        claim.percents.append(Decimal(m.group(1)))
        claim.has_numeric = True
    for m in re.finditer(r"save\s+(\d+(?:\.\d+)?)\s*%", t, re.I):
        claim.percents.append(Decimal(m.group(1)))
        claim.has_numeric = True
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*折", t):
        # 5折 = 50% off
        zhe = Decimal(m.group(1))
        off = (Decimal("10") - zhe) * 10 if zhe <= 10 else Decimal("100") - zhe
        claim.percents.append(off)
        claim.has_numeric = True

    # $X/each 或 only $X each
    for m in re.finditer(
        r"(?:only\s*)?\$\s*(\d+(?:\.\d+)?)\s*(?:/|\s+)?each\b",
        t,
        re.I,
    ):
        claim.each_prices.append(Decimal(m.group(1)))
        claim.has_numeric = True
    for m in re.finditer(
        r"(?:only\s*)?\$\s*(\d+(?:\.\d+)?)\s*/\s*set\b",
        t,
        re.I,
    ):
        claim.set_prices.append(Decimal(m.group(1)))
        claim.has_numeric = True
    # 文案只有 only $X，没有 each/set，也按单价/件处理
    if not claim.each_prices and not claim.set_prices:
        for m in re.finditer(r"only\s*\$\s*(\d+(?:\.\d+)?)", t, re.I):
            claim.each_prices.append(Decimal(m.group(1)))
            claim.has_numeric = True
    return claim


def _attr_text(variant: dict) -> str:
    parts = []
    for a in variant.get("attrs") or []:
        if isinstance(a, dict):
            parts.append(str(a.get("value") or ""))
    return " ".join(parts)


def infer_piece_count(sku: str, attr: str, title: str, product_title: str) -> int | None:
    m = re.search(r"(\d+)\s*件(?:\s*\*\s*(\d+))?", sku or "")
    if m:
        return int(m.group(1)) * int(m.group(2) or 1)

    blob = f"{attr} {title}"
    m = re.search(r"(\d+)\s*(?:pcs?|pieces?|units?)\b", blob, re.I)
    if m:
        return int(m.group(1))

    set_of = None
    for src in (attr, title, product_title):
        m = re.search(r"set of\s+(\d+)", src or "", re.I)
        if m:
            set_of = int(m.group(1))
            break
    if set_of is None:
        m = re.search(r"(\d+)\s*sets?\s*/\s*bag", product_title or "", re.I)
        if m:
            set_of = int(m.group(1))

    m = re.search(r"(\d+)\s*sets?\b", blob, re.I)
    if m:
        return int(m.group(1)) * (set_of or 1)

    m = re.search(r"(\d+)\s*styles?\b", blob, re.I)
    if m:
        return int(m.group(1))

    m = re.search(r"\*((?:[1-9]\d*))\s*$", sku or "")
    if m:
        return int(m.group(1))

    if sku and "+" in sku and "*" not in sku:
        parts = [p for p in sku.split("+") if p.strip()]
        if len(parts) >= 2:
            return len(parts)
    return None


def infer_set_count(sku: str, attr: str, title: str) -> int | None:
    m = re.search(r"\*\s*(\d+)\s*$", attr or "")
    if m:
        return int(m.group(1))
    nums = [int(x) for x in re.findall(r"\*(\d+)", sku or "")]
    if nums and len(set(nums)) == 1:
        return nums[0]
    blob = f"{attr} {title}"
    m = re.search(r"(\d+)\s*sets?\b", blob, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*pcs?\b", blob, re.I)
    if m:
        return int(m.group(1))
    return None


@dataclass
class PricedOffer:
    index: int
    label: str
    sku: str
    price: Decimal | None
    regular: Decimal | None
    price_tag: str
    attr: str
    title: str
    product_title: str


def _static_meta(cfg: list | None) -> dict:
    if not cfg:
        return {}
    for item in cfg:
        if not isinstance(item, dict):
            continue
        if item.get("key") != "staticData" and item.get("type") != "static":
            continue
        for prop in item.get("_props") or []:
            if isinstance(prop, dict) and prop.get("title") == "meta":
                val = prop.get("value")
                return val if isinstance(val, dict) else {}
    return {}


def extract_priced_offers(cfg: list | None) -> list[PricedOffer]:
    meta = _static_meta(cfg)
    product = meta.get("product") or {}
    setting = meta.get("setting") or {}
    variants = product.get("variants") or []
    sku_cfg = setting.get("skuConfig") or []
    product_title = str(product.get("title") or "")
    n = max(len(variants), len(sku_cfg))
    offers: list[PricedOffer] = []
    for i in range(n):
        var = variants[i] if i < len(variants) and isinstance(variants[i], dict) else {}
        sku = sku_cfg[i] if i < len(sku_cfg) and isinstance(sku_cfg[i], dict) else {}
        tags = _price_tag_texts(sku.get("priceTags"))
        tag = tags[0] if tags else ""
        if not tag:
            continue
        attr = _attr_text(var)
        title = str(var.get("title") or var.get("post_title") or "")
        offers.append(
            PricedOffer(
                index=i,
                label=attr or title or f"套餐{i + 1}",
                sku=str(sku.get("sku") or ""),
                price=_dec(var.get("price") or var.get("sale_price")),
                regular=_dec(var.get("regular_price") or var.get("compare_at_price")),
                price_tag=tag,
                attr=attr,
                title=title,
                product_title=product_title,
            )
        )
    return offers


@dataclass
class OfferVerdict:
    tag: str
    label: str
    status: str
    detail: str


def evaluate_offer(offer: PricedOffer) -> OfferVerdict:
    claim = parse_claim(offer.price_tag)
    bits: list[str] = []
    statuses: list[str] = []

    if not claim.has_numeric and not claim.free_shipping:
        return OfferVerdict(offer.price_tag, offer.label, UNCHECKABLE, "文案没有可测算的价格或折扣数字")
    if not claim.has_numeric and claim.free_shipping:
        return OfferVerdict(
            offer.price_tag,
            offer.label,
            NOT_PRICE,
            "仅为包邮/运费文案，不按售价测算",
        )

    if claim.percents:
        if offer.price is None or offer.regular is None or offer.regular <= 0:
            statuses.append(UNCHECKABLE)
            bits.append("有折扣%但缺少现价或划线价，无法验算")
        else:
            actual = (offer.regular - offer.price) / offer.regular * 100
            actual = actual.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            for pct in claim.percents:
                ok = percent_matches(actual, pct)
                statuses.append(REASONABLE if ok else UNREASONABLE)
                mark = "符合" if ok else "不符"
                bits.append(
                    f"文案{pct}% OFF，划线价{_money(offer.regular)}→现价{_money(offer.price)}"
                    f"=实际{actual}% OFF（{mark}，允许±{PERCENT_TOL}%）"
                )

    if claim.each_prices:
        pieces = infer_piece_count(offer.sku, offer.attr, offer.title, offer.product_title)
        if offer.price is None:
            statuses.append(UNCHECKABLE)
            bits.append("有单价文案但缺少现价")
        elif not pieces:
            statuses.append(UNCHECKABLE)
            bits.append(f"有「each」单价但无法从规格推断件数（sku={offer.sku}）")
        else:
            actual = offer.price / Decimal(pieces)
            for claimed in claim.each_prices:
                ok = money_matches(actual, claimed)
                statuses.append(REASONABLE if ok else UNREASONABLE)
                mark = "符合" if ok else "不符"
                bits.append(
                    f"文案{_money(claimed)}/件，现价{_money(offer.price)}÷{pieces}件"
                    f"=实际{_money(actual, 4)}（{mark}）"
                )

    if claim.set_prices:
        sets = infer_set_count(offer.sku, offer.attr, offer.title)
        if offer.price is None:
            statuses.append(UNCHECKABLE)
            bits.append("有套价文案但缺少现价")
        elif not sets:
            statuses.append(UNCHECKABLE)
            bits.append(f"有「/set」但无法推断套数（sku={offer.sku}）")
        else:
            actual = offer.price / Decimal(sets)
            for claimed in claim.set_prices:
                ok = money_matches(actual, claimed)
                statuses.append(REASONABLE if ok else UNREASONABLE)
                mark = "符合" if ok else "不符"
                bits.append(
                    f"文案{_money(claimed)}/套，现价{_money(offer.price)}÷{sets}套"
                    f"=实际{_money(actual, 4)}（{mark}）"
                )

    if UNREASONABLE in statuses:
        status = UNREASONABLE
    elif UNCHECKABLE in statuses:
        status = UNCHECKABLE
    elif statuses:
        status = REASONABLE
    else:
        status = UNCHECKABLE
        bits.append("未能解析出可测算项")

    prefix = offer.label.strip() or f"套餐{offer.index + 1}"
    return OfferVerdict(offer.price_tag, prefix, status, f"{prefix}：文案「{offer.price_tag}」；" + "；".join(bits))


def summarize(verdicts: list[OfferVerdict]) -> tuple[str, str]:
    """返回 (测算结论, 说明)。无文案时由调用方处理。"""
    if not verdicts:
        return "", ""
    statuses = {v.status for v in verdicts}
    if UNREASONABLE in statuses:
        overall = UNREASONABLE
    elif UNCHECKABLE in statuses:
        overall = UNCHECKABLE
    elif statuses <= {REASONABLE}:
        overall = REASONABLE
    elif statuses <= {NOT_PRICE}:
        overall = NOT_PRICE
    elif statuses <= {REASONABLE, NOT_PRICE}:
        overall = REASONABLE
    else:
        overall = UNCHECKABLE
    detail = " | ".join(v.detail for v in verdicts)
    return overall, detail
