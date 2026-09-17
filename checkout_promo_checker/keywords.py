"""套餐价格下方促销文案的归类规则。

检测对象是结账页套餐现价下面那一行（priceTags），不是顶栏。
有文案即提示人工复核；本模块只给命中类型，不判断折扣是否合理。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 命中即视为促销文案（英文独立站结账页为主，附中文）
PROMO_PATTERNS: list[tuple[str, str]] = [
    ("百分比折扣", r"\d+\s*%\s*-?\s*off"),
    ("百分比折扣", r"off\s+\d+\s*%"),
    ("百分比折扣", r"\d+\s*%\s*discount"),
    ("百分比折扣", r"save\s+\d+\s*%"),
    ("百分比折扣", r"up\s*to\s*\d+\s*%"),
    ("百分比折扣", r"\d+\s*折"),
    ("金额优惠", r"save\s*\$\s*\d+(?:\.\d+)?"),
    ("金额优惠", r"\$\s*\d+(?:\.\d+)?\s*off"),
    ("促销价", r"only\s*\$\s*\d+(?:\.\d+)?"),
    ("促销价", r"(?:was|now)\s*\$\s*\d+(?:\.\d+)?"),
    ("促销价", r"\$\s*\d+(?:\.\d+)?\s*/?\s*(?:each|set|pc|pcs)?"),
    ("折扣词", r"\b\d+\s*%\s*off\b"),
    ("折扣词", r"\bdiscount(?:s)?\b"),
    ("折扣词", r"\bcoupon\b"),
    ("折扣词", r"\bpromo(?:tion|tional)?\b"),
    ("折扣词", r"\bflash\s+sale\b"),
    ("折扣词", r"limited[-\s]?time\s+(?:discount|offer|deal|sale)"),
    ("折扣词", r"\bhalf\s*-?\s*off\b"),
    ("折扣词", r"buy\s+\d+\s+get\s+\d+"),
    ("折扣词", r"\bfree\s+shipping\b"),
    ("折扣词", r"优惠|满减|特价|秒杀|限时折扣|限时优惠"),
]

# 编译
_COMPILED = [(name, re.compile(pat, re.I)) for name, pat in PROMO_PATTERNS]

# 这些「百分号/折扣词」出现在保障、支付安全文案里，不算促销
_FALSE_POSITIVE = re.compile(
    r"("
    r"100\s*%\s*(encrypted|secure|satisfied|satisfaction|happy|guarantee|guaranteed)|"
    r"\b\d{1,3}\s*%\s*(encrypted|secure)\b|"
    r"\b\d+\s*[- ]?day[s]?\s+(money\s+back|guarantee|return)|"
    r"money\s+back\s+guarantee|"
    r"secure(?:d)?\s+checkout|"
    r"satisfaction\s+guarantee|"
    r"recommended\s+deal|"
    r"best\s+seller|"
    r"order\s+now|"
    r"final\s+step|"
    r"complete\s+your\s+order"
    r")",
    re.I,
)

# 评论、页脚、拒买文案里的促销词不作为结账页促销条
SKIP_PATH_HINTS = (
    "comment",
    "review",
    "faq",
    "footer",
    "shippingzones",
    "seodescription",
    "seotitle",
    "upsell",
    "privacy",
    "terms",
)


@dataclass
class PromoHit:
    text: str
    location: str
    keywords: list[str]


def _normalize(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ").replace("&nbsp;", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_false_positive(text: str) -> bool:
    t = _normalize(text)
    if not t:
        return True
    if _FALSE_POSITIVE.fullmatch(t):
        return True
    # 整句都是保障/结账提示
    if re.search(
        r"(encrypted|secure checkout|money back|satisfaction guarantee|final step: complete)",
        t,
        re.I,
    ) and not re.search(r"\d+\s*%\s*off|save\s*\$|only\s*\$", t, re.I):
        return True
    return False


def match_promo(text: str) -> list[str]:
    """返回命中的规则名称；无命中返回空列表。"""
    t = _normalize(text)
    if not t or is_false_positive(t):
        return []
    names: list[str] = []
    seen = set()
    for name, cre in _COMPILED:
        if name in seen:
            continue
        if cre.search(t):
            # 纯 "100%" 且不是 off/discount，上面已过滤
            names.append(name)
            seen.add(name)
    return names


def should_skip_path(path: str) -> bool:
    p = (path or "").lower()
    return any(h in p for h in SKIP_PATH_HINTS)
