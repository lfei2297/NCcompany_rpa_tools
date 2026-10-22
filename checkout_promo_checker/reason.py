"""按结账价测算促销文案是否成立。

检测位置：套餐价下方、规格名称、规格标签、顶栏（含价格或折扣时）。
规则：
- only $X each / $X/each / Each $X / 德文 nur 8,66 € pro Stück：现价 ÷ 件数 ≈ 文案单价
  （SKU 写明一份数量时相乘：4件*2 → 8；60set*2 → 120；30set+60set → 90）
  （规格名写了 3-piece / Three-piece 时按这个件数，末尾 *N 再乘：三件套*2 → 6）
  （规格名里的 N Stück 按 N 件）
- $X/set：现价 ÷ 套数 ≈ 文案套价
- N% OFF（价下方 / 顶栏 / 标签）：相对划线价
- 规格名称里的 Save N% / N% OFF：相对「单独买各规格现价合计」，不是划线价
  （只看十分位：0–4 舍、5–9 入；第二位不向前进位。49.45% 应写 49% OFF；32.90% 应写 33% OFF）
金额按文案小数位四舍五入，允许 0.02 元误差；折扣不设区间，必须等于按第一位四舍五入后的整数。
规格价的货币（店铺 currency，如 EUR→€）和促销文案里的货币符号不一致时，记为不符。
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


def _money(value: Decimal, places: int = 2, symbol: str = "$") -> str:
    if places <= 0:
        step = Decimal("1")
    else:
        step = Decimal("1").scaleb(-places)
    q = value.quantize(step, rounding=ROUND_HALF_UP)
    return f"{symbol}{q}"


# 裸 $ 视为美元符号，和同样用 $ 展示的币种兼容；写明 US$/A$/€ 则按该符号比对。
_PAGE_UNITS: dict[str, set[str]] = {
    "USD": {"$", "US$"},
    "EUR": {"€"},
    "GBP": {"£"},
    "JPY": {"¥"},
    "CNY": {"¥"},
    "AUD": {"$", "A$"},
    "CAD": {"$", "C$"},
    "NZD": {"$", "NZ$"},
    "HKD": {"$", "HK$"},
    "SGD": {"$", "S$"},
    "TWD": {"$", "NT$"},
    "MXN": {"$"},
    "BRL": {"$", "R$"},
    "CHF": {"CHF"},
}

_PAGE_LABEL = {
    "USD": "$（USD）",
    "EUR": "€（EUR）",
    "GBP": "£（GBP）",
    "JPY": "¥（JPY）",
    "CNY": "¥（CNY）",
    "AUD": "$（AUD）",
    "CAD": "$（CAD）",
    "NZD": "$（NZD）",
    "HKD": "$（HKD）",
    "SGD": "$（SGD）",
    "TWD": "NT$（TWD）",
    "MXN": "$（MXN）",
    "BRL": "R$（BRL）",
    "CHF": "CHF",
}

_UNIT_ALIAS = {
    "$": "$",
    "US$": "US$",
    "USD": "US$",
    "€": "€",
    "EUR": "€",
    "£": "£",
    "GBP": "£",
    "¥": "¥",
    "￥": "¥",
    "JPY": "¥",
    "CNY": "¥",
    "A$": "A$",
    "AU$": "A$",
    "AUD": "A$",
    "C$": "C$",
    "CA$": "C$",
    "CAD": "C$",
    "NZ$": "NZ$",
    "NZD": "NZ$",
    "HK$": "HK$",
    "HKD": "HK$",
    "S$": "S$",
    "SGD": "S$",
    "NT$": "NT$",
    "TWD": "NT$",
    "R$": "R$",
    "BRL": "R$",
    "CHF": "CHF",
}

_UNIT_TOKEN = (
    r"US\$|AU\$|A\$|CA\$|C\$|NZ\$|HK\$|S\$|NT\$|R\$|"
    r"€|£|¥|￥|\$|"
    r"\b(?:USD|EUR|GBP|AUD|CAD|NZD|HKD|SGD|TWD|JPY|CNY|BRL|CHF)\b"
)
_UNIT_RE = re.compile(
    rf"(?:({_UNIT_TOKEN})\s*\d|\d\s*({_UNIT_TOKEN}))",
    re.I,
)
_CUR_PREFIX = r"(?:US\$|AU\$|A\$|CA\$|C\$|NZ\$|HK\$|S\$|NT\$|R\$|€|£|¥|￥|\$)"
_AMT = r"(\d+(?:[.,]\d+)?)"


def currency_symbol(code: str) -> str:
    """店铺货币在测算说明里用的符号。未识别时仍用 $，和旧结果一致。"""
    return {
        "EUR": "€",
        "GBP": "£",
        "JPY": "¥",
        "CNY": "¥",
        "BRL": "R$",
        "TWD": "NT$",
        "CHF": "CHF",
    }.get((code or "").strip().upper(), "$")


def _offer_money_text(value: Decimal | None, currency: str) -> str:
    if value is None:
        return ""
    return _money(value, symbol=currency_symbol(currency))


def _offer_price_text(offer: PricedOffer) -> str:
    """规格当前售价，给测算表「现价」列。没有现价时留空。"""
    return _offer_money_text(offer.price, offer.currency)


def _offer_regular_text(offer: PricedOffer) -> str:
    """规格划线价，给测算表「原价」列。没有划线价时留空。"""
    return _offer_money_text(offer.regular, offer.currency)


def _norm_unit(token: str) -> str:
    return _UNIT_ALIAS.get(token.upper(), token.upper())


def _amount(raw: str) -> Decimal:
    text = raw.strip()
    if re.fullmatch(r"\d+,\d{1,2}", text):
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    return Decimal(text)


def currency_conflict_text(page_code: str, units: list[str]) -> str:
    """规格价货币和文案货币不是同一单位时，返回不符说明。"""
    code = (page_code or "").strip().upper()
    allowed = _PAGE_UNITS.get(code)
    if not allowed or not units:
        return ""
    bad: list[str] = []
    for unit in units:
        if unit not in allowed and unit not in bad:
            bad.append(unit)
    if not bad:
        return ""
    page = _PAGE_LABEL.get(code, code)
    return f"规格价货币为{page}，文案货币为{'、'.join(bad)}，货币单位不一致（不符）"


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
    money_units: list[str] = field(default_factory=list)
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

    # $X/each、€X each，或金额在后的 16,66 € each
    for m in re.finditer(
        rf"(?:only\s*)?{_CUR_PREFIX}\s*{_AMT}\s*(?:/|\s+)?each\b",
        t,
        re.I,
    ):
        _push_unique(claim.each_prices, _amount(m.group(1)))
        claim.has_numeric = True
    for m in re.finditer(
        rf"(?:only\s*)?{_AMT}\s*(?:€|£|¥|￥)\s*(?:/|\s+)?each\b",
        t,
        re.I,
    ):
        _push_unique(claim.each_prices, _amount(m.group(1)))
        claim.has_numeric = True
    # Each $X：each 写在价格前面，如「6 PCS - Each $15.49」
    for m in re.finditer(
        rf"\beach\b\s*[:\-–—]?\s*(?:only\s*)?{_CUR_PREFIX}\s*{_AMT}",
        t,
        re.I,
    ):
        _push_unique(claim.each_prices, _amount(m.group(1)))
        claim.has_numeric = True
    for m in re.finditer(
        rf"\beach\b\s*[:\-–—]?\s*(?:only\s*)?{_AMT}\s*(?:€|£|¥|￥)",
        t,
        re.I,
    ):
        _push_unique(claim.each_prices, _amount(m.group(1)))
        claim.has_numeric = True
    # 德文 nur 8,66 € pro Stück / nur €8,66 pro Stück，等于 only €X each
    _de_each = r"pro\s+st(?:ück|ueck)\b"
    for m in re.finditer(rf"(?:nur\s+)?{_AMT}\s*€\s*{_de_each}", t, re.I):
        _push_unique(claim.each_prices, _amount(m.group(1)))
        claim.has_numeric = True
    for m in re.finditer(rf"(?:nur\s+)?€\s*{_AMT}\s*{_de_each}", t, re.I):
        _push_unique(claim.each_prices, _amount(m.group(1)))
        claim.has_numeric = True
    for m in re.finditer(
        rf"(?:only\s*)?{_CUR_PREFIX}\s*{_AMT}\s*/\s*set\b",
        t,
        re.I,
    ):
        _push_unique(claim.set_prices, _amount(m.group(1)))
        claim.has_numeric = True
    for m in re.finditer(
        rf"(?:only\s*)?{_AMT}\s*(?:€|£|¥|￥)\s*/\s*set\b",
        t,
        re.I,
    ):
        _push_unique(claim.set_prices, _amount(m.group(1)))
        claim.has_numeric = True
    # 文案只有 only $X / only €X，没有 each/set，也按单价/件处理
    if not claim.each_prices and not claim.set_prices:
        for m in re.finditer(rf"only\s*{_CUR_PREFIX}\s*{_AMT}", t, re.I):
            _push_unique(claim.each_prices, _amount(m.group(1)))
            claim.has_numeric = True
        for m in re.finditer(rf"only\s*{_AMT}\s*(?:€|£|¥|￥)", t, re.I):
            _push_unique(claim.each_prices, _amount(m.group(1)))
            claim.has_numeric = True
    for m in _UNIT_RE.finditer(t):
        token = m.group(1) or m.group(2)
        if token:
            _push_unique(claim.money_units, _norm_unit(token))
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


def _sold_as_sets(attr: str, title: str) -> bool:
    """规格按套出售：写了 N sets，或选项名以 *N 结尾。set of N 仍按里面的件数。"""
    blob = f"{attr or ''} {title or ''}"
    if re.search(r"set of\s+\d+", blob, re.I):
        return False
    if re.search(r"\d+\s*sets?\b", blob, re.I):
        return True
    for src in (attr, title):
        if re.search(r"\*\s*\d+\s*$", (src or "").strip()):
            return True
    return False


_PIECE_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}


def _written_set_pieces(attr: str, title: str) -> int | None:
    """规格名写明一套几件：3-piece、3 piece、Three-piece。

    只看规格名。变体 title 常把商品名拼在前面，商品名里的 three-piece
    不能套到别的规格。6 PCS 仍走后面的件数，这里不认 pcs。
    """
    text = (attr or "").strip() or (title or "")
    if not text:
        return None
    m = re.search(r"\b(\d+)\s*-\s*pieces?\b", text, re.I)
    if m and int(m.group(1)) > 0:
        return int(m.group(1))
    m = re.search(r"\b(\d+)\s+pieces?\b", text, re.I)
    if m and int(m.group(1)) > 0:
        return int(m.group(1))
    word = "|".join(_PIECE_WORDS)
    m = re.search(rf"\b({word})(?:\s*-\s*|\s+)pieces?\b", text, re.I)
    if m:
        return _PIECE_WORDS[m.group(1).lower()]
    return None


def _pieces_in_one_set(*texts: str) -> int | None:
    """一套里有几件。来自 Set of N、N Sets/bag、N pcs/set，不看 SKU 编码。"""
    for text in texts:
        if not text:
            continue
        m = re.search(r"set of\s+(\d+)", text, re.I)
        if m:
            return int(m.group(1))
        m = re.search(r"(\d+)\s*(?:pcs?|pieces?)\s*/\s*set\b", text, re.I)
        if m:
            return int(m.group(1))
        m = re.search(r"(\d+)\s*sets?\s*/\s*bag\b", text, re.I)
        if m:
            return int(m.group(1))
    return None


def _sku_inner_qty(code: str) -> int | None:
    """一份 SKU 自己带的数量：4件、60set、30套。不算货号，也不算「10包」。"""
    text = code or ""
    m = re.search(r"(\d+)\s*件", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*套(?!装)", text)
    if m:
        return int(m.group(1))
    # 60set礼盒装：set 后面是汉字，不能用 \b（汉字也算单词字符）
    m = re.search(r"(\d+)\s*sets?(?![a-zA-Z])", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*(?:pcs?|pieces?)(?![a-zA-Z])", text, re.I)
    if m:
        return int(m.group(1))
    return None


def sku_coded_piece_count(sku: str) -> int | None:
    """SKU 写明的总件数。60set*2 → 120；30set+60set → 90；4件*2 → 8。"""
    parts = parse_sku_components(sku)
    if not parts:
        return None
    total = 0
    for code, qty in parts:
        inner = _sku_inner_qty(code)
        if inner is None:
            return None
        total += inner * qty
    return total if total else None


def _sku_pieces_per_set(sku: str) -> int | None:
    """SKU「4件」或「4件*2」里的 4，是一套的件数。"""
    return _sku_inner_qty(sku or "")


def _bundle_repeat(attr: str, title: str) -> int | None:
    """规格名把整组括起来再乘 N，如（4-hole+10包）*2。N 是购买组数。"""
    for src in (attr, title):
        m = re.search(r"[)）]\s*[*×x]\s*(\d+)\s*$", (src or "").strip(), re.I)
        if m:
            return int(m.group(1))
    return None


def _option_set_count(sku: str, attr: str, title: str) -> int | None:
    """这一档买了几套。不把标题里的 4 Sets/bag 当成购买套数。"""
    for src in (attr, title):
        text = re.sub(r"\d+\s*sets?\s*/\s*(?:bag|pack)\b", " ", src or "", flags=re.I)
        m = re.search(r"(\d+)\s*sets?\b", text, re.I)
        if m:
            return int(m.group(1))
    for src in (attr, title):
        m = re.search(r"\*\s*(\d+)\s*$", (src or "").strip())
        if m:
            return int(m.group(1))
    nums = [int(x) for x in re.findall(r"\*(\d+)", sku or "")]
    if nums and len(set(nums)) == 1 and _sold_as_sets(attr, title):
        return nums[0]
    return None


def _shared_pieces_per_set(rows: list) -> int | None:
    """同一商品各规格如果都指向同一个「一套几件」，空白 SKU 也沿用。"""
    found: list[int] = []
    for row in rows:
        n = _pieces_in_one_set(row.attr, row.title, row.product_title)
        if n is None:
            n = _sku_pieces_per_set(row.sku)
        if n is not None:
            found.append(n)
    if found and len(set(found)) == 1:
        return found[0]
    return None


def infer_piece_count(
    sku: str,
    attr: str,
    title: str,
    product_title: str,
    pieces_per_set: int | None = None,
) -> int | None:
    coded = sku_coded_piece_count(sku)
    if coded:
        return coded

    per_set = pieces_per_set or _pieces_in_one_set(attr, title, product_title)
    set_count = _option_set_count(sku, attr, title)
    # 页面写了一套有几件时，each 按件：2 Sets × 4 = 8。
    if per_set and set_count:
        return per_set * set_count

    # 3-piece / Three-piece 是一套的件数。末尾 *2 表示再买 2 套，按 6 件。
    # 必须写在「货号*2 收成 2」之前，否则三件套*2 会被当成 2 件。
    written = _written_set_pieces(attr, title)
    if written:
        return written * (set_count or 1)

    # 「（组合）*N」且每个子件都是 *N：each 按这 N 组，不再把子件加成 2N。
    # 「零件 + 零件, N sets」没有这层括号，仍走下面的零件相加。
    repeat = _bundle_repeat(attr, title)
    if repeat and not per_set:
        grouped = parse_sku_components(sku or "")
        if grouped and len(grouped) >= 2 and all(q == repeat for _, q in grouped):
            return repeat

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
            # SKU 没写 60set/4件 时，规格名 120 sets 仍按对外套数
            if set_count and set_count > total:
                return set_count
            return total

    m = re.search(r"(\d+)\s*(?:pcs?|pieces?|units?|packs?|st(?:ück|ueck))\b", blob, re.I)
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
    pieces_per_set: int | None = None
    each_count: int | None = None
    each_by_set: bool = False
    currency: str = ""


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


def _meta_currency(meta: dict) -> str:
    for src in (meta, meta.get("setting") or {}, meta.get("product") or {}):
        if not isinstance(src, dict):
            continue
        val = src.get("currency")
        if isinstance(val, str) and val.strip():
            return val.strip().upper()
    return ""


def _sku_rows(cfg: list | None) -> list[PricedOffer]:
    """SKU 新布局按 skuConfig.ID 对齐 variants，避免推荐套餐排在前面时对错价。"""
    meta = _static_meta(cfg)
    currency = _meta_currency(meta)
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
                currency=currency,
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
    shared_per_set = _shared_pieces_per_set(rows)
    for row in rows:
        row.pieces_per_set = shared_per_set
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
                pieces_per_set=row.pieces_per_set,
                currency=row.currency,
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
                currency=(priced[0].currency if priced else (rows[0].currency if rows else "")),
            )
        )

    align_each_counts(offers, [row.sku for row in rows if row.sku])
    return offers


def _component_total(sku: str) -> int | None:
    """子件箱数相加。SKU 已写 4件/60set 时不算，避免把 60set*2 收成 2。"""
    if sku_coded_piece_count(sku):
        return None
    parts = parse_sku_components(sku or "")
    if not parts:
        return None
    total = sum(q for _, q in parts)
    if len(parts) >= 2 or total >= 2:
        return total
    return None


def _each_matches(price: Decimal | None, count: int | None, claims: list[Decimal]) -> bool:
    if not count or price is None or not claims:
        return False
    actual = price / Decimal(count)
    return all(money_matches(actual, claimed) for claimed in claims)


def _sku_code_key(code: str) -> str:
    return re.sub(r"\s+", "", code or "").casefold()


def _sku_part_list(sku: str) -> list[tuple[str, int]]:
    return [
        (_sku_code_key(code), qty)
        for code, qty in parse_sku_components(sku or "")
        if str(code).strip()
    ]


def _parts_sold_as_single_items(sku: str, catalog: list[str]) -> bool:
    """组合里的货号能在本页单独买到，或另有一档是这些货号各 1 个。"""
    parts = _sku_part_list(sku)
    if len(parts) < 2:
        return False
    codes = {code for code, _qty in parts}
    singles: set[str] = set()
    qty1_combos: list[set[str]] = []
    for raw in catalog:
        comp = _sku_part_list(raw)
        if len(comp) == 1:
            singles.add(comp[0][0])
        elif comp and all(qty == 1 for _code, qty in comp):
            qty1_combos.append({code for code, _qty in comp})
    if codes <= singles:
        return True
    return any(combo == codes for combo in qty1_combos)


def _group_repeat_count(offer: PricedOffer) -> int | None:
    """（组合）×N 且每个子件都是 *N。零件没单卖时按这 N 组。"""
    repeat = _bundle_repeat(offer.attr, offer.title)
    if not repeat:
        return None
    parts = parse_sku_components(offer.sku or "")
    if len(parts) >= 2 and all(qty == repeat for _, qty in parts):
        return repeat
    return None


def align_each_counts(offers: list[PricedOffer], catalog: list[str] | None = None) -> None:
    """同一链接的 each 用同一种算法。

    先看能分清的规格：若有规格的 each 对得上「一套几件」，整页按件。
    否则若有规格的套数和件数相同、each 对得上这个数，其余规格也按套数。
    （组合）×N 默认按 N 组。这些货号若在本页单独有售，或另有一档各买 1 个，
    则按子件件数相加。不看文案单价更接近哪一个数。
    """
    rows = []
    for offer in offers:
        claims = parse_claim(offer.price_tag).each_prices
        if not claims or offer.price is None:
            continue
        rows.append(
            (
                offer,
                claims,
                _option_set_count(offer.sku, offer.attr, offer.title),
                _component_total(offer.sku),
                infer_piece_count(
                    offer.sku,
                    offer.attr,
                    offer.title,
                    offer.product_title,
                    offer.pieces_per_set,
                ),
            )
        )
    if not rows:
        return

    has_pack = any(
        offer.pieces_per_set or _pieces_in_one_set(offer.attr, offer.title, offer.product_title)
        for offer, *_ in rows
    )
    if has_pack and any(
        _each_matches(offer.price, primary, claims)
        for offer, claims, _sets, _components, primary in rows
    ):
        return

    clear = False
    component_only = False
    set_only = False
    for offer, claims, sets, components, _primary in rows:
        match_sets = _each_matches(offer.price, sets, claims)
        match_components = _each_matches(offer.price, components, claims)
        if sets and components and sets == components and match_sets:
            clear = True
        elif match_components and sets and not match_sets:
            component_only = True
        elif match_sets and components and components != sets and not match_components:
            set_only = True
    if clear and set_only and not component_only:
        for offer, _claims, sets, _components, _primary in rows:
            if sets:
                offer.each_count = sets
                offer.each_by_set = True

    # （组合）×N 的货号如果本页有单卖，或另有一档各 1 个，×N 就是每种再买 N 个。
    # 零件从未单卖时仍按组。不拿这一档的文案单价选择组数或件数。
    sku_catalog = list(catalog or [])
    sku_catalog.extend(offer.sku for offer, *_rest in rows if offer.sku)
    for offer, _claims, _sets, components, _primary in rows:
        repeat = _group_repeat_count(offer)
        if not repeat or not components or components == repeat:
            continue
        label = f"{offer.attr or ''} {offer.title or ''}"
        if re.search(r"\d+\s*sets?\b", label, re.I):
            continue
        if _parts_sold_as_single_items(offer.sku, sku_catalog):
            offer.each_count = components
            offer.each_by_set = False


@dataclass
class OfferVerdict:
    tag: str
    label: str
    status: str
    detail: str
    location: str = ""
    calc: str = ""
    price_text: str = ""
    regular_text: str = ""
    # 顶栏按规格拆行时，与明细行顺序一致的 (规格名, 现价, 原价)
    spec_prices: list = field(default_factory=list)


def _loc_short(location: str) -> str:
    return LOC_LABELS.get(location or "", location or "文案")


def evaluate_offer(offer: PricedOffer) -> OfferVerdict:
    if offer.location == LOC_HEADER and offer.peers:
        return _evaluate_header(offer)
    claim = parse_claim(offer.price_tag)
    bits: list[str] = []
    statuses: list[str] = []
    page_sym = currency_symbol(offer.currency)
    claim_sym = claim.money_units[0] if claim.money_units else page_sym
    conflict = currency_conflict_text(offer.currency, claim.money_units)

    if not claim.has_numeric and conflict:
        return OfferVerdict(
            offer.price_tag,
            offer.label,
            UNREASONABLE,
            conflict,
            location=offer.location or LOC_PRICE,
            calc=conflict,
            price_text=_offer_price_text(offer),
            regular_text=_offer_regular_text(offer),
        )
    if not claim.has_numeric and not claim.free_shipping:
        return OfferVerdict(
            offer.price_tag,
            offer.label,
            UNCHECKABLE,
            "文案没有可测算的价格或折扣数字",
            price_text=_offer_price_text(offer),
            regular_text=_offer_regular_text(offer),
        )
    if not claim.has_numeric and claim.free_shipping:
        return OfferVerdict(
            offer.price_tag,
            offer.label,
            NOT_PRICE,
            "仅为包邮/运费文案，不按售价测算",
            price_text=_offer_price_text(offer),
            regular_text=_offer_regular_text(offer),
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
            base_desc = f"单独买合计{_money(base, symbol=page_sym)}→套餐现价{_money(offer.price, symbol=page_sym)}"
        elif offer.price is None or offer.regular is None or offer.regular <= 0:
            statuses.append(UNCHECKABLE)
            bits.append("有折扣%但缺少现价或划线价，无法验算")
            base = None
            actual = None
            base_desc = ""
        else:
            base = offer.regular
            actual = (offer.regular - offer.price) / offer.regular * 100
            base_desc = f"划线价{_money(offer.regular, symbol=page_sym)}→现价{_money(offer.price, symbol=page_sym)}"
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
        pieces = offer.each_count or infer_piece_count(
            offer.sku,
            offer.attr,
            offer.title,
            offer.product_title,
            offer.pieces_per_set,
        )
        if offer.price is None:
            statuses.append(UNCHECKABLE)
            bits.append("有单价文案但缺少现价")
        elif not pieces:
            statuses.append(UNCHECKABLE)
            bits.append(f"有「each」单价但无法从规格推断件数（sku={offer.sku}）")
        else:
            actual = offer.price / Decimal(pieces)
            set_count = _option_set_count(offer.sku, offer.attr, offer.title)
            for claimed in claim.each_prices:
                ok = money_matches(actual, claimed)
                statuses.append(REASONABLE if ok else UNREASONABLE)
                mark = "符合" if ok else "不符"
                named_sets = bool(
                    re.search(r"\d+\s*sets?\b", f"{offer.attr or ''} {offer.title or ''}", re.I)
                )
                unit = (
                    "套"
                    if offer.each_by_set or (named_sets and set_count and pieces == set_count)
                    else "件"
                )
                line = (
                    f"现价{_money(offer.price, symbol=page_sym)}÷{pieces}{unit}={_money(actual, 4, symbol=page_sym)}，"
                    f"文案{_money(claimed, symbol=claim_sym)}/{unit}（{mark}）"
                )
                if (
                    not ok
                    and set_count
                    and set_count != pieces
                    and offer.price is not None
                    and money_matches(offer.price / Decimal(set_count), claimed)
                ):
                    line += (
                        f"；按{set_count}套={_money(offer.price / Decimal(set_count), 4, symbol=page_sym)}，"
                        "与套单价一致"
                    )
                bits.append(line)

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
                    f"现价{_money(offer.price, symbol=page_sym)}÷{sets}套={_money(actual, 4, symbol=page_sym)}，"
                    f"文案{_money(claimed, symbol=claim_sym)}/套（{mark}）"
                )

    if conflict:
        statuses.append(UNREASONABLE)
        bits.append(conflict)

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
        price_text=_offer_price_text(offer),
        regular_text=_offer_regular_text(offer),
    )


def _evaluate_header(offer: PricedOffer) -> OfferVerdict:
    """顶栏按每个规格算出明细，符合/不符都列出划线价和折扣。"""
    match_bits: list[str] = []
    mismatch_bits: list[str] = []
    other_bits: list[str] = []
    match_prices: list[tuple[str, str]] = []
    mismatch_prices: list[tuple[str, str]] = []
    other_prices: list[tuple[str, str]] = []
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
            currency=row.currency or offer.currency,
        )
        v = evaluate_offer(sub)
        statuses.append(v.status)
        calc = v.calc or v.detail
        line = f"{row.label}：{calc}"
        priced = (row.label, _offer_price_text(row), _offer_regular_text(row))
        if v.status == REASONABLE:
            match_bits.append(line)
            match_prices.append(priced)
        elif v.status == UNREASONABLE:
            mismatch_bits.append(line)
            mismatch_prices.append(priced)
        else:
            other_bits.append(line)
            other_prices.append(priced)

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
        spec_prices=match_prices + mismatch_prices + other_prices,
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
    """拆成表格行：结论、规格、现价、原价、位置、促销文案、测算。"""
    rows: list[dict] = []
    skip = re.compile(r"^\d+个规格|无法完整测算|没有可对照|顶栏折扣仅供参考")
    for v in verdicts:
        if (v.location or "") == LOC_HEADER or v.label == "整页":
            copy = re.sub(r"\s+", " ", v.tag or "").strip()
            prices = list(v.spec_prices or [])
            pi = 0
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
                item = prices[pi] if pi < len(prices) else ()
                price = item[1] if len(item) > 1 else ""
                regular = item[2] if len(item) > 2 else ""
                pi += 1
                rows.append(
                    {
                        "status": mark,
                        "label": lab,
                        "price": price,
                        "regular": regular,
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
                "price": v.price_text or "",
                "regular": v.regular_text or "",
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
