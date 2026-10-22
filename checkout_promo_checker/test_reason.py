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
    format_verdict_rows,
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
from parser import LOC_BADGE, LOC_HEADER, LOC_PRICE, LOC_SPEC, has_order_module


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
    assert infer_piece_count("QH2692361", "2 Sets", "", "4 Sets/bag") == 8
    assert infer_piece_count("QH2692361*2", "2 Sets", "", "4 Sets/bag") == 8
    assert infer_piece_count("QH2692361-4件", "1 Set (Set of 4)", "", "") == 4
    assert infer_piece_count("FD3096590-1*2+FD3352377-切丝*2", "2× Combo Set", "", "") == 4
    assert infer_piece_count("FD3096590-1+FD3352377-切丝", "Combo Set", "", "") == 2
    assert infer_piece_count("A+B+C+D", "1 Set (Set of 4)", "", "") == 4
    # 没写一套有几件时，A*N+B*N 按零件数，不收成 N 套
    assert infer_piece_count(
        "TG2452538-套筒加接杆*2+WB3340827-棘轮蓝色手柄*2",
        "Adjustable sleeve + extension rod + Blue Handle, 2 sets",
        "",
        "",
    ) == 4
    assert infer_piece_count(
        "XL3505149A-四孔*2+IP3541886-10包*2",
        "（4-hole+10 Packs Bait）*2",
        "",
        "",
    ) == 2
    assert infer_set_count("A*2+B*2", "(Style A + Style B) * 2", "") == 2
    # SKU 写明一份数量则相乘：60set*2 → 120，30set+60set → 90
    assert infer_piece_count("KC3173821-60set礼盒装*2", "", "", "") == 120
    assert infer_piece_count(
        "KC3173821-30set礼盒装+KC3173821-60set礼盒装", "", "", ""
    ) == 90
    assert (
        infer_piece_count(
            "KC3173821-60set礼盒装*2",
            "120 sets+Gift Box",
            "Mini Envelopes With Blank Cards - 120 sets+Gift Box",
            "Mini Envelopes With Blank Cards",
        )
        == 120
    )
    print("parse ok")


def test_color_combo_repeat_follows_per_piece_siblings():
    """(三色)×N：同页单色、三色各 1 已按件，×N 是每种再买 N 个，不是 N 组。"""
    variants = [
        {
            "ID": 1,
            "price": 22.99,
            "regular_price": 45.9,
            "attrs": [{"name": "Style", "value": "Yellow - 2 PCS"}],
        },
        {
            "ID": 2,
            "price": 26.99,
            "regular_price": 53.9,
            "attrs": [{"name": "Style", "value": "Yellow + Orange + Rose Red"}],
        },
        {
            "ID": 3,
            "price": 32.99,
            "regular_price": 65.9,
            "attrs": [{"name": "Style", "value": "(Yellow + Orange + Rose Red) × 2"}],
        },
        {
            "ID": 4,
            "price": 42.99,
            "regular_price": 85.9,
            "attrs": [{"name": "Style", "value": "(Yellow + Orange + Rose Red) × 3"}],
        },
    ]
    sku_config = [
        {"ID": 1, "sku": "WO3550543A-黄色*2", "priceTags": "$11.49 each"},
        {
            "ID": 2,
            "sku": "WO3550543A-粉色+WO3550543A-黄色+WO3550543A-橙色",
            "priceTags": "$8.99 each",
        },
        {
            "ID": 3,
            "sku": "WO3550543A-粉色*2+WO3550543A-黄色*2+WO3550543A-橙色*2",
            "priceTags": "$5.49 each",
        },
        {
            "ID": 4,
            "sku": "WO3550543A-粉色*3+WO3550543A-黄色*3+WO3550543A-橙色*3",
            "priceTags": "$4.77 each",
        },
    ]
    offers = extract_priced_offers(_cfg(variants, sku_config))
    by_label = {o.label: evaluate_offer(o) for o in offers if o.location == LOC_PRICE}
    assert by_label["Yellow - 2 PCS"].status == "文案合理"
    assert "÷2件" in by_label["Yellow - 2 PCS"].detail
    assert by_label["Yellow + Orange + Rose Red"].status == "文案合理"
    assert "÷3件" in by_label["Yellow + Orange + Rose Red"].detail
    doubled = by_label["(Yellow + Orange + Rose Red) × 2"]
    assert doubled.status == "文案合理", doubled.detail
    assert "÷6件" in doubled.detail, doubled.detail
    tripled = by_label["(Yellow + Orange + Rose Red) × 3"]
    assert tripled.status == "文案合理", tripled.detail
    assert "÷9件" in tripled.detail, tripled.detail

    # 同页按件的是另一款商品时，括号里的不同零件仍按组，不跟着改
    mixed = extract_priced_offers(
        _cfg(
            [
                {
                    "ID": 1,
                    "price": 22.99,
                    "regular_price": 45.9,
                    "attrs": [{"name": "Style", "value": "Yellow - 2 PCS"}],
                },
                {
                    "ID": 2,
                    "price": 62.99,
                    "regular_price": 125.9,
                    "attrs": [{"name": "Style", "value": "（4-hole+10 Packs Bait）*2"}],
                },
            ],
            [
                {"ID": 1, "sku": "WO3550543A-黄色*2", "priceTags": "$11.49 each"},
                {
                    "ID": 2,
                    "sku": "XL3505149A-四孔*2+IP3541886-10包*2",
                    "priceTags": "🔥Only $31.49 each",
                },
            ],
        )
    )
    trap = next(o for o in mixed if "4-hole" in o.label)
    verdict = evaluate_offer(trap)
    assert verdict.status == "文案合理", verdict.detail
    assert "÷2件" in verdict.detail, verdict.detail

    # 单色没有单价文案也行：货号在本页单独有售，×N 就按件数
    singles = extract_priced_offers(
        _cfg(
            [
                {
                    "ID": 1,
                    "price": 17.99,
                    "regular_price": 35.9,
                    "attrs": [{"name": "Style", "value": "Yellow - 1 PC"}],
                },
                {
                    "ID": 2,
                    "price": 17.99,
                    "regular_price": 35.9,
                    "attrs": [{"name": "Style", "value": "Orange - 1 PC"}],
                },
                {
                    "ID": 3,
                    "price": 17.99,
                    "regular_price": 35.9,
                    "attrs": [{"name": "Style", "value": "Rose Red - 1 PC"}],
                },
                {
                    "ID": 4,
                    "price": 32.99,
                    "regular_price": 65.9,
                    "attrs": [{"name": "Style", "value": "(Yellow + Orange + Rose Red) × 2"}],
                },
            ],
            [
                {"ID": 1, "sku": "WO3550543A-黄色", "priceTags": None},
                {"ID": 2, "sku": "WO3550543A-橙色", "priceTags": None},
                {"ID": 3, "sku": "WO3550543A-粉色", "priceTags": None},
                {
                    "ID": 4,
                    "sku": "WO3550543A-粉色*2+WO3550543A-黄色*2+WO3550543A-橙色*2",
                    "priceTags": "$5.49 each",
                },
            ],
        )
    )
    only_bundle = next(o for o in singles if "× 2" in o.label)
    single_verdict = evaluate_offer(only_bundle)
    assert single_verdict.status == "文案合理", single_verdict.detail
    assert "÷6件" in single_verdict.detail, single_verdict.detail

    # 零件没有单卖，页面上只有括号组合：仍按组
    alone = extract_priced_offers(
        _cfg(
            [
                {
                    "ID": 1,
                    "price": 62.99,
                    "regular_price": 125.9,
                    "attrs": [{"name": "Style", "value": "（4-hole+10 Packs Bait）*2"}],
                }
            ],
            [
                {
                    "ID": 1,
                    "sku": "XL3505149A-四孔*2+IP3541886-10包*2",
                    "priceTags": "🔥Only $31.49 each",
                }
            ],
        )
    )
    alone_verdict = evaluate_offer(alone[0])
    assert alone_verdict.status == "文案合理", alone_verdict.detail
    assert "÷2件" in alone_verdict.detail, alone_verdict.detail
    print("color combo repeat ok")


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


def test_each_stays_per_piece_without_pack_size():
    v = evaluate_offer(
        offer(
            sku="TG2452538-套筒加接杆*2+WB3340827-棘轮蓝色手柄*2",
            price=Decimal("97.99"),
            regular=Decimal("195.9"),
            price_tag="$48.99 each",
            attr="Adjustable sleeve + extension rod + Blue Handle, 2 sets",
            title="",
            product_title="Multi-function Universal Socket Wrench Tool",
        )
    )
    assert v.status == "文案不合理", v.detail
    assert "÷4件" in v.detail, v.detail
    assert "按2套" in v.detail and "与套单价一致" in v.detail, v.detail
    v = evaluate_offer(
        offer(
            sku="XL3505149A-四孔*2+IP3541886-10包*2",
            price=Decimal("62.99"),
            regular=Decimal("125.9"),
            price_tag="🔥Only $31.49 each",
            attr="（4-hole+10 Packs Bait）*2",
            title="",
            product_title="Reusable Fly Trap",
        )
    )
    assert v.status == "文案合理", v.detail
    assert "÷2件" in v.detail, v.detail
    hose = evaluate_offer(offer())
    assert "÷8件" in hose.detail, hose.detail
    bare = evaluate_offer(
        offer(
            sku="QH2692361*2",
            price=Decimal("68.99"),
            regular=Decimal("137.99"),
            price_tag="🔥only $8.62 each!",
            attr="2 Sets",
            title="2 Sets",
            product_title="3/4 Inch Garden Hose Quick Connector 4 Sets/bag",
        )
    )
    assert bare.status == "文案合理", bare.detail
    assert "÷8件" in bare.detail, bare.detail
    # 同页已有规格的 each 按「2 sets」除尽，组合装也按套数，不再加成 4 件
    offers = extract_priced_offers(
        _cfg(
            [
                {
                    "ID": 1,
                    "price": 62.99,
                    "regular_price": 125.9,
                    "attrs": [{"name": "Style", "value": "Adjustable sleeve + extension rod, 2 sets"}],
                },
                {
                    "ID": 2,
                    "price": 97.99,
                    "regular_price": 195.9,
                    "attrs": [
                        {
                            "name": "Style",
                            "value": "Adjustable sleeve + extension rod + Blue Handle, 2 sets",
                        }
                    ],
                },
            ],
            [
                {"ID": 1, "sku": "TG2452538-套筒加接杆*2", "priceTags": "$31.49 each"},
                {
                    "ID": 2,
                    "sku": "TG2452538-套筒加接杆*2+WB3340827-棘轮蓝色手柄*2",
                    "priceTags": "$48.99 each",
                },
            ],
        )
    )
    by_label = {o.label: evaluate_offer(o) for o in offers if o.location == LOC_PRICE}
    assert by_label["Adjustable sleeve + extension rod, 2 sets"].status == "文案合理"
    combo = by_label["Adjustable sleeve + extension rod + Blue Handle, 2 sets"]
    assert combo.status == "文案合理", combo.detail
    assert "÷2套" in combo.detail, combo.detail
    # 同页另一档写了 Set of 4，本档 SKU 没有「件」，仍按 2×4
    offers = extract_priced_offers(
        _cfg(
            [
                {
                    "ID": 1,
                    "price": 42.99,
                    "regular_price": 85.99,
                    "attrs": [{"name": "Style", "value": "1 Set (Set of 4)"}],
                },
                {
                    "ID": 2,
                    "price": 68.99,
                    "regular_price": 137.99,
                    "attrs": [{"name": "Style", "value": "2 Sets"}],
                },
            ],
            [
                {"ID": 1, "sku": "QH2692361", "priceTags": "only $10.75 each!"},
                {"ID": 2, "sku": "QH2692361*2", "priceTags": "only $8.62 each!"},
            ],
        )
    )
    two = next(o for o in offers if o.label == "2 Sets")
    v = evaluate_offer(two)
    assert v.status == "文案合理", v.detail
    assert "÷8件" in v.detail, v.detail
    # SKU 60set*2 → 120，each 按 $37.99÷120
    v = evaluate_offer(
        offer(
            sku="KC3173821-60set礼盒装*2",
            price=Decimal("37.99"),
            regular=Decimal("75.99"),
            price_tag="🔥only $0.31 each!",
            attr="120 sets+Gift Box",
            title="Mini Envelopes With Blank Cards - 120 sets+Gift Box",
            product_title="Mini Envelopes With Blank Cards",
            label="120 sets+Gift Box",
        )
    )
    assert v.status == "文案合理", v.detail
    assert "÷120套" in v.detail, v.detail
    assert "÷2件" not in v.detail, v.detail
    v = evaluate_offer(
        offer(
            sku="KC3173821-30set礼盒装+KC3173821-60set礼盒装",
            price=Decimal("33.99"),
            regular=Decimal("67.99"),
            price_tag="only $0.38 each!",
            attr="90 sets+Gift Box",
            title="Mini Envelopes With Blank Cards - 90 sets+Gift Box",
            product_title="Mini Envelopes With Blank Cards",
            label="90 sets+Gift Box",
        )
    )
    assert v.status == "文案合理", v.detail
    assert "÷90套" in v.detail, v.detail
    print("each-as-set ok")


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
            title="Combo Set",
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


def test_inline_checkout_has_order_module():
    assert has_order_module([{"tag": "order", "_props": []}])
    assert not has_order_module([{"tag": "header"}, {"tag": "Banner"}])
    assert not has_order_module(None)
    print("inline checkout ok")


def test_currency_unit_mismatch():
    c = parse_claim("🔥Only $16.66 each")
    assert c.each_prices == [Decimal("16.66")]
    assert c.money_units == ["$"]
    c = parse_claim("Only €16,66 each")
    assert c.each_prices == [Decimal("16.66")], c.each_prices
    assert c.money_units == ["€"]
    c = parse_claim("50% OFF")
    assert c.money_units == []

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
    assert "€（EUR）" in bad.detail and "文案货币为$" in bad.detail
    assert "符合" in bad.detail

    good = evaluate_offer(offer(price_tag="🔥Only €16.66 each", currency="EUR", **common))
    assert good.status == "文案合理", good.detail
    assert "不一致" not in good.detail
    assert "€49.99" in good.detail

    usd = evaluate_offer(offer(price_tag="🔥Only $16.66 each", currency="USD", **common))
    assert usd.status == "文案合理", usd.detail
    assert "不一致" not in usd.detail

    aud = evaluate_offer(offer(price_tag="Only $16.66 each", currency="AUD", **common))
    assert aud.status == "文案合理", aud.detail
    explicit = evaluate_offer(offer(price_tag="Only US$16.66 each", currency="AUD", **common))
    assert explicit.status == "文案不合理", explicit.detail
    assert "货币单位不一致" in explicit.detail

    legacy = evaluate_offer(offer(price_tag="🔥Only $16.66 each", **common))
    assert legacy.status == "文案合理", legacy.detail
    assert "不一致" not in legacy.detail

    variants = [
        {
            "ID": 1,
            "title": "3 PCS",
            "price": "49.99",
            "regular_price": "98.99",
            "attrs": [{"value": "3 PCS"}],
        }
    ]
    sku_config = [{"ID": 1, "sku": "WO2437037-狗粮秤*3", "priceTags": "🔥Only $16.66 each"}]
    cfg = _cfg(variants, sku_config)
    cfg[0]["_props"][0]["value"]["currency"] = "EUR"
    offers = extract_priced_offers(cfg)
    assert offers and offers[0].currency == "EUR"
    verdict = evaluate_offer(offers[0])
    assert verdict.status == "文案不合理", verdict.detail
    assert "货币单位不一致" in verdict.detail
    print("currency mismatch ok")


def test_calc_table_shows_spec_price():
    rows = format_verdict_rows([evaluate_offer(offer())])
    assert rows[0]["price"] == "$68.99", rows[0]
    assert rows[0]["regular"] == "$132.65", rows[0]
    assert rows[0]["label"] == "2 Sets"

    euro = evaluate_offer(
        offer(
            price=Decimal("16.66"),
            regular=Decimal("33.32"),
            currency="EUR",
            price_tag="Only €16.66 each",
        )
    )
    euro_row = format_verdict_rows([euro])[0]
    assert euro_row["price"] == "€16.66"
    assert euro_row["regular"] == "€33.32"

    missing = evaluate_offer(
        offer(price=None, regular=None, price_tag="Only $8.62 each")
    )
    missing_row = format_verdict_rows([missing])[0]
    assert missing_row["price"] == ""
    assert missing_row["regular"] == ""

    peer_ok = offer(
        label="Yellow - 2 PCS",
        sku="WO3550543A-黄*2",
        price=Decimal("22.99"),
        regular=Decimal("45.98"),
        price_tag="Order in the next 10 minutes and get 50% OFF!",
        attr="Yellow - 2 PCS",
        title="Yellow - 2 PCS",
    )
    peer_bad = offer(
        label="Yellow - 3 PCS",
        sku="WO3550543A-黄*3",
        price=Decimal("26.99"),
        regular=Decimal("40.00"),
        price_tag="Order in the next 10 minutes and get 50% OFF!",
        attr="Yellow - 3 PCS",
        title="Yellow - 3 PCS",
    )
    header = PricedOffer(
        index=0,
        label="整页",
        sku="",
        price=None,
        regular=None,
        price_tag="Order in the next 10 minutes and get 50% OFF!",
        attr="",
        title="",
        product_title="",
        location=LOC_HEADER,
        peers=[peer_ok, peer_bad],
    )
    header_rows = format_verdict_rows([evaluate_offer(header)])
    by_label = {r["label"]: (r["price"], r["regular"]) for r in header_rows}
    assert by_label["Yellow - 2 PCS"] == ("$22.99", "$45.98"), header_rows
    assert by_label["Yellow - 3 PCS"] == ("$26.99", "$40.00"), header_rows
    print("calc table spec price ok")


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


def test_each_before_price_and_named_piece_set():
    """Each $X 单价在 each 后面；Three-piece*2 按 3×2 件，不按货号 *2。"""
    c = parse_claim("🔥🔥6 PCS - Each $15.49")
    assert c.each_prices == [Decimal("15.49")], c.each_prices
    assert c.has_numeric
    c = parse_claim("8 PCS- Each $15.12")
    assert c.each_prices == [Decimal("15.12")]
    c = parse_claim("Each: €16,66")
    assert c.each_prices == [Decimal("16.66")]
    # 原来的 $X each 不能被拆成两遍
    c = parse_claim("🔥only $8.62 each!")
    assert c.each_prices == [Decimal("8.62")]

    six = evaluate_offer(
        offer(
            label="🔥🔥6 PCS - Each $15.49",
            sku="",
            attr="🔥🔥6 PCS - Each $15.49",
            title="Solar Light - 🔥🔥6 PCS - Each $15.49",
            product_title="Solar Light",
            price=Decimal("92.99"),
            regular=Decimal("185.99"),
            price_tag="🔥🔥6 PCS - Each $15.49",
            location=LOC_SPEC,
        )
    )
    assert six.status == "文案合理", six.detail
    assert "÷6件" in six.detail

    eight = evaluate_offer(
        offer(
            label="8 PCS- Each $15.12",
            sku="",
            attr="8 PCS- Each $15.12",
            title="Solar Light - 8 PCS- Each $15.12",
            product_title="Solar Light",
            price=Decimal("120.99"),
            regular=Decimal("241.99"),
            price_tag="8 PCS- Each $15.12",
            location=LOC_SPEC,
        )
    )
    assert eight.status == "文案合理", eight.detail
    assert "÷8件" in eight.detail

    combo = "Three-piece (850ML+1750ml+3300ml)"
    assert infer_piece_count("EI3179364-1", combo, "", "") == 3
    assert infer_piece_count("EI3179364-1*2", combo + "*2", "", "") == 6
    assert infer_piece_count("X", "3-piece set", "", "") == 3
    # 商品名里的 three-piece 不套到另一个规格
    assert infer_piece_count("Y*2", "2 Sets", "Three-piece Box - 2 Sets", "Three-piece Box") == 2
    # 飞虫诱捕（组合）*2 仍按 2 组
    assert infer_piece_count(
        "XL3505149A-四孔*2+IP3541886-10包*2",
        "（4-hole+10 Packs Bait）*2",
        "",
        "",
    ) == 2

    one_set = evaluate_offer(
        offer(
            label=combo,
            sku="EI3179364-1",
            attr=combo,
            title=combo,
            product_title="",
            price=Decimal("39.99"),
            regular=Decimal("79.90"),
            price_tag="🔥Only $13.33 each!",
        )
    )
    assert one_set.status == "文案合理", one_set.detail
    assert "÷3件" in one_set.detail

    two_sets = evaluate_offer(
        offer(
            label=combo + "*2",
            sku="EI3179364-1*2",
            attr=combo + "*2",
            title=combo + "*2",
            product_title="",
            price=Decimal("69.99"),
            regular=Decimal("139.99"),
            price_tag="🔥Only $11.66 each!",
        )
    )
    assert two_sets.status == "文案合理", two_sets.detail
    assert "÷6件" in two_sets.detail
    print("each-before-price and named piece set ok")


def test_german_per_piece():
    """德文 nur 8,66 € pro Stück 按 only €X each。N Stück 按 N 件。"""
    c = parse_claim("nur 8,66 € pro Stück")
    assert c.each_prices == [Decimal("8.66")], c.each_prices
    assert c.money_units == ["€"]
    assert is_promo_copy("nur 8,66 € pro Stück")
    c = parse_claim("nur €7,59 pro Stück")
    assert c.each_prices == [Decimal("7.59")], c.each_prices
    # 英文 each 仍只记一次
    c = parse_claim("Only €16,66 each")
    assert c.each_prices == [Decimal("16.66")]
    assert infer_piece_count("LQ2787998-1瓶*3", "3 Stück", "", "") == 3
    assert infer_piece_count("", "5 Stück", "", "") == 5
    three = evaluate_offer(
        offer(
            label="3 Stück",
            sku="LQ2787998-1瓶*3",
            attr="3 Stück",
            title="3 Stück",
            product_title="",
            price=Decimal("31.99"),
            regular=Decimal("62.70"),
            price_tag="nur 8,66 € pro Stück",
            currency="EUR",
        )
    )
    assert three.status == "文案不合理", three.detail
    assert "÷3件" in three.detail
    assert "€8.66" in three.detail
    five = evaluate_offer(
        offer(
            label="5 Stück",
            sku="LQ2787998-1瓶*5",
            attr="5 Stück",
            title="5 Stück",
            product_title="",
            price=Decimal("52.99"),
            regular=Decimal("103.90"),
            price_tag="nur 7,59 € pro Stück",
            currency="EUR",
        )
    )
    assert five.status == "文案不合理", five.detail
    assert "÷5件" in five.detail
    print("german per piece ok")
    assert not percent_matches(Decimal("49.48"), Decimal("50"))
    assert not percent_matches(Decimal("20"), Decimal("50"))
    print("helpers ok")


if __name__ == "__main__":
    test_parse_and_units()
    test_color_combo_repeat_follows_per_piece_siblings()
    test_hose_each()
    test_each_stays_per_piece_without_pack_size()
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
    test_inline_checkout_has_order_module()
    test_currency_unit_mismatch()
    test_calc_table_shows_spec_price()
    test_each_before_price_and_named_piece_set()
    test_german_per_piece()
    test_helpers()
    print("all reason tests ok")
