"""Environment guards: exact pins, Windows console encoding, contract document present."""
import os
import subprocess
import sys
import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent


def _dependencies() -> list[str]:
    return tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]


def test_all_dependencies_exactly_pinned():
    assert all("==" in d and ">=" not in d for d in _dependencies())


def test_sklearn_version_matches_pin():
    import sklearn

    pins = {d.split("==")[0]: d.split("==")[1] for d in _dependencies()}
    assert sklearn.__version__ == pins["scikit-learn"]


def test_cli_prints_rupee_without_pythonioencoding():
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    code = ("import sys; sys.argv = ['sentinel', 'generate']; "
            "from sentinel.cli import main; main(); print('\\u20b9')")
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, env=env, cwd=BACKEND)
    assert res.returncode == 0, res.stderr.decode("utf-8", "replace")
    assert "₹".encode("utf-8") in res.stdout


def test_architecture_contract_present():
    doc = (REPO / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    for heading in ("# 8. Expected-cost formula", "## 9.2 Corroborating signals",
                    "## 7.2 Leakage controls", "# Appendix A."):
        assert heading in doc
