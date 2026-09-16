"""C6: the policy tests still pass when Python strips assert statements (python -O)."""
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]


def test_policy_tests_pass_under_python_O():
    res = subprocess.run(
        [sys.executable, "-O", "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "tests/unit/test_engine.py", "tests/unit/test_policy_review.py::test_c6_invariant_raises_runtime_error"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=BACKEND,
    )
    assert res.returncode == 0, res.stdout[-3000:] + res.stderr[-3000:]
    assert " passed" in res.stdout and "failed" not in res.stdout
