"""Phase 6 purity: api/services never reach generator internals or labels, and mirrored constants agree."""
import ast
from pathlib import Path

import sentinel.api.services as services_pkg

SERVICES_DIR = Path(services_pkg.__file__).resolve().parent
FORBIDDEN = ("sentinel.data.generator", "sentinel.data.archetypes", "sentinel.data.labels")


def _imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


def test_services_exist_and_import_nothing_forbidden():
    files = sorted(SERVICES_DIR.glob("*.py"))
    assert {"scoring.py", "review.py"} <= {f.name for f in files}
    for path in files:
        bad = {m for m in _imports(path) for f in FORBIDDEN if m == f or m.startswith(f + ".")}
        assert not bad, f"{path.name}: {sorted(bad)}"


def test_services_never_read_offline_tables():
    for path in SERVICES_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "order_labels" not in text and "sim_ground_truth" not in text, path.name


def test_label_definition_version_mirrors_labels_module():
    from sentinel.api.services.scoring import LABEL_DEFINITION_VERSION
    from sentinel.data.labels import LABEL_DEFINITION_VERSION as OFFLINE
    assert LABEL_DEFINITION_VERSION == OFFLINE


def test_identifier_label_format_mirrors_the_generator():
    from sentinel.api.services.scoring import KIND_LABEL
    from sentinel.data.generator import KIND_LABEL as GENERATOR
    assert KIND_LABEL == GENERATOR


def test_seeded_ids_are_deterministic_and_distinct():
    from sentinel.api.services.scoring import seeded_decision_id, seeded_event_id
    assert seeded_decision_id("ORD-A") == seeded_decision_id("ORD-A")
    assert len({seeded_decision_id("ORD-A"), seeded_decision_id("ORD-B"), seeded_event_id("ORD-A")}) == 3


def test_matured_counts_recover_the_raw_history():
    from sentinel.db.seed import matured_counts
    assert matured_counts(28, 28 / 48) == (28, 48)
    assert matured_counts(0, float("nan")) == (0, 0)
    assert matured_counts(0, 0.0) is None
    for returns in range(1, 60):
        for matured in range(returns, 80):
            assert matured_counts(returns, returns / matured) == (returns, matured)
