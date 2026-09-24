from decimal import Decimal

from reason import (
    TYPE_BOTH,
    TYPE_DISCOUNT,
    TYPE_PRICE,
    TYPE_PURE,
    OfferVerdict,
    PricedOffer,
    classify_tag,
    evaluate_offer,
    extract_priced_offers,
    format_verdict_report,
    infer_piece_count,
    infer_set_count,
    infer_standalone_total,
    is_promo_copy,
    money_matches,
    parse_claim,
    parse_sku_components,
    percent_matches,
    summarize,
)
from parser import LOC_BADGE, LOC_HEADER, LOC_PRICE, LOC_SPEC


def offer(**kwargs):
    defaults = dict(
        index=0,
        label="2 Sets",
        sku="QH2692361-4件*2",
        price=Decimal("68.99"),
        regular=Decimal("132.65"),
        price_tag="🔥only $8.62 each!",
        attr="2 Sets",
        title="2 Sets",
        product_title="3/4 Inch Garden Hose Quick Connector 4 Sets/bag",
    )
    defaults.update(kwargs)
    return PricedOffer(**defaults)


def test_parse_and_units():
    c = parse_claim("Save21%")
    assert c.percents == [Decimal("21")]
    c = parse_claim("🔥only $8.62 each!")
    assert c.each_prices == [Decimal("8.62")]
    c = parse_claim("50% OFF $46.5/each")
    assert Decimal("50") in c.percents
    assert Decimal("46.5") in c.each_prices
    c = parse_claim("$38.99/set")
    assert c.set_prices == [Decimal("38.99")]
    assert infer_piece_count("QH2692361-4件*2", "2 Sets", "", "4 Sets/bag") == 8
    assert infer_piece_count("QH2692361-4件", "1 Set (Set of 4)", "", "") == 4
    assert infer_piece_count("FD3096590-1*2+FD3352377-切丝*2", "2× Combo Set", "", "") == 4
    assert infer_piece_count("FD3096590-1+FD3352377-切丝", "Combo Set", "", "") == 2
    assert infer_set_count("A*2+B*2", "(Style A + Style B) * 2", "") == 2
    print("parse ok")


def test_hose_each():
    v = evaluate_offer(offer())
    assert v.status == "文案合理", v.detail
    v = evaluate_offer(
        offer(
            sku="QH2692361-4件",
            price=Decimal("42.99"),
            regular=Decimal("82.65"),
            price_tag="🔥only $10.75 each!",
            attr="1 Set (Set of 4)",
        )
    )
    assert v.status == "文案合理", v.detail
    print("hose ok")


def test_percent_and_each():
    # (184.1 - 92.99) / 184.1 ≈ 49.49%，小数点后第一位是 4，应写 49% OFF，不能写 50%
    v = evaluate_offer(
        offer(
            sku="EI3610094A-棕色*2",
            price=Decimal("92.99"),
            regular=Decimal("184.1"),
            price_tag="49% OFF $46.5/each",
            attr="2 PCS",
            title="2 PCS",
        )
    )
    assert v.status == "文案合理", v.detail
    v = evaluate_offer(
        offer(
            sku="EI3610094A-棕色*2",
            price=Decimal("92.99"),
            regular=Decimal("184.1"),
            price_tag="50% OFF $46.5/each",
            attr="2 PCS",
            title="2 PCS",
        )
    )
    assert v.status == "文案不合理", v.detail
    print("percent+each ok")


def test_set_price():
    v = evaluate_offer(
        offer(
            sku="AX*2+UH*2",
            price=Decimal("77.99"),
            regular=Decimal("152.9"),
            price_tag="$38.99/set",
            attr="(Style A + Style B) * 2",
            title="",
        )
    )
    assert v.status == "文案合理", v.detail
    v = evaluate_offer(
        offer(
            sku="AX*3+UH*3",
            price=Decimal("102.99"),
            regular=Decimal("201.9"),
            price_tag="$34/set",
            attr="(Style A + Style B) * 3",
        )
    )
    assert v.status == "文案合理", v.detail
    print("set ok")


def test_mismatch():
    v = evaluate_offer(offer(price_tag="🔥only $1.00 each!"))
    assert v.status == "文案不合理", v.detail
    v = evaluate_offer(
        offer(
            sku="x",
            price=Decimal("90"),
            regular=Decimal("100"),
            price_tag="50% OFF",
            attr="1 PC",
        )
    )
    assert v.status == "文案不合理", v.detail
    print("mismatch ok")


def test_types():
    assert classify_tag("🔥only $8.62 each!") == TYPE_PRICE
    assert classify_tag("50% OFF") == TYPE_DISCOUNT
    assert classify_tag("50% OFF $46.5/each") == TYPE_BOTH
    assert classify_tag("💚Free Shipping") == TYPE_PURE
    assert "无需整改" not in TYPE_PURE
    print("types ok")


def _cfg(variants, sku_config, header=""):
    cfg = [
        {
            "key": "staticData",
            "type": "static",
            "_props": [
                {
                    "title": "meta",
                    "value": {
                        "product": {"title": "Demo", "variants": variants},
                        "setting": {"skuConfig": sku_config, "productShowMode": "sku"},
                    },
                }
            ],
        }
    ]
    if header:
        cfg.append(
            {
                "tag": "header",
                "_props": [{"key": "topText", "value": [{"key": "text", "value": header}]}],
            }
        )
    return cfg


def test_save_percent_in_spec_name():
    assert is_promo_copy("Save 32% OFF")
    assert is_promo_copy("Only $10.39 each!")
    assert not is_promo_copy("Best Seller")
    assert not is_promo_copy("🐱Cat")
    c = parse_claim("🐱Cat + 🐶Dog + 👻Ghost + 🎄Christmas (Save 32% OFF)")
    assert c.percents == [Decimal("32")], c.percents
    c = parse_claim("🐱Cat + 🐶Dog (Save 19%)")
    assert c.percents == [Decimal("19")]
    v = evaluate_offer(
        offer(
            sku="A+B+C+D",
            price=Decimal("45.59"),
            regular=Decimal("89.39"),
            price_tag="🐱Cat + 🐶Dog + 👻Ghost + 🎄Christmas (Save 32% OFF)",
            attr="🐱Cat + 🐶Dog + 👻Ghost + 🎄Christmas (Save 32% OFF)",
            location=LOC_SPEC,
        )
    )
    assert v.status == "文案不合理", v.detail
    v = evaluate_offer(
        offer(
            sku="A+B+C+D",
            price=Decimal("45.59"),
            regular=Decimal("89.39"),
            price_tag="Save 49% OFF",
            attr="Save 49% OFF",
            location=LOC_SPEC,
        )
    )
    assert v.status == "文案合理", v.detail
    print("spec save% ok")


def test_sku_id_pairing_and_locations():
    variants = [
        {
            "ID": 1,
            "title": "Cat",
            "price": 16.99,
            "regular_price": 33.9,
            "attrs": [{"name": "Style", "value": "🐱Cat"}],
        },
        {
            "ID": 10,
            "title": "Combo",
            "price": 45.59,
            "regular_price": 89.39,
            "attrs": [
                {
                    "name": "Style",
                    "value": "🐱Cat + 🐶Dog + 👻Ghost + 🎄Christmas (Save 32% OFF)",
                }
            ],
        },
    ]
    sku_config = [
        {
            "ID": 10,
            "sku": "A+B+C+D",
            "titleTags": [{"text": "Best Seller"}, {"text": "50% OFF"}],
            "priceTags": "Only $10.39 each!",
        },
        {"ID": 1, "sku": "A", "titleTags": [{"text": "Best Seller"}], "priceTags": None},
    ]
    offers = extract_priced_offers(
        _cfg(variants, sku_config, header="Order now and get 50% OFF!")
    )
    locs = {(o.location, o.label, o.price_tag) for o in offers}
    assert any(o.location == LOC_PRICE and "10.39" in o.price_tag for o in offers)
    assert any(o.location == LOC_SPEC and "Save 32% OFF" in o.price_tag for o in offers)
    assert any(o.location == LOC_BADGE and o.price_tag == "50% OFF" for o in offers)
    assert not any(o.location == LOC_BADGE and "Best Seller" in o.price_tag for o in offers)
    header_offers = [o for o in offers if o.location == LOC_HEADER]
    assert len(header_offers) == 1
    combo_price = next(o for o in offers if o.location == LOC_PRICE and "10.39" in o.price_tag)
    assert combo_price.price == Decimal("45.59"), combo_price
    assert combo_price.regular == Decimal("89.39")
    v = evaluate_offer(combo_price)
    assert v.status == "文案不合理", v.detail
    print("sku pairing ok", locs)


def test_do_not_attach_combo_pricetag_to_single_by_index():
    """书签页：skuConfig 把组合装排最前，variants 却是单件在前，按下标会算成 $16.99÷4。"""
    variants = [
        {
            "ID": 20835032,
            "price": 16.99,
            "regular_price": 33.9,
            "attrs": [{"name": "Style", "value": "🐱Cat"}],
        },
        {
            "ID": "20835033",
            "price": 16.99,
            "regular_price": 33.9,
            "attrs": [{"name": "Style", "value": "🐶Dog"}],
        },
        {
            "ID": 20835042,
            "price": 45.59,
            "regular_price": 89.39,
            "attrs": [
                {
                    "name": "Style",
                    "value": "🐱Cat + 🐶Dog + 👻Ghost + 🎄Christmas (Save 32% OFF)",
                }
            ],
        },
        {
            "ID": "20835043",
            "price": 76.75,
            "regular_price": 150.49,
            "attrs": [{"name": "Style", "value": "🎁All Style - 8PCS (Save 44% OFF)"}],
        },
        {
            "ID": 20835040,
            "price": 27.39,
            "regular_price": 53.7,
            "attrs": [{"name": "Style", "value": "🐱Cat + 🐶Dog (Save 19%)"}],
        },
    ]
    sku_config = [
        {
            "ID": "20835042",
            "sku": "VW-猫+VW-狗+VW-幽灵+VW-圣诞",
            "priceTags": "Only $10.39 each!",
        },
        {
            "ID": 20835043,
            "sku": "VW-猫+VW-狗+VW-虎+VW-鸟+VW-花+VW-恐龙+VW-幽灵+VW-圣诞",
            "priceTags": "Only $9.09 each!",
        },
        {"ID": 20835032, "sku": "VW-猫", "priceTags": None},
        {"ID": "20835033", "sku": "VW-狗", "priceTags": None},
        {
            "ID": 20835040,
            "sku": "VW-猫+VW-狗",
            "priceTags": "Only $11.69 each!",
        },
    ]
    offers = extract_priced_offers(_cfg(variants, sku_config))
    price_offers = [o for o in offers if o.location == LOC_PRICE]
    by_label = {o.label: o for o in price_offers}
    assert "🐱Cat" not in by_label
    assert "🐶Dog" not in by_label
    combo = by_label["🐱Cat + 🐶Dog + 👻Ghost + 🎄Christmas (Save 32% OFF)"]
    assert combo.price == Decimal("45.59")
    assert combo.sku.count("+") == 3
    v = evaluate_offer(combo)
    assert "$45.59÷4件" in v.detail, v.detail
    assert "$16.99" not in v.detail
    eight = by_label["🎁All Style - 8PCS (Save 44% OFF)"]
    assert eight.price == Decimal("76.75")
    v8 = evaluate_offer(eight)
    assert "$76.75÷8件" in v8.detail, v8.detail
    two = by_label["🐱Cat + 🐶Dog (Save 19%)"]
    assert two.price == Decimal("27.39")
    v2 = evaluate_offer(two)
    assert "$27.39÷2件" in v2.detail, v2.detail
    print("no index mismatch ok")


def test_bundle_save_vs_singles():
    singles = Decimal("16.99")
    by_sku = {
        "VW-猫": singles,
        "VW-狗": singles,
        "VW-幽灵": singles,
        "VW-圣诞": singles,
        "VW-虎": singles,
        "VW-鸟": singles,
        "VW-花": singles,
        "VW-恐龙": singles,
    }
    assert parse_sku_components("VW-猫+VW-狗+VW-幽灵+VW-圣诞") == [
        ("VW-猫", 1),
        ("VW-狗", 1),
        ("VW-幽灵", 1),
        ("VW-圣诞", 1),
    ]
    four = infer_standalone_total("VW-猫+VW-狗+VW-幽灵+VW-圣诞", by_sku)
    assert four == Decimal("67.96")
    v = evaluate_offer(
        offer(
            sku="VW-猫+VW-狗+VW-幽灵+VW-圣诞",
            price=Decimal("45.59"),
            regular=Decimal("89.39"),
            price_tag="🐱Cat + 🐶Dog + 👻Ghost + 🎄Christmas (Save 32% OFF)",
            attr="🐱Cat + 🐶Dog + 👻Ghost + 🎄Christmas (Save 32% OFF)",
            location=LOC_SPEC,
            standalone_total=four,
        )
    )
    # 22.37/67.96≈32.90%，十分位 9 → 应写 33% OFF，页面 32% 不符
    assert v.status == "文案不合理", v.detail
    assert "单独买合计$67.96" in v.detail, v.detail
    assert "应写33% OFF" in v.detail, v.detail

    two = infer_standalone_total("VW-猫+VW-狗", by_sku)
    assert two == Decimal("33.98")
    v = evaluate_offer(
        offer(
            sku="VW-猫+VW-狗",
            price=Decimal("27.39"),
            regular=Decimal("53.70"),
            price_tag="🐱Cat + 🐶Dog (Save 19%)",
            attr="🐱Cat + 🐶Dog (Save 19%)",
            location=LOC_SPEC,
            standalone_total=two,
        )
    )
    assert v.status == "文案合理", v.detail
    assert "单独买合计$33.98" in v.detail

    eight = infer_standalone_total(
        "VW-猫+VW-狗+VW-虎+VW-鸟+VW-花+VW-恐龙+VW-幽灵+VW-圣诞", by_sku
    )
    assert eight == Decimal("135.92")
    v = evaluate_offer(
        offer(
            sku="VW-猫+VW-狗+VW-虎+VW-鸟+VW-花+VW-恐龙+VW-幽灵+VW-圣诞",
            price=Decimal("76.75"),
            regular=Decimal("150.49"),
            price_tag="🎁All Style - 8PCS (Save 44% OFF)",
            attr="🎁All Style - 8PCS (Save 44% OFF)",
            location=LOC_SPEC,
            standalone_total=eight,
        )
    )
    assert v.status == "文案合理", v.detail
    report = format_verdict_report(
        [
            evaluate_offer(
                offer(
                    sku="VW-猫+VW-狗+VW-幽灵+VW-圣诞",
                    price=Decimal("45.59"),
                    regular=Decimal("89.39"),
                    price_tag="Only $10.39 each!",
                    attr="🐱Cat + 🐶Dog + 👻Ghost + 🎄Christmas (Save 32% OFF)",
                    location=LOC_PRICE,
                )
            ),
            evaluate_offer(
                offer(
                    sku="VW-猫+VW-狗+VW-幽灵+VW-圣诞",
                    price=Decimal("45.59"),
                    regular=Decimal("89.39"),
                    price_tag="Save 32% OFF",
                    attr="🐱Cat + 🐶Dog + 👻Ghost + 🎄Christmas (Save 32% OFF)",
                    location=LOC_SPEC,
                    standalone_total=four,
                )
            ),
        ]
    )
    assert "\n" in report
    assert "[价下方]" in report
    assert "[规格名]" in report
    assert "[不符]" in report
    assert "\n\n" not in report
    print("bundle save vs singles ok")


def test_header_does_not_veto_page():
    body = evaluate_offer(
        offer(
            sku="A+B",
            price=Decimal("27.99"),
            regular=Decimal("55.98"),
            price_tag="Only $13.99 each!",
            attr="Combo Set",
            location=LOC_PRICE,
        )
    )
    assert body.status == "文案合理", body.detail
    header = OfferVerdict(
        tag="get 49% OFF",
        label="整页",
        status="文案不合理",
        detail="8个规格不符",
        location=LOC_HEADER,
        calc="8个规格不符",
    )
    overall, detail = summarize([body, header])
    assert overall == "文案合理", (overall, detail)
    assert "未纳入整页结论" in detail
    print("header no veto ok")


def test_header_only_new_layout():
    variants = [
        {
            "ID": 26,
            "title": "1 set",
            "price": 28.99,
            "regular_price": 57.75,
            "attrs": [{"name": "Style", "value": "1 set"}],
        }
    ]
    sku_config = [{"ID": 26, "sku": "X-套装", "titleTags": [{"text": "Best Seller"}], "priceTags": None}]
    offers = extract_priced_offers(
        _cfg(variants, sku_config, header="get 50% OFF! Act fast")
    )
    assert offers, "new layout header should be detected"
    assert all(o.location == LOC_HEADER for o in offers)
    v = evaluate_offer(offers[0])
    assert v.status == "文案合理", v.detail
    print("header-only ok")


def test_currency_unit_mismatch():
    c = parse_claim("🔥Only $16.66 each")
    assert c.each_prices == [Decimal("16.66")]
    assert c.money_units == ["$"]
    c = parse_claim("Only €16,66 each")
    assert c.each_prices == [Decimal("16.66")], c.each_prices
    assert c.money_units == ["€"]
    c = parse_claim("Only €18.49 each")
    assert c.each_prices == [Decimal("18.49")]

    common = dict(
        sku="WO2437037-狗粮秤*3",
        label="3 PCS",
        attr="3 PCS",
        title="3 PCS",
        product_title="",
        price=Decimal("49.99"),
        regular=Decimal("98.99"),
    )
    bad = evaluate_offer(offer(price_tag="🔥Only $16.66 each", currency="EUR", **common))
    assert bad.status == "文案不合理", bad.detail
    assert "货币单位不一致" in bad.detail

    good = evaluate_offer(offer(price_tag="🔥Only €16.66 each", currency="EUR", **common))
    assert good.status == "文案合理", good.detail
    assert "不一致" not in good.detail
    print("currency mismatch ok")


def test_helpers():
    assert money_matches(Decimal("8.62375"), Decimal("8.62"))
    assert percent_matches(Decimal("49.45"), Decimal("49"))
    assert percent_matches(Decimal("49.48"), Decimal("49"))
    assert percent_matches(Decimal("49.50"), Decimal("50"))
    assert percent_matches(Decimal("49.99"), Decimal("50"))
    assert percent_matches(Decimal("50.00"), Decimal("50"))
    assert percent_matches(Decimal("50.49"), Decimal("50"))
    assert percent_matches(Decimal("50.50"), Decimal("51"))
    assert not percent_matches(Decimal("49.45"), Decimal("50"))
    assert not percent_matches(Decimal("49.48"), Decimal("50"))
    assert not percent_matches(Decimal("20"), Decimal("50"))
    print("helpers ok")


if __name__ == "__main__":
    test_parse_and_units()
    test_hose_each()
    test_percent_and_each()
    test_set_price()
    test_mismatch()
    test_types()
    test_save_percent_in_spec_name()
    test_sku_id_pairing_and_locations()
    test_do_not_attach_combo_pricetag_to_single_by_index()
    test_bundle_save_vs_singles()
    test_header_does_not_veto_page()
    test_header_only_new_layout()
    test_currency_unit_mismatch()
    test_helpers()
    print("all reason tests ok")
