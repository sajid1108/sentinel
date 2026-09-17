"""C7 / P11: serving packages never reach generator internals or offline ground truth."""
import ast
from pathlib import Path

import pytest

import sentinel

PACKAGE_ROOT = Path(sentinel.__file__).resolve().parent
SERVING_PACKAGES = ("features", "policy", "models", "api")
FORBIDDEN_MODULES = ("sentinel.data.generator", "sentinel.data.archetypes", "sentinel.data.labels")
FORBIDDEN_STRINGS = ("sim_ground_truth", "order_labels")


def _python_files(package: str) -> list[Path]:
    return sorted((PACKAGE_ROOT / package).rglob("*.py"))


def _imported_modules(tree: ast.AST) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


@pytest.mark.parametrize("package", SERVING_PACKAGES)
def test_c7_no_forbidden_imports(package):
    for path in _python_files(package):
        modules = _imported_modules(ast.parse(path.read_text(encoding="utf-8")))
        bad = {m for m in modules for f in FORBIDDEN_MODULES if m == f or m.startswith(f + ".")}
        assert not bad, f"{path}: {sorted(bad)}"


@pytest.mark.parametrize("package", SERVING_PACKAGES)
def test_c7_no_ground_truth_or_label_table_names(package):
    for path in _python_files(package):
        text = path.read_text(encoding="utf-8")
        assert not [s for s in FORBIDDEN_STRINGS if s in text], path


def test_c7_generator_uses_the_features_identifier_function():
    from sentinel.data import generator
    from sentinel.features import identifiers

    assert generator.identifier_id is identifiers.identifier_id


def test_c7_scan_catches_a_forbidden_import():
    tree = ast.parse("from sentinel.data.generator import generate\nimport sentinel.data.labels as L\n")
    assert {"sentinel.data.generator", "sentinel.data.labels"} <= _imported_modules(tree)
