"""Contract validation: hashed identifiers, COD/token rule, extra fields."""
import pytest
from pydantic import TypeAdapter, ValidationError

from sentinel.api.schemas import CheckoutRequest, HashedId, ScoreOrderRequest

HASHED = TypeAdapter(HashedId)


def test_hashed_id_accepts_32_lowercase_hex():
    assert HASHED.validate_python("0123456789abcdef0123456789abcdef")


@pytest.mark.parametrize("value", [
    "a" * 31,
    "a" * 33,
    "0123456789ABCDEF0123456789ABCDEF",
    "priya.sharma@example.com",
    "+919876543210",
    "g" * 32,
    "0123456789abcdef0123456789abcde!",
])
def test_hashed_id_rejects(value):
    with pytest.raises(ValidationError):
        HASHED.validate_python(value)


@pytest.mark.parametrize("model", [ScoreOrderRequest, CheckoutRequest])
def test_valid_payload_accepted(model, order_payload):
    assert model(**order_payload).order_id == "ORD-TEST-001"


@pytest.mark.parametrize("model", [ScoreOrderRequest, CheckoutRequest])
def test_cod_with_token_rejected(model, order_payload):
    order_payload["payment_method"] = "COD"
    with pytest.raises(ValidationError, match="payment_token_id"):
        model(**order_payload)


@pytest.mark.parametrize("model", [ScoreOrderRequest, CheckoutRequest])
def test_prepaid_without_token_rejected(model, order_payload):
    order_payload["payment_token_id"] = None
    with pytest.raises(ValidationError, match="payment_token_id"):
        model(**order_payload)


@pytest.mark.parametrize("model", [ScoreOrderRequest, CheckoutRequest])
def test_extra_field_p_abuse_rejected(model, order_payload):
    order_payload["p_abuse"] = 0.01
    with pytest.raises(ValidationError, match="p_abuse"):
        model(**order_payload)


def test_checkout_request_inherits_score_order_request():
    assert issubclass(CheckoutRequest, ScoreOrderRequest)
