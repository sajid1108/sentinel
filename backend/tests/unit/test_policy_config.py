"""Policy config loader and validator (B11, B13)."""
from pathlib import Path

import pytest

from sentinel.policy.config import load_policy_config

SOURCE = Path(__file__).resolve().parents[2] / "sentinel" / "config" / "policy_v1_0.toml"


def _write(tmp_path, text: str, name: str = "policy.toml", newline: str = "\n") -> Path:
    path = tmp_path / name
    path.write_bytes(text.replace("\r\n", "\n").replace("\n", newline).encode("utf-8"))
    return path


@pytest.fixture
def toml_text() -> str:
    return SOURCE.read_bytes().decode("utf-8")


@pytest.mark.parametrize("old, new", [
    ("review_cost_inr = 250\n", ""),                                            # missing key
    ("review_cost_inr = 250\n", "review_cost_inr = 250\nsurprise_inr = 1\n"),  # unknown key
    ("abuse_recovery_rate = 0.15", "abuse_recovery_rate = 1.2"),                # rate outside [0, 1]
    ("new_customer_floor_inr = 2000", "new_customer_floor_inr = 200000"),       # floor > cap
    ("block_min_corroborating_signals = 2", "block_min_corroborating_signals = 1"),
    ("genuine_support_cost_inr = 100", "genuine_support_cost_inr = -1"),        # negative INR
    ("tie_tolerance_inr = 1.0", "tie_tolerance_inr = -1.0"),
    ("high_exposure_min_p_abuse = 0.40", "high_exposure_min_p_abuse = 0.80"),   # not < block_min_p_abuse
    ("high_exposure_min_p_abuse = 0.40", "high_exposure_min_p_abuse = 0.0"),
    ("block_min_p_abuse = 0.70", "block_min_p_abuse = 0.50"),
    ("reviewer_detection_rate = 0.80", "reviewer_detection_rate = 0.0"),
])
def test_invalid_config_raises(tmp_path, toml_text, old, new):
    assert old in toml_text.replace("\r\n", "\n")
    with pytest.raises(ValueError):
        load_policy_config(_write(tmp_path, toml_text.replace("\r\n", "\n").replace(old, new, 1)))


def test_missing_section_raises(tmp_path, toml_text):
    text = toml_text.replace("\r\n", "\n")
    without_block = text[:text.index("[block]")] + text[text.index("[guardrails]"):]
    with pytest.raises(ValueError, match=r"missing section \[block\]"):
        load_policy_config(_write(tmp_path, without_block))


def test_crlf_copy_hashes_identically(tmp_path, toml_text):
    lf = load_policy_config(_write(tmp_path, toml_text, "lf.toml", "\n"))
    crlf_path = _write(tmp_path, toml_text, "crlf.toml", "\r\n")
    assert b"\r\n" in crlf_path.read_bytes()
    assert load_policy_config(crlf_path).config_sha256 == lf.config_sha256 == load_policy_config().config_sha256
