"""B9: one rounding function for all money shown anywhere."""
import pytest

from sentinel.money import format_inr, format_probability, make_money


@pytest.mark.parametrize("value, expected", [
    (18866.5, "₹18,867"),
    (12345678, "₹1,23,45,678"),
    (-1490, "-₹1,490"),
    (999.5, "₹1,000"),
    (99999.5, "₹1,00,000"),
    (0, "₹0"),
    (1490.05, "₹1,490"),
    (500, "₹500"),
])
def test_format_inr(value, expected):
    assert format_inr(value) == expected


@pytest.mark.parametrize("value, inr", [(2.675, 2.68), (18866.5, 18866.5), (4045.454, 4045.45), (0, 0.0)])
def test_make_money_quantizes_half_up(value, inr):
    money = make_money(value)
    assert money.inr == inr
    assert money.display == format_inr(value)


# ── format_probability: the page's own rule, server-side (Phase 9 brief 1.3) ──
@pytest.mark.parametrize("value, expected", [
    (0.0, "0%"),                 # exactly zero, and only exactly zero
    (1e-7, "<0.1%"),
    (0.00099, "<0.1%"),          # 0.099 % is below the floor, so it is not rounded up onto it
    (0.001, "0.1%"),
    (0.03, "3.0%"),
    (0.4, "40.0%"),
    (0.6913, "69.1%"),
    (0.7, "70.0%"),
    (0.75, "75.0%"),
    (0.9511, "95.1%"),
    (1.0, "100.0%"),
])
def test_format_probability(value, expected):
    assert format_probability(value) == expected


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_format_probability_refuses_a_value_outside_zero_to_one(value):
    with pytest.raises(ValueError):
        format_probability(value)


def test_format_probability_matches_the_frontends_rule():
    """The browser formats `p` as `(p * 100).toFixed(1)`, with `<0.1%` below 0.1 % and `0%` only at zero
    (lib/format.ts). A sentence from the server must not disagree with the card above it."""
    def frontend(p: float) -> str:
        if p == 0:
            return "0%"
        pct = p * 100
        return "<0.1%" if pct < 0.1 else f"{pct:.1f}%"

    for i in range(0, 10_001):
        p = i / 10_000
        assert format_probability(p) == frontend(p), p
