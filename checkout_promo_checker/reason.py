"""按结账价测算促销文案是否成立。

检测位置：套餐价下方、规格名称、规格标签、顶栏（含价格或折扣时）。
规则：
- only $X each / $X/each：现价 ÷ 件数 ≈ 文案单价
- $X/set：现价 ÷ 套数 ≈ 文案套价
- N% OFF（价下方 / 顶栏 / 标签）：相对划线价
- 规格名称里的 Save N% / N% OFF：相对「单独买各规格现价合计」，不是划线价
  （只看十分位：0–4 舍、5–9 入；第二位不向前进位。49.45% 应写 49% OFF；32.90% 应写 33% OFF）
金额按文案小数位四舍五入，允许 0.02 元误差；折扣不设区间，必须等于按第一位四舍五入后的整数。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from keywords import match_promo
from parser import (
    LOC_BADGE,
    LOC_HEADER,
    LOC_LABELS,
    LOC_PRICE,
    LOC_SPEC,
    _header_top_text,
    _price_tag_texts,
)

PRICE_ABS_TOL = Decimal("0.02")

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


def expected_off_percent(actual: Decimal) -> Decimal:
    """百分比按小数点后第一位四舍五入到整数。

    只看十分位（0–4 舍、5–9 入），十分位之后不进位：
    49.45% → 看 4 → 49%；49.50% → 看 5 → 50%；49.99% → 看 9 → 50%。
    """
    one_place = actual.quantize(Decimal("0.1"), rounding=ROUND_DOWN)
    return one_place.to_integral_value(rounding=ROUND_HALF_UP)


def percent_matches(actual: Decimal, claimed: Decimal) -> bool:
    return claimed == expected_off_percent(actual)


@dataclass
class Claim:
    percents: list[Decimal] = field(default_factory=list)
    each_prices: list[Decimal] = field(default_factory=list)
    set_prices: list[Decimal] = field(default_factory=list)
    free_shipping: bool = False
    has_numeric: bool = False


def _push_unique(seq: list, val) -> None:
    if val not in seq:
        seq.append(val)


def parse_claim(text: str) -> Claim:
    t = re.sub(r"\s+", " ", (text or "")).strip()
    claim = Claim()
    if not t:
        return claim
    if re.search(r"free\s+shipping", t, re.I) or "包邮" in t:
        claim.free_shipping = True
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*%\s*-?\s*off", t, re.I):
        _push_unique(claim.percents, Decimal(m.group(1)))
        claim.has_numeric = True
    for m in re.finditer(r"off\s+(\d+(?:\.\d+)?)\s*%", t, re.I):
        _push_unique(claim.percents, Decimal(m.group(1)))
        claim.has_numeric = True
    for m in re.finditer(r"save\s*(\d+(?:\.\d+)?)\s*%", t, re.I):
        _push_unique(claim.percents, Decimal(m.group(1)))
        claim.has_numeric = True
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*折", t):
        # 5折 = 50% off
        zhe = Decimal(m.group(1))
        off = (Decimal("10") - zhe) * 10 if zhe <= 10 else Decimal("100") - zhe
        _push_unique(claim.percents, off)
        claim.has_numeric = True

    # $X/each 或 only $X each
    for m in re.finditer(
        r"(?:only\s*)?\$\s*(\d+(?:\.\d+)?)\s*(?:/|\s+)?each\b",
        t,
        re.I,
    ):
        _push_unique(claim.each_prices, Decimal(m.group(1)))
        claim.has_numeric = True
    for m in re.finditer(
        r"(?:only\s*)?\$\s*(\d+(?:\.\d+)?)\s*/\s*set\b",
        t,
        re.I,
    ):
        _push_unique(claim.set_prices, Decimal(m.group(1)))
        claim.has_numeric = True
    # 文案只有 only $X，没有 each/set，也按单价/件处理
    if not claim.each_prices and not claim.set_prices:
        for m in re.finditer(r"only\s*\$\s*(\d+(?:\.\d+)?)", t, re.I):
            _push_unique(claim.each_prices, Decimal(m.group(1)))
            claim.has_numeric = True
    return claim


def is_promo_copy(text: str) -> bool:
    """价下/规格名/标签/顶栏：有价格、折扣或包邮等促销词才收录。"""
    t = re.sub(r"\s+", " ", (text or "")).strip()
    if not t:
        return False
    claim = parse_claim(t)
    if claim.has_numeric or claim.free_shipping:
        return True
    return bool(match_promo(t))


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
    parts = parse_sku_components(sku or "")
    if parts:
        total = sum(q for _, q in parts)
        if len(parts) >= 2 or total >= 2:
            # sku 已是 A*2+B*2 时不要再乘名称里的 2×，避免算成 8 件
            if all(q == 1 for _, q in parts):
                xm = re.search(r"(\d+)\s*[x×]", blob, re.I)
                if xm:
                    total *= int(xm.group(1))
            return total

    m = re.search(r"(\d+)\s*(?:pcs?|pieces?|units?|packs?)\b", blob, re.I)
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
    return None


def parse_sku_components(sku: str) -> list[tuple[str, int]]:
    """拆 SKU：A+B+C → 各 1 件；A*2+B*2 → A 两件。"""
    parts: list[tuple[str, int]] = []
    for raw in re.split(r"\s*\+\s*", sku or ""):
        token = raw.strip()
        if not token:
            continue
        m = re.search(r"^(.*?)(?:\*|×|x)(\d+)\s*$", token, re.I)
        if m and m.group(1).strip():
            parts.append((m.group(1).strip(), int(m.group(2))))
        else:
            parts.append((token, 1))
    return parts


def infer_standalone_total(sku: str, price_by_sku: dict[str, Decimal]) -> Decimal | None:
    """组合装相对单独买：把 SKU 拆成子件，用各子件现价相加。"""
    parts = parse_sku_components(sku)
    if not parts:
        return None
    total_qty = sum(q for _, q in parts)
    if len(parts) < 2 and total_qty < 2:
        return None
    total = Decimal(0)
    for code, qty in parts:
        unit = price_by_sku.get(code)
        if unit is None:
            return None
        total += unit * qty
    if total <= 0:
        return None
    return total


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
    location: str = LOC_PRICE
    sku_meta: dict = field(default_factory=dict)
    peers: list = field(default_factory=list)
    standalone_total: Decimal | None = None


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


def _id_key(value) -> str:
    """统一规格 ID，避免 int/str/20835042.0 对不上。"""
    if value is None or value is False:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)
    text = str(value).strip()
    if not text:
        return ""
    try:
        num = Decimal(text)
        if num == num.to_integral_value():
            return str(int(num))
    except Exception:
        pass
    return text


def _obj_ids(obj: dict) -> list[str]:
    keys = []
    for name in ("ID", "id", "variant_id", "variantId"):
        key = _id_key(obj.get(name))
        if key and key not in keys:
            keys.append(key)
    return keys


def _variant_by_id(variants: list) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for var in variants:
        if not isinstance(var, dict):
            continue
        for key in _obj_ids(var):
            out[key] = var
    return out


def _match_variant(sku: dict, variants: list, index: int, by_id: dict[str, dict]) -> dict:
    """有规格 ID 时只按 ID 对齐，绝不按下标凑合（推荐组合装常排在 skuConfig 最前）。"""
    for key in _obj_ids(sku):
        if key in by_id:
            return by_id[key]
    if _obj_ids(sku):
        return {}
    if index < len(variants) and isinstance(variants[index], dict):
        return variants[index]
    return {}


def _sku_rows(cfg: list | None) -> list[PricedOffer]:
    """SKU 新布局按 skuConfig.ID 对齐 variants，避免推荐套餐排在前面时对错价。"""
    meta = _static_meta(cfg)
    product = meta.get("product") or {}
    setting = meta.get("setting") or {}
    variants = [v for v in (product.get("variants") or []) if isinstance(v, dict)]
    sku_cfg = [s for s in (setting.get("skuConfig") or []) if isinstance(s, dict)]
    product_title = str(product.get("title") or "")
    by_id = _variant_by_id(variants)
    rows: list[PricedOffer] = []
    if sku_cfg:
        pairs = list(enumerate(sku_cfg))
    else:
        pairs = [(i, {}) for i in range(len(variants))]
    for i, sku in pairs:
        var = _match_variant(sku, variants, i, by_id)
        if not var and not sku:
            continue
        attr = _attr_text(var)
        title = str(var.get("title") or var.get("post_title") or "")
        rows.append(
            PricedOffer(
                index=i,
                label=attr or title or f"套餐{i + 1}",
                sku=str(sku.get("sku") or var.get("sku") or ""),
                price=_dec(var.get("price") or var.get("sale_price")),
                regular=_dec(var.get("regular_price") or var.get("compare_at_price")),
                price_tag="",
                attr=attr,
                title=title,
                product_title=product_title,
                location=LOC_PRICE,
                sku_meta=sku,
            )
        )
    return rows


def _spec_name_text(row: PricedOffer) -> str:
    if is_promo_copy(row.attr):
        return row.attr
    if is_promo_copy(row.title):
        return row.title
    return ""


def _fill_standalone_totals(rows: list[PricedOffer]) -> None:
    price_by_sku: dict[str, Decimal] = {}
    for row in rows:
        if row.sku and row.price is not None:
            price_by_sku[row.sku] = row.price
    for row in rows:
        row.standalone_total = infer_standalone_total(row.sku, price_by_sku)


def extract_priced_offers(cfg: list | None) -> list[PricedOffer]:
    rows = _sku_rows(cfg)
    _fill_standalone_totals(rows)
    offers: list[PricedOffer] = []
    seen: set[tuple[str, str, str]] = set()

    def add_offer(row: PricedOffer, location: str, text: str):
        t = re.sub(r"\s+", " ", (text or "")).strip()
        if not t or not is_promo_copy(t):
            return
        key = (row.sku or row.label, location, t)
        if key in seen:
            return
        seen.add(key)
        offers.append(
            PricedOffer(
                index=row.index,
                label=row.label,
                sku=row.sku,
                price=row.price,
                regular=row.regular,
                price_tag=t,
                attr=row.attr,
                title=row.title,
                product_title=row.product_title,
                location=location,
                standalone_total=row.standalone_total,
            )
        )

    for row in rows:
        sku = row.sku_meta or {}
        for text in _price_tag_texts(sku.get("priceTags")):
            add_offer(row, LOC_PRICE, text)
        spec = _spec_name_text(row)
        if spec:
            add_offer(row, LOC_SPEC, spec)
        for text in _price_tag_texts(sku.get("titleTags")):
            add_offer(row, LOC_BADGE, text)

    header = _header_top_text(cfg)
    if header and is_promo_copy(header):
        priced = [r for r in rows if r.price is not None]
        offers.append(
            PricedOffer(
                index=0,
                label="整页",
                sku="",
                price=(priced[0].price if priced else None),
                regular=(priced[0].regular if priced else None),
                price_tag=re.sub(r"\s+", " ", header).strip(),
                attr="",
                title="",
                product_title=rows[0].product_title if rows else "",
                location=LOC_HEADER,
                peers=priced or list(rows),
            )
        )

    return offers


@dataclass
class OfferVerdict:
    tag: str
    label: str
    status: str
    detail: str
    location: str = ""
    calc: str = ""


def _loc_short(location: str) -> str:
    return LOC_LABELS.get(location or "", location or "文案")


def evaluate_offer(offer: PricedOffer) -> OfferVerdict:
    if offer.location == LOC_HEADER and offer.peers:
        return _evaluate_header(offer)
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
        use_bundle = (
            offer.location == LOC_SPEC
            and offer.standalone_total is not None
            and offer.standalone_total > 0
            and offer.price is not None
        )
        if use_bundle:
            base = offer.standalone_total
            actual = (base - offer.price) / base * 100
            base_desc = f"单独买合计{_money(base)}→套餐现价{_money(offer.price)}"
        elif offer.price is None or offer.regular is None or offer.regular <= 0:
            statuses.append(UNCHECKABLE)
            bits.append("有折扣%但缺少现价或划线价，无法验算")
            base = None
            actual = None
            base_desc = ""
        else:
            base = offer.regular
            actual = (offer.regular - offer.price) / offer.regular * 100
            base_desc = f"划线价{_money(offer.regular)}→现价{_money(offer.price)}"
        if actual is not None and base is not None:
            shown = actual.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            expected = expected_off_percent(actual)
            for pct in claim.percents:
                ok = percent_matches(actual, pct)
                statuses.append(REASONABLE if ok else UNREASONABLE)
                mark = "符合" if ok else "不符"
                bits.append(
                    f"{base_desc}=实际{shown}%，应写{expected}% OFF（{mark}）"
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
                    f"现价{_money(offer.price)}÷{pieces}件={_money(actual, 4)}，"
                    f"文案{_money(claimed)}/件（{mark}）"
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
                    f"现价{_money(offer.price)}÷{sets}套={_money(actual, 4)}，"
                    f"文案{_money(claimed)}/套（{mark}）"
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
    loc = offer.location or LOC_PRICE
    calc = "；".join(bits)
    return OfferVerdict(
        offer.price_tag,
        prefix,
        status,
        calc,
        location=loc,
        calc=calc,
    )


def _evaluate_header(offer: PricedOffer) -> OfferVerdict:
    """顶栏按每个规格算出明细，符合/不符都列出划线价和折扣。"""
    match_bits: list[str] = []
    mismatch_bits: list[str] = []
    other_bits: list[str] = []
    statuses: list[str] = []
    for row in offer.peers:
        sub = PricedOffer(
            index=row.index,
            label=row.label,
            sku=row.sku,
            price=row.price,
            regular=row.regular,
            price_tag=offer.price_tag,
            attr=row.attr,
            title=row.title,
            product_title=row.product_title,
            location=LOC_HEADER,
        )
        v = evaluate_offer(sub)
        statuses.append(v.status)
        calc = v.calc or v.detail
        line = f"{row.label}：{calc}"
        if v.status == REASONABLE:
            match_bits.append(line)
        elif v.status == UNREASONABLE:
            mismatch_bits.append(line)
        else:
            other_bits.append(line)

    if UNREASONABLE in statuses:
        status = UNREASONABLE
    elif UNCHECKABLE in statuses:
        status = UNCHECKABLE
    elif statuses and set(statuses) <= {REASONABLE}:
        status = REASONABLE
    elif statuses and set(statuses) <= {NOT_PRICE}:
        status = NOT_PRICE
    elif statuses and set(statuses) <= {REASONABLE, NOT_PRICE}:
        status = REASONABLE
    else:
        status = UNCHECKABLE

    lines: list[str] = []
    if match_bits:
        lines.append(f"{len(match_bits)}个规格符合")
        lines.extend(match_bits)
    if mismatch_bits:
        lines.append(f"{len(mismatch_bits)}个规格不符")
        lines.extend(mismatch_bits)
    if other_bits:
        lines.append("无法完整测算")
        lines.extend(other_bits)
    if not lines:
        lines.append("没有可对照的规格价格")
    calc = "\n".join(lines)
    return OfferVerdict(
        offer.price_tag,
        "整页",
        status,
        calc,
        location=LOC_HEADER,
        calc=calc,
    )


def _status_mark(status: str) -> str:
    return {
        REASONABLE: "符合",
        UNREASONABLE: "不符",
        NOT_PRICE: "包邮",
        UNCHECKABLE: "无法测算",
    }.get(status, status or "无法测算")


def _clean_calc(text: str) -> str:
    return re.sub(r"（(?:符合|不符)）\s*$", "", (text or "").strip()).strip()


def format_verdict_rows(verdicts: list[OfferVerdict]) -> list[dict]:
    """拆成表格行：结论、规格、位置、促销文案、测算。"""
    rows: list[dict] = []
    skip = re.compile(r"^\d+个规格|无法完整测算|没有可对照|顶栏折扣仅供参考")
    for v in verdicts:
        if (v.location or "") == LOC_HEADER or v.label == "整页":
            copy = re.sub(r"\s+", " ", v.tag or "").strip()
            for line in (v.calc or v.detail or "").splitlines():
                line = line.strip()
                if not line or skip.search(line):
                    continue
                if "：" in line:
                    lab, rest = line.split("：", 1)
                    lab = re.sub(r"^顶栏\s*", "", lab).strip()
                else:
                    lab, rest = (v.label or "规格"), line
                if "不符" in rest:
                    mark = "不符"
                elif "符合" in rest:
                    mark = "符合"
                else:
                    mark = "无法测算"
                rows.append(
                    {
                        "status": mark,
                        "label": lab,
                        "location": "顶栏",
                        "copy": copy,
                        "calc": _clean_calc(rest),
                    }
                )
            continue
        rows.append(
            {
                "status": _status_mark(v.status),
                "label": v.label or "套餐",
                "location": _loc_short(v.location),
                "copy": re.sub(r"\s+", " ", v.tag or "").strip(),
                "calc": _clean_calc(v.calc or v.detail),
            }
        )
    return rows


def format_verdict_report(verdicts: list[OfferVerdict]) -> str:
    """Excel / 纯文本：一行一条，带结论标识和促销文案。"""
    lines: list[str] = []
    for r in format_verdict_rows(verdicts):
        copy = r["copy"]
        if len(copy) > 72:
            copy = copy[:69] + "..."
        lines.append(
            f"[{r['status']}] {r['label']}  [{r['location']}] {copy}  {r['calc']}"
        )
    return "\n".join(lines)


def _overall_from_statuses(statuses: set[str]) -> str:
    if not statuses:
        return ""
    if UNREASONABLE in statuses:
        return UNREASONABLE
    if UNCHECKABLE in statuses:
        return UNCHECKABLE
    if statuses <= {REASONABLE}:
        return REASONABLE
    if statuses <= {NOT_PRICE}:
        return NOT_PRICE
    if statuses <= {REASONABLE, NOT_PRICE}:
        return REASONABLE
    return UNCHECKABLE


def summarize(verdicts: list[OfferVerdict]) -> tuple[str, str]:
    """返回 (测算结论, 说明)。

    整页结论以价下方 / 规格名 / 标签为准。顶栏仍测算并写入说明，
    但不因个别规格对不上就把整页打成不符（全站倒计时条常是统一话术）。
    页面上只有顶栏促销时，仍用顶栏结论（例如仅顶栏 50% OFF）。
    """
    if not verdicts:
        return "", ""
    body = [
        v
        for v in verdicts
        if (v.location or "") != LOC_HEADER and v.label != "整页"
    ]
    header = [v for v in verdicts if v not in body]
    use = body if body else verdicts
    overall = _overall_from_statuses({v.status for v in use})
    detail = format_verdict_report(verdicts)
    if body and header:
        h_over = _overall_from_statuses({v.status for v in header})
        if h_over == UNREASONABLE and overall != UNREASONABLE:
            detail += "\n顶栏折扣仅供参考，未纳入整页结论（全站倒计时条常是统一话术）。"
    return overall, detail
