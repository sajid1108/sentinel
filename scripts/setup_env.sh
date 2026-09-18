#!/usr/bin/env bash
#
# Bring a fresh checkout to the state the test suite and `serve` expect.
#
# Idempotent: every step checks for its own output first and is skipped when that output is already
# there, so running this twice is safe and the second run does almost nothing. Delete the output you
# want rebuilt (the venv directory, `frontend/node_modules`, a file under `backend/data/`) and run it
# again to redo just that step.
#
# It installs exactly what `backend/requirements.lock` and `frontend/package-lock.json` pin, via
# `pip install -r` and `npm ci`. It never adds, removes or re-pins a dependency, and it changes no
# tracked file: everything it writes is git-ignored.
#
# Usage:  bash scripts/setup_env.sh
#
# On Windows run it from Git Bash. Steps that need a Python interpreter use the project's own venv, so
# nothing is installed into a system Python.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$REPO_ROOT/backend"
FRONTEND="$REPO_ROOT/frontend"
VENV="$BACKEND/.venv"
DATA="$BACKEND/data"

step() { printf '\n== %s\n' "$1"; }
skip() { printf '   skipped: %s\n' "$1"; }
run()  { printf '   %s\n' "$1"; }

# A venv is `.venv/bin/python` on POSIX and `.venv/Scripts/python.exe` on Windows.
venv_python() {
  if [ -x "$VENV/bin/python" ]; then
    printf '%s' "$VENV/bin/python"
  elif [ -x "$VENV/Scripts/python.exe" ]; then
    printf '%s' "$VENV/Scripts/python.exe"
  else
    return 1
  fi
}

# The project is pinned to Python 3.12 (`requires-python = "==3.12.*"`); the committed model artifacts
# only load under the pinned scikit-learn, which in turn is pinned to that interpreter.
find_python312() {
  local candidate
  for candidate in python3.12 python312; do
    if command -v "$candidate" >/dev/null 2>&1; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  # Windows launcher
  if command -v py >/dev/null 2>&1 && py -3.12 -c '' >/dev/null 2>&1; then
    printf '%s' "py -3.12"
    return 0
  fi
  # A bare python3 counts only if it is already 3.12.
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)' 2>/dev/null; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

# ── 1. virtualenv ────────────────────────────────────────────────────────────
step "backend virtualenv ($VENV)"
if venv_python >/dev/null 2>&1; then
  skip "$( "$(venv_python)" -V ) already present"
else
  if ! PY312="$(find_python312)"; then
    echo "   ERROR: no Python 3.12 found. The backend pins requires-python = \"==3.12.*\"," >&2
    echo "          and the committed model artifacts load only under the pinned scikit-learn." >&2
    exit 1
  fi
  run "creating with $PY312"
  # shellcheck disable=SC2086
  $PY312 -m venv "$VENV"
  venv_python >/dev/null
fi
PYTHON="$(venv_python)"

# ── 2. pinned dependencies ───────────────────────────────────────────────────
# The output of this step is a set of installed packages, not a file, so it is stamped with the hash of
# the lockfile it installed. A changed lockfile re-installs; an unchanged one does not.
step "backend dependencies (requirements.lock)"
LOCK="$BACKEND/requirements.lock"
STAMP="$VENV/.requirements.lock.sha256"
lock_hash() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$LOCK" | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$LOCK" | cut -d' ' -f1
  else
    "$PYTHON" -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$LOCK"
  fi
}
WANT="$(lock_hash)"
if [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$WANT" ]; then
  skip "requirements.lock unchanged since the last install"
else
  run "pip install -r requirements.lock"
  "$PYTHON" -m pip install --quiet --disable-pip-version-check -r "$LOCK"
  printf '%s' "$WANT" > "$STAMP"
fi

# ── 3. the package itself, editable ──────────────────────────────────────────
# --no-deps because requirements.lock is the single source of pins; a plain editable install would let
# pip resolve versions of its own.
step "sentinel package (editable)"
if "$PYTHON" -c 'import sentinel' >/dev/null 2>&1; then
  skip "sentinel already importable"
else
  run "pip install --no-deps -e backend"
  "$PYTHON" -m pip install --quiet --disable-pip-version-check --no-deps -e "$BACKEND"
fi

# ── 4. frontend dependencies ─────────────────────────────────────────────────
step "frontend dependencies (npm ci)"
if [ -d "$FRONTEND/node_modules" ]; then
  skip "frontend/node_modules already present"
elif ! command -v npm >/dev/null 2>&1; then
  echo "   ERROR: npm not found. Install Node.js 20+ and run this script again." >&2
  exit 1
else
  run "npm ci"
  ( cd "$FRONTEND" && npm ci --silent )
fi

# ── 5-7. the offline pipeline ────────────────────────────────────────────────
# Each command writes files under backend/data/ (git-ignored), in this order: the seeded world, the
# point-in-time feature tables, then the demo database. Later steps read the earlier ones' output.
cli() {
  run "python -m sentinel.cli $1"
  ( cd "$BACKEND" && "$PYTHON" -m sentinel.cli "$1" )
}

step "synthetic world (generate)"
if [ -f "$DATA/events.parquet" ]; then
  skip "backend/data/events.parquet already written"
else
  cli generate
fi

step "point-in-time features (build-features)"
if [ -f "$DATA/features.parquet" ] && [ -f "$DATA/policy_inputs.parquet" ]; then
  skip "backend/data/features.parquet already written"
else
  cli build-features
fi

step "demo database (seed-db)"
if [ -f "$DATA/sentinel.db" ]; then
  skip "backend/data/sentinel.db already written"
else
  cli seed-db
fi

# ── done ─────────────────────────────────────────────────────────────────────
cat <<EOF

Environment ready.

  backend tests   cd backend && .venv/bin/python -m pytest -q -m "not slow"
  backend serve   cd backend && .venv/bin/python -m sentinel.cli serve
  frontend tests  cd frontend && npm test
  frontend dev    cd frontend && npm run dev

EOF
