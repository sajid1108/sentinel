"""Money helpers. All INR rounding and display formatting happens here, once, server-side."""
from decimal import ROUND_HALF_UP, Decimal

from sentinel.api.schemas import Money


def _quantize(value: float, exp: str) -> Decimal:
    # str() first so 2.675 is quantized as written, not as its binary approximation.
    return Decimal(str(value)).quantize(Decimal(exp), rounding=ROUND_HALF_UP)


def format_inr(value: float) -> str:
    """Whole rupees, ROUND_HALF_UP, Indian digit grouping: 12345678 -> "₹1,23,45,678"."""
    d = _quantize(value, "1")
    sign = "-" if d < 0 else ""
    digits = str(abs(int(d)))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        while len(head) > 2:
            tail = f"{head[-2:]},{tail}"
            head = head[:-2]
        digits = f"{head},{tail}"
    return f"{sign}₹{digits}"


def make_money(value: float) -> Money:
    """Money with inr quantized to 0.01 (ROUND_HALF_UP) and the formatted display string."""
    return Money(inr=float(_quantize(value, "0.01")), display=format_inr(value))


# Probabilities are reviewer-facing text too, and the page they sit on renders them one way (DESIGN.md
# §10): a percentage with one decimal, "<0.1%" for anything smaller that is not zero, "0%" only for an
# exact zero. Formatting them here, once, keeps a server sentence and the card above it from disagreeing.
#
# Unlike format_inr this rounds the binary float, not the decimal as written, because that is what
# `(p * 100).toFixed(1)` in lib/format.ts does. Half-up on the written decimal is the better rounding
# and is what money uses, but a probability printed in a sentence sits directly beneath the same
# probability printed on a card, and the two agreeing matters more here than the tie-breaking rule.
MIN_SHOWN_PERCENT = 0.1


def format_probability(p: float) -> str:
    """A probability as the dashboard renders it: "69.1%", "<0.1%", "0%"."""
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"probability must be in [0, 1], got {p!r}")
    if p == 0.0:
        return "0%"
    pct = p * 100
    # The floor is read off the exact percentage, so 0.09 % reads "<0.1%" rather than being rounded up
    # into a figure the value never reached.
    if pct < MIN_SHOWN_PERCENT:
        return f"<{MIN_SHOWN_PERCENT}%"
    return f"{pct:.1f}%"
