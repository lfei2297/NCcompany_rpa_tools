from keywords import match_promo


def test_match():
    assert match_promo("🔥only $8.62 each!")
    assert match_promo("$38.99/set")
    assert match_promo("50% OFF")
    assert match_promo("50% OFF $46.5/each")
    assert match_promo("$31.49/each 50% OFF")
    assert match_promo("🐱Cat + 🐶Dog + 👻Ghost + 🎄Christmas (Save 32% OFF)")
    assert match_promo("Save 19%")
    assert match_promo("Save21%")
    assert match_promo("get 50% OFF")
    assert match_promo("50% OFF")
    assert not match_promo("Best Seller")
    assert not match_promo("Best Value")
    assert not match_promo("Bester Price")
    print("keyword tests ok")


if __name__ == "__main__":
    test_match()
