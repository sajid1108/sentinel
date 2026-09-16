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
