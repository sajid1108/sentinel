"""B9: one rounding function for all money shown anywhere."""
import pytest

from sentinel.money import format_inr, make_money


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
