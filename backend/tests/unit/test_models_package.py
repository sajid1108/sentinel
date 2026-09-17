"""Models predict, policy decides (non-negotiable 1): purity of sentinel/models, artifact integrity, the
policy-input boundary and the metric implementations."""
import ast
import json
import typing
from pathlib import Path

import numpy as np
import pytest
import sklearn
from sklearn.metrics import average_precision_score

import sentinel
from sentinel.api.schemas import Action, Category
from sentinel.evaluation import metrics as M
from sentinel.features.builder import POLICY_INPUT_COLUMNS
from sentinel.features.definitions import ABUSE_FEATURES, RETURN_FEATURES, all_features
from sentinel.models import registry
from sentinel.models.train import CATEGORY_LEVELS

MODELS_DIR = Path(sentinel.__file__).resolve().parent / "models"
ACTION_NAMES = {a.value for a in Action} | {"Action", "SEVERITY"}
POLICY_ONLY = {"clv_inr", "matured_returns", "matured_return_rate", "burst_link_kinds", "device_weight",
               "token_weight", "address_weight", "address_confirmed_abuse_weight", "burst_weight",
               "address_is_multi_tenant", "graph_state_as_of", "payment_method"}


# ── models package purity ────────────────────────────────────────────────────
def _names(tree: ast.AST) -> tuple[set[str], set[str]]:
    imports, names = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)
    return imports, names


def test_models_package_scan_covers_the_modules():
    assert {p.name for p in MODELS_DIR.glob("*.py")} >= {"__init__.py", "train.py", "calibrate.py", "registry.py"}


@pytest.mark.parametrize("path", sorted(MODELS_DIR.glob("*.py")), ids=lambda p: p.name)
def test_models_package_has_no_policy_imports_or_action_names(path):
    imports, names = _names(ast.parse(path.read_text(encoding="utf-8")))
    assert not [m for m in imports if m == "sentinel.policy" or m.startswith("sentinel.policy.")], path
    assert not names & ACTION_NAMES, (path, sorted(names & ACTION_NAMES))


def test_scan_catches_policy_import_and_action_names():
    imports, names = _names(ast.parse("from sentinel.policy.engine import decide\nx = Action.BLOCK\ny = 'ALLOW'\n"))
    assert "sentinel.policy.engine" in imports and {"Action", "BLOCK", "ALLOW"} <= names


# ── policy inputs are never model features ───────────────────────────────────
def test_policy_only_columns_are_not_model_features():
    assert POLICY_ONLY <= set(POLICY_INPUT_COLUMNS)
    assert not POLICY_ONLY & set(RETURN_FEATURES)
    assert not POLICY_ONLY & set(ABUSE_FEATURES)
    assert set(POLICY_INPUT_COLUMNS) - set(all_features()) == POLICY_ONLY


def test_category_levels_match_the_contract():
    assert CATEGORY_LEVELS["primary_category"] == typing.get_args(Category)


# ── artifact integrity ───────────────────────────────────────────────────────
def _bundle(name: str, **overrides) -> dict:
    return {"name": name, "base_model": None, "calibrator": None, "calibration_method": "sigmoid",
            "feature_list": ["order_value_inr"], "feature_set_version": "fs-1.0-test",
            "sklearn_version": sklearn.__version__, "train_window": {}, "calibration_window": {},
            "trained_at": "2026-09-01T10:30:00+05:30", **overrides}


@pytest.fixture
def artifacts(tmp_path):
    registry.save_bundles({n: _bundle(n) for n in registry.MODEL_NAMES}, tmp_path)
    return tmp_path


def test_saved_bundle_loads_with_registry_version(artifacts):
    bundle = registry.load_bundle("abuse", artifacts)
    entry = registry.load_registry(artifacts)["models"]["abuse"]
    assert bundle["model_version"] == entry["model_version"] == f"abuse-hgb-fs1.0-{entry['sha256'][:8]}"


def test_tampered_artifact_refuses_to_load(artifacts):
    path = registry.artifact_path("return", artifacts)
    data = bytearray(path.read_bytes())
    data[-1] ^= 0xFF
    path.write_bytes(bytes(data))
    with pytest.raises(registry.ArtifactError, match="SHA-256 mismatch"):
        registry.load_bundle("return", artifacts)


def test_wrong_sklearn_version_refuses_to_load(tmp_path):
    registry.save_bundles({"return": _bundle("return"), "abuse": _bundle("abuse", sklearn_version="0.0.1")}, tmp_path)
    registry.load_bundle("return", tmp_path)
    with pytest.raises(registry.ArtifactError, match="scikit-learn 0.0.1"):
        registry.load_bundle("abuse", tmp_path)


def test_missing_registry_entry_refuses_to_load(artifacts):
    path = registry.registry_path(artifacts)
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["models"]["abuse"]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(registry.ArtifactError, match="not in the registry"):
        registry.load_bundle("abuse", artifacts)


def test_save_refuses_to_overwrite_without_force(artifacts):
    before = registry.sha256_file(registry.artifact_path("abuse", artifacts))
    with pytest.raises(registry.ArtifactError, match="--force"):
        registry.save_bundles({n: _bundle(n, trained_at="other") for n in registry.MODEL_NAMES}, artifacts)
    assert registry.sha256_file(registry.artifact_path("abuse", artifacts)) == before
    registry.save_bundles({n: _bundle(n, trained_at="other") for n in registry.MODEL_NAMES}, artifacts, force=True)
    assert registry.sha256_file(registry.artifact_path("abuse", artifacts)) != before


def test_cli_train_refuses_existing_artifacts_without_force(artifacts, monkeypatch):
    from sentinel import cli, settings

    monkeypatch.setattr(settings, "ARTIFACTS_DIR", artifacts)
    before = registry.sha256_file(registry.registry_path(artifacts))
    with pytest.raises(SystemExit, match="refusing to overwrite"):
        cli.cmd_train(type("Args", (), {"force": False})())
    assert registry.sha256_file(registry.registry_path(artifacts)) == before


# ── metrics ──────────────────────────────────────────────────────────────────
def test_average_precision_matches_sklearn_with_ties():
    rng = np.random.default_rng(3)
    for _ in range(20):
        y = rng.integers(0, 2, 300)
        p = np.round(rng.random(300), 1)                          # many ties
        assert M.average_precision(y, p) == pytest.approx(average_precision_score(y, p))
    assert M.average_precision([0, 0], [0.1, 0.2]) is None


def test_ece_and_reliability_curve_use_equal_frequency_bins():
    p = np.arange(20) / 20
    y = np.array([0] * 10 + [1] * 10)
    curve = M.reliability_curve(y, p)
    assert [c["count"] for c in curve] == [2] * 10
    assert curve[0] == {"bin_mean_predicted": pytest.approx(0.025), "observed_rate": 0.0, "count": 2}
    expected = np.mean([abs(np.mean(p[i:i + 2]) - np.mean(y[i:i + 2])) for i in range(0, 20, 2)])
    assert M.ece(y, p) == pytest.approx(expected)


def test_bootstrap_ci_is_seeded():
    rng = np.random.default_rng(4)
    y, p = rng.integers(0, 2, 200), rng.random(200)
    assert M.bootstrap_ci(y, p) == M.bootstrap_ci(y, p)
    lo, hi = M.bootstrap_ci(y, p)
    assert lo <= M.average_precision(y, p) <= hi


def test_wilson_interval_and_risk_bands():
    lo, hi = M.wilson_interval(8, 10)
    assert lo == pytest.approx(0.4902, abs=1e-3) and hi == pytest.approx(0.9433, abs=1e-3)
    assert M.wilson_interval(0, 0) is None
    bands = M.risk_bands([0, 1, 1], [0.01, 0.95, 1.0])
    assert [b["n"] for b in bands] == [1, 0, 0, 0, 0, 2]
    assert bands[1]["mean_predicted"] is None and bands[1]["observed_ci95_wilson"] is None


def test_equal_width_ece_only_uses_p_at_least_0_05():
    out = M.ece_equal_width_above([1, 0, 1], [0.01, 0.10, 0.10])
    assert out["rows_p_ge_0_05"] == 2 and out["ece_10bin_equal_width_p_ge_0_05"] == pytest.approx(0.4)


def test_monotonic_cst_is_aligned_and_never_on_categoricals():
    from sentinel.models.train import MODEL_SPECS, monotonic_cst

    abuse = MODEL_SPECS["abuse"]
    cst = monotonic_cst(abuse.features, abuse.monotonic_map())
    assert len(cst) == len(abuse.features) and set(cst) == {0, 1}
    assert cst[abuse.features.index("primary_category")] == 0
    assert sum(cst) == 11 and sum(monotonic_cst(MODEL_SPECS["return"].features, MODEL_SPECS["return"].monotonic_map())) == 3
    with pytest.raises(ValueError):
        monotonic_cst(["primary_category"], {"primary_category": 1})
